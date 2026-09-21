"""Create a reproducible list of the 90 most recent complete service days."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path


INDEX_PATH = Path("data/raw/subway-performance-index.csv")
OUTPUT_PATH = Path("data/processed/study_window.csv")
WINDOW_DAYS = 90


def main() -> None:
    with INDEX_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    cutoff = date.today() - timedelta(days=1)
    complete_rows = [
        row for row in rows if date.fromisoformat(row["service_date"]) <= cutoff
    ]
    latest_rows = sorted(complete_rows, key=lambda row: row["service_date"], reverse=True)[
        :WINDOW_DAYS
    ]
    latest_rows.sort(key=lambda row: row["service_date"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=["service_date", "file_url", "size_bytes"])
        writer.writeheader()
        writer.writerows(
            {
                "service_date": row["service_date"],
                "file_url": row["file_url"],
                "size_bytes": row["size_bytes"],
            }
            for row in latest_rows
        )

    dates = [date.fromisoformat(row["service_date"]) for row in latest_rows]
    missing_days = (dates[-1] - dates[0]).days + 1 - len(dates)
    print(f"Study window: {dates[0]} to {dates[-1]}")
    print(f"Service dates: {len(dates)}")
    print(f"Missing calendar days: {missing_days}")


if __name__ == "__main__":
    main()
