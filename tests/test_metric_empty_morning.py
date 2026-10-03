"""Tests for the G3 8:00 morning shortage headline (T-0048), on top of T-0047's
empty_minutes_by_station/_by_ortsteil window filter.

Expected values are derived from tests.synthetic's own documented constants:
S-EMPTY-0800 (EMPTY_STATION_ID) is empty only on weekdays, 07:45-08:30 local
(EMPTY_WINDOW_LOCAL), and is the only station ever at 0 bikes, so any window
that overlaps that span isolates it exactly to the overlap's minutes per
weekday occurrence.
"""

from __future__ import annotations

from datetime import date, time

import pyarrow.parquet as pq
import pytest

from berlinbikes.analysis.coverage import full_days
from berlinbikes.analysis.db import connect
from berlinbikes.analysis.empty import empty_minutes_by_ortsteil, empty_minutes_by_station, morning_shortage
from tests.synthetic import (
    EMPTY_STATION_BEZIRK,
    EMPTY_STATION_ID,
    EMPTY_STATION_ORTSTEIL,
    build_dataset,
)

START_DATE = date(2026, 1, 5)  # a Monday, clear of any DST transition
_BUILD_KWARGS = {"n_stations": 6, "snapshots_per_day": 96, "gap": False}


def _station_count(data_dir, source="nextbike_bn") -> int:
    table = pq.read_table(data_dir / "areas" / "station_areas.parquet")
    return len({row["station_id"] for row in table.to_pylist() if row["source"] == source})


def _expected_total(con, weekdays: set[int], per_day_minutes: float) -> float:
    days = full_days(con)
    n = sum(1 for d in days if d.weekday() in weekdays)
    return n * per_day_minutes


@pytest.mark.parametrize(
    "weekdays, start, end, per_day_minutes",
    [
        ({0, 1, 2, 3, 4}, time(7, 30), time(8, 30), 45),  # fully contains EMPTY_WINDOW_LOCAL
        ({0, 1, 2, 3, 4}, time(8, 0), time(8, 30), 30),  # overlaps the back half only
        ({0, 1, 2, 3, 4}, time(7, 30), time(8, 0), 15),  # overlaps the front half only
        ({0, 1, 2, 3, 4}, time(7, 30), time(7, 45), 0),  # ends exactly where the empty span starts
        ({5, 6}, time(7, 30), time(8, 30), 0),  # weekend-only: the empty station is never empty then
    ],
)
def test_window_filter_partial_overlap(synthetic_data_dir, weekdays, start, end, per_day_minutes):
    con = connect(synthetic_data_dir)
    window = (weekdays, start, end)

    result = empty_minutes_by_station(con, window=window)

    assert result.status == "ok"
    if per_day_minutes == 0:
        assert result.rows == []
        return
    expected_total = _expected_total(con, weekdays, per_day_minutes)
    assert len(result.rows) == 1
    station_id, bezirk, ortsteil, total_minutes, _per_day = result.rows[0]
    assert station_id == EMPTY_STATION_ID
    assert bezirk == EMPTY_STATION_BEZIRK
    assert ortsteil == EMPTY_STATION_ORTSTEIL
    assert total_minutes == pytest.approx(expected_total)


def test_window_filter_applies_to_ortsteil_too(synthetic_data_dir):
    con = connect(synthetic_data_dir)
    window = ({0, 1, 2, 3, 4}, time(8, 0), time(8, 30))

    result = empty_minutes_by_ortsteil(con, window=window)

    assert result.status == "ok"
    expected_total = _expected_total(con, {0, 1, 2, 3, 4}, 30)
    assert len(result.rows) == 1
    ortsteil, bezirk, total_minutes, _per_day = result.rows[0]
    assert ortsteil == EMPTY_STATION_ORTSTEIL
    assert bezirk == EMPTY_STATION_BEZIRK
    assert total_minutes == pytest.approx(expected_total)


def test_morning_shortage_shape_and_values(synthetic_data_dir):
    con = connect(synthetic_data_dir)
    n_stations = _station_count(synthetic_data_dir)

    result = morning_shortage(con)

    assert result.status == "ok"
    rows = result.rows
    assert set(rows) == {"stations", "ortsteile", "share_empty_at_0800"}

    expected_total = _expected_total(con, {0, 1, 2, 3, 4}, 45)

    stations = rows["stations"]
    assert len(stations) == 1
    station_id, bezirk, ortsteil, total_minutes, _per_day = stations[0]
    assert station_id == EMPTY_STATION_ID
    assert bezirk == EMPTY_STATION_BEZIRK
    assert ortsteil == EMPTY_STATION_ORTSTEIL
    assert total_minutes == pytest.approx(expected_total)

    ortsteile = rows["ortsteile"]
    assert len(ortsteile) == 1
    ortsteil_name, ortsteil_bezirk, ortsteil_total, _ortsteil_per_day = ortsteile[0]
    assert ortsteil_name == EMPTY_STATION_ORTSTEIL
    assert ortsteil_bezirk == EMPTY_STATION_BEZIRK
    assert ortsteil_total == pytest.approx(expected_total)

    assert rows["share_empty_at_0800"] == pytest.approx(1 / n_stations)


def test_morning_shortage_insufficient_data_at_13_days(tmp_path):
    build_dataset(tmp_path, start_date=START_DATE, days=13, **_BUILD_KWARGS)
    con = connect(tmp_path)

    result = morning_shortage(con)

    assert result.status == "insufficient_data"
    assert result.rows is None
    assert result.full_days == 13
    assert result.message
