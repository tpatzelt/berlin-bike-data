"""The DST-safe snapshot-to-weather join (ADR referenced by G2).

:func:`create_snapshot_weather_view` creates ``snapshot_weather``, a view
that LEFT JOINs ``station_status`` to ``weather`` on the UTC hour
(``date_trunc('hour', snapshot_ts) = hour_ts``), never on local wall-clock
time. Joining on local hours would double-match the repeated local hour on
the 25-hour DST fallback day and drop the skipped local hour on the 23-hour
DST spring-forward day; the UTC hour has no such ambiguity.
"""

from __future__ import annotations

import duckdb

_SNAPSHOT_WEATHER_SQL = """
CREATE VIEW snapshot_weather AS
SELECT
    s.*,
    s.snapshot_ts AT TIME ZONE 'Europe/Berlin' AS local_ts,
    w.precipitation_mm AS precipitation_mm,
    w.temperature_c AS temperature_c,
    w.condition AS condition,
    w.hour_ts IS NULL AS weather_missing
FROM station_status AS s
LEFT JOIN weather AS w
    ON date_trunc('hour', s.snapshot_ts) = w.hour_ts
"""


def create_snapshot_weather_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the ``snapshot_weather`` view on ``con`` (requires the ``station_status`` and ``weather`` views)."""
    con.execute(_SNAPSHOT_WEATHER_SQL)
