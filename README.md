# NetPulse V3

A lightweight desktop network monitor and diagnostic utility. V3 keeps the main application in **one Python file (`main.py`)** so it is easier to read, explain, and modify.

## Features
- **Traffic:** samples OS network counters once per second and calculates upload/download rates.
- **Connections:** displays sockets, protocol, local/remote endpoint, state and process (refresh manually; some process details may require elevated permissions).
- **Diagnostics:** ping, traceroute and DNS lookup for hosts you are authorized to test.
- **Simple UI:** three tabs, no database, no background service, and no telemetry built into the app.

## Requirements
- Python 3.10 or newer
- Windows, Linux or macOS (command availability varies by OS)

## Run from source
```bash
python -m venv .venv
```
Windows:
```bat
.venv\Scripts\activate
```
Linux/macOS:
```bash
source .venv/bin/activate
```
Then:
```bash
pip install -r requirements.txt
python main.py
```

## How it works
- **Throughput:** `psutil.net_io_counters()` returns cumulative byte counters. NetPulse subtracts the previous sample and divides by elapsed time to calculate a rate.
- **Connections:** `psutil.net_connections()` lists socket information; process names are looked up by PID.
- **Diagnostics:** DNS uses Python's `socket` library. Ping and traceroute call the operating system's command-line utilities and display their output.

## Limitations and safety
- Connection visibility can be limited by operating-system permissions.
- Traceroute may not be installed; firewall rules can block diagnostics.
- A port or connection being visible does not, by itself, indicate malicious activity.
- Use network diagnostics only on systems/networks you own or are authorized to assess.
- This is a local diagnostic utility, not a firewall, antivirus, packet analyzer or security scanner.

## V3 changes
V3 deliberately consolidates the app into a single readable file and reduces scope to the core features. It removes the separate view/core module architecture from the earlier build and keeps the interface and operations straightforward for learning and interview discussion.

The earlier versions are preserved in the repository's `.old_builds` folder for reference.
