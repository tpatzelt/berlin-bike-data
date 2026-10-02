"""Tests for the Dott Berlin source: selection, writes, no bike_id, ttl.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/dott_berlin/ (the autouse socket guard in
conftest.py would fail the test if it tried to reach the network).
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from berlinbikes.backoff import FakeClock
from berlinbikes.collector import FEED_TO_DATASET, PollResult
from berlinbikes.gbfs import REQUIRED_FEEDS
from berlinbikes.sources import DottSource, enabled_sources

from tests.helpers import fixture_replay_transport, load_fixture, make_collector, make_settings

SOURCE_NAME = "dott_berlin"
BASE_LAST_UPDATED = load_fixture(SOURCE_NAME, "station_status")["last_updated"]
NOW = datetime.fromtimestamp(BASE_LAST_UPDATED, tz=timezone.utc)


def _part_files(tmp_path, feed_name: str):
    dataset = FEED_TO_DATASET[feed_name]
    dataset_dir = tmp_path / SOURCE_NAME / dataset
    if not dataset_dir.is_dir():
        return []
    return sorted(dataset_dir.glob("date=*/part-*.parquet"))


# -- (a) source selection ------------------------------------------------


def test_enabled_sources_defaults_to_nextbike_only(tmp_path):
    settings = make_settings(tmp_path)
    assert [source.name for source in enabled_sources(settings)] == ["nextbike_bn"]


def test_enabled_sources_adds_dott_when_enabled(tmp_path):
    settings = make_settings(tmp_path, BIKES_DOTT_ENABLED="true")
    assert [source.name for source in enabled_sources(settings)] == ["nextbike_bn", "dott_berlin"]


# -- (b) polling writes the expected rows under the dott_berlin tree -----


def test_polling_dott_writes_expected_rows(tmp_path):
    clock = FakeClock(NOW)
    settings = make_settings(tmp_path)
    source = DottSource(settings)
    transport = fixture_replay_transport(SOURCE_NAME)
    collector = make_collector(tmp_path, source, transport, clock)

    for feed_name in REQUIRED_FEEDS:
        assert collector.poll_feed(feed_name) == PollResult.WRITTEN

    station_status = load_fixture(SOURCE_NAME, "station_status")
    station_information = load_fixture(SOURCE_NAME, "station_information")
    vehicle_types = load_fixture(SOURCE_NAME, "vehicle_types")
    free_bike_status = load_fixture(SOURCE_NAME, "free_bike_status")

    status_table = pq.read_table(_part_files(tmp_path, "station_status")[0])
    assert status_table.num_rows == 568 == len(station_status["data"]["stations"])
    assert all(value is None for value in status_table.column("num_docks_available").to_pylist())

    info_table = pq.read_table(_part_files(tmp_path, "station_information")[0])
    assert info_table.num_rows == 568 == len(station_information["data"]["stations"])

    vehicle_table = pq.read_table(_part_files(tmp_path, "vehicle_types")[0])
    assert vehicle_table.num_rows == 1 == len(vehicle_types["data"]["vehicle_types"])

    cell_table = pq.read_table(_part_files(tmp_path, "free_bike_status")[0])
    unique_bike_ids = {bike["bike_id"] for bike in free_bike_status["data"]["bikes"]}
    assert sum(cell_table.column("num_bikes").to_pylist()) == len(unique_bike_ids)


# -- (c) no bike_id reaches disk ------------------------------------------


def test_no_bike_id_reaches_written_parquet_files(tmp_path):
    clock = FakeClock(NOW)
    settings = make_settings(tmp_path)
    source = DottSource(settings)
    transport = fixture_replay_transport(SOURCE_NAME)
    collector = make_collector(tmp_path, source, transport, clock)

    for feed_name in REQUIRED_FEEDS:
        assert collector.poll_feed(feed_name) == PollResult.WRITTEN

    free_bike_status = load_fixture(SOURCE_NAME, "free_bike_status")
    bike_ids = {bike["bike_id"] for bike in free_bike_status["data"]["bikes"]}
    assert bike_ids

    parquet_files = list(tmp_path.rglob("part-*.parquet"))
    assert parquet_files
    for path in parquet_files:
        table = pq.read_table(path)
        for column, field in zip(table.columns, table.schema):
            if pa.types.is_string(field.type):
                assert bike_ids.isdisjoint(column.to_pylist())


# -- (d) ttl 0 still polls 2-minute feeds no more often than every 120 s -


def _advancing_response(feed_name: str, interval_s: int = 120, ttl: int = 0):
    body = load_fixture(SOURCE_NAME, feed_name)

    def _respond(request: httpx.Request, call_count: int) -> httpx.Response:
        last_updated = BASE_LAST_UPDATED + call_count * interval_s
        return httpx.Response(200, json={**body, "last_updated": last_updated, "ttl": ttl})

    return _respond


def test_dott_ttl_zero_does_not_poll_2_minute_feeds_faster_than_120_s(tmp_path):
    clock = FakeClock(NOW)
    settings = make_settings(tmp_path)
    source = DottSource(settings)
    overrides = {
        "station_status": _advancing_response("station_status"),
        "free_bike_status": _advancing_response("free_bike_status"),
    }
    transport = fixture_replay_transport(SOURCE_NAME, overrides)
    collector = make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=10)

    assert clock.sleeps, "expected the loop to sleep between iterations"
    assert all(sleep == 120 for sleep in clock.sleeps)
