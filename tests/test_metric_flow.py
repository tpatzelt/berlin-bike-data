"""Tests for berlinbikes.analysis.flow (G3): net_flow_by_bezirk/flow_between_bezirke.

The only stations that ever change bike counts in the synthetic dataset are
the scripted flow pair (S-FLOW-A in BZ-A, S-FLOW-B in BZ-B,
tests.synthetic's FLOW_PER_HOUR per weekday morning/evening step) and the
empty-station pair (S-EMPTY-0800/S-BUDDY-0800, both in BZ-C). The buddy pair
cancels out at the Bezirk level (same Bezirk, opposite sign, same hour), so
net_per_day for BZ-C is 0 at 07:00 and 08:00 even though gains_per_day and
losses_per_day are not -- this is the "BZ-C effect" the flow metric must
show without inventing a BZ-C flow edge. Every other station's background
count is constant for the whole run, contributing no deltas. The session
fixture (28 days from 2026-10-12) carries one scripted ~90-minute gap on a
weekday outside the flow/empty windows, which drops its date from
full_days(), so expected per-day values are derived from full_days(), not a
hard-coded day count.
"""

from __future__ import annotations

from datetime import date

import pytest

from berlinbikes.analysis.coverage import full_days
from berlinbikes.analysis.db import connect
from berlinbikes.analysis.flow import flow_between_bezirke, net_flow_by_bezirk
from tests.synthetic import (
    EMPTY_STATION_BEZIRK,
    EMPTY_STATION_BIKES,
    EXPECTED_WEEKDAY_NET_BY_HOUR,
    FLOW_PER_HOUR,
    FLOW_STATION_A_BEZIRK,
    FLOW_STATION_B_BEZIRK,
    build_dataset,
)


def _weekday_rows(result) -> dict[tuple[str, int], tuple[float, float, float]]:
    return {
        (bezirk, hour): (gains, losses, net)
        for day_type, hour, bezirk, gains, losses, net in result.rows
        if day_type == "weekday"
    }


def test_net_flow_by_bezirk_matches_scripted_flow_and_shows_bz_c_cancelling(synthetic_data_dir):
    con = connect(synthetic_data_dir)

    result = net_flow_by_bezirk(con)

    assert result.status == "ok"
    by_key = _weekday_rows(result)
    for (bezirk, hour), expected_net in EXPECTED_WEEKDAY_NET_BY_HOUR.items():
        gains, losses, net = by_key[(bezirk, hour)]
        assert net == pytest.approx(expected_net)

    for hour in (7, 8):
        gains, losses, net = by_key[(EMPTY_STATION_BEZIRK, hour)]
        assert gains == pytest.approx(EMPTY_STATION_BIKES)
        assert losses == pytest.approx(EMPTY_STATION_BIKES)
        assert net == pytest.approx(0)

    expected_keys = set(EXPECTED_WEEKDAY_NET_BY_HOUR) | {(EMPTY_STATION_BEZIRK, 7), (EMPTY_STATION_BEZIRK, 8)}
    assert set(by_key) == expected_keys


def test_flow_between_bezirke_shows_morning_and_evening_reversal_and_no_bz_c_edge(synthetic_data_dir):
    con = connect(synthetic_data_dir)

    result = flow_between_bezirke(con)

    assert result.status == "ok"
    weekday_rows = {
        (hour, from_bezirk, to_bezirk): bikes_per_day
        for day_type, hour, from_bezirk, to_bezirk, bikes_per_day in result.rows
        if day_type == "weekday"
    }

    for hour in (7, 8):
        assert weekday_rows[(hour, FLOW_STATION_A_BEZIRK, FLOW_STATION_B_BEZIRK)] == pytest.approx(FLOW_PER_HOUR)
    for hour in (17, 18):
        assert weekday_rows[(hour, FLOW_STATION_B_BEZIRK, FLOW_STATION_A_BEZIRK)] == pytest.approx(FLOW_PER_HOUR)

    assert len(weekday_rows) == 4
    assert all(EMPTY_STATION_BEZIRK not in (from_b, to_b) for _hour, from_b, to_b in weekday_rows)

    assert not any(day_type == "weekend" for day_type, *_rest in result.rows)


def test_insufficient_data_returns_no_rows(tmp_path):
    build_dataset(tmp_path, start_date=date(2026, 1, 5), days=13, n_stations=6, snapshots_per_day=96, gap=False)
    con = connect(tmp_path)

    net_result = net_flow_by_bezirk(con)
    flow_result = flow_between_bezirke(con)

    for result in (net_result, flow_result):
        assert result.status == "insufficient_data"
        assert result.rows is None
        assert result.full_days == 13
