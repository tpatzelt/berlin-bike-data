"""Metric: the system's daily footprint (stations, bikes, e-bikes versus pedal bikes).

G3 requires the system's daily footprint: stations, bikes, and e-bikes
versus pedal bikes from ``vehicle_types``. :func:`daily_footprint` reports,
per Europe/Berlin full day, the distinct station count and the mean (over
that day's ``station_status`` snapshot_ts values) of bikes at stations,
free-floating bikes (``free_bike_cells`` where ``NOT at_station``), and the
e-bike/pedal/unknown split across both.

A bike's type comes from resolving its ``vehicle_type_id`` against
``vehicle_types`` with a DuckDB ASOF LEFT JOIN on ``(source,
vehicle_type_id, snapshot_ts >= vt.snapshot_ts)``: the latest row at or
before the bike's own snapshot. ``vehicle_types`` is a daily snapshot
feed, so a bike seen before that type's first recorded row has no ASOF
match; it falls back to the type's earliest-ever row (``arg_min`` over
``snapshot_ts``) rather than being left unresolved. The resolution is never
by calendar date, since a reclassification can land anywhere within a day.
``propulsion_type`` 'human' is pedal; 'electric_assist' and 'electric' are
e-bike; anything else, or a ``vehicle_type_id`` with no ``vehicle_types``
row at all (even in the fallback), is unknown and still counted, never
dropped.
"""

from __future__ import annotations

import duckdb

from berlinbikes.analysis import MetricResult, guard
from berlinbikes.analysis.coverage import full_days

_SQL = """
WITH full_days_cte AS (
    {full_days_values}
),
per_snapshot AS (
    SELECT DISTINCT
        source,
        snapshot_ts,
        CAST(snapshot_ts AT TIME ZONE 'Europe/Berlin' AS DATE) AS local_date
    FROM station_status
),
day_stations AS (
    SELECT
        CAST(snapshot_ts AT TIME ZONE 'Europe/Berlin' AS DATE) AS local_date,
        COUNT(DISTINCT station_id) AS n_stations
    FROM station_status
    GROUP BY local_date
),
station_totals AS (
    SELECT source, snapshot_ts, SUM(num_bikes_available) AS bikes_at_stations
    FROM station_status
    GROUP BY source, snapshot_ts
),
free_floating_totals AS (
    SELECT source, snapshot_ts, SUM(num_bikes) AS bikes_free_floating
    FROM free_bike_cells
    WHERE NOT at_station
    GROUP BY source, snapshot_ts
),
station_type_entries AS (
    SELECT s.source, s.snapshot_ts, entry.vehicle_type_id AS vehicle_type_id, entry.count AS count
    FROM station_status AS s, UNNEST(s.vehicle_types_available) AS u(entry)
),
free_floating_type_entries AS (
    SELECT source, snapshot_ts, vehicle_type_id, num_bikes AS count
    FROM free_bike_cells
    WHERE NOT at_station
),
type_entries AS (
    SELECT * FROM station_type_entries
    UNION ALL
    SELECT * FROM free_floating_type_entries
),
earliest_vehicle_type AS (
    SELECT source, vehicle_type_id, arg_min(propulsion_type, snapshot_ts) AS propulsion_type
    FROM vehicle_types
    GROUP BY source, vehicle_type_id
),
resolved_entries AS (
    SELECT
        e.source,
        e.snapshot_ts,
        e.count,
        COALESCE(asof_vt.propulsion_type, ev.propulsion_type) AS propulsion_type
    FROM type_entries AS e
    ASOF LEFT JOIN vehicle_types AS asof_vt
      ON asof_vt.source = e.source
     AND asof_vt.vehicle_type_id = e.vehicle_type_id
     AND e.snapshot_ts >= asof_vt.snapshot_ts
    LEFT JOIN earliest_vehicle_type AS ev
      ON ev.source = e.source AND ev.vehicle_type_id = e.vehicle_type_id
),
type_totals AS (
    SELECT
        source,
        snapshot_ts,
        SUM(CASE WHEN propulsion_type IN ('electric_assist', 'electric') THEN count ELSE 0 END) AS ebikes,
        SUM(CASE WHEN propulsion_type = 'human' THEN count ELSE 0 END) AS pedal_bikes,
        SUM(
            CASE
                WHEN propulsion_type IS NULL OR propulsion_type NOT IN ('human', 'electric_assist', 'electric')
                THEN count ELSE 0
            END
        ) AS unknown_type
    FROM resolved_entries
    GROUP BY source, snapshot_ts
)
SELECT
    ps.local_date,
    ds.n_stations,
    AVG(COALESCE(st.bikes_at_stations, 0)) AS mean_bikes_at_stations,
    AVG(COALESCE(ff.bikes_free_floating, 0)) AS mean_bikes_free_floating,
    AVG(COALESCE(tt.ebikes, 0)) AS mean_ebikes,
    AVG(COALESCE(tt.pedal_bikes, 0)) AS mean_pedal_bikes,
    AVG(COALESCE(tt.unknown_type, 0)) AS mean_unknown_type
FROM per_snapshot AS ps
JOIN day_stations AS ds ON ds.local_date = ps.local_date
LEFT JOIN station_totals AS st ON st.source = ps.source AND st.snapshot_ts = ps.snapshot_ts
LEFT JOIN free_floating_totals AS ff ON ff.source = ps.source AND ff.snapshot_ts = ps.snapshot_ts
LEFT JOIN type_totals AS tt ON tt.source = ps.source AND tt.snapshot_ts = ps.snapshot_ts
WHERE ps.local_date IN (SELECT local_date FROM full_days_cte)
GROUP BY ps.local_date, ds.n_stations
ORDER BY ps.local_date
"""


def _full_days_values(days) -> str:
    rows = ", ".join(f"(DATE '{d.isoformat()}')" for d in days)
    return f"SELECT local_date FROM (VALUES {rows}) AS t(local_date)"


def daily_footprint(con: duckdb.DuckDBPyConnection) -> MetricResult:
    """The system's daily footprint: stations, bikes, e-bikes versus pedal bikes.

    Rows are ``(local_date, n_stations, mean_bikes_at_stations,
    mean_bikes_free_floating, mean_ebikes, mean_pedal_bikes,
    mean_unknown_type)``, one per Europe/Berlin full day
    (:func:`berlinbikes.analysis.coverage.full_days`), ordered by
    ``local_date``. ``n_stations`` is the distinct ``station_id`` count in
    ``station_status`` that day. The other columns are means over that
    day's distinct ``station_status`` snapshot_ts values; see the module
    docstring for how bikes are split into e-bikes, pedal bikes and
    unknown. Below the 14-full-day minimum, returns the guard's
    ``insufficient_data`` result instead of computing.
    """
    days = full_days(con)
    n_days = len(days)

    def _compute():
        sql = _SQL.format(full_days_values=_full_days_values(days))
        return con.execute(sql).fetchall()

    return guard("daily_footprint", n_days, _compute)
