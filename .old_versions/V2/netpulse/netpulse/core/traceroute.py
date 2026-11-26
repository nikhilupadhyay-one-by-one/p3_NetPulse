"""Traceroute with hops parsed into rows.

Windows and Unix print hops in different orders — ``tracert`` puts the round
trips before the address, ``traceroute`` puts them after — so the parser pulls
each field out independently instead of splitting on position.
"""

from __future__ import annotations

import re
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

from .shell import IS_WINDOWS, stream, which

_HOP_START = re.compile(r"^\s*(\d{1,2})\s+(.*)$")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_RTT = re.compile(r"([\d.,]+)\s*ms", re.I)
_PRIVATE_PREFIXES = ("10.", "192.168.", "127.", "169.254.")


@dataclass
class Hop:
    """One router on the path."""

    number: int
    address: str | None = None
    hostname: str | None = None
    rtts: list[float] = field(default_factory=list)
    timed_out: bool = False

    @property
    def average(self) -> float | None:
        return sum(self.rtts) / len(self.rtts) if self.rtts else None

    @property
    def best(self) -> float | None:
        return min(self.rtts) if self.rtts else None

    @property
    def label(self) -> str:
        if self.timed_out or not self.address:
            return "* * *"
        return self.hostname or self.address

    @property
    def is_private(self) -> bool:
        if not self.address:
            return False
        if self.address.startswith(_PRIVATE_PREFIXES):
            return True
        if self.address.startswith("172."):
            try:
                second = int(self.address.split(".")[1])
            except (IndexError, ValueError):
                return False
            return 16 <= second <= 31
        return False


def build_command(host: str, max_hops: int = 30, timeout_ms: int = 1500) -> list[str]:
    """Assemble the platform's traceroute invocation (numeric output only)."""
    if IS_WINDOWS:
        return ["tracert", "-d", "-h", str(max_hops), "-w", str(timeout_ms), host]

    program = which("traceroute") or "traceroute"
    seconds = max(1, round(timeout_ms / 1000))
    return [program, "-n", "-m", str(max_hops), "-w", str(seconds), "-q", "3", host]


def parse_hop_line(line: str) -> Hop | None:
    """Parse one line of traceroute output into a :class:`Hop`.

    Returns ``None`` for banners, blank lines and trailing summaries.
    """
    match = _HOP_START.match(line)
    if match is None:
        return None

    number = int(match.group(1))
    rest = match.group(2)

    rtts: list[float] = []
    for value in _RTT.findall(rest):
        try:
            rtts.append(float(value.replace(",", ".")))
        except ValueError:
            continue

    address_match = _IPV4.search(rest)
    address = address_match.group(0) if address_match else None

    hop = Hop(number=number, address=address, rtts=rtts)
    hop.timed_out = not rtts and address is None
    return hop


def trace(
    host: str,
    max_hops: int = 30,
    timeout_ms: int = 1500,
    resolve_names: bool = True,
    stop: threading.Event | None = None,
) -> Iterator[Hop]:
    """Run a traceroute, yielding each hop as it is discovered.

    Names are resolved in this process rather than by the traceroute binary so
    a slow reverse lookup delays one row instead of the whole trace.
    """
    for line in stream(build_command(host, max_hops, timeout_ms), stop=stop):
        if stop is not None and stop.is_set():
            return
        hop = parse_hop_line(line)
        if hop is None:
            continue
        if resolve_names and hop.address:
            hop.hostname = reverse_lookup(hop.address)
        yield hop


def reverse_lookup(address: str, timeout: float = 1.0) -> str | None:
    """Best-effort PTR lookup; returns ``None`` when there is no record."""
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        return socket.gethostbyaddr(address)[0]
    except (OSError, socket.herror, socket.gaierror):
        return None
    finally:
        socket.setdefaulttimeout(previous)
