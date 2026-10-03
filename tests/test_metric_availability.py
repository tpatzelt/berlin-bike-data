"""Tests for berlinbikes.analysis.availability.availability_by_hour (G3).

Expected values are derived from tests.synthetic's own documented constants
and formulas (EMPTY_STATION/EMPTY_BUDDY's conserved window swap, FLOW_STATION_A/B's
weekday rush-hour transfer, DEFAULT_BACKGROUND_BIKES's constant background),
not recomputed via the builder's private helpers. Snapshots are taken on the
hour (``snapshots_per_day=24``) so each cell's expected mean is an exact
integer, and DST days land their snapshots on exact local hour boundaries too
(verified by tests/test_analysis_guard.py's DST coverage).
"""

from __future__ import annotations

from datetime import date, time

import pyarrow.parquet as pq
import pytest

from berlinbikes.analysis.availability import availability_by_hour
from berlinbikes.analysis.db import connect
from tests.synthetic import (
    DEFAULT_BACKGROUND_BIKES,
    EMPTY_BUDDY_BASELINE,
    EMPTY_BUDDY_ID,
    EMPTY_STATION_BIKES,
    EMPTY_STATION_ID,
    EMPTY_WINDOW_LOCAL,
    FLOW_BASELINE,
    FLOW_EVENING_1,
    FLOW_EVENING_2,
    FLOW_MORNING_1,
    FLOW_MORNING_2,
    FLOW_PER_HOUR,
    FLOW_STATION_A,
    FLOW_STATION_B,
    build_dataset,
)

_BUILD_KWARGS = {"n_stations": 6, "snapshots_per_day": 24, "gap": False}
N_DAYS = 14  # two full weeks: every weekday occurs exactly twice, clear of the 14-day minimum


def _station_areas(data_dir, source="nextbike_bn") -> dict[str, str]:
    table = pq.read_table(data_dir / "areas" / "station_areas.parquet")
    return {row["station_id"]: row["bezirk"] for row in table.to_pylist() if row["source"] == source}


def _empty_active(hour: int, is_weekday: bool) -> bool:
    start, end = EMPTY_WINDOW_LOCAL
    return is_weekday and start <= time(hour, 0) < end


def _flow_offset_a(hour: int, is_weekday: bool) -> int:
    if not is_weekday:
        return 0
    t = time(hour, 0)
    morning = (t >= FLOW_MORNING_1) + (t >= FLOW_MORNING_2)
    evening = (t >= FLOW_EVENING_1) + (t >= FLOW_EVENING_2)
    return FLOW_PER_HOUR * (evening - morning)


def _station_bikes(station_id: str, hour: int, is_weekday: bool) -> int:
    """Expected num_bikes_available for one station at one local (hour, weekday), per tests.synthetic's formulas."""
    if station_id == EMPTY_STATION_ID:
        return 0 if _empty_active(hour, is_weekday) else EMPTY_STATION_BIKES
    if station_id == EMPTY_BUDDY_ID:
        return EMPTY_BUDDY_BASELINE + (EMPTY_STATION_BIKES if _empty_active(hour, is_weekday) else 0)
    if station_id == FLOW_STATION_A:
        return FLOW_BASELINE + _flow_offset_a(hour, is_weekday)
    if station_id == FLOW_STATION_B:
        return FLOW_BASELINE - _flow_offset_a(hour, is_weekday)
    return DEFAULT_BACKGROUND_BIKES  # n_stations=6 divides the background total evenly


def _expected_city(station_ids: list[str]) -> dict[tuple[int, int], int]:
    expected = {}
    for weekday in range(7):
        is_weekday = weekday <= 4
        for hour in range(24):
            expected[(weekday, hour)] = sum(_station_bikes(sid, hour, is_weekday) for sid in station_ids)
    return expected


def _expected_bezirk(areas: dict[str, str]) -> dict[tuple[int, int, str], int]:
    bezirke = sorted(set(areas.values()))
    expected = {}
    for weekday in range(7):
        is_weekday = weekday <= 4
        for hour in range(24):
            for bezirk in bezirke:
                station_ids = [sid for sid, bez in areas.items() if bez == bezirk]
                expected[(weekday, hour, bezirk)] = sum(_station_bikes(sid, hour, is_weekday) for sid in station_ids)
    return expected


