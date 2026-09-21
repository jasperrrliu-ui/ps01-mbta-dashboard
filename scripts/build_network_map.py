"""Create a geographic MBTA subway network layer for the dashboard."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd


GTFS_PATH = Path("data/raw/MBTA_GTFS.zip")
OUTPUT_PATH = Path("data/processed/network_map.json")
GRAPH_PATH = Path("data/processed/network_graph.json")
TARGET_ROUTES = {"Blue", "Orange", "Red", "Mattapan", "Green-B", "Green-C", "Green-D", "Green-E"}


def trunk(route_id: str) -> str:
    return "Green" if route_id.startswith("Green-") else route_id


def main() -> None:
    summary = pd.read_csv("data/processed/station_delay_summary.csv")
    with zipfile.ZipFile(GTFS_PATH) as archive:
        stops = pd.read_csv(archive.open("stops.txt"), dtype={"stop_id": str})
        all_trips = pd.read_csv(archive.open("trips.txt"), dtype={"trip_id": str, "route_id": str, "shape_id": str})
        shapes = pd.read_csv(archive.open("shapes.txt"), dtype={"shape_id": str})
        stop_times = pd.read_csv(archive.open("stop_times.txt"), usecols=["trip_id", "stop_id", "stop_sequence"], dtype={"trip_id": str, "stop_id": str})

    shape_trips = all_trips[all_trips["route_id"].isin(TARGET_ROUTES)][["route_id", "shape_id"]].drop_duplicates()
    paths = []
    for trip in shape_trips.itertuples(index=False):
        points = shapes[shapes["shape_id"].eq(trip.shape_id)].sort_values("shape_pt_sequence")
        if len(points) > 1:
            paths.append({"line": trunk(trip.route_id), "route_id": trip.route_id, "points": points[["shape_pt_lon", "shape_pt_lat"]].values.tolist()})

    station_ids = set(summary["parent_station"])
    stop_coordinates = stops[stops["stop_id"].isin(station_ids)][["stop_id", "stop_lat", "stop_lon"]].drop_duplicates("stop_id")
    coordinates = stop_coordinates.set_index("stop_id")[["stop_lon", "stop_lat"]].to_dict("index")
    station_rows = []
    for row in summary.itertuples(index=False):
        coordinate = coordinates.get(row.parent_station)
        if coordinate:
            station_rows.append({"line": row.line, "parent_station": row.parent_station, "station_name": row.station_name, "lon": coordinate["stop_lon"], "lat": coordinate["stop_lat"], "late_share": row.share_late_over_5_minutes, "median_difference": row.median_schedule_difference_seconds})

    OUTPUT_PATH.write_text(json.dumps({"paths": paths, "stations": station_rows}), encoding="utf-8")
    stop_lookup = stops[["stop_id", "parent_station", "stop_name"]].copy()
    stop_lookup["parent_station"] = stop_lookup["parent_station"].fillna(stop_lookup["stop_id"])
    station_names = summary[["parent_station", "station_name"]].drop_duplicates("parent_station")
    station_ids = set(station_names["parent_station"])
    route_trips = all_trips[all_trips["route_id"].isin(TARGET_ROUTES)][["trip_id", "route_id"]]
    journey_stops = (
        stop_times.merge(route_trips, on="trip_id")
        .merge(stop_lookup[["stop_id", "parent_station"]], on="stop_id")
        .query("parent_station in @station_ids")
        .sort_values(["trip_id", "stop_sequence"])
    )
    edges: set[tuple[str, str, str]] = set()
    for (trip_id, route_id), group in journey_stops.groupby(["trip_id", "route_id"]):
        sequence = group.drop_duplicates("parent_station")["parent_station"].tolist()
        for left, right in zip(sequence, sequence[1:]):
            if left != right:
                edges.add((min(left, right), max(left, right), trunk(route_id)))
    node_lines = summary.groupby("parent_station")["line"].agg(lambda values: sorted(set(values))).to_dict()
    graph = {
        "stations": [
            {"id": row.parent_station, "name": row.station_name, "lines": node_lines.get(row.parent_station, [])}
            for row in station_names.itertuples(index=False)
        ],
        "edges": [{"from": left, "to": right, "line": line} for left, right, line in sorted(edges)],
    }
    GRAPH_PATH.write_text(json.dumps(graph), encoding="utf-8")
    print(f"Wrote {len(paths)} paths and {len(station_rows)} station-line points.")


if __name__ == "__main__":
    main()
