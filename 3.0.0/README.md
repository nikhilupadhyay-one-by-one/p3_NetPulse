# NetPulse 3.0.0

Cross-platform network monitoring and diagnostic desktop application, rewritten as a **single application source file (`app.py`)**. It uses Python, PySide6 and psutil. The optional `dnspython` package enables advanced DNS record lookups.

## Features
- Live adapter-level receive/send rates and session totals
- Socket/process connection table with filtering
- Ping analysis (latency, packet loss, min/average/max and jitter when parsable)
- Traceroute parsing for Windows and Unix-like systems
- DNS A/AAAA using stdlib fallback; advanced DNS record types with dnspython
- TCP port scan with common service labels and flexible port/range input
- Local IPv4 discovery based on TCP probes plus ARP-cache entries
- CSV and JSON export for table data
- CLI and desktop UI share the same functions

## Setup
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

## CLI
```bash
python app.py interfaces
python app.py ping example.com -c 5
python app.py trace example.com --hops 20
python app.py dns example.com -t MX
python app.py scan 192.168.1.1 22,80,443,8000-8100
python app.py connections
python app.py devices 192.168.1.0/24
```

## Limitations and honest scope
- Bandwidth is measured at the adapter level; connections are attributed to processes, but per-process bandwidth accounting is not implemented.
- Port scanning only tests TCP connection availability. It is not an exploit or vulnerability scanner.
- Device discovery uses limited TCP probes and the local ARP cache. Devices that block probes may not be detected; MAC/vendor identification is not bundled in this single-file rewrite.
- Some network commands may require elevated privileges or be absent on the host OS.
- Parsing of system ping/traceroute output varies by platform and locale; raw output is not currently shown in the GUI for every tool.
- The desktop UI needs PySide6; CLI-only commands do not launch the GUI unless no command is supplied.

## Project layout
```
NetPulse/
  app.py                 # All application code
  requirements.txt
  README.md
  CHANGELOG.md
```

This deliberately prioritizes a single readable application file over a multi-module architecture. No telemetry or remote data service is used.
