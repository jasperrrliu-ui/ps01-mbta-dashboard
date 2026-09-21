# Data plan

## Decision and audience

The primary audience is a Boston subway rider who wants to see which lines or stations have had more recorded service problems during the study period. A secondary audience is a transit advocate who wants a transparent starting point for identifying service patterns worth investigating.

The dashboard will answer:

1. Which subway lines had the highest recorded disruption frequency in the selected period?
2. What types of disruptions were recorded for each line?
3. Did disruption signals or observed service performance vary by date, weekday, or month?
4. Which stations appear most often in valid station-linked alerts?

The site will not predict a specific rider's delay or claim why disruptions occurred.

## Study window

The initial analysis will use the most recent 90 complete service days listed in MBTA's official subway-performance index. The final dates, download date, and exclusions will be written into a source manifest after collection.

## Official sources

| Dataset | Role | Required fields |
| --- | --- | --- |
| `LAMP_RT_ALERTS.parquet` | Historical recorded alerts | alert ID, effect, cause, severity, active period, route ID, stop ID |
| Subway performance `index.csv` and daily files | Select the time window and compare observed service | service date, file location, route ID, stop ID, actual/scheduled performance fields |
| `LAMP_static_stops.parquet` | Translate valid station IDs into user-facing names | stop ID, stop name, parent station |

Source URLs are listed in the README. Raw downloads will be preserved where practical. A manifest will record URL, retrieval date, row count, and transformation. The submitted data will be cleaned CSV files plus a data dictionary.

## Analysis tables

| Table | Grain | Purpose |
| --- | --- | --- |
| `alerts_clean.csv` | alert-route-stop-active-period record | Preserve alert classification and source links |
| `line_day_alerts.csv` | line per calendar date | Count distinct alerts without double-counting exploded rows |
| `line_day_performance.csv` | line per service date | Aggregate an official performance measure after schema review |
| `station_alerts.csv` | station per calendar date | Support a station ranking or map when matching coverage is adequate |

## Candidate dashboard views

| View | Measure | Decision supported |
| --- | --- | --- |
| Line comparison | Distinct alerts per 100 study days | Compare historical disruption frequency |
| Alert composition | Count and share by `effect` and line | Understand disruption types |
| Date pattern | Weekly or monthly distinct alert counts | Identify clusters over time |
| Performance comparison | A documented official performance measure | Separate actual service performance from alert counts |
| Station view | Distinct station-linked alerts | Identify stations appearing frequently in valid records |

Filters will include line and date range. A weekday, time-of-day, or map filter will be added only when the downloaded data supports it.

## Data-quality rules and limitations

1. Alert archive rows are exploded from source messages. Counts use distinct alert IDs at the stated aggregation level.
2. Alerts attached to several routes or stops are not treated as independent incidents.
3. Missing station identifiers are not inferred from alert text.
4. Performance metrics remain unavailable until their fields and daily coverage are inspected.
5. Alerts are MBTA-published records, not a complete census of passenger delay. They do not establish causation or the number of affected riders.
