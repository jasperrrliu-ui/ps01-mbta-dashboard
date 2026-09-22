# Data and methodology note

## Purpose

This project examines historical MBTA subway service signals to help Boston riders compare lines and identify patterns that may deserve further investigation. It is a 90-day historical snapshot, not a prediction of a specific trip.

## Sources and study window

The project uses MBTA LAMP public data downloaded on September 20, 2026. The study window contains the 90 most recent complete dates in the official subway-performance index: June 22 through September 19, 2026. Source files include the LAMP real-time alerts archive, the static stops export, and one subway-performance Parquet export per study date. Source URLs and file hashes are stored in `data/raw/source_manifest.json` and `data/raw/daily-performance/manifest.json`.

## Measures

An alert is counted once per line using its MBTA alert ID. Alerts are classified as `delay` when the alert text describes a delay, `service_change` for detours, reduced service, or no service, `accessibility` for accessibility issues, and `other_notice` otherwise. The dashboard's service-impact visuals include only delay and service-change alerts. Accessibility alerts remain in the cleaned analysis table because they represent a different rider need.

Observed schedule difference is the recorded stop timestamp minus scheduled arrival time, in seconds. The analysis uses comparable events from the five subway lines whose difference falls between 30 minutes early and 30 minutes late. A stop is marked more than five minutes late when the difference exceeds 300 seconds. Positive differences mean later than schedule.

For the time-of-day analysis, every comparable stop event is assigned the hour of its actual timestamp in Boston local time. Station values within a selected window are weighted by their number of comparable observed events.

The trip-time view does not convert a vehicle's late-stop share into passenger delay. It reports three separate historical components: excess boarding wait, calculated as half of the observed headway above scheduled headway under a random rider-arrival assumption; excess in-vehicle time, calculated from actual versus scheduled travel time for each selected segment; and extra transfer wait. For a transfer, the analysis assumes a three-minute walk, identifies the outgoing train scheduled immediately after that threshold, and marks a missed scheduled connection when that train's actual departure already occurred. The displayed transfer percentage is this measured missed-connection rate for the selected directions and hour, not the probability that either line is late.

## Findings in this snapshot

Red Line had the largest service-impact alert rate in the period, with 141 alerts over 65 dates and 36.0% of comparable stop events more than five minutes late. Blue Line had 131 service-impact alerts over 74 dates and 33.5% of comparable events more than five minutes late. In the two requested commuter windows, Red Line's late-stop share rises from 23.0% in the morning to 43.4% in the evening, while Blue rises from 26.0% to 43.2%. At 8 AM, the combined historical exposure at the Park Street Red/Green transfer is 43.3%. These descriptive measures do not show why the differences occurred.

## Practical recommendations

For a time-critical trip, riders should compare the available hours and leave at least the displayed expected added time. When a route includes a transfer, riders should prefer the hour with the lower measured missed-connection rate and check current MBTA notices before departure. These recommendations use historical averages and do not guarantee the outcome of a live trip.

## Limitations

MBTA alerts record issues that were published, not every passenger delay. A single alert can affect several stops or routes, and alert text is not a standardized measure of delay duration. Performance records have incomplete or non-comparable observations, which is why the analysis excludes schedule differences outside the stated range. The 90-day window is a summer snapshot, so it is not calibrated for year-round use or for a particular future train. The transfer measure uses a fixed three-minute walk assumption and does not capture an individual rider's platform choice, walking speed, crowding, or intended train. Neither source measures rider volume, weather, construction impacts, or causation.
