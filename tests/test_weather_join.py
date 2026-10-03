"""Tests for the DST-safe snapshot_weather join (berlinbikes.analysis.weather_join).

Weather Parquet files are written directly here with pyarrow at the T-0044
cache layout, using WEATHER_SCHEMA; no HTTP, no fixtures. station_status is
built with tests.synthetic.build_dataset for days around both 2026 DST
transitions (2026-03-29 spring-forward, 2026-10-25 fall-back).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.weather_join import create_snapshot_weather_view
from berlinbikes.weather import WEATHER_SCHEMA
from tests.synthetic import build_dataset

_REF = datetime(2026, 1, 1, tzinfo=timezone.utc)
_BUILD_KWARGS = {"n_stations": 6, "snapshots_per_day": 96, "gap": False}


def _write_weather_day(data_dir, day: date) -> None:
    """Write one WEATHER_SCHEMA Parquet file for the UTC calendar date ``day``.

    Every hour gets a distinct temperature: the number of hours since a fixed
    UTC reference instant, so a row's temperature identifies its UTC hour.
    """
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rows = [
        {
            "hour_ts": start + timedelta(hours=i),
            "precipitation_mm": 0.0,
            "temperature_c": (start + timedelta(hours=i) - _REF).total_seconds() / 3600,
            "condition": "dry",
        }
        for i in range(24)
    ]
    table = pa.Table.from_pylist(rows, schema=WEATHER_SCHEMA)
    out_dir = data_dir / "weather" / f"date={day.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_dir / "weather.parquet")


def _build(tmp_path, start_date: date, days: int) -> list[date]:
    """Build station_status, then weather covering every UTC date it spans."""
    build_dataset(tmp_path, start_date=start_date, days=days, **_BUILD_KWARGS)
    utc_dates = [
        row[0] for row in connect(tmp_path).execute("SELECT DISTINCT date FROM station_status ORDER BY date").fetchall()
    ]
    for utc_date in utc_dates:
        _write_weather_day(tmp_path, utc_date)
    return utc_dates


def _joined(tmp_path):
    con = connect(tmp_path)
    create_snapshot_weather_view(con)
    return con


# -- (a) every snapshot row joins exactly one weather row -----------------------


def test_every_snapshot_row_joins_exactly_one_weather_row(tmp_path):
    _build(tmp_path, date(2026, 10, 23), days=5)

    con = _joined(tmp_path)
    status_count = con.execute("SELECT count(*) FROM station_status").fetchone()[0]
    joined_count = con.execute("SELECT count(*) FROM snapshot_weather").fetchone()[0]
    missing_count = con.execute("SELECT count(*) FROM snapshot_weather WHERE weather_missing").fetchone()[0]

    assert status_count > 0
    assert joined_count == status_count
    assert missing_count == 0


# -- (b) the two local 02:xx hours on the fall-back day get distinct temperatures,
#        equal to their own UTC hours -------------------------------------------


def test_fall_back_day_local_02xx_hours_carry_their_own_utc_temperature(tmp_path):
    _build(tmp_path, date(2026, 10, 23), days=5)

    con = _joined(tmp_path)
    rows = con.execute(
        """
        SELECT CAST(local_ts AS VARCHAR), temperature_c
        FROM snapshot_weather
        WHERE CAST(local_ts AS DATE) = DATE '2026-10-25'
          AND EXTRACT(hour FROM local_ts) = 2
          AND station_id = (SELECT MIN(station_id) FROM station_status)
        ORDER BY temperature_c
        """
    ).fetchall()

    temperatures = sorted({row[1] for row in rows})
    assert len(temperatures) == 2, "expected two distinct local 02:xx hours on the fall-back day"

    first_utc_hour = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
    second_utc_hour = datetime(2026, 10, 25, 1, tzinfo=timezone.utc)
    expected = sorted(
        (ts - _REF).total_seconds() / 3600 for ts in (first_utc_hour, second_utc_hour)
    )
    assert temperatures == expected


# -- (c) the spring-forward day has no local 02:xx snapshot and nothing unmatched


def test_spring_forward_day_has_no_local_02xx_and_nothing_unmatched(tmp_path):
    _build(tmp_path, date(2026, 3, 27), days=5)

    con = _joined(tmp_path)
    local_02xx_count = con.execute(
        """
        SELECT count(*) FROM snapshot_weather
        WHERE CAST(local_ts AS DATE) = DATE '2026-03-29' AND EXTRACT(hour FROM local_ts) = 2
        """
    ).fetchone()[0]
    day_total = con.execute(
        "SELECT count(*) FROM snapshot_weather WHERE CAST(local_ts AS DATE) = DATE '2026-03-29'"
    ).fetchone()[0]
    day_missing = con.execute(
        """
        SELECT count(*) FROM snapshot_weather
        WHERE CAST(local_ts AS DATE) = DATE '2026-03-29' AND weather_missing
        """
    ).fetchone()[0]

    assert local_02xx_count == 0
    assert day_total > 0
    assert day_missing == 0


# -- (d) a deleted weather file only affects that UTC day's snapshots -----------


def test_deleted_weather_file_marks_only_that_utc_day_missing_without_dropping_rows(tmp_path):
    utc_dates = _build(tmp_path, date(2026, 10, 23), days=5)

    con_before = _joined(tmp_path)
    total_before = con_before.execute("SELECT count(*) FROM snapshot_weather").fetchone()[0]

    missing_date = utc_dates[2]
    weather_file = tmp_path / "weather" / f"date={missing_date.isoformat()}" / "weather.parquet"
    weather_file.unlink()

    con_after = _joined(tmp_path)
    total_after = con_after.execute("SELECT count(*) FROM snapshot_weather").fetchone()[0]
    missing_rows = con_after.execute(
        "SELECT date, count(*) FROM snapshot_weather WHERE weather_missing GROUP BY date"
    ).fetchall()
    expected_missing = con_after.execute(
        "SELECT count(*) FROM station_status WHERE date = ?", [missing_date]
    ).fetchone()[0]

    assert total_after == total_before
    assert missing_rows == [(missing_date, expected_missing)]
