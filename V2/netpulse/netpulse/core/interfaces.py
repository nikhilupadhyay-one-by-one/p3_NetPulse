"""Enumerating adapters and working out which one carries the traffic."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass

import psutil


@dataclass
class Interface:
    """A network adapter as NetPulse presents it."""

    name: str
    is_up: bool = False
    ipv4: str | None = None
    netmask: str | None = None
    ipv6: str | None = None
    mac: str | None = None
    speed_mbps: int = 0
    mtu: int = 0
    bytes_recv: int = 0
    bytes_sent: int = 0
    is_loopback: bool = False

    @property
    def cidr(self) -> str | None:
        """The adapter's subnet in CIDR form, e.g. ``192.168.1.0/24``."""
        if not self.ipv4 or not self.netmask:
            return None
        try:
            network = ipaddress.ip_network(f"{self.ipv4}/{self.netmask}", strict=False)
        except ValueError:
            return None
        return str(network)

    @property
    def status(self) -> str:
        return "Connected" if self.is_up else "Down"


def list_interfaces(include_down: bool = False) -> list[Interface]:
    """Return every adapter on the machine, best candidates first."""
    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)

    interfaces: list[Interface] = []
    for name, addr_list in addresses.items():
        nic = Interface(name=name)
        stat = stats.get(name)
        if stat is not None:
            nic.is_up = stat.isup
            nic.speed_mbps = stat.speed
            nic.mtu = stat.mtu

        io = counters.get(name)
        if io is not None:
            nic.bytes_recv = io.bytes_recv
            nic.bytes_sent = io.bytes_sent

        for addr in addr_list:
            if addr.family == socket.AF_INET and nic.ipv4 is None:
                nic.ipv4 = addr.address
                nic.netmask = addr.netmask
            elif addr.family == socket.AF_INET6 and nic.ipv6 is None:
                # Strip the zone index Windows/Linux append to link-local v6.
                nic.ipv6 = addr.address.split("%")[0]
            elif addr.family == psutil.AF_LINK and nic.mac is None:
                nic.mac = _normalise_mac(addr.address)

        nic.is_loopback = _is_loopback(nic)
        if nic.is_up or include_down:
            interfaces.append(nic)

    interfaces.sort(key=lambda i: (i.is_loopback, i.ipv4 is None, -i.bytes_recv))
    return interfaces


def local_ip() -> str | None:
    """The address the OS would use to reach the internet.

    Connecting a UDP socket does not send a packet; it just asks the routing
    table which source address applies. That makes this a cheap, offline-safe
    way to find the default-route adapter.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.settimeout(0.5)
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def primary_interface() -> Interface | None:
    """The adapter that owns the default route, falling back to the busiest."""
    interfaces = list_interfaces()
    if not interfaces:
        return None

    address = local_ip()
    if address:
        for nic in interfaces:
            if nic.ipv4 == address:
                return nic

    for nic in interfaces:
        if not nic.is_loopback and nic.ipv4:
            return nic
    return interfaces[0]


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def fqdn() -> str:
    try:
        return socket.getfqdn()
    except OSError:
        return hostname()


def _is_loopback(nic: Interface) -> bool:
    if nic.ipv4 and nic.ipv4.startswith("127."):
        return True
    if nic.ipv6 == "::1":
        return True
    return nic.name.lower().startswith(("lo", "loopback"))


def _normalise_mac(raw: str) -> str | None:
    cleaned = raw.replace("-", ":").lower().strip()
    parts = [p for p in cleaned.split(":") if p]
    if len(parts) != 6:
        return None
    if all(p == "00" for p in parts):
        return None
    return ":".join(p.zfill(2) for p in parts)
