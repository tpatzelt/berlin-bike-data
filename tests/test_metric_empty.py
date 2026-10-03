"""Tests for berlinbikes.analysis.empty (G3): empty_minutes_by_station/_by_ortsteil.

S-EMPTY-0800 is the synthetic dataset's only station that ever reaches 0
bikes (tests.synthetic's EMPTY_WINDOW_LOCAL, 07:45-08:30 on weekdays); every
other station (including its buddy and the flow pair) stays above 0 by
construction, so it is the only nonzero row in either ranking. The session
fixture (28 days from 2026-10-12, spanning the 2026-10-25 DST fall-back day)
also carries one scripted ~90-minute gap on a weekday outside that window,
which drops its calendar date from full_days() (ADR-0003's 1-hour overlap
threshold), so the expected total is derived from full_days(), not a
hard-coded day count.
"""

from __future__ import annotations

from datetime import date

import pytest

from berlinbikes.analysis.coverage import full_days
from berlinbikes.analysis.db import connect
from berlinbikes.analysis.empty import empty_minutes_by_ortsteil, empty_minutes_by_station
from tests.synthetic import (
    EMPTY_STATION_BEZIRK,
    EMPTY_STATION_ID,
    EMPTY_STATION_ORTSTEIL,
    build_dataset,
)

_EMPTY_MINUTES_PER_WEEKDAY = 45  # EMPTY_WINDOW_LOCAL is 45 minutes, snapshots land on its exact boundaries


def _expected_total(con) -> tuple[int, int]:
    days = full_days(con)
    weekdays = sum(1 for d in days if d.weekday() <= 4)
    return weekdays * _EMPTY_MINUTES_PER_WEEKDAY, len(days)


def test_station_ranking_has_only_the_scripted_empty_station(synthetic_data_dir):
    con = connect(synthetic_data_dir)
    expected_total, n_days = _expected_total(con)

    result = empty_minutes_by_station(con)

    assert result.status == "ok"
    assert result.full_days == n_days
    assert len(result.rows) == 1
    station_id, bezirk, ortsteil, total, per_day = result.rows[0]
    assert station_id == EMPTY_STATION_ID
    assert bezirk == EMPTY_STATION_BEZIRK
    assert ortsteil == EMPTY_STATION_ORTSTEIL
    assert total == pytest.approx(expected_total)
    assert per_day == pytest.approx(expected_total / n_days)


def test_ortsteil_ranking_has_only_the_scripted_empty_ortsteil(synthetic_data_dir):
    con = connect(synthetic_data_dir)
    expected_total, n_days = _expected_total(con)

    result = empty_minutes_by_ortsteil(con)

    assert result.status == "ok"
    assert result.full_days == n_days
    assert len(result.rows) == 1
    ortsteil, bezirk, total, per_day = result.rows[0]
    assert ortsteil == EMPTY_STATION_ORTSTEIL
    assert bezirk == EMPTY_STATION_BEZIRK
    assert total == pytest.approx(expected_total)
    assert per_day == pytest.approx(expected_total / n_days)


def test_insufficient_data_returns_no_rows_for_both_rankings(tmp_path):
    build_dataset(tmp_path, start_date=date(2026, 1, 5), days=13, n_stations=6, snapshots_per_day=96, gap=False)
    con = connect(tmp_path)

    station_result = empty_minutes_by_station(con)
    ortsteil_result = empty_minutes_by_ortsteil(con)

    for result in (station_result, ortsteil_result):
        assert result.status == "insufficient_data"
        assert result.rows is None
        assert result.message
