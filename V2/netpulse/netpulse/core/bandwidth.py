"""Live throughput measurement.

Task Manager's network graph is drawn from per-adapter byte counters the kernel
maintains. ``psutil.net_io_counters`` reads those same counters directly, so
NetPulse samples the source rather than scraping a window: no screen reading, no
admin rights, and it works the same way on Windows, macOS and Linux.

Rate is a finite difference: ``(bytes_now - bytes_before) / elapsed_seconds``.
The first sample only establishes a baseline and reports nothing.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import psutil

ALL_INTERFACES = "All interfaces"


@dataclass(frozen=True)
class Sample:
    """One throughput measurement."""

    timestamp: float
    down_bps: float
    """Inbound bytes per second."""
    up_bps: float
    """Outbound bytes per second."""
    session_down: int
    """Bytes received since the monitor was last reset."""
    session_up: int
    """Bytes sent since the monitor was last reset."""


@dataclass
class _Counters:
    recv: int = 0
    sent: int = 0


def _read(interface: str) -> _Counters:
    """Read raw cumulative counters for one interface, or every interface."""
    if interface == ALL_INTERFACES:
        totals = psutil.net_io_counters()
        if totals is None:
            return _Counters()
        return _Counters(totals.bytes_recv, totals.bytes_sent)

    per_nic = psutil.net_io_counters(pernic=True)
    stats = per_nic.get(interface)
    if stats is None:
        return _Counters()
    return _Counters(stats.bytes_recv, stats.bytes_sent)


class BandwidthMonitor:
    """Samples one interface (or the whole machine) at a fixed interval.

    The monitor keeps a rolling history so a freshly opened chart is not blank,
    and tracks peaks and session totals for the readout strip.
    """

    def __init__(self, interface: str = ALL_INTERFACES, history: int = 180) -> None:
        self.interface = interface
        self.history: deque[Sample] = deque(maxlen=history)
        self.peak_down: float = 0.0
        self.peak_up: float = 0.0
        self.started_at: float = time.monotonic()
        self._previous: _Counters | None = None
        self._previous_time: float = 0.0
        self._origin: _Counters = _read(interface)

    # ------------------------------------------------------------------ API

    def set_interface(self, interface: str) -> None:
        """Switch adapters and start a fresh session."""
        if interface == self.interface:
            return
        self.interface = interface
        self.reset()

    def reset(self) -> None:
        """Clear history, peaks and session totals."""
        self.history.clear()
        self.peak_down = 0.0
        self.peak_up = 0.0
        self.started_at = time.monotonic()
        self._previous = None
        self._previous_time = 0.0
        self._origin = _read(self.interface)

    def sample(self) -> Sample | None:
        """Take a measurement. Returns ``None`` for the very first call."""
        now = time.monotonic()
        current = _read(self.interface)

        if self._previous is None:
            self._previous = current
            self._previous_time = now
            return None

        elapsed = now - self._previous_time
        if elapsed <= 0:
            return None

        down = self._delta(current.recv, self._previous.recv) / elapsed
        up = self._delta(current.sent, self._previous.sent) / elapsed

        self._previous = current
        self._previous_time = now

        sample = Sample(
            timestamp=now,
            down_bps=down,
            up_bps=up,
            session_down=self._delta(current.recv, self._origin.recv),
            session_up=self._delta(current.sent, self._origin.sent),
        )
        self.peak_down = max(self.peak_down, down)
        self.peak_up = max(self.peak_up, up)
        self.history.append(sample)
        return sample

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _delta(current: int, previous: int) -> int:
        """Difference between two counter readings, ignoring wraps and resets.

        Adapter counters are unsigned and reset when the interface is disabled
        or the driver reloads. A negative delta means one of those happened, and
        the honest answer is zero rather than a huge spike.
        """
        delta = current - previous
        return delta if delta >= 0 else 0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def latest(self) -> Sample | None:
        return self.history[-1] if self.history else None

    def series(self) -> tuple[list[float], list[float], list[float]]:
        """Return ``(seconds_ago, down_bps, up_bps)`` ready to plot.

        The x values are negative offsets from now, so the newest point always
        sits at zero and the chart scrolls without rescaling the axis.
        """
        if not self.history:
            return [], [], []
        newest = self.history[-1].timestamp
        offsets = [s.timestamp - newest for s in self.history]
        return offsets, [s.down_bps for s in self.history], [s.up_bps for s in self.history]

    def average(self) -> tuple[float, float]:
        """Mean down/up rate across the retained history."""
        if not self.history:
            return 0.0, 0.0
        count = len(self.history)
        return (
            sum(s.down_bps for s in self.history) / count,
            sum(s.up_bps for s in self.history) / count,
        )
