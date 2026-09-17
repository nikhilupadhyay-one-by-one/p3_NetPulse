"""Terminal interface.

The same core modules power this and the GUI, so anything you can see in the
window you can also get over SSH. Running with no arguments opens the numbered
menu the first version of NetPulse used.
"""

from __future__ import annotations

import argparse
import sys
import time

from .core import dns_tools, lanscan, portscan, traceroute
from .core.bandwidth import ALL_INTERFACES, BandwidthMonitor
from .core.connections import list_connections, summarise
from .core.formatting import human_bytes, human_latency, human_speed
from .core.interfaces import hostname, list_interfaces, primary_interface
from .core.ping import PingStats, ping_stream
from .version import APP_NAME, TAGLINE, __version__

# ANSI colours, disabled when output is piped to a file.
_TTY = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def dim(text: str) -> str:
    return _c(text, "2")


def bold(text: str) -> str:
    return _c(text, "1")


def cyan(text: str) -> str:
    return _c(text, "36")


def amber(text: str) -> str:
    return _c(text, "33")


def red(text: str) -> str:
    return _c(text, "31")


def green(text: str) -> str:
    return _c(text, "32")


def banner() -> None:
    print()
    print(bold(f"  {APP_NAME} {__version__}"))
    print(dim(f"  {TAGLINE}"))
    print(dim("  " + "─" * 52))
    print()


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_watch(args: argparse.Namespace) -> int:
    """Live throughput, refreshed in place."""
    monitor = BandwidthMonitor(args.interface or ALL_INTERFACES)
    target = args.interface or "all interfaces"
    print(f"Watching {cyan(target)} on {hostname()}.  Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
            sample = monitor.sample()
            if sample is None:
                continue
            line = (
                f"  {cyan('↓')} {human_speed(sample.down_bps):>12}"
                f"   {amber('↑')} {human_speed(sample.up_bps):>12}"
                f"   {dim('session')} {human_bytes(sample.session_down + sample.session_up):>10}"
            )
            print(f"\r{line}", end="", flush=True)
    except KeyboardInterrupt:
        average_down, average_up = monitor.average()
        print("\n")
        print(f"  Average down  {human_speed(average_down)}")
        print(f"  Average up    {human_speed(average_up)}")
        print(f"  Peak down     {human_speed(monitor.peak_down)}")
        print(f"  Peak up       {human_speed(monitor.peak_up)}")
    return 0


def cmd_ping(args: argparse.Namespace) -> int:
    stats = PingStats()
    count = None if args.count == 0 else args.count
    print(f"Pinging {cyan(args.host)}\n")
    try:
        for reply in ping_stream(args.host, count=count, interval=args.interval):
            stats.add(reply)
            marker = green("·") if reply.success else red("×")
            print(f"  {marker} {reply}")
    except KeyboardInterrupt:
        print()

    print()
    print(f"  Sent {stats.sent}, received {stats.received}, lost {stats.lost} ({stats.loss_pct:.0f}%)")
    if stats.rtts:
        print(
            f"  min {human_latency(stats.minimum)}   "
            f"avg {human_latency(stats.average)}   "
            f"max {human_latency(stats.maximum)}   "
            f"jitter {human_latency(stats.jitter)}"
        )
        print(f"  Connection quality: {bold(stats.quality)}")
    return 0 if stats.received else 1


def cmd_trace(args: argparse.Namespace) -> int:
    print(f"Tracing the route to {cyan(args.host)}\n")
    count = 0
    for hop in traceroute.trace(args.host, max_hops=args.max_hops):
        count += 1
        if hop.timed_out or hop.average is None:
            print(f"  {hop.number:>2}  {dim('no response')}")
            continue
        name = f"  {dim(hop.hostname)}" if hop.hostname else ""
        scope = amber("local") if hop.is_private else cyan("internet")
        print(f"  {hop.number:>2}  {hop.address:<16} {human_latency(hop.average):>9}  {scope}{name}")
    return 0 if count else 1


def cmd_dns(args: argparse.Namespace) -> int:
    try:
        records = dns_tools.lookup(args.host, args.type)
    except LookupError as exc:
        print(red(f"  {exc}"))
        return 1
    print(f"{args.type} records for {cyan(args.host)}\n")
    for record in records:
        ttl = dim(f"  ttl {record.ttl}s") if record.ttl else ""
        print(f"  {record.value}{ttl}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        ports = portscan.parse_port_range(args.ports)
    except ValueError as exc:
        print(red(f"  {exc}"))
        return 2

    print(f"Scanning {len(ports):,} ports on {cyan(args.host)}\n")
    try:
        results = portscan.scan(args.host, ports, grab_banner=True)
    except LookupError as exc:
        print(red(f"  {exc}"))
        return 1

    if not results:
        print("  No open ports found.")
        return 0
    for result in results:
        banner_text = dim(f"  {result.banner}") if result.banner else ""
        print(f"  {green(str(result.port)):>12}  {result.service}{banner_text}")
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    subnet = args.subnet or lanscan.default_subnet()
    if not subnet:
        print(red("  Could not work out your subnet. Pass one with --subnet."))
        return 1

    print(f"Sweeping {cyan(subnet)}. This takes a moment.\n")
    try:
        devices = lanscan.sweep(subnet)
    except ValueError as exc:
        print(red(f"  {exc}"))
        return 2

    if not devices:
        print("  Nothing answered. Many devices ignore ping by default.")
        return 0

    for device in devices:
        name = device.hostname or device.vendor or ""
        role = f"  {amber(device.role)}" if device.role != "—" else ""
        print(f"  {device.ip:<16} {(device.mac or '—'):<19} {name}{role}")
    print(f"\n  {len(devices)} devices found.")
    return 0


def cmd_connections(args: argparse.Namespace) -> int:
    rows = list_connections()
    if args.filter:
        rows = [c for c in rows if c.matches(args.filter)]
    stats = summarise(rows)

    print(f"{stats['total']} sockets across {stats['processes']} processes\n")
    for connection in rows[: args.limit]:
        print(
            f"  {connection.process[:22]:<22} {connection.protocol:<6} "
            f"{connection.local:<24} {connection.remote:<28} {connection.state}"
        )
    if len(rows) > args.limit:
        print(dim(f"\n  … and {len(rows) - args.limit} more. Raise --limit to see them."))
    return 0


def cmd_interfaces(args: argparse.Namespace) -> int:
    active = primary_interface()
    for nic in list_interfaces(include_down=True):
        marker = cyan(" ← default route") if active and nic.name == active.name else ""
        status = green(nic.status) if nic.is_up else dim(nic.status)
        print(f"  {bold(nic.name):<24} {status}{marker}")
        print(f"    address  {nic.ipv4 or '—'}   subnet {nic.cidr or '—'}")
        print(f"    mac      {nic.mac or '—'}   mtu {nic.mtu or '—'}")
        print(
            f"    traffic  {human_bytes(nic.bytes_recv)} in, "
            f"{human_bytes(nic.bytes_sent)} out\n"
        )
    return 0


# --------------------------------------------------------------------------- #
# Interactive menu — the original NetPulse experience, kept for old muscle memory
# --------------------------------------------------------------------------- #

MENU = [
    ("Watch live traffic", lambda: cmd_watch(_ns(interface=None))),
    ("Ping a host", lambda: cmd_ping(_ns(host=_ask("Host or IP"), count=4, interval=1.0))),
    ("Trace a route", lambda: cmd_trace(_ns(host=_ask("Host or IP"), max_hops=30))),
    ("Look up DNS records", lambda: cmd_dns(_ns(host=_ask("Host"), type=_ask("Record type", "A").upper()))),
    ("Scan ports", lambda: cmd_scan(_ns(host=_ask("Host or IP"), ports=_ask("Ports", "1-1024")))),
    ("Find devices on this network", lambda: cmd_devices(_ns(subnet=None))),
    ("List connections", lambda: cmd_connections(_ns(filter=None, limit=40))),
    ("Show network adapters", lambda: cmd_interfaces(_ns())),
]


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"  {prompt}{suffix}: ").strip()
    return answer or default


def interactive() -> int:
    banner()
    while True:
        for index, (label, _) in enumerate(MENU, start=1):
            print(f"  {cyan(str(index))}  {label}")
        print(f"  {dim('0')}  {dim('Quit')}\n")

        raw = input("  Choose: ").strip()
        if raw in ("0", "q", "quit", "exit"):
            print("\n  Goodbye.\n")
            return 0
        if not raw.isdigit() or not 1 <= int(raw) <= len(MENU):
            print(red(f"\n  {raw!r} is not on the menu. Pick a number from the list.\n"))
            continue

        print()
        try:
            MENU[int(raw) - 1][1]()
        except KeyboardInterrupt:
            print("\n  Stopped.")
        except Exception as exc:  # a failed tool should not end the session
            print(red(f"  {exc}"))
        print()


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netpulse",
        description=f"{APP_NAME} — {TAGLINE}",
        epilog="Run with no arguments for the interactive menu, or 'netpulse-gui' for the desktop app.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    watch = subparsers.add_parser("watch", help="live download and upload rates")
    watch.add_argument("-i", "--interface", help="adapter name; defaults to all of them")
    watch.set_defaults(func=cmd_watch)

    ping_parser = subparsers.add_parser("ping", help="ping a host and summarise the result")
    ping_parser.add_argument("host")
    ping_parser.add_argument("-c", "--count", type=int, default=4, help="0 runs until interrupted")
    ping_parser.add_argument("-I", "--interval", type=float, default=1.0, help="seconds between requests")
    ping_parser.set_defaults(func=cmd_ping)

    trace = subparsers.add_parser("trace", help="trace the route to a host")
    trace.add_argument("host")
    trace.add_argument("-m", "--max-hops", type=int, default=30)
    trace.set_defaults(func=cmd_trace)

    dns = subparsers.add_parser("dns", help="look up DNS records")
    dns.add_argument("host")
    dns.add_argument("-t", "--type", default="A", choices=dns_tools.RECORD_TYPES)
    dns.set_defaults(func=cmd_dns)

    scan = subparsers.add_parser("scan", help="scan TCP ports on a host you control")
    scan.add_argument("host")
    scan.add_argument("-p", "--ports", default="1-1024", help="e.g. 22,80,443,8000-8100")
    scan.set_defaults(func=cmd_scan)

    devices = subparsers.add_parser("devices", help="find devices on the local network")
    devices.add_argument("-s", "--subnet", help="e.g. 192.168.1.0/24; detected automatically by default")
    devices.set_defaults(func=cmd_devices)

    conns = subparsers.add_parser("connections", help="list open sockets by process")
    conns.add_argument("-f", "--filter", help="match process, address, port or state")
    conns.add_argument("-n", "--limit", type=int, default=40)
    conns.set_defaults(func=cmd_connections)

    interfaces = subparsers.add_parser("interfaces", help="show network adapters")
    interfaces.set_defaults(func=cmd_interfaces)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command is None:
        return interactive()

    banner()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n  Stopped.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
