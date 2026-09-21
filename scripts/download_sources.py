"""Download the official MBTA source files used by this project.

Run from the repository root:
    python scripts/download_sources.py

The script deliberately saves source files unchanged. Cleaning and analysis
happen in separate scripts so the project can document every transformation.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen


RAW_DIR = Path("data/raw")
MANIFEST_PATH = RAW_DIR / "source_manifest.json"
SOURCES = {
    "subway_performance_index": (
        "https://performancedata.mbta.com/lamp/subway-on-time-performance-v1/index.csv",
        "subway-performance-index.csv",
    ),
    "alerts": (
        "https://performancedata.mbta.com/lamp/tableau/alerts/LAMP_RT_ALERTS.parquet",
        "LAMP_RT_ALERTS.parquet",
    ),
    "stops": (
        "https://performancedata.mbta.com/lamp/tableau/rail/LAMP_static_stops.parquet",
        "LAMP_static_stops.parquet",
    ),
}


def download(url: str, destination: Path) -> dict[str, str | int]:
    with urlopen(url, timeout=120) as response:
        payload = response.read()

    destination.write_bytes(payload)
    return {
        "url": url,
        "file": str(destination).replace("\\", "/"),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
    }


def newest_dates(index_path: Path, count: int = 90) -> list[str]:
    with index_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    date_column = next(
        (column for column in ("service_date", "date", "serviceDate") if column in rows[0]),
        None,
    )
    if date_column is None:
        raise ValueError(f"Could not find a service-date field in {rows[0].keys()}")

    return sorted({row[date_column] for row in rows if row.get(date_column)}, reverse=True)[:count]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"sources": {}}

    for name, (url, filename) in SOURCES.items():
        print(f"Downloading {name}...")
        manifest["sources"][name] = download(url, RAW_DIR / filename)

    index_path = RAW_DIR / SOURCES["subway_performance_index"][1]
    manifest["candidate_study_dates"] = newest_dates(index_path)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
