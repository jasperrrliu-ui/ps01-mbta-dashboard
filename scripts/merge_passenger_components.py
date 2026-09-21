"""Merge small passenger-component batches into dashboard CSV files."""

from pathlib import Path

import pandas as pd


OUTPUT = Path("data/processed")


def weighted_merge(pattern: str, group: list[str], mean_column: str, output: str) -> None:
    frames = [pd.read_csv(path) for path in OUTPUT.glob(pattern)]
    frame = pd.concat(frames, ignore_index=True)
    frame["weighted"] = frame["comparable_observations"] * frame[mean_column]
    merged = frame.groupby(group, as_index=False).agg(
        comparable_observations=("comparable_observations", "sum"), weighted=("weighted", "sum")
    )
    merged[mean_column] = merged["weighted"] / merged["comparable_observations"]
    merged.drop(columns="weighted").to_csv(OUTPUT / output, index=False)


def main() -> None:
    weighted_merge(
        "boarding_wait_components_part_*.csv",
        ["line", "parent_station", "service_hour"],
        "mean_excess_wait_seconds",
        "boarding_wait_components.csv",
    )
    weighted_merge(
        "in_vehicle_components_part_*.csv",
        ["line", "to_station", "service_hour"],
        "mean_excess_travel_seconds",
        "in_vehicle_components.csv",
    )
    transfers = pd.concat([pd.read_csv(path) for path in OUTPUT.glob("transfer_connection_components_part_*.csv")], ignore_index=True)
    keys = ["parent_station", "service_hour", "from_line", "from_direction", "to_line", "to_direction"]
    transfers["wait_weighted"] = transfers["comparable_connections"] * transfers["mean_extra_transfer_wait_seconds"]
    transfers["missed_weighted"] = transfers["comparable_connections"] * transfers["missed_scheduled_connection_rate"]
    transfers = transfers.groupby(keys, as_index=False).agg(
        comparable_connections=("comparable_connections", "sum"),
        wait_weighted=("wait_weighted", "sum"),
        missed_weighted=("missed_weighted", "sum"),
    )
    transfers["mean_extra_transfer_wait_seconds"] = transfers["wait_weighted"] / transfers["comparable_connections"]
    transfers["missed_scheduled_connection_rate"] = transfers["missed_weighted"] / transfers["comparable_connections"]
    transfers.drop(columns=["wait_weighted", "missed_weighted"]).to_csv(OUTPUT / "transfer_connection_components.csv", index=False)

    edges = pd.concat([pd.read_csv(path) for path in OUTPUT.glob("directed_edges_part_*.csv")], ignore_index=True)
    edges = edges.sort_values("observations", ascending=False).drop_duplicates(["line", "from_station", "to_station"])
    edges.to_csv(OUTPUT / "directed_edges.csv", index=False)


if __name__ == "__main__":
    main()
