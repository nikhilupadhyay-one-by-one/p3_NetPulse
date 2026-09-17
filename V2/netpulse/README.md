# NetPulse

Network diagnostics and live traffic monitoring, in a desktop app.

NetPulse watches throughput on any adapter in real time, shows which process
owns every open socket, runs ping and traceroute with parsed results instead of
console text, and discovers the other devices on your network. It runs on
Windows, macOS and Linux from the same codebase.

![The live traffic screen](docs/traffic.png)

[![CI](https://github.com/YOUR-USERNAME/netpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR-USERNAME/netpulse/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platforms](https://img.shields.io/badge/platform-windows%20%7C%20macos%20%7C%20linux-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## What it does

### Live traffic

Download and upload rates sampled once a second and drawn on a two-minute
scrolling chart, with session totals, peaks and rolling averages. You can watch
one adapter or every adapter combined, and export the samples to CSV.

The chart is hand-drawn with `QPainter` rather than a plotting library. The
vertical scale eases toward the window's peak instead of snapping to it, so one
burst does not make the whole trace jump, and hovering reads out the exact
values under the cursor.

### Connections

![Connections](docs/connections.png)

`netstat` tells you a socket exists. This view also answers the more useful
question — which program opened it — by joining the kernel socket table against
the process table. Filter by process, address, port or state; narrow to sockets
that leave the machine; optionally resolve remote addresses to host names.

### Diagnostics

![Ping](docs/ping.png)

Four tools, each parsing its output into structured readings:

| Tool | What you get |
|---|---|
| **Ping** | Live latency trace, packet loss, min/average/max, jitter, and a plain-language quality verdict |
| **Traceroute** | Hop table with reverse-resolved names and local-vs-internet classification |
| **DNS** | A, AAAA, CNAME, MX, NS, TXT, SOA and PTR records with TTLs |
| **Port scan** | Concurrent TCP connect scan with service names and banner grabs |

![Traceroute](docs/traceroute.png)

### Devices

![Devices](docs/devices.png)

Sweeps your subnet, then identifies what answered: hardware address, vendor,
host name and an inferred device class. Works entirely offline.

---

## How it works

The parts worth reading the source for.

**Throughput comes from kernel counters, not from Task Manager.** Every adapter
keeps a cumulative byte count that the operating system maintains; Task Manager
draws its graph from exactly those numbers. `psutil.net_io_counters()` reads the
same counters directly, so NetPulse samples the source rather than scraping a
window. The rate is a finite difference — `(bytes_now − bytes_before) ÷ elapsed`
— which needs no admin rights and behaves identically on all three platforms.

Counters are unsigned and reset when an adapter is disabled or a driver
reloads. A naive subtraction reports a multi-gigabyte spike when that happens,
so a negative delta is treated as zero. That rule is [tested][tests].

**Command output is parsed, not printed.** `ping` and `traceroute` differ across
platforms — Windows prints round-trip times before the address, Unix prints them
after — and both are translated into the user's language. The parsers key off
the numeric patterns that survive translation (`=12ms`, `ttl=115`) rather than
English words, and pull each field out independently instead of splitting on
position. Captured output from Windows, Linux, macOS and a Spanish-locale
Windows box is checked in the test suite.

**Device discovery uses the ARP cache.** The sweep pings every address in the
subnet concurrently, which makes the OS resolve each responding host's hardware
address. It then reads the ARP table, where those resolutions now sit, and joins
the two on IP. That gets MAC addresses without raw sockets or elevation. Vendors
come from a bundled table of IEEE OUI prefixes, so it needs no internet
connection. Addresses with the locally-administered bit set are reported as
randomised rather than unknown — that is what phones do for Wi-Fi privacy.

**Nothing blocks the interface.** Scans, traces and socket enumeration run on
`QThread` workers that push results back through Qt signals, so rows appear as
they are found and every long operation can be stopped mid-flight. Child
processes are launched with `CREATE_NO_WINDOW` on Windows, so no console flashes
on screen, and in their own process group elsewhere, so cancelling a trace does
not signal the whole app.

---

## Running it

```bash
git clone https://github.com/YOUR-USERNAME/netpulse.git
cd netpulse
pip install -r requirements.txt
python run.py
```

Python 3.10 or newer. `dnspython` is optional — without it the DNS tool falls
back to the standard library and offers A, AAAA and PTR only.

### Terminal version

The same core powers a command-line interface, so everything works over SSH:

```bash
python -m netpulse --cli                        # interactive menu
python -m netpulse --cli watch                  # live throughput
python -m netpulse --cli ping google.com -c 10
python -m netpulse --cli trace github.com
python -m netpulse --cli dns github.com -t MX
python -m netpulse --cli devices
python -m netpulse --cli connections -f chrome
python -m netpulse --cli interfaces
```

Installing the package (`pip install -e .`) also puts `netpulse` and
`netpulse-gui` on your PATH.

### Standalone executable

```bash
pip install pyinstaller
pyinstaller netpulse.spec      # produces dist/NetPulse
```

CI builds a Windows binary on every push to `main`.

---

## Layout

```
netpulse/
├── core/              no Qt imports anywhere in here
│   ├── bandwidth.py     throughput sampling and session statistics
│   ├── connections.py   socket table joined to the process table
│   ├── dns_tools.py     record lookups, dnspython optional
│   ├── interfaces.py    adapter enumeration, default-route detection
│   ├── lanscan.py       subnet sweep and ARP correlation
│   ├── oui.py           offline MAC vendor table
│   ├── ping.py          ping wrapper, output parser, statistics
│   ├── portscan.py      concurrent TCP connect scan
│   ├── traceroute.py    traceroute wrapper and hop parser
│   ├── shell.py         cross-platform subprocess plumbing
│   ├── export.py        CSV and JSON output
│   └── formatting.py    byte, rate, latency and duration formatting
├── ui/                Qt layer, no networking logic
│   ├── theme.py         design tokens and stylesheet
│   ├── widgets.py       task runner, readouts, chart, sparkline
│   ├── traffic.py       live traffic screen
│   ├── connections_view.py
│   ├── diagnostics.py   ping, traceroute, DNS, port scan
│   ├── devices.py       network discovery
│   └── main_window.py   navigation and lifecycle
├── cli.py             terminal interface
└── app.py             GUI entry point
```

The split is strict: `core` never imports Qt, which is why the same code serves
the window, the terminal and the tests.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest
ruff check netpulse tests
```

70 tests covering the parsers, statistics and range arithmetic. They need no
network and no display, and CI runs them on Windows, macOS and Linux against
Python 3.10 and 3.12.

The suite is aimed at the code most likely to break quietly: locale-dependent
regexes, counter-wrap arithmetic, subnet maths, and the jitter and packet-loss
calculations. One of the tests exists because it caught a real bug — rejecting
an oversized subnet was expanding 16.7 million addresses before deciding they
were too many, which took 17 seconds. Checking `num_addresses` first brought the
suite from 17s to 0.09s.

[tests]: tests/test_core.py

---

## A note on the port scanner

Scan hosts you own or have written permission to test. Port scanning other
people's systems is unlawful in many places, including under the Information
Technology Act in India and the Computer Fraud and Abuse Act in the United
States. The tool says so on screen too.

---

## Where it came from

v1 was a single script that printed a numbered menu and shelled out to nine
Windows commands, sending their raw output to the terminal. v2 keeps that menu
— it is still there under `--cli` — and adds a desktop interface, real-time
monitoring, cross-platform support, structured parsing, background threading and
a test suite.

## Ideas not yet built

- Per-process bandwidth rather than per-adapter, which needs packet capture or
  ETW on Windows
- Alert thresholds with system notifications
- Saved sessions, so two captures can be compared
- IPv6 subnet discovery via neighbour discovery
- A tray icon showing current throughput

## License

MIT. See [LICENSE](LICENSE).
