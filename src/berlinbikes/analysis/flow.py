"""Metric: net flow between Bezirke by local hour, inferred from station-level
gains and losses.

Trips cannot be reconstructed (bike ids rotate), so flow is inferred from
changes in station-level ``num_bikes_available`` between consecutive
snapshots of the same station. Per station, each delta (current minus the
LAG'd previous snapshot) is dropped (treated as 0) when its interval exceeds
2x the dataset's median snapshot interval, or when it overlaps a ``gaps``
row, mirroring the ADR-0003 point 5 guard used by
:mod:`berlinbikes.analysis.empty`. A delta is attributed to the Europe/Berlin
local hour and weekday of its *later* snapshot, and to that station's Bezirk
via ``station_areas``. Only deltas whose later snapshot falls on a date
counted by :func:`berlinbikes.analysis.coverage.full_days` are summed.
Below the 14-full-day minimum, both functions return the guard's
``insufficient_data`` result.
"""

from __future__ import annotations

from datetime import date

import duckdb

from berlinbikes.analysis import MetricResult, guard
from berlinbikes.analysis.coverage import full_days

_DELTAS_CTE = """
WITH full_days_cte AS (
    {full_days_values}
),
lagged AS (
    SELECT
        s.source,
        s.station_id,
        s.snapshot_ts,
        s.num_bikes_available,
        LAG(s.snapshot_ts) OVER (PARTITION BY s.source, s.station_id ORDER BY s.snapshot_ts) AS prev_ts,
        LAG(s.num_bikes_available) OVER (PARTITION BY s.source, s.station_id ORDER BY s.snapshot_ts) AS prev_bikes
    FROM station_status AS s
),
median_interval AS (
    SELECT median(date_diff('second', prev_ts, snapshot_ts)) AS median_seconds
    FROM lagged
    WHERE prev_ts IS NOT NULL
),
deltas AS (
    SELECT
        l.source,
        l.station_id,
        l.num_bikes_available - l.prev_bikes AS delta,
        CAST(isodow(l.snapshot_ts AT TIME ZONE 'Europe/Berlin') AS INTEGER) - 1 AS local_weekday,
        CAST(EXTRACT(HOUR FROM (l.snapshot_ts AT TIME ZONE 'Europe/Berlin')) AS INTEGER) AS local_hour
    FROM lagged AS l
    CROSS JOIN median_interval AS m
    WHERE l.prev_ts IS NOT NULL
      AND l.num_bikes_available - l.prev_bikes <> 0
      AND date_diff('second', l.prev_ts, l.snapshot_ts) <= 2 * m.median_seconds
      AND NOT EXISTS (
          SELECT 1 FROM gaps AS g
          WHERE g.source = l.source
            AND g.gap_start < l.snapshot_ts AND g.gap_end > l.prev_ts
      )
      AND CAST(l.snapshot_ts AT TIME ZONE 'Europe/Berlin' AS DATE) IN (SELECT local_date FROM full_days_cte)
),
bezirk_deltas AS (
    SELECT d.local_weekday, d.local_hour, a.bezirk, d.delta
    FROM deltas AS d
    JOIN station_areas AS a ON a.source = d.source AND a.station_id = d.station_id
)
"""

_NET_SELECT = """
SELECT
    CASE WHEN local_weekday <= 4 THEN 'weekday' ELSE 'weekend' END AS day_type,
    local_hour,
    bezirk,
    SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END) AS gains_total,
    SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END) AS losses_total,
    SUM(delta) AS net_total
FROM bezirk_deltas
GROUP BY day_type, local_hour, bezirk
ORDER BY day_type, local_hour, bezirk
"""


def _full_days_values(days: list[date]) -> str:
    rows = ", ".join(f"(DATE '{d.isoformat()}')" for d in days)
    return f"SELECT local_date FROM (VALUES {rows}) AS t(local_date)"


def net_flow_by_bezirk(con: duckdb.DuckDBPyConnection) -> MetricResult:
    """Net station-level flow per (day_type, local_hour, bezirk).

    Rows are ``(day_type, local_hour, bezirk, gains_per_day, losses_per_day,
    net_per_day)`` where ``day_type`` is ``'weekday'`` or ``'weekend'``,
    sorted by day_type then local_hour then bezirk. ``gains_per_day`` and
    ``losses_per_day`` are the mean daily sum of positive/negative station
    deltas attributed to that Bezirk and hour; ``net_per_day`` is their sum
    and can be 0 even when gains/losses are not, when two stations in the
    same Bezirk move bikes between each other. A (day_type, hour, bezirk)
    with no attributable deltas is omitted. Below the 14-full-day minimum,
    returns the guard's ``insufficient_data`` result.
    """
    days = full_days(con)
    n_days = len(days)
    weekday_days = sum(1 for d in days if d.weekday() <= 4)
    day_counts = {"weekday": weekday_days, "weekend": n_days - weekday_days}

    def _compute():
        sql = _DELTAS_CTE.format(full_days_values=_full_days_values(days)) + _NET_SELECT
        rows = con.execute(sql).fetchall()
        result = []
        for day_type, local_hour, bezirk, gains_total, losses_total, net_total in rows:
            n = day_counts[day_type]
            if n == 0:
                continue
            result.append((day_type, local_hour, bezirk, gains_total / n, losses_total / n, net_total / n))
        return result

    return guard("net_flow_by_bezirk", n_days, _compute)


def flow_between_bezirke(con: duckdb.DuckDBPyConnection) -> MetricResult:
    """Inferred pairwise bike flow between Bezirke per (day_type, local_hour).

    This is an inference, not an observation: trips cannot be reconstructed
    from rotating bike ids, so for each (day_type, local_hour) the net loss
    of each Bezirk with ``net_per_day < 0`` (from :func:`net_flow_by_bezirk`)
    is split among the Bezirke with ``net_per_day > 0`` in proportion to
    their net gain. A Bezirk whose net is 0 (for example because two of its
    own stations exchanged bikes) does not appear as either a source or a
    target. Rows are ``(day_type, local_hour, from_bezirk, to_bezirk,
    bikes_per_day)``, sorted by day_type, local_hour, from_bezirk, to_bezirk.
    An hour with no losing or no gaining Bezirk contributes no rows. Below
    the 14-full-day minimum, returns the guard's ``insufficient_data``
    result.
    """
    days = full_days(con)
    n_days = len(days)

    def _compute():
        net_rows = net_flow_by_bezirk(con).rows
        grouped: dict[tuple[str, int], list[tuple[str, float]]] = {}
        for day_type, local_hour, bezirk, _gains, _losses, net in net_rows:
            grouped.setdefault((day_type, local_hour), []).append((bezirk, net))

        result = []
        for (day_type, local_hour), items in sorted(grouped.items()):
            losing = sorted((bezirk, -net) for bezirk, net in items if net < 0)
            gaining = sorted((bezirk, net) for bezirk, net in items if net > 0)
            total_gain = sum(gain for _, gain in gaining)
            if not losing or not gaining or total_gain == 0:
                continue
            for from_bezirk, loss_amount in losing:
                for to_bezirk, gain_amount in gaining:
                    result.append(
                        (day_type, local_hour, from_bezirk, to_bezirk, loss_amount * gain_amount / total_gain)
                    )
        return result

    return guard("flow_between_bezirke", n_days, _compute)
