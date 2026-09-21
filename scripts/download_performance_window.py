"""Download the official daily subway-performance files in the study window."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen


WINDOW_PATH = Path("data/processed/study_window.csv")
DESTINATION_DIR = Path("data/raw/daily-performance")
MANIFEST_PATH = DESTINATION_DIR / "manifest.json"


def main() -> None:
    with WINDOW_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    DESTINATION_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"retrieved_at_utc": datetime.now(UTC).isoformat(), "files": []}

    for position, row in enumerate(rows, start=1):
        destination = DESTINATION_DIR / f"{row['service_date']}.parquet"
        print(f"[{position}/{len(rows)}] {row['service_date']}")
        if destination.exists() and destination.stat().st_size > 0:
            payload = destination.read_bytes()
        else:
            with urlopen(row["file_url"], timeout=120) as response:
                payload = response.read()
            destination.write_bytes(payload)
        manifest["files"].append(
            {
                "service_date": row["service_date"],
                "source_url": row["file_url"],
                "file": str(destination).replace("\\", "/"),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
