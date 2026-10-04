"""Metric: typical availability curves per station and per Ortsteil, for the map.

Answers "will there be a bike at my station at 8:00 on Monday?": the mean
``num_bikes_available`` per (weekday, Europe/Berlin local hour), counting only
snapshots on full days (:func:`berlinbikes.analysis.coverage.full_days`).
Like :mod:`berlinbikes.analysis.availability`, values are averaged per
snapshot, never summed per hour, so the repeated hour of the 25-hour DST day
is just more snapshots in the same cell and the mean is unaffected.
"""

from __future__ import annotations

from datetime import date

import duckdb

from berlinbikes.analysis import MetricResult, guard
from berlinbikes.analysis.coverage import full_days

_LOCAL_CTE = """
WITH full_days_cte AS (
    {full_days_values}
),
local AS (
    SELECT
        s.source,
        s.station_id,
        s.snapshot_ts,
        s.num_bikes_available,
        CAST(isodow(s.snapshot_ts AT TIME ZONE 'Europe/Berlin') AS INTEGER) - 1 AS weekday,
        CAST(extract(hour FROM (s.snapshot_ts AT TIME ZONE 'Europe/Berlin')) AS INTEGER) AS local_hour
    FROM station_status AS s
    WHERE CAST(s.snapshot_ts AT TIME ZONE 'Europe/Berlin' AS DATE) IN (SELECT local_date FROM full_days_cte)
)
"""

_STATION_SQL = """,
latest_info AS (
    SELECT source, station_id,
           arg_max(name, snapshot_ts) AS name,
           arg_max(lat, snapshot_ts) AS lat,
           arg_max(lon, snapshot_ts) AS lon
    FROM station_information
    GROUP BY source, station_id
)
SELECT
    l.station_id,
    i.name,
    i.lat,
    i.lon,
    a.ortsteil,
    l.weekday,
    l.local_hour,
    AVG(l.num_bikes_available) AS mean_bikes_available,
    COUNT(*) AS n_snapshots
FROM local AS l
JOIN latest_info AS i ON i.source = l.source AND i.station_id = l.station_id
LEFT JOIN station_areas AS a ON a.source = l.source AND a.station_id = l.station_id
GROUP BY l.station_id, i.name, i.lat, i.lon, a.ortsteil, l.weekday, l.local_hour
ORDER BY l.station_id, l.weekday, l.local_hour
"""

_ORTSTEIL_SQL = """,
per_snapshot AS (
    SELECT a.ortsteil, l.snapshot_ts, l.weekday, l.local_hour, SUM(l.num_bikes_available) AS total_bikes
    FROM local AS l
    JOIN station_areas AS a ON a.source = l.source AND a.station_id = l.station_id
    GROUP BY a.ortsteil, l.snapshot_ts, l.weekday, l.local_hour
)
SELECT ortsteil, weekday, local_hour, AVG(total_bikes) AS mean_bikes_available, COUNT(*) AS n_snapshots
FROM per_snapshot
GROUP BY ortsteil, weekday, local_hour
ORDER BY ortsteil, weekday, local_hour
"""


def _full_days_values(days: list[date]) -> str:
    rows = ", ".join(f"(DATE '{d.isoformat()}')" for d in days)
    return f"SELECT local_date FROM (VALUES {rows}) AS t(local_date)"


def _run(con: duckdb.DuckDBPyConnection, name: str, select_sql: str) -> MetricResult:
    days = full_days(con)
    return guard(
        name,
        len(days),
        lambda: con.execute(_LOCAL_CTE.format(full_days_values=_full_days_values(days)) + select_sql).fetchall(),
    )


def station_profiles(con: duckdb.DuckDBPyConnection) -> MetricResult:
    """Rows ``(station_id, name, lat, lon, ortsteil, weekday, local_hour,
    mean_bikes_available, n_snapshots)``; ``weekday`` is 0=Monday..6=Sunday,
    ``name``/``lat``/``lon`` come from the station's latest
    ``station_information`` row and ``ortsteil`` is ``None`` when unmapped.
    """
    return _run(con, "station_profiles", _STATION_SQL)


def ortsteil_profiles(con: duckdb.DuckDBPyConnection) -> MetricResult:
    """Rows ``(ortsteil, weekday, local_hour, mean_bikes_available,
    n_snapshots)``, where each snapshot's value is the sum over the
    Ortsteil's stations.
    """
    return _run(con, "ortsteil_profiles", _ORTSTEIL_SQL)
