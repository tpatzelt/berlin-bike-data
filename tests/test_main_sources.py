"""Tests for berlinbikes.__main__: the multi-source threaded run loop.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/<source_name>/ (the autouse socket guard
in conftest.py would fail a test that tried to reach the network).

Every test drives real Collectors (via tests.helpers.make_collector) through
run_sources, bounded by a counting response override that sets ``stop`` once
enough has happened, plus a hang-guard timer in case that trigger is ever
missed, so a bug here fails fast instead of hanging the suite.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

import httpx

from berlinbikes.__main__ import build_collectors, run_sources
from berlinbikes.backoff import FakeClock

from tests.helpers import fixture_replay_transport, make_collector, make_settings, make_source

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)

#: Safety net only: each test's own counting override is expected to set
#: ``stop`` well before this fires.
HANG_GUARD_S = 2.0


def _hang_guard(stop: threading.Event, seconds: float = HANG_GUARD_S) -> threading.Timer:
    timer = threading.Timer(seconds, stop.set)
    timer.daemon = True
    timer.start()
    return timer


def _run_bounded(collectors, stop: threading.Event, **kwargs) -> None:
    guard = _hang_guard(stop)
    try:
        run_sources(collectors, stop, **kwargs)
    finally:
        guard.cancel()


def _part_files(tmp_path, source_name: str, dataset: str = "station_status"):
    dataset_dir = tmp_path / source_name / dataset
    if not dataset_dir.is_dir():
        return []
    return [p for day_dir in dataset_dir.glob("date=*") for p in day_dir.glob("part-*.parquet")]


def _stop_after(stop: threading.Event, source_name: str, feed_name: str, limit: int):
    """A station_status override that counts calls and sets ``stop`` once
    ``limit`` requests for this source have been served.
    """

    def _respond(request: httpx.Request, call_count: int) -> httpx.Response:
        from tests.helpers import load_fixture

        if call_count + 1 >= limit:
            stop.set()
        return httpx.Response(200, json=load_fixture(source_name, feed_name))

    return _respond


def _all_503_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(503))


def test_run_sources_writes_both_sources_under_their_own_source_dir(tmp_path):
    stop = threading.Event()
    nextbike_settings = make_settings(tmp_path)
    dott_settings = make_settings(tmp_path, BIKES_DOTT_ENABLED="true")

    nextbike_source = make_source("nextbike_bn", nextbike_settings)
    dott_source = make_source("dott_berlin", dott_settings)

    nextbike_transport = fixture_replay_transport(
        "nextbike_bn", {"station_status": _stop_after(stop, "nextbike_bn", "station_status", limit=3)}
    )
    dott_transport = fixture_replay_transport("dott_berlin")

    nextbike_collector = make_collector(tmp_path, nextbike_source, nextbike_transport, FakeClock(NOW))
    dott_collector = make_collector(tmp_path, dott_source, dott_transport, FakeClock(NOW))

    _run_bounded([nextbike_collector, dott_collector], stop, restart_delay_s=0.01)

    assert stop.is_set()
    assert _part_files(tmp_path, "nextbike_bn")
    assert _part_files(tmp_path, "dott_berlin")


def test_a_failing_dott_source_does_not_stop_or_gap_nextbike(tmp_path):
    stop = threading.Event()
    nextbike_settings = make_settings(tmp_path)
    dott_settings = make_settings(tmp_path, BIKES_DOTT_ENABLED="true")

    nextbike_source = make_source("nextbike_bn", nextbike_settings)
    dott_source = make_source("dott_berlin", dott_settings)

    nextbike_transport = fixture_replay_transport(
        "nextbike_bn", {"station_status": _stop_after(stop, "nextbike_bn", "station_status", limit=3)}
    )
    dott_transport = _all_503_transport()

    nextbike_collector = make_collector(tmp_path, nextbike_source, nextbike_transport, FakeClock(NOW))
    dott_collector = make_collector(tmp_path, dott_source, dott_transport, FakeClock(NOW))

    _run_bounded([nextbike_collector, dott_collector], stop, restart_delay_s=0.01)

    assert stop.is_set()
    assert _part_files(tmp_path, "nextbike_bn")
    assert _part_files(tmp_path, "nextbike_bn", "gaps") == []


def test_a_crashing_collector_is_logged_and_restarted_without_affecting_the_other(tmp_path, caplog):
    stop = threading.Event()
    nextbike_settings = make_settings(tmp_path)
    dott_settings = make_settings(tmp_path, BIKES_DOTT_ENABLED="true")

    nextbike_source = make_source("nextbike_bn", nextbike_settings)
    dott_source = make_source("dott_berlin", dott_settings)

    nextbike_transport = fixture_replay_transport(
        "nextbike_bn", {"station_status": _stop_after(stop, "nextbike_bn", "station_status", limit=3)}
    )
    dott_transport = fixture_replay_transport("dott_berlin")

    nextbike_collector = make_collector(tmp_path, nextbike_source, nextbike_transport, FakeClock(NOW))
    dott_collector = make_collector(tmp_path, dott_source, dott_transport, FakeClock(NOW))

    original_run = dott_collector.run
    call_count = {"n": 0}

    def _flaky_run(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom")
        return original_run(*args, **kwargs)

    dott_collector.run = _flaky_run

    with caplog.at_level(logging.ERROR):
        _run_bounded([nextbike_collector, dott_collector], stop, restart_delay_s=0.01)

    assert stop.is_set()
    assert call_count["n"] >= 2, "the dott collector should have been restarted after crashing"
    crash_records = [r for r in caplog.records if "dott_berlin" in r.message and "crashed" in r.message]
    assert crash_records
    assert _part_files(tmp_path, "nextbike_bn")


def test_build_collectors_defaults_to_nextbike_only(tmp_path):
    settings = make_settings(tmp_path)
    collectors = build_collectors(settings, FakeClock(NOW))
    assert [c.source.name for c in collectors] == ["nextbike_bn"]


def test_build_collectors_includes_dott_when_enabled(tmp_path):
    settings = make_settings(tmp_path, BIKES_DOTT_ENABLED="true")
    collectors = build_collectors(settings, FakeClock(NOW))
    assert [c.source.name for c in collectors] == ["nextbike_bn", "dott_berlin"]
