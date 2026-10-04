"""Metric: availability on rainy versus dry, and cold versus warm, hours.

G3 requires availability on rainy versus dry hours and cold versus warm
hours, via the ``snapshot_weather`` join (ADR-0003, ADR-0015).
:func:`weather_effect` buckets every snapshot by its joined weather:

- ``kind="rain"``: ``rainy`` when ``precipitation_mm >= RAIN_MM_THRESHOLD``
  (0.1 mm), otherwise ``dry``.
- ``kind="temperature"``: ``cold`` when ``temperature_c < COLD_C_THRESHOLD``
  (10.0 degrees C), otherwise ``warm``.

A snapshot with ``weather_missing`` or a ``NULL`` value for the bucketed
variable cannot be classified; it is excluded from the rainy/dry or
cold/warm rows and counted instead in a separate ``"excluded"`` row (with
``local_hour``, ``mean_bikes_available`` and ``empty_station_share`` all
``None``), so it is never silently dropped or folded into either bucket.
Grouping by local hour (not weekday) controls for the daily rhythm while
keeping cells populated; weather varies day to day, so a given local hour is
rainy on some days and dry on others within the same dataset.
"""

from __future__ import annotations

import duckdb

from berlinbikes.analysis import MetricResult, guard
from berlinbikes.analysis.coverage import full_days
from berlinbikes.analysis.weather_join import create_snapshot_weather_view

RAIN_MM_THRESHOLD = 0.1
COLD_C_THRESHOLD = 10.0

_BUCKET_CONFIG = {
    "rain": ("precipitation_mm", ">=", RAIN_MM_THRESHOLD, "rainy", "dry"),
    "temperature": ("temperature_c", "<", COLD_C_THRESHOLD, "cold", "warm"),
}

_SQL_TEMPLATE = """
WITH per_snapshot AS (
    SELECT
        snapshot_ts,
        local_ts,
        MAX(precipitation_mm) AS precipitation_mm,
        MAX(temperature_c) AS temperature_c,
        BOOL_OR(weather_missing) AS weather_missing,
        SUM(num_bikes_available) AS total_bikes,
        SUM(CASE WHEN is_installed THEN 1 ELSE 0 END) AS installed,
        SUM(CASE WHEN is_installed AND num_bikes_available = 0 THEN 1 ELSE 0 END) AS installed_empty
    FROM snapshot_weather
    GROUP BY snapshot_ts, local_ts
),
classified AS (
    SELECT
        *,
        CAST(EXTRACT(HOUR FROM local_ts) AS INTEGER) AS local_hour,
        date_trunc('hour', snapshot_ts) AS utc_hour,
        CASE
            WHEN weather_missing OR {bucket_col} IS NULL THEN 'excluded'
            WHEN {bucket_col} {operator} {threshold} THEN '{active_bucket}'
            ELSE '{other_bucket}'
        END AS bucket
    FROM per_snapshot
),
grouped_hour AS (
    SELECT *, CASE WHEN bucket = 'excluded' THEN NULL ELSE local_hour END AS group_hour
    FROM classified
)
SELECT
    bucket,
    group_hour AS local_hour,
    CASE WHEN bucket = 'excluded' THEN NULL ELSE AVG(total_bikes) END AS mean_bikes_available,
    CASE WHEN bucket = 'excluded' THEN NULL ELSE AVG(installed_empty * 1.0 / installed) END AS empty_station_share,
    COUNT(*) AS n_snapshots,
    COUNT(DISTINCT utc_hour) AS n_hours
FROM grouped_hour
GROUP BY bucket, group_hour
ORDER BY CASE bucket WHEN '{active_bucket}' THEN 0 WHEN '{other_bucket}' THEN 1 ELSE 2 END, group_hour
"""


def _ensure_snapshot_weather_view(con: duckdb.DuckDBPyConnection) -> None:
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'snapshot_weather'"
    ).fetchone()
    if exists is None:
        create_snapshot_weather_view(con)


def weather_effect(con: duckdb.DuckDBPyConnection, kind: str) -> MetricResult:
    """Availability by weather bucket and local hour.

    ``kind="rain"`` buckets by precipitation (``rainy``/``dry``);
    ``kind="temperature"`` buckets by temperature (``cold``/``warm``); any
    other value raises ``ValueError``. Rows are ``(bucket, local_hour,
    mean_bikes_available, empty_station_share, n_snapshots, n_hours)``.
    ``mean_bikes_available`` is the per-snapshot citywide sum of
    ``num_bikes_available``, averaged within the cell.
    ``empty_station_share`` is the mean over snapshots of installed stations
    with 0 bikes divided by installed stations. ``n_hours`` is the count of
    distinct UTC weather hours in the cell. See the module docstring for the
    ``"excluded"`` row. Below the 14-full-day minimum
    (:func:`berlinbikes.analysis.coverage.full_days`), returns the guard's
    ``insufficient_data`` result instead of computing.
    """
    if kind not in _BUCKET_CONFIG:
        raise ValueError(f"kind must be 'rain' or 'temperature', got {kind!r}")

    _ensure_snapshot_weather_view(con)

    bucket_col, operator, threshold, active_bucket, other_bucket = _BUCKET_CONFIG[kind]
    sql = _SQL_TEMPLATE.format(
        bucket_col=bucket_col,
        operator=operator,
        threshold=threshold,
        active_bucket=active_bucket,
        other_bucket=other_bucket,
    )

    n_days = len(full_days(con))
    return guard(f"weather_effect:{kind}", n_days, lambda: con.execute(sql).fetchall())
