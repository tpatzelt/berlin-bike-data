"""Metric: empty station minutes (a station with 0 bikes), ranked by station and Ortsteil.

A snapshot counts as empty when ``num_bikes_available = 0`` and
``is_installed`` is true. Its duration is the gap to the next snapshot of
the same station (the last snapshot of a station contributes 0). Per
ADR-0003 point 5, a duration is dropped (counted as 0) when it exceeds 2x
the dataset's median snapshot interval, or when it overlaps a ``gaps`` row,
so a feed outage or restart never inflates a station's empty minutes. Only
intervals starting on an Europe/Berlin calendar date counted by
:func:`berlinbikes.analysis.coverage.full_days` are summed, so a day
excluded from the 14-day guard also does not skew these totals. Below the
14-full-day minimum, returns the guard's ``insufficient_data`` result.
"""

from __future__ import annotations

from datetime import date

import duckdb

from berlinbikes.analysis import MetricResult, guard
from berlinbikes.analysis.coverage import full_days

_DURATIONS_CTE = """
WITH full_days_cte AS (
    {full_days_values}
),
intervals AS (
    SELECT
        s.source,
        s.station_id,
        s.snapshot_ts,
        s.num_bikes_available,
        s.is_installed,
        CAST(s.snapshot_ts AT TIME ZONE 'Europe/Berlin' AS DATE) AS local_date,
        LEAD(s.snapshot_ts) OVER (PARTITION BY s.source, s.station_id ORDER BY s.snapshot_ts) AS next_ts
    FROM station_status AS s
),
median_interval AS (
    SELECT median(date_diff('second', snapshot_ts, next_ts)) AS median_seconds
    FROM intervals
    WHERE next_ts IS NOT NULL
),
durations AS (
    SELECT
        i.source,
        i.station_id,
        i.num_bikes_available,
        i.is_installed,
        CASE
            WHEN i.next_ts IS NULL THEN 0
            WHEN date_diff('second', i.snapshot_ts, i.next_ts) > 2 * m.median_seconds THEN 0
            WHEN EXISTS (
                SELECT 1 FROM gaps AS g
                WHERE g.source = i.source
                  AND g.gap_start < i.next_ts AND g.gap_end > i.snapshot_ts
            ) THEN 0
            ELSE date_diff('second', i.snapshot_ts, i.next_ts)
        END AS duration_seconds
    FROM intervals AS i
    CROSS JOIN median_interval AS m
    WHERE i.local_date IN (SELECT local_date FROM full_days_cte)
),
empty_seconds AS (
    SELECT source, station_id, SUM(duration_seconds) AS total_seconds
    FROM durations
    WHERE num_bikes_available = 0 AND is_installed
    GROUP BY source, station_id
)
"""

_STATION_SELECT = """
SELECT
    e.station_id,
    a.bezirk,
    a.ortsteil,
    e.total_seconds / 60.0 AS empty_minutes_total,
    e.total_seconds / 60.0 / {n_days} AS empty_minutes_per_day
FROM empty_seconds AS e
JOIN station_areas AS a ON a.source = e.source AND a.station_id = e.station_id
WHERE e.total_seconds > 0
ORDER BY empty_minutes_total DESC, e.station_id ASC
"""

_ORTSTEIL_SELECT = """
, by_ortsteil AS (
    SELECT a.ortsteil, a.bezirk, SUM(e.total_seconds) AS total_seconds
    FROM empty_seconds AS e
    JOIN station_areas AS a ON a.source = e.source AND a.station_id = e.station_id
    GROUP BY a.ortsteil, a.bezirk
)
SELECT
    ortsteil,
    bezirk,
    total_seconds / 60.0 AS empty_minutes_total,
    total_seconds / 60.0 / {n_days} AS empty_minutes_per_day
FROM by_ortsteil
WHERE total_seconds > 0
ORDER BY empty_minutes_total DESC, ortsteil ASC
"""


def _full_days_values(days: list[date]) -> str:
    rows = ", ".join(f"(DATE '{d.isoformat()}')" for d in days)
    return f"SELECT local_date FROM (VALUES {rows}) AS t(local_date)"


def empty_minutes_by_station(con: duckdb.DuckDBPyConnection) -> MetricResult:
    """Empty station minutes ranked by station.

    Rows are ``(station_id, bezirk, ortsteil, empty_minutes_total,
    empty_minutes_per_day)``, sorted by total descending then station_id
    ascending. Stations with zero empty minutes are omitted.
    """
    days = full_days(con)
    n_days = len(days)

    def _compute():
        sql = _DURATIONS_CTE.format(full_days_values=_full_days_values(days)) + _STATION_SELECT.format(
            n_days=n_days
        )
        return con.execute(sql).fetchall()

    return guard("empty_minutes_by_station", n_days, _compute)


def empty_minutes_by_ortsteil(con: duckdb.DuckDBPyConnection) -> MetricResult:
    """Empty station minutes ranked by Ortsteil.

    Rows are ``(ortsteil, bezirk, empty_minutes_total,
    empty_minutes_per_day)``, summed across the Ortsteil's stations, sorted
    by total descending then ortsteil ascending. Ortsteile with zero empty
    minutes are omitted.
    """
    days = full_days(con)
    n_days = len(days)

    def _compute():
        sql = _DURATIONS_CTE.format(full_days_values=_full_days_values(days)) + _ORTSTEIL_SELECT.format(
            n_days=n_days
        )
        return con.execute(sql).fetchall()

    return guard("empty_minutes_by_ortsteil", n_days, _compute)
