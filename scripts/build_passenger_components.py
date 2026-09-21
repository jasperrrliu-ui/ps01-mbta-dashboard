"""Build rider-time components from MBTA LAMP files one service day at a time."""

from __future__ import annotations

import csv
import gc
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow.parquet as pq


RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("data/processed")
EASTERN = ZoneInfo("America/New_York")
LINES = {"Blue", "Green", "Mattapan", "Orange", "Red"}
TRANSFER_STATIONS = {
    "place-asmnl", "place-dwnxg", "place-gover", "place-haecl", "place-north", "place-pktrm", "place-state",
}


def study_dates() -> list[str]:
    with (OUTPUT_DIR / "study_window.csv").open(newline="", encoding="utf-8") as source:
        return [row["service_date"] for row in csv.DictReader(source)]


def write_rows(path: str, columns: list[str], rows: list[dict[str, object]]) -> None:
    with (OUTPUT_DIR / path).open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=90)
    args = parser.parse_args()
    dates = study_dates()[args.start:args.end]
    suffix = f"_part_{args.start}_{args.end}.csv"
    wait_totals: defaultdict[tuple, list[float]] = defaultdict(lambda: [0, 0.0])
    travel_totals: defaultdict[tuple, list[float]] = defaultdict(lambda: [0, 0.0])
    transfer_totals: defaultdict[tuple, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    edge_counts: Counter[tuple] = Counter()
    columns = [
        "stop_timestamp", "move_timestamp", "scheduled_arrival_time", "scheduled_departure_time",
        "travel_time_seconds", "scheduled_travel_time", "headway_trunk_seconds", "scheduled_headway_trunk",
        "trunk_route_id", "parent_station", "stop_sequence", "trip_id", "start_time", "direction_id",
    ]

    for offset, service_date in enumerate(dates):
        frame = pq.read_table(RAW_DIR / "daily-performance" / f"{service_date}.parquet", columns=columns).to_pandas()
        frame = frame[frame["trunk_route_id"].isin(LINES)].dropna(subset=["stop_timestamp", "parent_station"])
        actual = pd.to_datetime(frame["stop_timestamp"], unit="s", utc=True).dt.tz_convert(EASTERN)
        frame["service_hour"] = actual.dt.hour
        frame["actual_seconds"] = actual.dt.hour * 3600 + actual.dt.minute * 60 + actual.dt.second

        wait = frame.dropna(subset=["headway_trunk_seconds", "scheduled_headway_trunk"])
        wait = wait.assign(excess_wait=((wait["headway_trunk_seconds"] - wait["scheduled_headway_trunk"]).clip(lower=0) / 2))
        for row in wait.groupby(["trunk_route_id", "parent_station", "service_hour"])["excess_wait"].agg(["count", "sum"]).reset_index().itertuples(index=False):
            total = wait_totals[(row.trunk_route_id, row.parent_station, row.service_hour)]
            total[0] += row.count
            total[1] += row.sum

        travel = frame.dropna(subset=["travel_time_seconds", "scheduled_travel_time"])
        travel = travel.assign(excess_travel=(travel["travel_time_seconds"] - travel["scheduled_travel_time"]).clip(lower=0))
        for row in travel.groupby(["trunk_route_id", "parent_station", "service_hour"])["excess_travel"].agg(["count", "sum"]).reset_index().itertuples(index=False):
            total = travel_totals[(row.trunk_route_id, row.parent_station, row.service_hour)]
            total[0] += row.count
            total[1] += row.sum

        sequence = frame.dropna(subset=["trip_id", "direction_id"]).sort_values(
            ["trunk_route_id", "trip_id", "start_time", "direction_id", "stop_sequence"]
        )
        group = ["trunk_route_id", "trip_id", "start_time", "direction_id"]
        sequence["next_station"] = sequence.groupby(group)["parent_station"].shift(-1)
        for row in sequence.dropna(subset=["next_station"]).itertuples(index=False):
            if row.parent_station != row.next_station:
                edge_counts[(row.trunk_route_id, row.parent_station, row.next_station, int(row.direction_id))] += 1

        transfer = frame[frame["parent_station"].isin(TRANSFER_STATIONS)].dropna(
            subset=["move_timestamp", "scheduled_arrival_time", "scheduled_departure_time", "direction_id"]
        ).copy()
        moved = pd.to_datetime(transfer["move_timestamp"], unit="s", utc=True).dt.tz_convert(EASTERN)
        transfer["actual_departure_seconds"] = moved.dt.hour * 3600 + moved.dt.minute * 60 + moved.dt.second
        transfer["direction_id"] = transfer["direction_id"].astype(int)
        for station, station_rows in transfer.groupby("parent_station"):
            groups = list(station_rows.groupby(["trunk_route_id", "direction_id"]))
            for (from_line, from_direction), incoming in groups:
                for (to_line, to_direction), outgoing in groups:
                    if from_line == to_line:
                        continue
                    outgoing = outgoing.sort_values("scheduled_departure_time")
                    scheduled = outgoing["scheduled_departure_time"].to_numpy()
                    actual_outgoing = outgoing.sort_values("actual_departure_seconds")
                    actual_departures = actual_outgoing["actual_departure_seconds"].to_numpy()
                    actual_by_scheduled = dict(zip(outgoing["scheduled_departure_time"], outgoing["actual_departure_seconds"]))
                    for item in incoming.itertuples(index=False):
                        planned_threshold = int(item.scheduled_arrival_time) + 180
                        actual_threshold = int(item.actual_seconds) + 180
                        planned_index = scheduled.searchsorted(planned_threshold, side="left")
                        actual_index = actual_departures.searchsorted(actual_threshold, side="left")
                        if planned_index >= len(scheduled) or actual_index >= len(actual_departures):
                            continue
                        planned = scheduled[planned_index]
                        extra_wait = max(0, actual_departures[actual_index] - actual_threshold - (planned - planned_threshold))
                        missed = int(actual_by_scheduled.get(planned, actual_threshold) < actual_threshold)
                        key = (station, item.service_hour, from_line, from_direction, to_line, to_direction)
                        total = transfer_totals[key]
                        total[0] += 1
                        total[1] += extra_wait
                        total[2] += missed
        print(f"Processed {args.start + offset + 1}/90 service days", flush=True)
        del frame, wait, travel, sequence, transfer
        gc.collect()

    write_rows(
        "boarding_wait_components" + suffix,
        ["line", "parent_station", "service_hour", "comparable_observations", "mean_excess_wait_seconds"],
        [
            {"line": key[0], "parent_station": key[1], "service_hour": key[2], "comparable_observations": int(value[0]), "mean_excess_wait_seconds": value[1] / value[0]}
            for key, value in wait_totals.items() if value[0]
        ],
    )
    write_rows(
        "in_vehicle_components" + suffix,
        ["line", "to_station", "service_hour", "comparable_observations", "mean_excess_travel_seconds"],
        [
            {"line": key[0], "to_station": key[1], "service_hour": key[2], "comparable_observations": int(value[0]), "mean_excess_travel_seconds": value[1] / value[0]}
            for key, value in travel_totals.items() if value[0]
        ],
    )
    strongest_edges: dict[tuple, tuple[int, int]] = {}
    for (line, origin, destination, direction), observations in edge_counts.items():
        key = (line, origin, destination)
        if key not in strongest_edges or observations > strongest_edges[key][1]:
            strongest_edges[key] = (direction, observations)
    write_rows(
        "directed_edges" + suffix,
        ["line", "from_station", "to_station", "direction_id", "observations"],
        [
            {"line": key[0], "from_station": key[1], "to_station": key[2], "direction_id": value[0], "observations": value[1]}
            for key, value in strongest_edges.items()
        ],
    )
    write_rows(
        "transfer_connection_components" + suffix,
        ["parent_station", "service_hour", "from_line", "from_direction", "to_line", "to_direction", "comparable_connections", "mean_extra_transfer_wait_seconds", "missed_scheduled_connection_rate"],
        [
            {"parent_station": key[0], "service_hour": key[1], "from_line": key[2], "from_direction": key[3], "to_line": key[4], "to_direction": key[5], "comparable_connections": int(value[0]), "mean_extra_transfer_wait_seconds": value[1] / value[0], "missed_scheduled_connection_rate": value[2] / value[0]}
            for key, value in transfer_totals.items() if value[0]
        ],
    )


if __name__ == "__main__":
    main()
