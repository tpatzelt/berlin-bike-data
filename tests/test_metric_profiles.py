"""Tests for berlinbikes.analysis.profiles: station and Ortsteil weekday x hour curves.

The session synthetic dataset has 96 snapshots a day (every 15 minutes) and
S-EMPTY-0800 is empty in the half-open weekday window 07:45-08:30, with
EMPTY_STATION_BIKES otherwise.
"""

from __future__ import annotations

from datetime import date

import pytest

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.profiles import ortsteil_profiles, station_profiles
from tests.synthetic import (
    EMPTY_BUDDY_ORTSTEIL,
    EMPTY_STATION_BIKES,
    EMPTY_STATION_ID,
    EMPTY_STATION_ORTSTEIL,
    build_dataset,
)


def _station_cells(rows, station_id):
    return {(r[5], r[6]): (r[7], r[8]) for r in rows if r[0] == station_id}


def test_station_curve_known_answers(synthetic_data_dir):
    result = station_profiles(connect(synthetic_data_dir))
    assert result.status == "ok"
    cells = _station_cells(result.rows, EMPTY_STATION_ID)

    # Monday 07:00-07:59: 07:00, 07:15, 07:30 have bikes, 07:45 is empty -> 3*5/4
    assert cells[(0, 7)][0] == 3 * EMPTY_STATION_BIKES / 4
    # Monday 08:00-08:59: 08:00, 08:15 empty, 08:30, 08:45 have bikes -> 2*5/4
    assert cells[(0, 8)][0] == 2 * EMPTY_STATION_BIKES / 4
    # Saturday: never empty
    assert cells[(5, 8)][0] == EMPTY_STATION_BIKES
    assert len(cells) == 7 * 24


def test_station_rows_carry_name_coordinates_and_ortsteil(synthetic_data_dir):
    rows = station_profiles(connect(synthetic_data_dir)).rows
    row = next(r for r in rows if r[0] == EMPTY_STATION_ID)
    _, name, lat, lon, ortsteil, *_ = row
    assert name == f"Station {EMPTY_STATION_ID}"
    assert 52 < lat < 53 and 13 < lon < 14
    assert ortsteil == EMPTY_STATION_ORTSTEIL


def test_dst_fall_back_hour_has_more_snapshots_but_the_same_mean(tmp_path):
    # One week around 2026-10-25 (25-hour Sunday): local hour 2 occurs twice.
    build_dataset(tmp_path, start_date=date(2026, 10, 12), days=14, n_stations=6, snapshots_per_day=96, gap=False)
    rows = station_profiles(connect(tmp_path)).rows
    cells = _station_cells(rows, EMPTY_STATION_ID)
    # Sunday hour 1 vs hour 2 summed over the two Sundays in range (10-18, 10-25):
    # 4 + 4 snapshots at hour 1; 4 + 8 at hour 2 -- unless 10-25 is not a full day
    n1, n2 = cells[(6, 1)][1], cells[(6, 2)][1]
    assert n2 > n1
    assert cells[(6, 2)][0] == cells[(6, 1)][0] == EMPTY_STATION_BIKES


def test_ortsteil_curve_sums_its_stations(synthetic_data_dir):
    con = connect(synthetic_data_dir)
    ortsteil_cells = {(r[0], r[1], r[2]): r[3] for r in ortsteil_profiles(con).rows}
    station_rows = station_profiles(con).rows
    # Every synthetic station reports in every snapshot, so the mean of the
    # per-snapshot sum equals the sum of the per-station means.
    for ortsteil in (EMPTY_STATION_ORTSTEIL, EMPTY_BUDDY_ORTSTEIL):
        for weekday, hour in ((0, 7), (0, 8), (5, 8)):
            expected = sum(r[7] for r in station_rows if r[4] == ortsteil and (r[5], r[6]) == (weekday, hour))
            assert ortsteil_cells[(ortsteil, weekday, hour)] == pytest.approx(expected)
    # The empty station's Monday 07:00 dip (-5/4) shows in its Ortsteil vs Saturday.
    assert ortsteil_cells[(EMPTY_STATION_ORTSTEIL, 5, 7)] - ortsteil_cells[(EMPTY_STATION_ORTSTEIL, 0, 7)] == pytest.approx(
        EMPTY_STATION_BIKES / 4
    )


def test_insufficient_data_at_13_days(tmp_path):
    build_dataset(tmp_path, start_date=date(2026, 1, 5), days=13, n_stations=6, snapshots_per_day=96, gap=False)
    con = connect(tmp_path)
    for result in (station_profiles(con), ortsteil_profiles(con)):
        assert result.status == "insufficient_data"
        assert result.full_days == 13
        assert result.rows is None
