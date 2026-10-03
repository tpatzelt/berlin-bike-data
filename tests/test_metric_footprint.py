"""Tests for berlinbikes.analysis.footprint.daily_footprint (G3).

The session fixture (tests.synthetic's 28-day, 30-station, n_bikes=None
dataset) only exercises vehicle_types rows that are stable from day one, so
a second, hand-built 14-day dataset covers the ASOF resolution's time
behaviour: a GHOST id with no vehicle_types row ever (always unknown), a
LATE id whose only vehicle_types row lands on day 3 (resolved on days 0-2
by falling back to that row, the earliest one for its id, rather than
being left unknown), and a SWITCH id reclassified on day 9. A per-calendar-
date join would fail this dataset, since vehicle_types rows exist only on
days 0, 3 and 9 and every other day would resolve to unknown.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pyarrow as pa
import pytest

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.footprint import daily_footprint
from berlinbikes.schemas import SCHEMAS
from berlinbikes.storage import Storage
from tests.synthetic import expected_totals, gap_date

SOURCE = "nextbike_bn"
STATION_ID = "ST1"
BERLIN = ZoneInfo("Europe/Berlin")

LATE_STATION_COUNT = 5
SWITCH_COUNT = 7
EBIKE_FREE = 3
PEDAL_FREE = 4
GHOST_FREE = 2
LATE_FREE = 6
DISTRACTOR_COUNT = 999

START = date(2026, 1, 5)  # a Monday, winter CET, clear of any DST transition
N_FULL_DAYS = 14
SWITCH_DAY_INDEX = 9
LATE_DAY_INDEX = 3


def _local(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=BERLIN).astimezone(timezone.utc)


def _vehicle_types_table(snapshot_ts: datetime, rows: list[tuple[str, str]]) -> pa.Table:
    data = [
        {
            "snapshot_ts": snapshot_ts,
            "source": SOURCE,
            "vehicle_type_id": vehicle_type_id,
            "form_factor": "bicycle",
            "propulsion_type": propulsion_type,
            "name": None,
        }
        for vehicle_type_id, propulsion_type in rows
    ]
    return pa.Table.from_pylist(data, schema=SCHEMAS["vehicle_types"])


def _station_status_table(snapshot_ts: datetime) -> pa.Table:
    row = {
        "snapshot_ts": snapshot_ts,
        "fetched_at": snapshot_ts,
        "source": SOURCE,
        "station_id": STATION_ID,
        "num_bikes_available": LATE_STATION_COUNT + SWITCH_COUNT,
        "num_docks_available": 5,
        "num_bikes_disabled": None,
        "is_installed": True,
        "is_renting": True,
        "is_returning": True,
        "last_reported": snapshot_ts,
        "vehicle_types_available": [
            {"vehicle_type_id": "LATE", "count": LATE_STATION_COUNT},
            {"vehicle_type_id": "SWITCH", "count": SWITCH_COUNT},
        ],
    }
    return pa.Table.from_pylist([row], schema=SCHEMAS["station_status"])


def _free_bike_cells_table(snapshot_ts: datetime) -> pa.Table:
    def row(vehicle_type_id: str, at_station: bool, num_bikes: int) -> dict:
        return {
            "snapshot_ts": snapshot_ts,
            "fetched_at": snapshot_ts,
            "source": SOURCE,
            "cell": "C1",
            "vehicle_type_id": vehicle_type_id,
            "at_station": at_station,
            "num_bikes": num_bikes,
            "num_disabled": 0,
            "num_reserved": 0,
        }

    rows = [
        row("EBIKE", False, EBIKE_FREE),
        row("PEDAL", False, PEDAL_FREE),
        row("GHOST", False, GHOST_FREE),
        row("LATE", False, LATE_FREE),
        row("EBIKE", True, DISTRACTOR_COUNT),  # at_station distractor: must never count as free-floating
    ]
    return pa.Table.from_pylist(rows, schema=SCHEMAS["free_bike_cells"])


def _build_sparse_dataset(tmp_path, n_days: int) -> None:
    store = Storage(tmp_path)

    store.write(
        "vehicle_types",
        SOURCE,
        _vehicle_types_table(
            _local(START, 0, 0),
            [("EBIKE", "electric_assist"), ("PEDAL", "human"), ("SWITCH", "human")],
        ),
    )
    store.write(
        "vehicle_types",
        SOURCE,
        _vehicle_types_table(_local(START + timedelta(days=LATE_DAY_INDEX), 0, 0), [("LATE", "electric")]),
    )
    store.write(
        "vehicle_types",
        SOURCE,
        _vehicle_types_table(_local(START + timedelta(days=SWITCH_DAY_INDEX), 0, 0), [("SWITCH", "electric_assist")]),
    )

    for i in range(n_days):
        day = START + timedelta(days=i)
        for hour, minute in ((0, 30), (23, 30)):
            ts = _local(day, hour, minute)
            store.write("station_status", SOURCE, _station_status_table(ts))
            store.write("free_bike_cells", SOURCE, _free_bike_cells_table(ts))


def test_sparse_dataset_fallback_and_reclassification(tmp_path):
    _build_sparse_dataset(tmp_path, n_days=N_FULL_DAYS)
    con = connect(tmp_path)

    result = daily_footprint(con)

    assert result.status == "ok"
    assert result.full_days == N_FULL_DAYS
    assert len(result.rows) == N_FULL_DAYS

    rows = {row[0]: row for row in result.rows}
    assert rows.keys() == {START + timedelta(days=i) for i in range(N_FULL_DAYS)}

    for i in range(N_FULL_DAYS):
        d = START + timedelta(days=i)
        _, n_stations, mean_at_stations, mean_free_floating, mean_ebikes, mean_pedal, mean_unknown = rows[d]
        assert n_stations == 1, d
        assert mean_at_stations == pytest.approx(LATE_STATION_COUNT + SWITCH_COUNT), d
        assert mean_free_floating == pytest.approx(EBIKE_FREE + PEDAL_FREE + GHOST_FREE + LATE_FREE), d
        assert mean_unknown == pytest.approx(GHOST_FREE), d  # GHOST has no vehicle_types row at all, ever

        late_total = LATE_FREE + LATE_STATION_COUNT  # e-bike on every day: fallback (0-2) or direct match (3+)
        if i < SWITCH_DAY_INDEX:
            assert mean_ebikes == pytest.approx(EBIKE_FREE + late_total), d
            assert mean_pedal == pytest.approx(PEDAL_FREE + SWITCH_COUNT), d
        else:
            assert mean_ebikes == pytest.approx(EBIKE_FREE + late_total + SWITCH_COUNT), d
            assert mean_pedal == pytest.approx(PEDAL_FREE), d


def test_thirteen_days_is_insufficient_data(tmp_path):
    _build_sparse_dataset(tmp_path, n_days=13)
    con = connect(tmp_path)

    result = daily_footprint(con)

    assert result.status == "insufficient_data"
    assert result.rows is None
    assert result.full_days == 13
    assert result.message


def test_synthetic_fixture_known_answer_every_full_day(synthetic_data_dir):
    con = connect(synthetic_data_dir)
    totals = expected_totals(30, None)
    gap_day = gap_date(date(2026, 10, 12))
    fallback_day = date(2026, 10, 25)

    result = daily_footprint(con)

    assert result.status == "ok"
    assert len(result.rows) == 27
    assert result.full_days == 27

    local_dates = [row[0] for row in result.rows]
    assert gap_day not in local_dates
    assert fallback_day in local_dates

    for row in result.rows:
        _, n_stations, mean_at_stations, mean_free_floating, mean_ebikes, mean_pedal, mean_unknown = row
        assert n_stations == 30
        assert mean_at_stations == pytest.approx(totals["stations_ebike"] + totals["stations_pedal"])
        assert mean_ebikes == pytest.approx(totals["stations_ebike"])
        assert mean_pedal == pytest.approx(totals["stations_pedal"])
        assert mean_free_floating == pytest.approx(totals["free_floating"])
        assert mean_unknown == pytest.approx(0)
