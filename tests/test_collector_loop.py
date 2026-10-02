"""Tests for Collector.run: ttl-aware scheduling and the failure retry floor.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/<source_name>/ (the autouse socket guard
in conftest.py would fail the test if it tried to reach the network).

The retry-floor tests (NEVER-SUCCEEDED, SUCCEEDED-THEN-FAILING, RECOVERY)
assert on the simulated-time gap between requests, not just on
``clock.sleeps``: a loop that skips sleeping and re-polls instantly can still
produce sleep values and request counts that look correct.

Parametrized over the ``source_name`` fixture (nextbike_bn, dott_berlin) so
the same loop and retry-floor behaviour is proven against both sources
behind the Source interface.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import httpx

from berlinbikes.backoff import FakeClock

from tests.helpers import (
    StubSource,
    fixture_replay_transport,
    load_fixture,
    make_collector,
    make_settings,
    make_source,
)

FEED_TO_DATASET = {
    "station_status": "station_status",
    "station_information": "station_information",
    "vehicle_types": "vehicle_types",
    "free_bike_status": "free_bike_cells",
}


def _now(source_name: str) -> datetime:
    """NOW anchored to the fixture's own last_updated.

    The fixtures record a real ``last_updated`` far in the future of any
    fixed calendar date. Anchoring NOW to it keeps ``next_due`` (which takes
    the max of ``last_updated + ttl`` and ``fetched_at + interval``) driven
    by the interval in these tests, instead of by an unrelated multi-year
    gap between a hardcoded NOW and the fixture's recorded timestamp.
    """
    last_updated = load_fixture(source_name, "station_status")["last_updated"]
    return datetime.fromtimestamp(last_updated, tz=timezone.utc)


def _envelope(source_name: str, feed_name: str, last_updated: int, ttl: int = 60) -> dict:
    body = load_fixture(source_name, feed_name)
    return {**body, "last_updated": last_updated, "ttl": ttl}


def _advancing_response(source_name: str, feed_name: str, interval_s: int = 120, ttl: int = 60):
    base_last_updated = load_fixture(source_name, "station_status")["last_updated"]

    def _respond(request: httpx.Request, call_count: int) -> httpx.Response:
        last_updated = base_last_updated + call_count * interval_s
        return httpx.Response(200, json=_envelope(source_name, feed_name, last_updated, ttl=ttl))

    return _respond


def _part_files(tmp_path, source_name: str, feed_name: str):
    dataset = FEED_TO_DATASET[feed_name]
    dataset_dir = tmp_path / source_name / dataset
    if not dataset_dir.is_dir():
        return []
    return sorted(dataset_dir.glob("date=*/part-*.parquet"))


# -- (a) a simulated hour follows the 120 s / 86400 s schedule ----------------
def test_run_polls_2_minute_feeds_every_120_s_and_daily_feeds_once(tmp_path, source_name):
    clock = FakeClock(_now(source_name))
    settings = make_settings(tmp_path)
    source = make_source(source_name, settings)
    overrides = {
        "station_status": _advancing_response(source_name, "station_status"),
        "free_bike_status": _advancing_response(source_name, "free_bike_status"),
    }
    transport = fixture_replay_transport(source_name, overrides)
    collector = make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=30)

    assert clock.sleeps, "expected the loop to sleep between iterations"
    assert all(s == 120 for s in clock.sleeps)

    status_files = _part_files(tmp_path, source_name, "station_status")
    cell_files = _part_files(tmp_path, source_name, "free_bike_status")
    assert 28 <= len(status_files) <= 30
    assert 28 <= len(cell_files) <= 30

    assert len(_part_files(tmp_path, source_name, "station_information")) == 1
    assert len(_part_files(tmp_path, source_name, "vehicle_types")) == 1

# -- (b) a longer ttl stretches the sleep interval ----------------------------
def test_run_sleeps_for_the_feeds_ttl_when_it_exceeds_the_interval(tmp_path, source_name):
    clock = FakeClock(_now(source_name))
    source = StubSource(
        name=source_name, gbfs_url="https://example.invalid/gbfs.json", feeds=("station_status",)
    )
    overrides = {"station_status": _advancing_response(source_name, "station_status", interval_s=300, ttl=300)}
    transport = fixture_replay_transport(source_name, overrides)
    collector = make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=5)

    assert clock.sleeps
    assert all(s == 300 for s in clock.sleeps)

# -- (c) a malformed payload is logged and the other feeds keep going --------
def _malformed_station_status_response(source_name: str) -> httpx.Response:
    body = load_fixture(source_name, "station_status")
    stations = [dict(station) for station in body["data"]["stations"]]
    del stations[0]["station_id"]
    broken = {**body, "data": {**body["data"], "stations": stations}}
    return httpx.Response(200, json=broken)


def test_run_logs_and_continues_when_a_feed_payload_is_malformed(tmp_path, source_name, caplog):
    clock = FakeClock(_now(source_name))
    settings = make_settings(tmp_path)
    source = make_source(source_name, settings)
    overrides = {"station_status": _malformed_station_status_response(source_name)}
    transport = fixture_replay_transport(source_name, overrides)
    collector = make_collector(tmp_path, source, transport, clock)

    with caplog.at_level("WARNING"):
        collector.run(max_iterations=3)

    assert _part_files(tmp_path, source_name, "station_status") == []
    assert len(_part_files(tmp_path, source_name, "free_bike_status")) >= 1
    assert len(_part_files(tmp_path, source_name, "station_information")) == 1
    assert len(_part_files(tmp_path, source_name, "vehicle_types")) == 1
    assert any("station_status" in record.message for record in caplog.records)

# -- (d) a stop event set mid-run ends run() promptly -------------------------
def test_run_stops_as_soon_as_the_stop_event_is_set(tmp_path, source_name):
    clock = FakeClock(_now(source_name))
    settings = make_settings(tmp_path)
    source = make_source(source_name, settings)
    stop = threading.Event()
    request_count = {"station_status": 0}

    def _respond(request: httpx.Request, call_count: int) -> httpx.Response:
        request_count["station_status"] = call_count + 1
        if call_count == 1:
            stop.set()
        return httpx.Response(200, json=load_fixture(source_name, "station_status"))

    overrides = {"station_status": _respond}
    transport = fixture_replay_transport(source_name, overrides)
    collector = make_collector(tmp_path, source, transport, clock)

    collector.run(stop=stop)

    assert stop.is_set()
    assert request_count["station_status"] <= 2

# -- (e) NEVER-SUCCEEDED: a permanently failing feed is never hammered -------
def test_run_never_exceeds_retry_floor_for_a_feed_that_has_never_succeeded(tmp_path, source_name):
    clock = FakeClock(_now(source_name))
    settings = make_settings(tmp_path)
    source = make_source(source_name, settings)
    request_times: list[datetime] = []

    def _always_503(request: httpx.Request, call_count: int) -> httpx.Response:
        request_times.append(clock.now())
        return httpx.Response(503)

    overrides = {
        "vehicle_types": _always_503,
        "station_status": _advancing_response(source_name, "station_status"),
        "free_bike_status": _advancing_response(source_name, "free_bike_status"),
    }
    transport = fixture_replay_transport(source_name, overrides)
    collector = make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=6)

    assert 1.0 not in clock.sleeps
    assert all(s >= 120 for s in clock.sleeps)
    for earlier, later in zip(request_times, request_times[1:]):
        assert (later - earlier).total_seconds() >= 120
    assert len(_part_files(tmp_path, source_name, "vehicle_types")) == 0

# -- (f)/(g) SUCCEEDED-THEN-FAILING, then RECOVERY ---------------------------
def test_run_retries_a_feed_that_failed_after_succeeding_at_no_more_than_the_floor(tmp_path, source_name):
    clock = FakeClock(_now(source_name))
    base_last_updated = load_fixture(source_name, "station_status")["last_updated"]
    source = StubSource(
        name=source_name, gbfs_url="https://example.invalid/gbfs.json", feeds=("station_status",)
    )
    request_times: list[datetime] = []

    def _succeed_once_then_fail(request: httpx.Request, call_count: int) -> httpx.Response:
        request_times.append(clock.now())
        if call_count == 0:
            return httpx.Response(200, json=_envelope(source_name, "station_status", base_last_updated))
        return httpx.Response(503)

    overrides = {"station_status": _succeed_once_then_fail}
    transport = fixture_replay_transport(source_name, overrides)
    collector = make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=6)

    assert len(request_times) == 6
    assert 1.0 not in clock.sleeps
    assert all(s >= 120 for s in clock.sleeps)
    for earlier, later in zip(request_times, request_times[1:]):
        assert (later - earlier).total_seconds() >= 120
    assert len(_part_files(tmp_path, source_name, "station_status")) == 1


def test_run_recovers_and_resumes_the_normal_schedule_after_a_feed_heals(tmp_path, source_name):
    clock = FakeClock(_now(source_name))
    base_last_updated = load_fixture(source_name, "station_status")["last_updated"]
    source = StubSource(
        name=source_name, gbfs_url="https://example.invalid/gbfs.json", feeds=("station_status",)
    )
    request_times: list[datetime] = []

    def _fail_then_heal(request: httpx.Request, call_count: int) -> httpx.Response:
        request_times.append(clock.now())
        if call_count == 0:
            return httpx.Response(200, json=_envelope(source_name, "station_status", base_last_updated))
        if call_count < 6:
            return httpx.Response(503)
        last_updated = base_last_updated + call_count * 120
        return httpx.Response(200, json=_envelope(source_name, "station_status", last_updated))

    overrides = {"station_status": _fail_then_heal}
    transport = fixture_replay_transport(source_name, overrides)
    collector = make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=6)
    assert "station_status" in collector._retry_at
    files_during_outage = len(_part_files(tmp_path, source_name, "station_status"))
    assert files_during_outage == 1

    collector.run(max_iterations=3)

    assert "station_status" not in collector._retry_at
    assert len(_part_files(tmp_path, source_name, "station_status")) > files_during_outage
    for earlier, later in zip(request_times, request_times[1:]):
        assert (later - earlier).total_seconds() >= 120
