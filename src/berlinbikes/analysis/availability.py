"""Metric: mean bikes available by local hour and weekday, citywide or per Bezirk.

The charter requires this metric to not double-count the repeated local
hour on the 25-hour DST fall-back day, nor drop the skipped hour on the
23-hour spring-forward day. :func:`availability_by_hour` converts each
snapshot's UTC ``snapshot_ts`` to its Europe/Berlin wall-clock hour and
averages the per-snapshot total ``num_bikes_available`` within that
(weekday, hour) cell, never by summing per hour: the repeated local hour is
just two snapshots landing in the same cell, and the skipped hour is a cell
with fewer snapshots that day, not a special case.
"""

from __future__ import annotations

import duckdb

from berlinbikes.analysis import MetricResult, guard
from berlinbikes.analysis.coverage import full_days

_CITY_SQL = """
WITH per_snapshot AS (
    SELECT snapshot_ts, SUM(num_bikes_available) AS total_bikes
    FROM station_status
    GROUP BY snapshot_ts
),
local AS (
    SELECT total_bikes, snapshot_ts AT TIME ZONE 'Europe/Berlin' AS local_ts
    FROM per_snapshot
)
SELECT
    CAST(isodow(local_ts) AS INTEGER) - 1 AS weekday,
    CAST(extract(hour FROM local_ts) AS INTEGER) AS local_hour,
    AVG(total_bikes) AS mean_bikes_available,
    COUNT(*) AS n_snapshots
FROM local
GROUP BY weekday, local_hour
ORDER BY weekday, local_hour
"""

_BEZIRK_SQL = """
WITH per_snapshot AS (
    SELECT s.snapshot_ts, a.bezirk, SUM(s.num_bikes_available) AS total_bikes
    FROM station_status AS s
    JOIN station_areas AS a
      ON a.source = s.source AND a.station_id = s.station_id
    GROUP BY s.snapshot_ts, a.bezirk
),
local AS (
    SELECT bezirk, total_bikes, snapshot_ts AT TIME ZONE 'Europe/Berlin' AS local_ts
    FROM per_snapshot
)
SELECT
    CAST(isodow(local_ts) AS INTEGER) - 1 AS weekday,
    CAST(extract(hour FROM local_ts) AS INTEGER) AS local_hour,
    bezirk,
    AVG(total_bikes) AS mean_bikes_available,
    COUNT(*) AS n_snapshots
FROM local
GROUP BY weekday, local_hour, bezirk
ORDER BY weekday, local_hour, bezirk
"""


def availability_by_hour(con: duckdb.DuckDBPyConnection, by: str = "city") -> MetricResult:
    """Mean bikes available by (weekday, local hour), citywide or per Bezirk.

    ``by="city"`` rows are ``(weekday, local_hour, mean_bikes_available,
    n_snapshots)``. ``by="bezirk"`` rows are ``(weekday, local_hour, bezirk,
    mean_bikes_available, n_snapshots)``. ``weekday`` is 0=Monday..6=Sunday.
    Station-level ``num_bikes_available`` is summed per snapshot (citywide,
    or per Bezirk via ``station_areas``) before averaging, so a station
    never contributes more than once per snapshot. Below the 14-full-day
    minimum (:func:`berlinbikes.analysis.coverage.full_days`), returns the
    guard's ``insufficient_data`` result instead of computing.
    """
    if by not in ("city", "bezirk"):
        raise ValueError(f"by must be 'city' or 'bezirk', got {by!r}")
    sql = _CITY_SQL if by == "city" else _BEZIRK_SQL
    n_days = len(full_days(con))
    return guard(f"availability_by_hour:{by}", n_days, lambda: con.execute(sql).fetchall())
