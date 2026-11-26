"""Ping with parsed results instead of raw console text.

The original NetPulse handed ``ping`` output straight to the terminal. Parsing
it into structured replies is what makes the live latency chart, the packet-loss
counter and the jitter figure possible.

Parsing is deliberately tolerant: ``ping`` is localised, so the regexes key off
the numeric patterns (``=12ms``, ``ttl=115``) that survive translation rather
than off English words.
"""

from __future__ import annotations

import re
import statistics
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from .shell import IS_WINDOWS, run

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b")
# Matches "time=12ms", "time<1ms", "tiempo=12ms", "Zeit=12ms", "temps=12 ms".
_RTT_LABELLED = re.compile(r"(?:time|tiempo|tempo|zeit|temps|tid)\s*[=<]\s*([\d.,]+)\s*ms", re.I)
# Locale-agnostic fallback: any "=12ms" or "<1ms" token.
_RTT_BARE = re.compile(r"[=<]\s*([\d.,]+)\s*ms", re.I)
_TTL = re.compile(r"ttl\s*[=:]?\s*(\d+)", re.I)
# Lines that look like a reply but are really an error report.
_FAILURE_HINTS = re.compile(
    r"unreachable|timed out|time out|100%\s*(packet\s*)?loss|could not find|unknown host"
    r"|inaccesible|tiempo de espera|no se puede|non\s*joignable",
    re.I,
)


@dataclass
class Reply:
    """One ping response (or the absence of one)."""

    sequence: int
    host: str
    success: bool
    rtt_ms: float | None = None
    ttl: int | None = None
    address: str | None = None
    error: str | None = None
    timestamp: float = field(default_factory=time.time)

    def __str__(self) -> str:
        if not self.success:
            return f"seq={self.sequence}  {self.error or 'no reply'}"
        parts = [f"seq={self.sequence}", f"from {self.address or self.host}"]
        if self.rtt_ms is not None:
            parts.append(f"time={self.rtt_ms:.1f} ms")
        if self.ttl is not None:
            parts.append(f"ttl={self.ttl}")
        return "  ".join(parts)


@dataclass
class PingStats:
    """Running statistics over a ping session."""

    sent: int = 0
    received: int = 0
    rtts: list[float] = field(default_factory=list)

    def add(self, reply: Reply) -> None:
        self.sent += 1
        if reply.success and reply.rtt_ms is not None:
            self.received += 1
            self.rtts.append(reply.rtt_ms)

    @property
    def lost(self) -> int:
        return self.sent - self.received

    @property
    def loss_pct(self) -> float:
        return (self.lost / self.sent * 100) if self.sent else 0.0

    @property
    def minimum(self) -> float | None:
        return min(self.rtts) if self.rtts else None

    @property
    def maximum(self) -> float | None:
        return max(self.rtts) if self.rtts else None

    @property
    def average(self) -> float | None:
        return statistics.fmean(self.rtts) if self.rtts else None

    @property
    def jitter(self) -> float | None:
        """Mean absolute difference between consecutive round trips.

        This is the figure that predicts whether a call or a game will feel
        smooth; a low average with high jitter still stutters.
        """
        if len(self.rtts) < 2:
            return None
        diffs = [abs(b - a) for a, b in zip(self.rtts, self.rtts[1:], strict=False)]
        return statistics.fmean(diffs)

    @property
    def quality(self) -> str:
        """A plain-language verdict for the readout."""
        if self.sent == 0:
            return "No data"
        if self.received == 0:
            return "Unreachable"
        if self.loss_pct > 5:
            return "Lossy"
        average = self.average or 0
        jitter = self.jitter or 0
        if average < 40 and jitter < 10:
            return "Excellent"
        if average < 100 and jitter < 30:
            return "Good"
        if average < 200:
            return "Fair"
        return "Poor"


