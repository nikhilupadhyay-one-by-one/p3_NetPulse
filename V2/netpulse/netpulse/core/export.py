"""Writing results out to disk.

Every table in the app can be exported, so a diagnostic session can be attached
to a ticket rather than screenshotted.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def suggested_filename(prefix: str, extension: str = "csv") -> str:
    """A timestamped filename, e.g. ``netpulse-ping-20260917-143002.csv``."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"netpulse-{prefix}-{stamp}.{extension}"


def to_csv(path: str | Path, rows: Sequence[Any], columns: Sequence[str] | None = None) -> Path:
    """Write dataclasses or dicts to CSV. Returns the path written."""
    path = Path(path)
    records = [_as_dict(row) for row in rows]
    if not records:
        path.write_text("", encoding="utf-8")
        return path

    fieldnames = list(columns) if columns else list(records[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    return path


def to_json(path: str | Path, payload: Any, meta: dict | None = None) -> Path:
    """Write a JSON report with a small metadata header."""
    path = Path(path)
    document = {
        "tool": "NetPulse",
        "generated": datetime.now().isoformat(timespec="seconds"),
        **(meta or {}),
        "data": [_as_dict(item) for item in payload] if isinstance(payload, (list, tuple)) else payload,
    }
    path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
    return path


def _as_dict(row: Any) -> dict:
    if is_dataclass(row) and not isinstance(row, type):
        return asdict(row)
    if isinstance(row, dict):
        return row
    return {"value": row}
