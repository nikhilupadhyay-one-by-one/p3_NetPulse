# Changelog

## 3.1.0 — Single-file rewrite
- Rewritten into one `app.py` for easier reading, debugging and interview walkthroughs.
- Desktop tabs: traffic, connections, diagnostics and local devices.
- CLI commands for interfaces, ping, traceroute, DNS, TCP scanning, connections and discovery.
- CSV/JSON export for displayed tables.
- Optional dnspython with stdlib fallback for basic DNS.
- Reduced scope relative to prior V3: curated OUI database, custom painted chart, per-process traffic, full progress/cancel flows and deep platform parsing are not retained in this single-file rewrite. See README limitations.
