"""Build dashboard-ready MBTA analysis tables from the official raw files."""

from __future__ import annotations

import csv
import gc
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow.parquet as pq


RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("data/processed")
WINDOW_PATH = OUTPUT_DIR / "study_window.csv"
SUBWAY_ROUTES = {"Blue", "Orange", "Red", "Mattapan", "Green-B", "Green-C", "Green-D", "Green-E"}
EASTERN = ZoneInfo("America/New_York")


def line_name(route_id: str) -> str:
    return "Green" if route_id.startswith("Green-") else route_id


def load_window() -> list[str]:
    with WINDOW_PATH.open(newline="", encoding="utf-8") as source:
        return [row["service_date"] for row in csv.DictReader(source)]


def build_performance(window_dates: list[str]) -> pd.DataFrame:
    records: list[pd.DataFrame] = []

    for service_date in window_dates:
        table = pq.read_table(
            RAW_DIR / "daily-performance" / f"{service_date}.parquet",
            columns=["stop_timestamp", "scheduled_arrival_time", "start_time", "trunk_route_id", "parent_station", "stop_sequence"],
        )
        frame = table.to_pandas().dropna()
        frame = frame[frame["trunk_route_id"].isin({"Blue", "Green", "Mattapan", "Orange", "Red"})]
        actual = pd.to_datetime(frame["stop_timestamp"], unit="s", utc=True).dt.tz_convert(EASTERN)
        actual_seconds = actual.dt.hour * 3600 + actual.dt.minute * 60 + actual.dt.second
        scheduled = frame["scheduled_arrival_time"].astype("int64")
        frame["schedule_difference_seconds"] = actual_seconds.where(
            scheduled < 86400, actual_seconds + 86400
        ) - scheduled
        frame = frame[frame["schedule_difference_seconds"].between(-1800, 1800)]
        frame["service_date"] = service_date
        # Actual local arrival time, rather than a trip's scheduled start, drives the rider-facing hour.
        frame["service_hour"] = actual.dt.hour
        frame["time_period"] = pd.cut(
            frame["service_hour"],
            bins=[-1, 6, 8, 15, 17, 23],
            labels=["Early / night", "Morning peak (7-9 AM)", "Midday (9 AM-4 PM)", "Evening peak (4-6 PM)", "Night"],
        ).astype(str)
        frame["late_over_5_minutes"] = frame["schedule_difference_seconds"] > 300
        frame["within_5_minutes"] = frame["schedule_difference_seconds"].abs() <= 300
        records.append(frame)

    all_records = pd.concat(records, ignore_index=True)
    daily = (
        all_records.groupby(["service_date", "trunk_route_id"], as_index=False)
        .agg(
            comparable_stop_events=("schedule_difference_seconds", "size"),
            median_schedule_difference_seconds=("schedule_difference_seconds", "median"),
            mean_schedule_difference_seconds=("schedule_difference_seconds", "mean"),
            share_late_over_5_minutes=("late_over_5_minutes", "mean"),
            share_within_5_minutes=("within_5_minutes", "mean"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    summary = (
        all_records.groupby("trunk_route_id", as_index=False)
        .agg(
            comparable_stop_events=("schedule_difference_seconds", "size"),
            median_schedule_difference_seconds=("schedule_difference_seconds", "median"),
            mean_schedule_difference_seconds=("schedule_difference_seconds", "mean"),
            share_late_over_5_minutes=("late_over_5_minutes", "mean"),
            share_within_5_minutes=("within_5_minutes", "mean"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    daily.to_csv(OUTPUT_DIR / "line_day_performance.csv", index=False)
    summary.to_csv(OUTPUT_DIR / "line_performance_summary.csv", index=False)
    hourly = (
        all_records.groupby(["trunk_route_id", "service_hour", "time_period"], as_index=False)
        .agg(
            comparable_stop_events=("schedule_difference_seconds", "size"),
            median_schedule_difference_seconds=("schedule_difference_seconds", "median"),
            share_late_over_5_minutes=("late_over_5_minutes", "mean"),
            share_within_5_minutes=("within_5_minutes", "mean"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    hourly.to_csv(OUTPUT_DIR / "line_hour_performance.csv", index=False)
    period = (
        all_records.groupby(["trunk_route_id", "time_period"], as_index=False)
        .agg(
            comparable_stop_events=("schedule_difference_seconds", "size"),
            median_schedule_difference_seconds=("schedule_difference_seconds", "median"),
            share_late_over_5_minutes=("late_over_5_minutes", "mean"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    period.to_csv(OUTPUT_DIR / "line_period_performance.csv", index=False)
    build_station_tables(all_records)
    return all_records


def build_station_tables(records: pd.DataFrame) -> None:
    daily = (
        records.groupby(["service_date", "trunk_route_id", "parent_station"], as_index=False)
        .agg(
            comparable_stop_events=("schedule_difference_seconds", "size"),
            share_late_over_5_minutes=("late_over_5_minutes", "mean"),
            median_schedule_difference_seconds=("schedule_difference_seconds", "median"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    summary = (
        records.groupby(["trunk_route_id", "parent_station"], as_index=False)
        .agg(
            comparable_stop_events=("schedule_difference_seconds", "size"),
            share_late_over_5_minutes=("late_over_5_minutes", "mean"),
            median_schedule_difference_seconds=("schedule_difference_seconds", "median"),
            median_stop_sequence=("stop_sequence", "median"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    late_records = records[records["late_over_5_minutes"]]
    late_summary = (
        late_records.groupby(["trunk_route_id", "parent_station"], as_index=False)
        .agg(
            average_delay_when_late_seconds=("schedule_difference_seconds", "mean"),
            median_delay_when_late_seconds=("schedule_difference_seconds", "median"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    summary = summary.merge(late_summary, on=["line", "parent_station"], how="left")
    names = station_names(set(summary["parent_station"]))
    summary["station_name"] = summary["parent_station"].map(names).fillna(summary["parent_station"])
    daily["station_name"] = daily["parent_station"].map(names).fillna(daily["parent_station"])
    summary.to_csv(OUTPUT_DIR / "station_delay_summary.csv", index=False)
    daily.to_csv(OUTPUT_DIR / "station_day_performance.csv", index=False)

    hourly = (
        records.groupby(["trunk_route_id", "parent_station", "service_hour", "time_period"], as_index=False)
        .agg(
            comparable_stop_events=("schedule_difference_seconds", "size"),
            share_late_over_5_minutes=("late_over_5_minutes", "mean"),
            median_schedule_difference_seconds=("schedule_difference_seconds", "median"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    late_hourly = (
        late_records.groupby(["trunk_route_id", "parent_station", "service_hour", "time_period"], as_index=False)
        .agg(
            average_delay_when_late_seconds=("schedule_difference_seconds", "mean"),
            median_delay_when_late_seconds=("schedule_difference_seconds", "median"),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    hourly = hourly.merge(
        late_hourly,
        on=["line", "parent_station", "service_hour", "time_period"],
        how="left",
    )
    hourly["station_name"] = hourly["parent_station"].map(names).fillna(hourly["parent_station"])
    hourly.to_csv(OUTPUT_DIR / "station_hour_performance.csv", index=False)

    transfer_rows = []
    for station, group in summary.groupby("parent_station"):
        if group["line"].nunique() < 2:
            continue
        for left, right in combinations(group.to_dict("records"), 2):
            late_probability = 1 - (1 - left["share_late_over_5_minutes"]) * (1 - right["share_late_over_5_minutes"])
            transfer_rows.append(
                {
                    "parent_station": station,
                    "station_name": left["station_name"],
                    "from_line": left["line"],
                    "to_line": right["line"],
                    "from_late_over_5_minutes": left["share_late_over_5_minutes"],
                    "to_late_over_5_minutes": right["share_late_over_5_minutes"],
                    "combined_late_exposure": late_probability,
                }
            )
    pd.DataFrame(transfer_rows).to_csv(OUTPUT_DIR / "transfer_exposure.csv", index=False)

    transfer_hour_rows = []
    for (station, hour), group in hourly.groupby(["parent_station", "service_hour"]):
        if group["line"].nunique() < 2:
            continue
        for left, right in combinations(group.to_dict("records"), 2):
            late_probability = 1 - (1 - left["share_late_over_5_minutes"]) * (1 - right["share_late_over_5_minutes"])
            transfer_hour_rows.append(
                {
                    "parent_station": station,
                    "station_name": left["station_name"],
                    "service_hour": hour,
                    "time_period": left["time_period"],
                    "from_line": left["line"],
                    "to_line": right["line"],
                    "from_late_over_5_minutes": left["share_late_over_5_minutes"],
                    "to_late_over_5_minutes": right["share_late_over_5_minutes"],
                    "combined_late_exposure": late_probability,
                }
            )
    pd.DataFrame(transfer_hour_rows).to_csv(OUTPUT_DIR / "transfer_hour_exposure.csv", index=False)


def build_passenger_components(records: pd.DataFrame) -> None:
    """Create components that map to rider time, without treating stop lateness as wait time."""
    wait = records[["trunk_route_id", "parent_station", "service_hour", "headway_trunk_seconds", "scheduled_headway_trunk"]].dropna().copy()
    wait["excess_wait_seconds"] = (
        (wait["headway_trunk_seconds"] - wait["scheduled_headway_trunk"]).clip(lower=0) / 2
    )
    wait_summary = (
        wait.groupby(["trunk_route_id", "parent_station", "service_hour"], as_index=False)
        .agg(
            comparable_observations=("excess_wait_seconds", "size"),
            mean_excess_wait_seconds=("excess_wait_seconds", "mean"),
            p80_excess_wait_seconds=("excess_wait_seconds", lambda values: values.quantile(0.8)),
        )
        .rename(columns={"trunk_route_id": "line"})
    )
    wait_summary.to_csv(OUTPUT_DIR / "boarding_wait_components.csv", index=False)
    del wait, wait_summary
    gc.collect()

    travel = records[["trunk_route_id", "parent_station", "service_hour", "travel_time_seconds", "scheduled_travel_time"]].dropna().copy()
    travel["excess_travel_seconds"] = (
        travel["travel_time_seconds"] - travel["scheduled_travel_time"]
    ).clip(lower=0)
    travel_summary = (
        travel.groupby(["trunk_route_id", "parent_station", "service_hour"], as_index=False)
        .agg(
            comparable_observations=("excess_travel_seconds", "size"),
            mean_excess_travel_seconds=("excess_travel_seconds", "mean"),
            p80_excess_travel_seconds=("excess_travel_seconds", lambda values: values.quantile(0.8)),
        )
        .rename(columns={"trunk_route_id": "line", "parent_station": "to_station"})
    )
    travel_summary.to_csv(OUTPUT_DIR / "in_vehicle_components.csv", index=False)
    del travel, travel_summary
    gc.collect()

    ordered = records[["service_date", "trunk_route_id", "trip_id", "start_time", "stop_sequence", "direction_id", "parent_station"]].sort_values(
        ["service_date", "trunk_route_id", "trip_id", "start_time", "stop_sequence"]
    ).copy()
    trip_group = ["service_date", "trunk_route_id", "trip_id", "start_time", "direction_id"]
    ordered["next_station"] = ordered.groupby(trip_group)["parent_station"].shift(-1)
    directed = ordered.loc[
        ordered["next_station"].notna() & ordered["parent_station"].ne(ordered["next_station"]),
        ["trunk_route_id", "parent_station", "next_station", "direction_id"],
    ]
    directed = (
        directed.value_counts()
        .rename("observations")
        .reset_index()
        .sort_values("observations", ascending=False)
        .drop_duplicates(["trunk_route_id", "parent_station", "next_station"])
        .rename(columns={"trunk_route_id": "line", "parent_station": "from_station"})
    )
    directed.to_csv(OUTPUT_DIR / "directed_edges.csv", index=False)
    del ordered, directed
    gc.collect()

    transfer_rows: list[dict[str, object]] = []
    candidates = records[[
        "service_date", "parent_station", "trunk_route_id", "direction_id", "service_hour",
        "actual_seconds", "actual_departure_seconds", "scheduled_arrival_time", "scheduled_departure_time",
    ]].dropna().copy()
    candidates["direction_id"] = candidates["direction_id"].astype(int)
    shared = candidates.groupby("parent_station")["trunk_route_id"].nunique()
    transfer_stations = set(shared[shared > 1].index)
    for (service_date, station), group in candidates[candidates["parent_station"].isin(transfer_stations)].groupby(["service_date", "parent_station"]):
        routes = list(group.groupby(["trunk_route_id", "direction_id"]))
        for (from_line, from_direction), incoming in routes:
            for (to_line, to_direction), outgoing in routes:
                if from_line == to_line:
                    continue
                outgoing = outgoing.sort_values("scheduled_departure_time")
                planned_departures = outgoing["scheduled_departure_time"].to_numpy()
                actual_outgoing = outgoing.sort_values("actual_departure_seconds")
                actual_departures = actual_outgoing["actual_departure_seconds"].to_numpy()
                actual_by_schedule = dict(zip(outgoing["scheduled_departure_time"], outgoing["actual_departure_seconds"]))
                for item in incoming.itertuples(index=False):
                    planned_threshold = int(item.scheduled_arrival_time) + 180
                    actual_threshold = int(item.actual_seconds) + 180
                    planned_index = planned_departures.searchsorted(planned_threshold, side="left")
                    actual_index = actual_departures.searchsorted(actual_threshold, side="left")
                    if planned_index >= len(planned_departures) or actual_index >= len(actual_departures):
                        continue
                    planned_departure = planned_departures[planned_index]
                    scheduled_wait = planned_departure - planned_threshold
                    actual_wait = actual_departures[actual_index] - actual_threshold
                    planned_actual_departure = actual_by_schedule.get(planned_departure)
                    transfer_rows.append(
                        {
                            "parent_station": station,
                            "service_hour": item.service_hour,
                            "from_line": from_line,
                            "from_direction": from_direction,
                            "to_line": to_line,
                            "to_direction": to_direction,
                            "extra_transfer_wait_seconds": max(0, actual_wait - scheduled_wait),
                            "missed_scheduled_connection": int(planned_actual_departure is not None and planned_actual_departure < actual_threshold),
                        }
                    )
    transfers = pd.DataFrame(transfer_rows)
    if transfers.empty:
        return
    transfer_summary = (
        transfers.groupby(
            ["parent_station", "service_hour", "from_line", "from_direction", "to_line", "to_direction"],
            as_index=False,
        )
        .agg(
            comparable_connections=("extra_transfer_wait_seconds", "size"),
            mean_extra_transfer_wait_seconds=("extra_transfer_wait_seconds", "mean"),
            p80_extra_transfer_wait_seconds=("extra_transfer_wait_seconds", lambda values: values.quantile(0.8)),
            missed_scheduled_connection_rate=("missed_scheduled_connection", "mean"),
        )
    )
    transfer_summary.to_csv(OUTPUT_DIR / "transfer_connection_components.csv", index=False)


def station_names(parent_stations: set[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    parquet_file = pq.ParquetFile(RAW_DIR / "LAMP_static_stops.parquet")
    for batch in parquet_file.iter_batches(batch_size=250000, columns=["stop_id", "stop_name"]):
        frame = batch.to_pandas()
        matches = frame[frame["stop_id"].isin(parent_stations)]
        for row in matches.itertuples(index=False):
            names.setdefault(row.stop_id, row.stop_name)
    return names


def build_alerts(window_dates: list[str]) -> None:
    window = set(window_dates)
    batches: list[pd.DataFrame] = []
    parquet_file = pq.ParquetFile(RAW_DIR / "LAMP_RT_ALERTS.parquet")
    columns = [
        "id",
        "created_datetime",
        "effect",
        "effect_detail",
        "cause",
        "severity_level",
        "header_text.translation.text",
        "service_effect_text.translation.text",
        "informed_entity.route_id",
        "informed_entity.stop_id",
    ]

    for batch in parquet_file.iter_batches(batch_size=250000, columns=columns):
        frame = batch.to_pandas()
        frame = frame[frame["informed_entity.route_id"].isin(SUBWAY_ROUTES)]
        frame["service_date"] = pd.to_datetime(frame["created_datetime"]).dt.date.astype(str)
        frame = frame[frame["service_date"].isin(window)]
        if not frame.empty:
            frame["line"] = frame["informed_entity.route_id"].map(line_name)
            batches.append(frame)

    alerts = pd.concat(batches, ignore_index=True)
    alerts = alerts.rename(
        columns={
            "id": "alert_id",
            "informed_entity.route_id": "route_id",
            "informed_entity.stop_id": "stop_id",
        }
    )
    alert_text = (
        alerts["header_text.translation.text"].fillna("")
        + " "
        + alerts["service_effect_text.translation.text"].fillna("")
    ).str.lower()
    alerts["alert_category"] = "other_notice"
    alerts.loc[alerts["effect"].eq("ACCESSIBILITY_ISSUE"), "alert_category"] = "accessibility"
    alerts.loc[
        alerts["effect"].isin({"NO_SERVICE", "REDUCED_SERVICE", "DETOUR"}),
        "alert_category",
    ] = "service_change"
    alerts.loc[
        alerts["effect"].eq("OTHER_EFFECT") & alert_text.str.contains(r"\bdelay"),
        "alert_category",
    ] = "delay"
    alerts.to_csv(OUTPUT_DIR / "alerts_clean.csv", index=False)

    line_day_all = (
        alerts.drop_duplicates(["alert_id", "line"])
        .groupby(["service_date", "line"], as_index=False)
        .agg(distinct_alerts=("alert_id", "nunique"))
    )
    line_day_all.to_csv(OUTPUT_DIR / "line_day_all_alerts.csv", index=False)

    line_day = (
        alerts[alerts["alert_category"].isin({"delay", "service_change"})]
        .drop_duplicates(["alert_id", "line"])
        .groupby(["service_date", "line"], as_index=False)
        .agg(distinct_service_impact_alerts=("alert_id", "nunique"))
    )
    line_day.to_csv(OUTPUT_DIR / "line_day_alerts.csv", index=False)

    effects = (
        alerts.drop_duplicates(["alert_id", "line", "effect"])
        .groupby(["line", "effect"], as_index=False)
        .agg(distinct_alerts=("alert_id", "nunique"))
    )
    effects.to_csv(OUTPUT_DIR / "line_effect_alerts.csv", index=False)

    categories = (
        alerts.drop_duplicates(["alert_id", "line", "alert_category"])
        .groupby(["line", "alert_category"], as_index=False)
        .agg(distinct_alerts=("alert_id", "nunique"))
    )
    categories.to_csv(OUTPUT_DIR / "line_alert_category_summary.csv", index=False)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    window_dates = load_window()
    build_performance(window_dates)
    build_alerts(window_dates)
    print("Wrote processed performance and alert CSV files.")


if __name__ == "__main__":
    main()
