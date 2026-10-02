"""Tests for Collector restart resume: no duplicates/gaps, daily-feed skip,
and crash-during-write recovery.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/<source_name>/ (the autouse socket guard
in conftest.py would fail the test if it tried to reach the network).

Parametrized over the ``source_name`` fixture (nextbike_bn, dott_berlin) so
the same restart behaviour is proven against both sources behind the Source
interface.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pyarrow.parquet as pq
import pytest

from berlinbikes.backoff import FakeClock
from berlinbikes.collector import FEED_TO_DATASET, PollResult

from tests.helpers import StubSource, fixture_replay_transport, load_fixture, make_collector

BERLIN_TZ = ZoneInfo("Europe/Berlin")


def _now(source_name: str) -> datetime:
    last_updated = load_fixture(source_name, "station_status")["last_updated"]
    return datetime.fromtimestamp(last_updated, tz=timezone.utc)


def _envelope(source_name: str, feed_name: str, last_updated: int, ttl: int = 60) -> dict:
    body = load_fixture(source_name, feed_name)
    return {**body, "last_updated": last_updated, "ttl": ttl}


def _part_files(tmp_path, source_name: str, feed_name: str):
    dataset = FEED_TO_DATASET[feed_name]
    dataset_dir = tmp_path / source_name / dataset
    if not dataset_dir.is_dir():
        return []
    return sorted(dataset_dir.glob("date=*/part-*.parquet"))


def _gap_rows(tmp_path, source_name: str) -> list[dict]:
    dataset_dir = tmp_path / source_name / "gaps"
    if not dataset_dir.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(dataset_dir.glob("date=*/part-*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def _single_feed_source(source_name: str, feed_name: str) -> StubSource:
    return StubSource(name=source_name, gbfs_url="https://example.invalid/gbfs.json", feeds=(feed_name,))


def _expected_next_berlin_midnight(after: datetime) -> datetime:
    local = after.astimezone(BERLIN_TZ)
    next_midnight_local = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=BERLIN_TZ)
    return next_midnight_local.astimezone(timezone.utc)


# -- Test 1: a quick restart resumes without a duplicate row or a gap --------
def test_restart_mid_day_resumes_without_duplicate_or_gap(tmp_path, source_name):
    source = _single_feed_source(source_name, "station_status")
    now = _now(source_name)
    base_last_updated = load_fixture(source_name, "station_status")["last_updated"]

    first_clock = FakeClock(now)
    first_transport = fixture_replay_transport(
        source_name, {"station_status": httpx.Response(200, json=_envelope(source_name, "station_status", base_last_updated))}
    )
    first = make_collector(tmp_path, source, first_transport, first_clock)
    assert first.poll_feed("station_status") == PollResult.WRITTEN

    restart_clock = FakeClock(now)
    restart_transport = fixture_replay_transport(
        source_name, {"station_status": httpx.Response(200, json=_envelope(source_name, "station_status", base_last_updated))}
    )
    second = make_collector(tmp_path, source, restart_transport, restart_clock)

    poll_results: list[PollResult] = []
    original_poll_feed = second.poll_feed

    def _recording_poll_feed(feed_name: str) -> PollResult:
        result = original_poll_feed(feed_name)
        poll_results.append(result)
        return result

    second.poll_feed = _recording_poll_feed  # type: ignore[method-assign]
    second.run(max_iterations=1)

    assert poll_results == [PollResult.UNCHANGED]
    assert len(_part_files(tmp_path, source_name, "station_status")) == 1
    assert _gap_rows(tmp_path, source_name) == []


# -- Test 2: a daily feed is only skipped when its stored snapshot's --------
#    Europe/Berlin calendar date is today's ----------------------------------
TODAY_NOW = datetime(2026, 10, 2, 7, 0, 0, tzinfo=timezone.utc)
TODAY_STORED = TODAY_NOW - timedelta(hours=2)
YESTERDAY_STORED = TODAY_NOW - timedelta(days=1)
# UTC date is the same for both instants, but Europe/Berlin (UTC+2 in
# October) has already rolled over to the next calendar day by NEAR_NOW.
NEAR_MIDNIGHT_STORED = datetime(2026, 10, 2, 21, 50, 0, tzinfo=timezone.utc)
NEAR_MIDNIGHT_NOW = datetime(2026, 10, 2, 22, 10, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "label, stored_ts, now_ts, expect_fetch",
    [
        ("today_berlin_date_is_not_refetched", TODAY_STORED, TODAY_NOW, False),
        ("yesterday_berlin_date_is_refetched", YESTERDAY_STORED, TODAY_NOW, True),
        ("same_utc_day_but_berlin_rolled_over_is_refetched", NEAR_MIDNIGHT_STORED, NEAR_MIDNIGHT_NOW, True),
    ],
)
def test_daily_feed_skipped_only_when_stored_snapshot_is_todays_berlin_day(
    tmp_path, source_name, label, stored_ts, now_ts, expect_fetch
):
    source = _single_feed_source(source_name, "station_information")

    seed_clock = FakeClock(stored_ts)
    seed_transport = fixture_replay_transport(
        source_name,
        {
            "station_information": httpx.Response(
                200, json=_envelope(source_name, "station_information", int(stored_ts.timestamp()))
            )
        },
    )
    seed = make_collector(tmp_path, source, seed_transport, seed_clock)
    assert seed.poll_feed("station_information") == PollResult.WRITTEN

    call_count = {"n": 0}
    new_last_updated = int(now_ts.timestamp())

    def _respond(request: httpx.Request, count: int) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=_envelope(source_name, "station_information", new_last_updated))

    restart_transport = fixture_replay_transport(source_name, {"station_information": _respond})
    restart_clock = FakeClock(now_ts)
    restarted = make_collector(tmp_path, source, restart_transport, restart_clock)

    restarted.run(max_iterations=1)

    assert (call_count["n"] > 0) == expect_fetch, label
    if not expect_fetch:
        expected_due = _expected_next_berlin_midnight(now_ts)
        assert restarted._effective_due("station_information") == expected_due


# -- Test 3: a crash during a write leaves no partial or part file, and a ---
#    fresh collector then writes the snapshot normally -----------------------
def test_crash_during_write_leaves_no_partial_file_and_fresh_collector_recovers(tmp_path, monkeypatch, source_name):
    import berlinbikes.storage as storage_module

    source = _single_feed_source(source_name, "station_status")
    now = _now(source_name)
    base_last_updated = load_fixture(source_name, "station_status")["last_updated"]
    clock = FakeClock(now)
    transport = fixture_replay_transport(
        source_name, {"station_status": httpx.Response(200, json=_envelope(source_name, "station_status", base_last_updated))}
    )
    collector = make_collector(tmp_path, source, transport, clock)

    def _boom(src, dst):
        raise OSError("simulated crash during publish")

    monkeypatch.setattr(storage_module.os, "link", _boom)

    with pytest.raises(OSError):
        collector.poll_feed("station_status")

    partition_dir = tmp_path / source_name / "station_status" / f"date={now.date().isoformat()}"
    assert list(partition_dir.glob("part-*.parquet")) == []
    assert list(partition_dir.glob(".tmp-*")) == []

    monkeypatch.undo()

    fresh_transport = fixture_replay_transport(
        source_name, {"station_status": httpx.Response(200, json=_envelope(source_name, "station_status", base_last_updated))}
    )
    fresh = make_collector(tmp_path, source, fresh_transport, FakeClock(now))
    assert fresh.poll_feed("station_status") == PollResult.WRITTEN
