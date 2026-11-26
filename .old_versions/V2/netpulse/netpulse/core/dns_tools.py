"""DNS lookups.

Uses ``dnspython`` when it is installed, which gives real record types and TTLs.
Without it, the standard library still covers A, AAAA and PTR, so the feature
degrades instead of disappearing.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

try:  # pragma: no cover - availability differs per environment
    import dns.rdatatype
    import dns.resolver
    import dns.reversename

    HAS_DNSPYTHON = True
except ImportError:  # pragma: no cover
    HAS_DNSPYTHON = False

RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "PTR"]
STDLIB_RECORD_TYPES = ["A", "AAAA", "PTR"]


@dataclass
class Record:
    """A single DNS answer."""

    name: str
    type: str
    value: str
    ttl: int | None = None


def available_types() -> list[str]:
    """Record types this installation can actually query."""
    return RECORD_TYPES if HAS_DNSPYTHON else STDLIB_RECORD_TYPES


def lookup(name: str, record_type: str = "A", timeout: float = 5.0) -> list[Record]:
    """Resolve ``name`` and return the answers.

    Raises :class:`LookupError` with a readable message when resolution fails.
    """
    name = name.strip().rstrip(".")
    if not name:
        raise LookupError("Enter a hostname or IP address")

    record_type = record_type.upper()
    if HAS_DNSPYTHON:
        return _lookup_dnspython(name, record_type, timeout)
    return _lookup_stdlib(name, record_type, timeout)


def resolver_addresses() -> list[str]:
    """The DNS servers this machine is configured to use."""
    if not HAS_DNSPYTHON:
        return []
    try:
        return list(dns.resolver.Resolver().nameservers)
    except Exception:  # pragma: no cover - depends on system config
        return []


def _lookup_dnspython(name: str, record_type: str, timeout: float) -> list[Record]:
    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout

    query_name = name
    if record_type == "PTR" and _looks_like_ip(name):
        query_name = str(dns.reversename.from_address(name))

    try:
        answer = resolver.resolve(query_name, record_type)
    except dns.resolver.NXDOMAIN:
        raise LookupError(f"{name} does not exist") from None
    except dns.resolver.NoAnswer:
        raise LookupError(f"{name} has no {record_type} record") from None
    except dns.resolver.NoNameservers:
        raise LookupError("No DNS server answered the query") from None
    except dns.exception.Timeout:
        raise LookupError(f"DNS query timed out after {timeout:.0f}s") from None
    except Exception as exc:  # pragma: no cover - unexpected resolver errors
        raise LookupError(str(exc)) from None

    ttl = getattr(answer.rrset, "ttl", None)
    return [Record(name=name, type=record_type, value=rdata.to_text(), ttl=ttl) for rdata in answer]


def _lookup_stdlib(name: str, record_type: str, timeout: float) -> list[Record]:
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        if record_type == "PTR":
            try:
                host, aliases, _ = socket.gethostbyaddr(name)
            except OSError:
                raise LookupError(f"No PTR record for {name}") from None
            records = [Record(name, "PTR", host)]
            records += [Record(name, "PTR", alias) for alias in aliases]
            return records

        family = socket.AF_INET6 if record_type == "AAAA" else socket.AF_INET
        try:
            infos = socket.getaddrinfo(name, None, family, socket.SOCK_STREAM)
        except OSError:
            raise LookupError(f"Could not resolve {name}") from None

        seen: list[str] = []
        for info in infos:
            address = info[4][0]
            if address not in seen:
                seen.append(address)
        return [Record(name, record_type, address) for address in seen]
    finally:
        socket.setdefaulttimeout(previous)


def _looks_like_ip(value: str) -> bool:
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, value)
            return True
        except OSError:
            continue
    return False