def test_city_mean_matches_synthetic_formula_over_two_weeks(tmp_path):
    build_dataset(tmp_path, start_date=date(2026, 1, 5), days=N_DAYS, **_BUILD_KWARGS)
    areas = _station_areas(tmp_path)
    expected = _expected_city(list(areas))

    result = availability_by_hour(connect(tmp_path), by="city")

    assert result.status == "ok"
    assert result.full_days == N_DAYS
    rows = {(weekday, hour): (mean, n) for weekday, hour, mean, n in result.rows}
    assert len(rows) == 7 * 24
    for key, expected_mean in expected.items():
        mean, n = rows[key]
        assert mean == pytest.approx(expected_mean), key
        assert n == 2, key  # two full weeks: every (weekday, hour) cell has exactly two snapshots


def test_bezirk_mean_matches_synthetic_formula_over_two_weeks(tmp_path):
    build_dataset(tmp_path, start_date=date(2026, 1, 5), days=N_DAYS, **_BUILD_KWARGS)
    areas = _station_areas(tmp_path)
    expected = _expected_bezirk(areas)

    result = availability_by_hour(connect(tmp_path), by="bezirk")

    assert result.status == "ok"
    rows = {(weekday, hour, bezirk): (mean, n) for weekday, hour, bezirk, mean, n in result.rows}
    assert set(rows) == set(expected)
    for key, expected_mean in expected.items():
        mean, n = rows[key]
        assert mean == pytest.approx(expected_mean), key
        assert n == 2, key


def test_insufficient_data_returns_no_rows(tmp_path):
    build_dataset(tmp_path, start_date=date(2026, 1, 5), days=10, **_BUILD_KWARGS)

    result = availability_by_hour(connect(tmp_path), by="city")

    assert result.status == "insufficient_data"
    assert result.rows is None
    assert result.message


def test_invalid_by_raises(tmp_path):
    build_dataset(tmp_path, start_date=date(2026, 1, 5), days=N_DAYS, **_BUILD_KWARGS)
    with pytest.raises(ValueError):
        availability_by_hour(connect(tmp_path), by="ortsteil")


def test_dst_fallback_day_hour_counted_twice_not_double_counted_in_mean(tmp_path):
    start = date(2026, 10, 12)  # Monday; the second Sunday (2026-10-25) is the 25-hour fall-back day
    build_dataset(tmp_path, start_date=start, days=N_DAYS, **_BUILD_KWARGS)
    areas = _station_areas(tmp_path)
    expected = _expected_city(list(areas))

    result = availability_by_hour(connect(tmp_path), by="city")
    assert result.status == "ok"
    rows = {(weekday, hour): (mean, n) for weekday, hour, mean, n in result.rows}

    sunday = 6
    for hour in range(24):
        mean, n = rows[(sunday, hour)]
        assert mean == pytest.approx(expected[(sunday, hour)]), hour
        if hour == 2:
            assert n == 3, "the repeated local 02:00 hour has one extra snapshot, from the fall-back day"
        else:
            assert n == 2, hour

    for weekday in range(5):
        for hour in range(24):
            _, n = rows[(weekday, hour)]
            assert n == 2, (weekday, hour)


def test_dst_springforward_day_hour_has_fewer_snapshots_not_dropped(tmp_path):
    start = date(2026, 3, 16)  # Monday; the second Sunday (2026-03-29) is the 23-hour spring-forward day
    build_dataset(tmp_path, start_date=start, days=N_DAYS, **_BUILD_KWARGS)
    areas = _station_areas(tmp_path)
    expected = _expected_city(list(areas))

    result = availability_by_hour(connect(tmp_path), by="city")
    assert result.status == "ok"
    rows = {(weekday, hour): (mean, n) for weekday, hour, mean, n in result.rows}

    sunday = 6
    for hour in range(24):
        mean, n = rows[(sunday, hour)]
        assert mean == pytest.approx(expected[(sunday, hour)]), hour
        if hour == 2:
            assert n == 1, "the skipped local 02:00 hour only has the other Sunday's snapshot"
        else:
            assert n == 2, hour
