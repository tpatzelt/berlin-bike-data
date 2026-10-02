"""Tests for berlinbikes.collector: the single-feed poll step.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/nextbike_bn/ (the autouse socket guard in
conftest.py would fail the test if it tried to reach the network).
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pyarrow.parquet as pq

from berlinbikes.backoff import FakeClock
from berlinbikes.collector import Collector, PollResult
from berlinbikes.config import Settings
from berlinbikes.gbfs import REQUIRED_FEEDS, GbfsClient
from berlinbikes.sources import NextbikeSource
from berlinbikes.storage import Storage

from tests.helpers import fixture_replay_transport, load_fixture

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)
SOURCE_NAME = "nextbike_bn"

FEED_TO_DATASET = {
    "station_status": "station_status",
    "station_information": "station_information",
    "vehicle_types": "vehicle_types",
    "free_bike_status": "free_bike_cells",
}


def _settings(tmp_path) -> Settings:
    return Settings.from_env(
        {
            "BIKES_DATA_DIR": str(tmp_path),
            "BIKES_USER_AGENT": "berlinbikes-test/1.0",
        }
    )


def _make_collector(tmp_path, clock: FakeClock | None = None, overrides=None) -> Collector:
    clock = clock or FakeClock(NOW)
    settings = _settings(tmp_path)
    source = NextbikeSource(settings)
    transport = fixture_replay_transport(SOURCE_NAME, overrides)
    client = GbfsClient(source.gbfs_url, settings.user_agent, transport=transport, clock=clock)
    storage = Storage(tmp_path)
    return Collector(source, client, storage, clock)


def _snapshot_day(feed_name: str = "station_status"):
    last_updated = load_fixture(SOURCE_NAME, feed_name)["last_updated"]
    return datetime.fromtimestamp(last_updated, tz=timezone.utc).date()


def _partition_dir(tmp_path, feed_name: str, day=None):
    day = day or _snapshot_day(feed_name)
    dataset = FEED_TO_DATASET[feed_name]
    return tmp_path / SOURCE_NAME / dataset / f"date={day.isoformat()}"


def _part_files(tmp_path, feed_name: str):
    partition_dir = _partition_dir(tmp_path, feed_name)
    if not partition_dir.is_dir():
        return []
    return sorted(partition_dir.glob("part-*.parquet"))


def test_poll_feed_writes_rows_matching_fixture_counts(tmp_path):
    collector = _make_collector(tmp_path)

    for feed_name in REQUIRED_FEEDS:
        assert collector.poll_feed(feed_name) == PollResult.WRITTEN

    station_status = load_fixture(SOURCE_NAME, "station_status")
    station_information = load_fixture(SOURCE_NAME, "station_information")
    vehicle_types = load_fixture(SOURCE_NAME, "vehicle_types")
    free_bike_status = load_fixture(SOURCE_NAME, "free_bike_status")

    status_files = _part_files(tmp_path, "station_status")
    assert len(status_files) == 1
    status_table = pq.read_table(status_files[0])
    assert status_table.num_rows == len(station_status["data"]["stations"])

    info_files = _part_files(tmp_path, "station_information")
    assert len(info_files) == 1
    info_table = pq.read_table(info_files[0])
    assert info_table.num_rows == len(station_information["data"]["stations"])

    vehicle_files = _part_files(tmp_path, "vehicle_types")
    assert len(vehicle_files) == 1
    vehicle_table = pq.read_table(vehicle_files[0])
    assert vehicle_table.num_rows == len(vehicle_types["data"]["vehicle_types"])

    cell_files = _part_files(tmp_path, "free_bike_status")
    assert len(cell_files) == 1
    cells_table = pq.read_table(cell_files[0])
    assert sum(cells_table.column("num_bikes").to_pylist()) == len(free_bike_status["data"]["bikes"])


def test_poll_feed_returns_unchanged_when_last_updated_has_not_advanced(tmp_path):
    collector = _make_collector(tmp_path)

    assert collector.poll_feed("station_status") == PollResult.WRITTEN
    assert collector.poll_feed("station_status") == PollResult.UNCHANGED

    assert len(_part_files(tmp_path, "station_status")) == 1


def test_poll_feed_returns_duplicate_for_a_fresh_collector_on_the_same_storage(tmp_path):
    first_collector = _make_collector(tmp_path)
    assert first_collector.poll_feed("station_status") == PollResult.WRITTEN

    second_collector = _make_collector(tmp_path)
    assert second_collector.poll_feed("station_status") == PollResult.DUPLICATE

    assert len(_part_files(tmp_path, "station_status")) == 1


def test_no_bike_id_reaches_written_parquet_files(tmp_path):
    collector = _make_collector(tmp_path)

    for feed_name in REQUIRED_FEEDS:
        assert collector.poll_feed(feed_name) == PollResult.WRITTEN

    free_bike_status = load_fixture(SOURCE_NAME, "free_bike_status")
    bike_ids = [bike["bike_id"].encode() for bike in free_bike_status["data"]["bikes"]]
    assert bike_ids

    parquet_files = list(tmp_path.rglob("part-*.parquet"))
    assert parquet_files
    for path in parquet_files:
        content = path.read_bytes()
        for bike_id in bike_ids:
            assert bike_id not in content


def test_station_missing_num_docks_available_is_stored_as_null(tmp_path):
    body = load_fixture(SOURCE_NAME, "station_status")
    stations = [dict(station) for station in body["data"]["stations"]]
    missing_station_id = stations[0]["station_id"]
    del stations[0]["num_docks_available"]
    modified = {**body, "data": {**body["data"], "stations": stations}}

    collector = _make_collector(
        tmp_path, overrides={"station_status": httpx.Response(200, json=modified)}
    )

    assert collector.poll_feed("station_status") == PollResult.WRITTEN

    status_table = pq.read_table(_part_files(tmp_path, "station_status")[0])
    rows = {row["station_id"]: row["num_docks_available"] for row in status_table.to_pylist()}

    assert rows[missing_station_id] is None
    other_values = [value for station_id, value in rows.items() if station_id != missing_station_id]
    assert other_values
    assert all(isinstance(value, int) for value in other_values)
