"""Human-readable formatting for byte counts, transfer rates and durations.

Everything the readouts display goes through here so the units stay consistent
across the dashboard, the CSV exports and the CLI.
"""

from __future__ import annotations

_BYTE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
_BIT_UNITS = ("bps", "Kbps", "Mbps", "Gbps", "Tbps")


def human_bytes(count: float, precision: int = 1) -> str:
    """Format a byte count using binary (1024) steps, e.g. ``1.4 GB``."""
    count = float(max(count, 0))
    unit_index = 0
    while count >= 1024 and unit_index < len(_BYTE_UNITS) - 1:
        count /= 1024
        unit_index += 1
    # Whole bytes never need a decimal point.
    digits = 0 if unit_index == 0 else precision
    return f"{count:.{digits}f} {_BYTE_UNITS[unit_index]}"


def human_speed(bytes_per_second: float, precision: int = 1) -> str:
    """Format a transfer rate in bytes/sec, e.g. ``2.4 MB/s``."""
    return f"{human_bytes(bytes_per_second, precision)}/s"


def human_bits(bytes_per_second: float, precision: int = 1) -> str:
    """Format a transfer rate the way ISPs quote it, e.g. ``94.2 Mbps``.

    Uses decimal (1000) steps because that is the convention for line rates.
    """
    bits = float(max(bytes_per_second, 0)) * 8
    unit_index = 0
    while bits >= 1000 and unit_index < len(_BIT_UNITS) - 1:
        bits /= 1000
        unit_index += 1
    return f"{bits:.{precision}f} {_BIT_UNITS[unit_index]}"


def split_speed(bytes_per_second: float, precision: int = 1) -> tuple[str, str]:
    """Return ``(value, unit)`` so a readout can size the two parts differently."""
    text = human_speed(bytes_per_second, precision)
    value, unit = text.split(" ", 1)
    return value, unit


def human_duration(seconds: float) -> str:
    """Format an elapsed time as ``1h 04m 09s`` / ``4m 09s`` / ``9s``."""
    seconds = int(max(seconds, 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def human_latency(milliseconds: float | None) -> str:
    """Format a round-trip time, keeping sub-millisecond values readable."""
    if milliseconds is None:
        return "—"
    if milliseconds < 1:
        return f"{milliseconds:.2f} ms"
    if milliseconds < 100:
        return f"{milliseconds:.1f} ms"
    return f"{milliseconds:.0f} ms"
