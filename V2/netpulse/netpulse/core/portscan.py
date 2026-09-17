"""Concurrent TCP port scanning.

Uses ``connect_ex`` on a short timeout across a thread pool. The work is almost
entirely waiting on sockets, so threads scale well here despite the GIL — a
/24-sized port range finishes in seconds rather than minutes.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

COMMON_PORTS: dict[int, str] = {
    20: "FTP data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 67: "DHCP server", 68: "DHCP client", 69: "TFTP", 80: "HTTP",
    110: "POP3", 111: "RPC", 123: "NTP", 135: "MS RPC", 137: "NetBIOS name",
    139: "NetBIOS session", 143: "IMAP", 161: "SNMP", 389: "LDAP", 443: "HTTPS",
    445: "SMB", 465: "SMTPS", 514: "Syslog", 587: "SMTP submission", 631: "IPP",
    636: "LDAPS", 993: "IMAPS", 995: "POP3S", 1433: "MS SQL", 1521: "Oracle",
    1723: "PPTP", 1883: "MQTT", 2049: "NFS", 2375: "Docker", 3000: "Dev server",
    3306: "MySQL", 3389: "RDP", 4444: "Metasploit", 5000: "Dev server",
    5060: "SIP", 5432: "PostgreSQL", 5900: "VNC", 5985: "WinRM", 6379: "Redis",
    8000: "HTTP alt", 8080: "HTTP proxy", 8443: "HTTPS alt", 8888: "HTTP alt",
    9000: "HTTP alt", 9090: "HTTP alt", 9200: "Elasticsearch", 11211: "Memcached",
    27017: "MongoDB",
}

QUICK_SCAN_PORTS = sorted(COMMON_PORTS)


@dataclass
class PortResult:
    """One open port."""

    port: int
    service: str
    banner: str | None = None
    latency_ms: float | None = None


def service_name(port: int) -> str:
    """Friendly name for a port, falling back to the system services table."""
    if port in COMMON_PORTS:
        return COMMON_PORTS[port]
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return "Unknown"


def parse_port_range(text: str) -> list[int]:
    """Parse ``"22,80,443,8000-8100"`` into a sorted list of ports.

    Raises :class:`ValueError` on anything malformed so the UI can explain what
    to fix instead of silently scanning nothing.
    """
    ports: set[int] = set()
    for chunk in text.replace(" ", "").split(","):
        if not chunk:
            continue
        if "-" in chunk:
            start_text, _, end_text = chunk.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                raise ValueError(f"{chunk!r} is not a valid range") from None
            if start > end:
                start, end = end, start
            if not (1 <= start <= 65535 and 1 <= end <= 65535):
                raise ValueError("Ports must be between 1 and 65535")
            ports.update(range(start, end + 1))
        else:
            try:
                port = int(chunk)
            except ValueError:
                raise ValueError(f"{chunk!r} is not a valid port") from None
            if not 1 <= port <= 65535:
                raise ValueError("Ports must be between 1 and 65535")
            ports.add(port)

    if not ports:
        raise ValueError("Enter at least one port")
    return sorted(ports)


def check_port(host: str, port: int, timeout: float = 0.6, grab_banner: bool = False) -> PortResult | None:
    """Return a :class:`PortResult` if the port accepts a connection."""
    import time

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    started = time.monotonic()
    try:
        if sock.connect_ex((host, port)) != 0:
            return None
        latency = (time.monotonic() - started) * 1000
        banner = _read_banner(sock) if grab_banner else None
        return PortResult(port=port, service=service_name(port), banner=banner, latency_ms=latency)
    except OSError:
        return None
    finally:
        sock.close()


def scan(
    host: str,
    ports: list[int],
    timeout: float = 0.6,
    workers: int = 200,
    grab_banner: bool = False,
    on_result: Callable[[PortResult], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    stop: threading.Event | None = None,
) -> list[PortResult]:
    """Scan ``ports`` on ``host``, reporting results as they are found."""
    try:
        target = socket.gethostbyname(host)
    except OSError:
        raise LookupError(f"Could not resolve {host}") from None

    found: list[PortResult] = []
    total = len(ports)
    done = 0

    with ThreadPoolExecutor(max_workers=min(max(1, workers), 500)) as pool:
        futures = {pool.submit(check_port, target, port, timeout, grab_banner): port for port in ports}
        for future in as_completed(futures):
            done += 1
            if stop is not None and stop.is_set():
                for pending in futures:
                    pending.cancel()
                break
            result = future.result()
            if result is not None:
                found.append(result)
                if on_result is not None:
                    on_result(result)
            if on_progress is not None:
                on_progress(done, total)

    found.sort(key=lambda r: r.port)
    return found


def iter_scan(host: str, ports: list[int], **kwargs) -> Iterator[PortResult]:
    """Generator wrapper for callers that prefer iteration to callbacks."""
    results: list[PortResult] = []
    scan(host, ports, on_result=results.append, **kwargs)
    yield from results


def _read_banner(sock: socket.socket, limit: int = 128) -> str | None:
    """Read whatever a service volunteers on connect. Many say nothing."""
    try:
        sock.settimeout(0.8)
        data = sock.recv(limit)
    except OSError:
        return None
    if not data:
        return None
    return data.decode("utf-8", "replace").strip().splitlines()[0][:limit] or None
