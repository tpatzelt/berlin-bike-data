"""Tests for berlinbikes.analysis.weather_effect.weather_effect (G3 x G2 join).

Weather is written directly as WEATHER_SCHEMA Parquet (T-0044 cache layout),
with precipitation and temperature scripted into the UTC hours that contain
weekday local 07:00-08:59 (06:00-07:59 UTC in winter CET, the dataset's
start date is clear of any DST transition): rain and cold on weekdays, dry
and warm otherwise. S-EMPTY-0800 (``EMPTY_STATION_ID``) is the synthetic
dataset's only station that ever reaches 0 bikes, weekdays only, during
``EMPTY_WINDOW_LOCAL``. For local_hour 8, that window ([07:45, 08:30)) covers
the first half of the hour (30 of 60 minutes), so the rainy/cold bucket's
``empty_station_share`` is exactly ``30 / 60 / n_stations``, while the
dry/warm bucket (built from the same local hour on weekends) is 0.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.weather_effect import (
    COLD_C_THRESHOLD,
    RAIN_MM_THRESHOLD,
    weather_effect,
)
from berlinbikes.weather import WEATHER_SCHEMA
from tests.synthetic import EMPTY_WINDOW_LOCAL, build_dataset

_BUILD_KWARGS = {"n_stations": 6, "snapshots_per_day": 96, "gap": False}
_N_STATIONS = 6
_START = date(2026, 1, 5)  # a Monday, clear of any DST transition (CET, UTC+1)
_N_DAYS = 14
_RAIN_COLD_UTC_HOURS = {6, 7}  # weekday local 07:00-08:59 == UTC 06:00-07:59 in winter CET


def _overlap_minutes(window: tuple[time, time], hour: int) -> float:
    """Minutes of ``window`` (a half-open [start, end) local time range) inside local_hour ``hour``."""
    ref = date(2000, 1, 1)
    start, end = window
    window_start = datetime.combine(ref, start)
    window_end = datetime.combine(ref, end)
    hour_start = datetime.combine(ref, time(hour, 0))
    hour_end = hour_start + timedelta(hours=1)
    overlap = min(window_end, hour_end) - max(window_start, hour_start)
    return max(overlap.total_seconds(), 0.0) / 60


_EXPECTED_SHARE_HOUR_8 = _overlap_minutes(EMPTY_WINDOW_LOCAL, 8) / 60 / _N_STATIONS


def _write_weather_day(data_dir, day: date, scripted_utc_hours: set[int]) -> None:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rows = [
        {
            "hour_ts": start + timedelta(hours=h),
            "precipitation_mm": 1.0 if h in scripted_utc_hours else 0.0,
            "temperature_c": -5.0 if h in scripted_utc_hours else 20.0,
            "condition": "rain" if h in scripted_utc_hours else "dry",
        }
        for h in range(24)
    ]
    table = pa.Table.from_pylist(rows, schema=WEATHER_SCHEMA)
    out_dir = data_dir / "weather" / f"date={day.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_dir / "weather.parquet")


def _build(tmp_path, days: int = _N_DAYS):
    """Build station_status for ``days`` from ``_START``, then weather scripting rain/cold on weekdays."""
    build_dataset(tmp_path, start_date=_START, days=days, **_BUILD_KWARGS)
    probe = connect(tmp_path)
    utc_dates = [row[0] for row in probe.execute("SELECT DISTINCT date FROM station_status ORDER BY date").fetchall()]

    for utc_date in utc_dates:
        scripted = _RAIN_COLD_UTC_HOURS if utc_date.weekday() <= 4 else set()
        _write_weather_day(tmp_path, utc_date, scripted)

    return connect(tmp_path), utc_dates


def _rows_by_bucket_hour(result):
    return {(bucket, local_hour): (mean, share, n_snapshots, n_hours) for bucket, local_hour, mean, share, n_snapshots, n_hours in result.rows}


def _weekday_weekend_counts_at_local_hour(con, hour: int) -> tuple[int, int]:
    """(n_weekdays, n_weekend_days) among the Europe/Berlin local calendar dates with a snapshot at ``local_hour=hour``."""
    local_dates = [
        row[0]
        for row in con.execute(
            """
            SELECT DISTINCT CAST(snapshot_ts AT TIME ZONE 'Europe/Berlin' AS DATE) AS local_date
            FROM station_status
            WHERE EXTRACT(hour FROM snapshot_ts AT TIME ZONE 'Europe/Berlin') = ?
            """,
            [hour],
        ).fetchall()
    ]
    n_weekdays = sum(1 for d in local_dates if d.weekday() <= 4)
    return n_weekdays, len(local_dates) - n_weekdays


def test_rain_bucket_known_answer_at_local_hour_8(tmp_path):
    con, _utc_dates = _build(tmp_path)
    n_weekdays, n_weekend_days = _weekday_weekend_counts_at_local_hour(con, 8)

    result = weather_effect(con, "rain")

    assert result.status == "ok"
    rows = _rows_by_bucket_hour(result)

    _mean, rainy_share, _n, rainy_n_hours = rows[("rainy", 8)]
    assert rainy_share == pytest.approx(_EXPECTED_SHARE_HOUR_8)
    assert rainy_n_hours == n_weekdays

    _mean, dry_share, _n, dry_n_hours = rows[("dry", 8)]
    assert dry_share == pytest.approx(0.0)
    assert dry_n_hours == n_weekend_days


def test_temperature_bucket_known_answer_at_local_hour_8(tmp_path):
    con, _utc_dates = _build(tmp_path)
    n_weekdays, n_weekend_days = _weekday_weekend_counts_at_local_hour(con, 8)

    result = weather_effect(con, "temperature")

    assert result.status == "ok"
    rows = _rows_by_bucket_hour(result)

    _mean, cold_share, _n, cold_n_hours = rows[("cold", 8)]
    assert cold_share == pytest.approx(_EXPECTED_SHARE_HOUR_8)
    assert cold_n_hours == n_weekdays

    _mean, warm_share, _n, warm_n_hours = rows[("warm", 8)]
    assert warm_share == pytest.approx(0.0)
    assert warm_n_hours == n_weekend_days


def test_missing_weather_day_counted_as_excluded(tmp_path):
    build_dataset(tmp_path, start_date=_START, days=_N_DAYS, **_BUILD_KWARGS)
    probe = connect(tmp_path)
    utc_dates = [row[0] for row in probe.execute("SELECT DISTINCT date FROM station_status ORDER BY date").fetchall()]
    missing_date = utc_dates[2]

    for utc_date in utc_dates:
        if utc_date == missing_date:
            continue
        scripted = _RAIN_COLD_UTC_HOURS if utc_date.weekday() <= 4 else set()
        _write_weather_day(tmp_path, utc_date, scripted)

    con = connect(tmp_path)
    expected_missing_snapshots = con.execute(
        "SELECT count(DISTINCT snapshot_ts) FROM station_status WHERE date = ?", [missing_date]
    ).fetchone()[0]

    expected_missing_hours = con.execute(
        "SELECT count(DISTINCT date_trunc('hour', snapshot_ts)) FROM station_status WHERE date = ?", [missing_date]
    ).fetchone()[0]

    result = weather_effect(con, "rain")

    assert result.status == "ok"
    rows = {(bucket, local_hour): (n_snapshots, n_hours) for bucket, local_hour, _mean, _share, n_snapshots, n_hours in result.rows}
    excluded_n_snapshots, excluded_n_hours = rows[("excluded", None)]
    assert excluded_n_snapshots == expected_missing_snapshots
    assert excluded_n_hours == expected_missing_hours

    total_snapshots = sum(n for (_b, _h), (n, _nh) in rows.items())
    expected_total_snapshots = con.execute("SELECT count(DISTINCT snapshot_ts) FROM station_status").fetchone()[0]
    assert total_snapshots == expected_total_snapshots


def test_insufficient_data_at_13_days(tmp_path):
    con, _ = _build(tmp_path, days=13)

    result = weather_effect(con, "rain")

    assert result.status == "insufficient_data"
    assert result.rows is None
    assert result.full_days == 13
    assert result.message


def test_invalid_kind_raises(tmp_path):
    con, _ = _build(tmp_path)
    with pytest.raises(ValueError):
        weather_effect(con, "humidity")


def test_thresholds_documented_as_module_constants():
    assert RAIN_MM_THRESHOLD == 0.1
    assert COLD_C_THRESHOLD == 10.0