def build_command(host: str, count: int = 1, timeout_ms: int = 2000) -> list[str]:
    """Assemble the platform's ping invocation."""
    if IS_WINDOWS:
        return ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    # BSD/macOS takes -W in milliseconds; GNU/Linux takes whole seconds.
    from .shell import IS_MACOS

    wait = str(timeout_ms) if IS_MACOS else str(max(1, round(timeout_ms / 1000)))
    return ["ping", "-c", str(count), "-W", wait, host]


def parse_reply_line(line: str) -> tuple[float | None, int | None, str | None]:
    """Extract ``(rtt_ms, ttl, address)`` from a single line of ping output.

    Returns ``(None, None, None)`` for headers, blank lines and failures.
    """
    if not line.strip():
        return None, None, None
    if _FAILURE_HINTS.search(line):
        return None, None, None

    match = _RTT_LABELLED.search(line) or _RTT_BARE.search(line)
    if match is None:
        return None, None, None

    try:
        rtt = float(match.group(1).replace(",", "."))
    except ValueError:
        return None, None, None

    ttl_match = _TTL.search(line)
    ttl = int(ttl_match.group(1)) if ttl_match else None

    address = None
    ipv4 = _IPV4.search(line)
    if ipv4:
        address = ipv4.group(0)
    else:
        ipv6 = _IPV6.search(line)
        if ipv6 and ":" in ipv6.group(0):
            address = ipv6.group(0)

    return rtt, ttl, address


def parse_output(output: str) -> tuple[float | None, int | None, str | None, str | None]:
    """Parse a whole ping invocation into ``(rtt, ttl, address, error)``."""
    for line in output.splitlines():
        rtt, ttl, address = parse_reply_line(line)
        if rtt is not None:
            return rtt, ttl, address, None

    for line in output.splitlines():
        stripped = line.strip()
        if stripped and _FAILURE_HINTS.search(stripped):
            return None, None, None, stripped
    return None, None, None, "No reply"


def ping_once(host: str, sequence: int = 1, timeout_ms: int = 2000) -> Reply:
    """Send a single echo request and return the parsed result."""
    code, output = run(build_command(host, 1, timeout_ms), timeout=timeout_ms / 1000 + 3)
    if code == 127:
        return Reply(sequence, host, False, error="ping is not installed on this system")

    rtt, ttl, address, error = parse_output(output)
    if rtt is None:
        return Reply(sequence, host, False, error=error or "Request timed out")
    return Reply(sequence, host, True, rtt_ms=rtt, ttl=ttl, address=address)


def ping_stream(
    host: str,
    count: int | None = None,
    interval: float = 1.0,
    timeout_ms: int = 2000,
    stop: threading.Event | None = None,
) -> Iterator[Reply]:
    """Ping repeatedly, yielding each reply as it arrives.

    ``count=None`` runs until ``stop`` is set, which is how the UI's continuous
    mode works. Each request is a separate process so a single hang cannot stall
    the whole session.
    """
    sequence = 0
    while count is None or sequence < count:
        if stop is not None and stop.is_set():
            return
        sequence += 1
        started = time.monotonic()
        yield ping_once(host, sequence, timeout_ms)

        if count is not None and sequence >= count:
            return
        remaining = interval - (time.monotonic() - started)
        if remaining > 0:
            if stop is not None:
                if stop.wait(remaining):
                    return
            else:
                time.sleep(remaining)


def ping_many(
    hosts: list[str],
    timeout_ms: int = 1000,
    workers: int = 64,
    on_result: Callable[[Reply], None] | None = None,
    stop: threading.Event | None = None,
) -> list[Reply]:
    """Ping a list of hosts concurrently. Used by the subnet sweep."""
    from concurrent.futures import ThreadPoolExecutor

    results: list[Reply] = []

    def task(item: tuple[int, str]) -> Reply | None:
        index, host = item
        if stop is not None and stop.is_set():
            return None
        return ping_once(host, index, timeout_ms)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for reply in pool.map(task, enumerate(hosts, start=1)):
            if reply is None:
                continue
            results.append(reply)
            if on_result is not None:
                on_result(reply)
    return results
