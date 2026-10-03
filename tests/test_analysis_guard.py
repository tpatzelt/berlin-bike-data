"""Tests for the shared 14-day 'not enough data yet' guard (ADR-0003)."""

from __future__ import annotations

from datetime import date, timedelta

from berlinbikes.analysis import MIN_FULL_DAYS, guard
from berlinbikes.analysis.coverage import full_days
from berlinbikes.analysis.db import connect
from tests.synthetic import build_dataset, gap_date

START_DATE = date(2026, 1, 5)  # a Monday, clear of any DST transition

_BUILD_KWARGS = {"n_stations": 6, "snapshots_per_day": 96, "gap": False}


def _full_days(data_dir, start_date: date, days: int, **overrides) -> list[date]:
    kwargs = {**_BUILD_KWARGS, **overrides}
    build_dataset(data_dir, start_date=start_date, days=days, **kwargs)
    return full_days(connect(data_dir))


def test_below_minimum_days_is_insufficient_data(tmp_path):
    n_days = len(_full_days(tmp_path, START_DATE, MIN_FULL_DAYS - 1))
    assert n_days == MIN_FULL_DAYS - 1

    def _must_not_run():
        raise AssertionError("compute must not be called below the minimum")

    result = guard("availability", n_days, _must_not_run)
    assert result.status == "insufficient_data"
    assert result.rows is None
    assert result.full_days == MIN_FULL_DAYS - 1
    assert result.message


def test_at_minimum_days_is_ok(tmp_path):
    n_days = len(_full_days(tmp_path, START_DATE, MIN_FULL_DAYS))
    assert n_days == MIN_FULL_DAYS

    result = guard("availability", n_days, lambda: "computed-rows")
    assert result.status == "ok"
    assert result.rows == "computed-rows"
    assert result.full_days == MIN_FULL_DAYS
    assert result.message is None


def test_gap_day_is_not_counted_as_full(tmp_path):
    days = 20
    build_dataset(tmp_path, start_date=START_DATE, days=days, n_stations=6, gap=True)
    counted = full_days(connect(tmp_path))

    dropped = gap_date(START_DATE)
    assert dropped not in counted

    expected = {START_DATE + timedelta(days=i) for i in range(days)} - {dropped}
    assert set(counted) == expected


def test_dst_fallback_day_counts_once(tmp_path):
    counted = _full_days(tmp_path, date(2026, 10, 20), 10)
    dst_day = date(2026, 10, 25)
    assert counted.count(dst_day) == 1
