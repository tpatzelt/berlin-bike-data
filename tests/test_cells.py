"""Tests for berlinbikes.cells: free_bike_status -> H3 res-8 cell counts.

Charter non-goal: a rotating ``bike_id`` must never reach disk, an
exception or a log record. These tests assert that against both a
synthetic payload and the recorded ``free_bike_status`` fixture.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import h3
import pyarrow as pa
import pytest

from berlinbikes.cells import H3_RESOLUTION, aggregate_free_bikes
from berlinbikes.schemas import FREE_BIKE_CELLS_SCHEMA

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "gbfs" / "nextbike_bn" / "free_bike_status.json"
)
SNAPSHOT_TS = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
FETCHED_AT = datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc)
SOURCE = "nextbike_bn"
SENTINEL_BIKE_ID = "SENTINEL-BIKE-ID-42"

# Two cells roughly 2km apart in Berlin, far enough to land in different
# res-8 hexagons (~0.7 km^2 each).
CELL_A = {"lat": 52.515903, "lon": 13.479364}
CELL_B = {"lat": 52.52, "lon": 13.40}


def _bike(bike_id, lat, lon, vehicle_type_id="431", station_id=None, disabled=False, reserved=False):
    return {
        "bike_id": bike_id,
        "lat": lat,
        "lon": lon,
        "vehicle_type_id": vehicle_type_id,
        "station_id": station_id,
        "is_disabled": disabled,
        "is_reserved": reserved,
    }


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())["data"]


def test_result_schema_matches_free_bike_cells_exactly():
    payload = {"bikes": [_bike("b1", **CELL_A)]}
    table = aggregate_free_bikes(payload, SNAPSHOT_TS, FETCHED_AT, SOURCE)
    assert table.schema.equals(FREE_BIKE_CELLS_SCHEMA)


def test_groups_by_cell_vehicle_type_and_at_station():
    payload = {
        "bikes": [
            _bike("b1", **CELL_A, vehicle_type_id="431", station_id="S1"),
            _bike("b2", **CELL_A, vehicle_type_id="431", station_id="S1", disabled=True),
            _bike("b3", **CELL_A, vehicle_type_id="431", station_id=None),
            _bike("b4", **CELL_A, vehicle_type_id="999", station_id="S1"),
            _bike("b5", **CELL_B, vehicle_type_id="431", station_id="S1", reserved=True),
        ]
    }
    table = aggregate_free_bikes(payload, SNAPSHOT_TS, FETCHED_AT, SOURCE)
    rows = table.to_pylist()
    assert len(rows) == 4

    cell_a = h3.latlng_to_cell(CELL_A["lat"], CELL_A["lon"], H3_RESOLUTION)
    cell_b = h3.latlng_to_cell(CELL_B["lat"], CELL_B["lon"], H3_RESOLUTION)
    assert cell_a != cell_b

    by_key = {(r["cell"], r["vehicle_type_id"], r["at_station"]): r for r in rows}

    docked_431 = by_key[(cell_a, "431", True)]
    assert docked_431["num_bikes"] == 2
    assert docked_431["num_disabled"] == 1
    assert docked_431["num_reserved"] == 0

    free_431 = by_key[(cell_a, "431", False)]
    assert free_431["num_bikes"] == 1
    assert free_431["num_disabled"] == 0

    docked_999 = by_key[(cell_a, "999", True)]
    assert docked_999["num_bikes"] == 1

    other_cell = by_key[(cell_b, "431", True)]
    assert other_cell["num_bikes"] == 1
    assert other_cell["num_reserved"] == 1

    for row in rows:
        assert row["snapshot_ts"] == SNAPSHOT_TS
        assert row["fetched_at"] == FETCHED_AT
        assert row["source"] == SOURCE


def test_duplicate_bike_id_within_payload_counted_once():
    bike = _bike("dup", **CELL_A, station_id="S1")
    payload = {"bikes": [bike, dict(bike)]}
    table = aggregate_free_bikes(payload, SNAPSHOT_TS, FETCHED_AT, SOURCE)
    assert table.column("num_bikes").to_pylist() == [1]


def test_cells_are_h3_resolution_8():
    payload = {"bikes": [_bike("b1", **CELL_A, station_id="S1")]}
    table = aggregate_free_bikes(payload, SNAPSHOT_TS, FETCHED_AT, SOURCE)
    cell = table.column("cell").to_pylist()[0]
    assert h3.get_resolution(cell) == 8


def test_sentinel_bike_id_never_reaches_table_or_logs(caplog):
    payload = {
        "bikes": [
            _bike(SENTINEL_BIKE_ID, **CELL_A, station_id="S1"),
            _bike("ordinary", **CELL_A, station_id="S1"),
        ]
    }
    with caplog.at_level(logging.DEBUG):
        table = aggregate_free_bikes(payload, SNAPSHOT_TS, FETCHED_AT, SOURCE)

    for column_name in table.schema.names:
        column = table.column(column_name)
        if pa.types.is_string(column.type):
            assert SENTINEL_BIKE_ID not in column.to_pylist()
    assert SENTINEL_BIKE_ID not in caplog.text


def test_sentinel_bike_id_never_reaches_exceptions(caplog):
    malformed = _bike(SENTINEL_BIKE_ID, lat=52.5, lon=13.4, station_id="S1")
    del malformed["vehicle_type_id"]
    payload = {"bikes": [malformed]}

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(KeyError) as exc_info:
            aggregate_free_bikes(payload, SNAPSHOT_TS, FETCHED_AT, SOURCE)
    assert SENTINEL_BIKE_ID not in str(exc_info.value)
    assert SENTINEL_BIKE_ID not in caplog.text


def test_empty_payload_returns_empty_table_with_correct_schema():
    table = aggregate_free_bikes({"bikes": []}, SNAPSHOT_TS, FETCHED_AT, SOURCE)
    assert table.num_rows == 0
    assert table.schema.equals(FREE_BIKE_CELLS_SCHEMA)


def test_fixture_sum_of_num_bikes_equals_bikes_in_fixture():
    data = _load_fixture()
    bikes = data["bikes"]
    unique_bike_ids = {bike["bike_id"] for bike in bikes}
    assert len(unique_bike_ids) == len(bikes), "fixture is expected to carry no duplicate bike_id"

    table = aggregate_free_bikes(data, SNAPSHOT_TS, FETCHED_AT, SOURCE)
    assert table.schema.equals(FREE_BIKE_CELLS_SCHEMA)
    assert sum(table.column("num_bikes").to_pylist()) == len(bikes)


def test_fixture_bike_id_never_reaches_table_or_logs(caplog):
    data = _load_fixture()
    bike_ids = {bike["bike_id"] for bike in data["bikes"]}

    with caplog.at_level(logging.DEBUG):
        table = aggregate_free_bikes(data, SNAPSHOT_TS, FETCHED_AT, SOURCE)

    cells = set(table.column("cell").to_pylist())
    vehicle_type_ids = set(table.column("vehicle_type_id").to_pylist())
    assert not (cells & bike_ids)
    assert not (vehicle_type_ids & bike_ids)
    assert not any(bike_id in caplog.text for bike_id in bike_ids)
