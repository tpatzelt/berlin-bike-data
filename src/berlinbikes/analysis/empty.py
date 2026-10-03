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

An optional ``window`` restricts both ranked metrics to intervals whose
*starting* snapshot's Europe/Berlin local weekday and wall-clock time fall
inside it, which :func:`morning_shortage` uses for the G3 8:00 morning
shortage headline.
"""

from __future__ import annotations

from datetime import date, time

import duckdb

from berlinbikes.analysis import MetricResult, guard
from berlinbikes.analysis.coverage import full_days

#: (weekdays, local_start, local_end): weekdays is a set of 0=Mon..6=Sun,
#: local_start/local_end are an Europe/Berlin half-open [start, end) range.
Window = tuple[set[int], time, time]

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
        CAST(s.snapshot_ts AT TIME ZONE 'Europe/Berlin' AS TIME) AS local_time,
        CAST(isodow(s.snapshot_ts AT TIME ZONE 'Europe/Berlin') AS INTEGER) - 1 AS local_weekday,
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
    WHERE i.local_date IN (SELECT local_date FROM full_days_cte){window_filter}
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


def _window_filter(window: Window | None) -> str:
    if window is None:
        return ""
    weekdays, start, end = window
    weekday_list = ", ".join(str(int(w)) for w in sorted(weekdays)) or "-1"
    return (
        f"\n      AND i.local_weekday IN ({weekday_list})"
        f"\n      AND i.local_time >= TIME '{start.isoformat()}'"
        f"\n      AND i.local_time < TIME '{end.isoformat()}'"
    )


def empty_minutes_by_station(con: duckdb.DuckDBPyConnection, window: Window | None = None) -> MetricResult:
    """Empty station minutes ranked by station.

    Rows are ``(station_id, bezirk, ortsteil, empty_minutes_total,
    empty_minutes_per_day)``, sorted by total descending then station_id
    ascending. Stations with zero empty minutes are omitted. ``window``, if
    given, restricts summed intervals to those starting inside it (see
    module docstring).
    """
    days = full_days(con)
    n_days = len(days)

    def _compute():
        sql = _DURATIONS_CTE.format(
            full_days_values=_full_days_values(days), window_filter=_window_filter(window)
        ) + _STATION_SELECT.format(n_days=n_days)
        return con.execute(sql).fetchall()

    return guard("empty_minutes_by_station", n_days, _compute)


def empty_minutes_by_ortsteil(con: duckdb.DuckDBPyConnection, window: Window | None = None) -> MetricResult:
    """Empty station minutes ranked by Ortsteil.

    Rows are ``(ortsteil, bezirk, empty_minutes_total,
    empty_minutes_per_day)``, summed across the Ortsteil's stations, sorted
    by total descending then ortsteil ascending. Ortsteile with zero empty
    minutes are omitted. ``window``, if given, restricts summed intervals to
    those starting inside it (see module docstring).
    """
    days = full_days(con)
    n_days = len(days)

    def _compute():
        sql = _DURATIONS_CTE.format(
            full_days_values=_full_days_values(days), window_filter=_window_filter(window)
        ) + _ORTSTEIL_SELECT.format(n_days=n_days)
        return con.execute(sql).fetchall()

    return guard("empty_minutes_by_ortsteil", n_days, _compute)


#: The G3 8:00 morning shortage window: weekday mornings, 07:30-08:30 Europe/Berlin.
MORNING_WINDOW: Window = ({0, 1, 2, 3, 4}, time(7, 30), time(8, 30))

_MORNING_SHARE_CTE = """
WITH full_days_cte AS (
    {full_days_values}
),
snapshot_local AS (
    SELECT
        source,
        snapshot_ts,
        station_id,
        num_bikes_available,
        is_installed,
        CAST(snapshot_ts AT TIME ZONE 'Europe/Berlin' AS DATE) AS local_date,
        CAST(snapshot_ts AT TIME ZONE 'Europe/Berlin' AS TIME) AS local_time,
        CAST(isodow(snapshot_ts AT TIME ZONE 'Europe/Berlin') AS INTEGER) - 1 AS local_weekday
    FROM station_status
),
at_0800 AS (
    SELECT *
    FROM snapshot_local
    WHERE local_date IN (SELECT local_date FROM full_days_cte)
      AND local_weekday IN (0, 1, 2, 3, 4)
      AND local_time = TIME '08:00:00'
),
per_snapshot AS (
    SELECT
        source,
        snapshot_ts,
        SUM(CASE WHEN is_installed THEN 1 ELSE 0 END) AS installed,
        SUM(CASE WHEN is_installed AND num_bikes_available = 0 THEN 1 ELSE 0 END) AS installed_empty
    FROM at_0800
    GROUP BY source, snapshot_ts
)
SELECT AVG(installed_empty * 1.0 / installed) AS share_empty_at_0800
FROM per_snapshot
WHERE installed > 0
"""


def morning_shortage(con: duckdb.DuckDBPyConnection) -> MetricResult:
    """The G3 8:00 morning shortage headline.

    ``rows`` is a dict with keys ``'stations'`` and ``'ortsteile'`` (the
    :func:`empty_minutes_by_station`/:func:`empty_minutes_by_ortsteil`
    rankings for :data:`MORNING_WINDOW`) and ``'share_empty_at_0800'``: the
    mean, over weekday full days, of (installed stations with 0 bikes at
    the local 08:00 snapshot) / (installed stations at that snapshot).
    Below the 14-full-day minimum, returns the guard's ``insufficient_data``
    result.
    """
    days = full_days(con)
    n_days = len(days)

    def _compute():
        stations = empty_minutes_by_station(con, window=MORNING_WINDOW).rows
        ortsteile = empty_minutes_by_ortsteil(con, window=MORNING_WINDOW).rows
        sql = _MORNING_SHARE_CTE.format(full_days_values=_full_days_values(days))
        share = con.execute(sql).fetchone()[0]
        return {"stations": stations, "ortsteile": ortsteile, "share_empty_at_0800": share}

    return guard("morning_shortage", n_days, _compute)
