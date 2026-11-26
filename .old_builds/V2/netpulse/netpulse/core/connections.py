"""Active network connections, attributed to the process that opened them.

``netstat -a`` tells you a socket exists. This module also answers the more
useful question — which program is at the other end of it — by joining psutil's
socket table against the process table.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

import psutil

_STATE_LABELS = {
    "ESTABLISHED": "Established",
    "SYN_SENT": "Connecting",
    "SYN_RECV": "Connecting",
    "FIN_WAIT1": "Closing",
    "FIN_WAIT2": "Closing",
    "TIME_WAIT": "Closing",
    "CLOSE": "Closed",
    "CLOSE_WAIT": "Closing",
    "LAST_ACK": "Closing",
    "LISTEN": "Listening",
    "CLOSING": "Closing",
    "NONE": "—",
}


@dataclass
class Connection:
    """One open socket."""

    protocol: str
    local_address: str
    local_port: int
    remote_address: str | None
    remote_port: int | None
    state: str
    pid: int | None
    process: str
    remote_host: str | None = None

    @property
    def local(self) -> str:
        return _endpoint(self.local_address, self.local_port)

    @property
    def remote(self) -> str:
        if self.remote_address is None:
            return "—"
        return _endpoint(self.remote_host or self.remote_address, self.remote_port)

    @property
    def is_listening(self) -> bool:
        return self.state == "Listening"

    @property
    def is_external(self) -> bool:
        """True when the far end is outside this machine and off the LAN."""
        if not self.remote_address:
            return False
        try:
            import ipaddress

            address = ipaddress.ip_address(self.remote_address)
        except ValueError:
            return False
        return not (address.is_private or address.is_loopback or address.is_link_local)

    def matches(self, needle: str) -> bool:
        """Case-insensitive search across every visible field."""
        needle = needle.lower()
        haystack = (
            self.protocol,
            self.local,
            self.remote,
            self.state,
            self.process,
            str(self.pid or ""),
        )
        return any(needle in value.lower() for value in haystack)


def list_connections(kind: str = "inet", resolve_names: bool = False) -> list[Connection]:
    """Snapshot every socket the current user is allowed to see.

    Sockets owned by other users need elevation on Windows and macOS; those are
    reported with an unknown process name rather than dropped, so the row count
    still matches ``netstat``.
    """
    try:
        raw = psutil.net_connections(kind=kind)
    except (psutil.AccessDenied, PermissionError):
        return []

    names = _process_names()
    results: list[Connection] = []

    for item in raw:
        protocol = _protocol_name(item.type, item.family)
        local_address, local_port = _split(item.laddr)
        remote_address, remote_port = _split(item.raddr)

        connection = Connection(
            protocol=protocol,
            local_address=local_address or "*",
            local_port=local_port or 0,
            remote_address=remote_address,
            remote_port=remote_port,
            state=_STATE_LABELS.get(item.status, item.status or "—"),
            pid=item.pid,
            process=names.get(item.pid, "—" if item.pid is None else f"PID {item.pid}"),
        )

        if resolve_names and connection.is_external and remote_address:
            connection.remote_host = _reverse(remote_address)

        results.append(connection)

    results.sort(key=lambda c: (c.process.lower(), c.protocol, c.local_port))
    return results


def summarise(connections: list[Connection]) -> dict[str, int]:
    """Counts for the status strip above the table."""
    return {
        "total": len(connections),
        "established": sum(1 for c in connections if c.state == "Established"),
        "listening": sum(1 for c in connections if c.is_listening),
        "external": sum(1 for c in connections if c.is_external),
        "processes": len({c.pid for c in connections if c.pid}),
    }


def top_talkers(connections: list[Connection], limit: int = 5) -> list[tuple[str, int]]:
    """Processes holding the most sockets right now."""
    counts: dict[str, int] = {}
    for connection in connections:
        if connection.process.startswith("PID ") or connection.process == "—":
            continue
        counts[connection.process] = counts.get(connection.process, 0) + 1
    return sorted(counts.items(), key=lambda item: -item[1])[:limit]


def _process_names() -> dict[int, str]:
    names: dict[int, str] = {}
    for process in psutil.process_iter(["pid", "name"]):
        try:
            names[process.info["pid"]] = process.info["name"] or f"PID {process.info['pid']}"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return names


def _protocol_name(sock_type: int, family: int) -> str:
    base = "TCP" if sock_type == socket.SOCK_STREAM else "UDP"
    return f"{base}v6" if family == socket.AF_INET6 else base


def _split(addr) -> tuple[str | None, int | None]:
    if not addr:
        return None, None
    return getattr(addr, "ip", None), getattr(addr, "port", None)


def _endpoint(address: str, port: int | None) -> str:
    if ":" in address and not address.startswith("["):
        address = f"[{address}]"
    return f"{address}:{port}" if port else address


_reverse_cache: dict[str, str | None] = {}


def _reverse(address: str) -> str | None:
    if address in _reverse_cache:
        return _reverse_cache[address]
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(0.5)
    try:
        name = socket.gethostbyaddr(address)[0]
    except OSError:
        name = None
    finally:
        socket.setdefaulttimeout(previous)
    _reverse_cache[address] = name
    return name
