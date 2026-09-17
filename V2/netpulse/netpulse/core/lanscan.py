"""Discovering the other devices on your network.

The sweep runs in two passes. First it pings every address in the subnet
concurrently, which forces the OS to resolve each responding host's hardware
address. Then it reads the ARP table, where those resolutions now sit, and joins
the two on IP. That gets MAC addresses and vendor names without raw sockets or
administrator rights.
"""

from __future__ import annotations

import ipaddress
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import oui
from .interfaces import primary_interface
from .ping import ping_once
from .shell import IS_WINDOWS, run, which
from .traceroute import reverse_lookup

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")

MAX_SWEEP_HOSTS = 1024

# Vendor -> the kind of thing that vendor almost always is on a home or office
# network. Deliberately conservative: a wrong guess is worse than no guess.
_DEVICE_CLASSES: dict[str, str] = {
    "Roku": "Streaming box",
    "Sonos": "Speaker",
    "Amazon": "Echo or Fire device",
    "Google Nest": "Smart home",
    "Nest": "Smart home",
    "Philips Hue": "Smart lighting",
    "LIFX": "Smart lighting",
    "Wyze": "Camera",
    "Belkin/Wemo": "Smart plug",
    "HP": "Printer",
    "Raspberry Pi": "Single-board computer",
    "Synology": "Network storage",
    "QNAP": "Network storage",
    "VMware": "Virtual machine",
    "VirtualBox": "Virtual machine",
    "QEMU/KVM": "Virtual machine",
    "Xen": "Virtual machine",
    "Docker": "Container",
    "Microsoft (Hyper-V)": "Virtual machine",
    "Parallels": "Virtual machine",
    "Apple": "Phone or computer",
    "Samsung": "Phone or TV",
    "Xiaomi": "Phone or smart home",
    "Huawei": "Phone or router",
    "TP-Link": "Network equipment",
    "Netgear": "Network equipment",
    "D-Link": "Network equipment",
    "Ubiquiti": "Network equipment",
    "ASUS": "Router or computer",
    "Cisco": "Network equipment",
    "Cisco Meraki": "Network equipment",
    "Cisco-Linksys": "Network equipment",
    "Aruba": "Network equipment",
    "Fortinet": "Firewall",
    "Polycom": "Conference phone",
}


@dataclass
class Device:
    """A host found on the local network."""

    ip: str
    mac: str | None = None
    vendor: str | None = None
    hostname: str | None = None
    rtt_ms: float | None = None
    is_self: bool = False
    is_gateway: bool = False

    @property
    def role(self) -> str:
        """What this device probably is.

        The vendor is a strong hint — a Roku OUI is a streaming box, an HP OUI
        on a home network is almost always a printer. Where there is no hint,
        say so rather than repeating the vendor column back.
        """
        if self.is_self:
            return "This computer"
        if self.is_gateway:
            return "Router"
        if not self.vendor:
            return "—"
        return _DEVICE_CLASSES.get(self.vendor, "—")

    # Kept so older scripts written against v2.0 keep working.
    label = role


def default_subnet() -> str | None:
    """The CIDR of the adapter carrying the default route."""
    nic = primary_interface()
    return nic.cidr if nic else None


def parse_subnet(text: str) -> list[str]:
    """Expand a CIDR into a list of host addresses to probe.

    Raises :class:`ValueError` for bad input or for ranges too large to sweep in
    a reasonable time.
    """
    text = text.strip()
    if not text:
        raise ValueError("Enter a subnet, for example 192.168.1.0/24")
    try:
        network = ipaddress.ip_network(text, strict=False)
    except ValueError as exc:
        raise ValueError(str(exc)) from None

    if network.version != 4:
        raise ValueError("Subnet sweeps support IPv4 only")

    # Check the size before expanding. A /8 holds 16.7 million addresses, and
    # building that list to measure it would hang for half a minute.
    if network.num_addresses > MAX_SWEEP_HOSTS + 2:
        raise ValueError(
            f"{network} holds {network.num_addresses:,} addresses. "
            "Narrow it to /22 or smaller."
        )

    return [str(host) for host in network.hosts()] or [str(network.network_address)]


def read_arp_table() -> dict[str, str]:
    """Map IP -> MAC from the system ARP cache."""
    if IS_WINDOWS:
        command = ["arp", "-a"]
    elif which("ip"):
        command = ["ip", "neigh", "show"]
    elif which("arp"):
        command = ["arp", "-a"]
    else:
        return {}

    code, output = run(command, timeout=10)
    if code not in (0, 1):
        return {}

    table: dict[str, str] = {}
    for line in output.splitlines():
        ip_match = _IPV4.search(line)
        mac_match = _MAC.search(line)
        if not ip_match or not mac_match:
            continue
        mac = oui.normalise(mac_match.group(0))
        if mac and mac != "ff:ff:ff:ff:ff:ff":
            table[ip_match.group(0)] = mac
    return table


def default_gateway() -> str | None:
    """The router's address, read from the routing table."""
    if IS_WINDOWS:
        code, output = run(["route", "print", "-4"], timeout=10)
        if code != 0:
            return None
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "0.0.0.0":
                return parts[2] if _IPV4.fullmatch(parts[2]) else None
        return None

    if which("ip"):
        code, output = run(["ip", "route", "show", "default"], timeout=10)
        if code == 0:
            match = _IPV4.search(output)
            return match.group(0) if match else None

    code, output = run(["netstat", "-rn"], timeout=10)
    if code != 0:
        return None
    for line in output.splitlines():
        parts = line.split()
        if parts and parts[0] in ("default", "0.0.0.0") and len(parts) > 1:
            match = _IPV4.search(parts[1])
            if match:
                return match.group(0)
    return None


def sweep(
    subnet: str,
    timeout_ms: int = 700,
    workers: int = 128,
    resolve_names: bool = True,
    on_device: Callable[[Device], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    stop: threading.Event | None = None,
) -> list[Device]:
    """Discover live hosts in ``subnet``."""
    hosts = parse_subnet(subnet)
    total = len(hosts)
    gateway = default_gateway()
    own_ip = None
    nic = primary_interface()
    if nic:
        own_ip = nic.ipv4

    alive: list[Device] = []
    done = 0
    lock = threading.Lock()

    def probe(address: str) -> Device | None:
        if stop is not None and stop.is_set():
            return None
        reply = ping_once(address, timeout_ms=timeout_ms)
        if not reply.success:
            return None
        return Device(ip=address, rtt_ms=reply.rtt_ms)

    with ThreadPoolExecutor(max_workers=min(max(1, workers), 256)) as pool:
        for device in pool.map(probe, hosts):
            with lock:
                done += 1
                if on_progress is not None:
                    on_progress(done, total)
            if device is None:
                continue
            alive.append(device)

    if stop is not None and stop.is_set():
        return alive

    # The sweep has just populated the ARP cache, so read it now.
    arp = read_arp_table()
    for device in alive:
        device.mac = arp.get(device.ip)
        if device.mac:
            device.vendor = oui.lookup(device.mac)
        device.is_self = device.ip == own_ip
        device.is_gateway = device.ip == gateway
        if resolve_names:
            device.hostname = reverse_lookup(device.ip, timeout=0.6)
        if on_device is not None:
            on_device(device)

    alive.sort(key=lambda d: ipaddress.ip_address(d.ip))
    return alive
