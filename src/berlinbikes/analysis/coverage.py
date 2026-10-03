"""The Europe/Berlin "full day" definition behind the 14-day guard (ADR-0003).

A calendar date in Europe/Berlin counts as a full day when ``station_status``
has a snapshot in its first local hour and in its last local hour, and the
total overlap of ``gaps`` rows with that local day is under one hour. A
23-hour or 25-hour DST day still counts as exactly one day: the first/last
hour check is wall-clock (DST-agnostic), and the gap overlap is measured
against the day's real UTC span either side of the transition.
"""

from __future__ import annotations

from datetime import date

import duckdb

_FULL_DAYS_SQL = """
WITH local AS (
    SELECT
        CAST(snapshot_ts AT TIME ZONE 'Europe/Berlin' AS DATE) AS local_date,
        snapshot_ts AT TIME ZONE 'Europe/Berlin' AS local_ts
    FROM station_status
),
day_coverage AS (
    SELECT
        local_date,
        BOOL_OR(local_ts < CAST(local_date AS TIMESTAMP) + INTERVAL 1 HOUR) AS has_first_hour,
        BOOL_OR(local_ts >= CAST(local_date AS TIMESTAMP) + INTERVAL 23 HOUR) AS has_last_hour
    FROM local
    GROUP BY local_date
),
bounds AS (
    SELECT
        local_date,
        CAST(local_date AS TIMESTAMP) AT TIME ZONE 'Europe/Berlin' AS day_start_utc,
        CAST(local_date + INTERVAL 1 DAY AS TIMESTAMP) AT TIME ZONE 'Europe/Berlin' AS day_end_utc
    FROM day_coverage
),
gap_overlap AS (
    SELECT
        b.local_date,
        SUM(
            GREATEST(0, date_diff('second',
                GREATEST(g.gap_start, b.day_start_utc),
                LEAST(g.gap_end, b.day_end_utc)))
        ) AS overlap_seconds
    FROM bounds b
    JOIN gaps g
      ON g.gap_start < b.day_end_utc AND g.gap_end > b.day_start_utc
    GROUP BY b.local_date
)
SELECT dc.local_date
FROM day_coverage dc
LEFT JOIN gap_overlap go USING (local_date)
WHERE dc.has_first_hour
  AND dc.has_last_hour
  AND COALESCE(go.overlap_seconds, 0) < 3600
ORDER BY dc.local_date
"""


def full_days(con: duckdb.DuckDBPyConnection) -> list[date]:
    """The Europe/Berlin calendar dates in ``con`` that count as full days."""
    return [row[0] for row in con.execute(_FULL_DAYS_SQL).fetchall()]
