"""Tests for collector_down gap rows written on restart after real downtime.

Covers the three scenarios from the task notes: a plain restart after
downtime (Test A), a restart that lands mid an already-flushed fetch_error
outage (Test B), and a restart that lands right after an already-written
stale_feed row (Test C). In every case the downtime must be covered by
non-overlapping gap rows and no "collided ... skipping" warning from
``Collector._write_gap`` may appear, since that warning means a gap got
silently dropped.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/<source_name>/ (the autouse socket guard
in conftest.py would fail the test if it tried to reach the network).

Parametrized over the ``source_name`` fixture (nextbike_bn, dott_berlin) so
the same restart-gap behaviour is proven against both sources behind the
Source interface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pyarrow.parquet as pq

from berlinbikes.backoff import FakeClock
from berlinbikes.collector import PollResult

from tests.helpers import StubSource, fixture_replay_transport, load_fixture, make_collector


def _now(source_name: str) -> datetime:
    last_updated = load_fixture(source_name, "station_status")["last_updated"]
    return datetime.fromtimestamp(last_updated, tz=timezone.utc)


def _envelope(source_name: str, feed_name: str, last_updated: datetime, ttl: int = 60) -> dict:
    body = load_fixture(source_name, feed_name)
    return {**body, "last_updated": int(last_updated.timestamp()), "ttl": ttl}


def _source(source_name: str) -> StubSource:
    return StubSource(name=source_name, gbfs_url="https://example.invalid/gbfs.json", feeds=("station_status",))


def _gap_rows(tmp_path, source_name: str, feed_name: str | None = None) -> list[dict]:
    dataset_dir = tmp_path / source_name / "gaps"
    if not dataset_dir.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(dataset_dir.glob("date=*/part-*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    if feed_name is not None:
        rows = [row for row in rows if row["feed"] == feed_name]
    return rows


def _assert_no_collision_warning(caplog) -> None:
    assert not any("collided" in record.message and "skipping" in record.message for record in caplog.records)


# -- Test A: a quick-enough restart resumes without a gap, a slow one opens --
#    a collector_down gap that ends at the first *new* snapshot, not at the
#    clock time the restarted process happened to poll at ------------------
def test_restart_after_real_downtime_writes_collector_down_gap_ending_at_first_new_snapshot(tmp_path, caplog, source_name):
    source = _source(source_name)
    t0 = _now(source_name)

    seed_clock = FakeClock(t0)
    seed_transport = fixture_replay_transport(
        source_name, {"station_status": httpx.Response(200, json=_envelope(source_name, "station_status", t0))}
    )
    seed = make_collector(tmp_path, source, seed_transport, seed_clock)
    assert seed.poll_feed("station_status") == PollResult.WRITTEN

    resume_at = t0 + timedelta(minutes=30)
    first_new_snapshot = t0 + timedelta(minutes=34)

    restart_transport = fixture_replay_transport(
        source_name,
        {"station_status": httpx.Response(200, json=_envelope(source_name, "station_status", first_new_snapshot))},
    )
    restart_clock = FakeClock(resume_at)
    restarted = make_collector(tmp_path, source, restart_transport, restart_clock)

    with caplog.at_level("INFO"):
        restarted.run(max_iterations=1)

    rows = _gap_rows(tmp_path, source_name, "station_status")
    assert len(rows) == 1
    row = rows[0]
    assert row["reason"] == "collector_down"
    assert row["gap_start"] == t0
    assert row["gap_end"] == first_new_snapshot
    assert "station_status" not in restarted._outage_start
    _assert_no_collision_warning(caplog)


# -- Test B: a fetch_error outage open at shutdown gets flushed; restarting --
#    30 minutes later must cover the rest of the downtime with a
#    collector_down gap that starts exactly where the flushed one ended,
#    with no overlap and no hole -------------------------------------------
def test_restart_after_flushed_fetch_error_outage_covers_downtime_without_overlap(tmp_path, caplog, source_name):
    source = _source(source_name)
    t0 = _now(source_name)

    clock1 = FakeClock(t0)

    def _respond_down(request: httpx.Request, call_count: int) -> httpx.Response:
        if call_count == 0:
            return httpx.Response(200, json=_envelope(source_name, "station_status", t0))
        return httpx.Response(503)

    transport1 = fixture_replay_transport(source_name, {"station_status": _respond_down})
    first = make_collector(tmp_path, source, transport1, clock1)

    with caplog.at_level("INFO"):
        first.run(max_iterations=4)

    flushed = _gap_rows(tmp_path, source_name, "station_status")
    assert len(flushed) == 1
    assert flushed[0]["reason"] == "fetch_error"
    assert flushed[0]["gap_start"] == t0
    shutdown_at = flushed[0]["gap_end"]
    assert shutdown_at == clock1.now()

    resume_at = shutdown_at + timedelta(minutes=30)
    first_new_snapshot = resume_at + timedelta(minutes=10)

    def _respond_restart(request: httpx.Request, call_count: int) -> httpx.Response:
        if call_count < 2:
            return httpx.Response(200, json=_envelope(source_name, "station_status", t0))
        return httpx.Response(200, json=_envelope(source_name, "station_status", first_new_snapshot))

    transport2 = fixture_replay_transport(source_name, {"station_status": _respond_restart})
    clock2 = FakeClock(resume_at)
    second = make_collector(tmp_path, source, transport2, clock2)

    with caplog.at_level("INFO"):
        second.run(max_iterations=3)

    rows = sorted(_gap_rows(tmp_path, source_name, "station_status"), key=lambda r: r["gap_start"])
    assert len(rows) == 2
    fetch_error_row, collector_down_row = rows

    assert fetch_error_row["reason"] == "fetch_error"
    assert fetch_error_row["gap_start"] == t0
    assert fetch_error_row["gap_end"] == shutdown_at

    assert collector_down_row["reason"] == "collector_down"
    assert collector_down_row["gap_start"] == shutdown_at
    assert collector_down_row["gap_end"] == first_new_snapshot

    _assert_no_collision_warning(caplog)


# -- Test C: a stale_feed row already written at last_ts before shutdown; ---
#    restarting 30 minutes later must not collide with that key and must
#    still cover the downtime ------------------------------------------------
def test_restart_after_stale_feed_row_does_not_collide_and_covers_downtime(tmp_path, caplog, source_name):
    source = _source(source_name)
    t0 = _now(source_name)
    clock1 = FakeClock(t0)

    transport1 = fixture_replay_transport(
        source_name, {"station_status": httpx.Response(200, json=_envelope(source_name, "station_status", t0))}
    )
    first = make_collector(tmp_path, source, transport1, clock1)

    with caplog.at_level("INFO"):
        # interval=120s, STALE_FACTOR=3 -> threshold 360s; the schedule
        # advances the clock by 120s per pass once the feed's own
        # last_updated (fixed at t0) is older than its ttl, so 5 passes
        # (iterations 0..4) land exactly on the first now - last_ts > 360s
        # check.
        first.run(max_iterations=5)

    stale_rows = _gap_rows(tmp_path, source_name, "station_status")
    assert len(stale_rows) == 1
    assert stale_rows[0]["reason"] == "stale_feed"
    assert stale_rows[0]["gap_start"] == t0
    stale_gap_end = stale_rows[0]["gap_end"]

    resume_at = stale_gap_end + timedelta(minutes=30)
    first_new_snapshot = resume_at + timedelta(minutes=5)

    transport2 = fixture_replay_transport(
        source_name,
        {"station_status": httpx.Response(200, json=_envelope(source_name, "station_status", first_new_snapshot))},
    )
    clock2 = FakeClock(resume_at)
    second = make_collector(tmp_path, source, transport2, clock2)

    with caplog.at_level("INFO"):
        second.run(max_iterations=1)

    rows = sorted(_gap_rows(tmp_path, source_name, "station_status"), key=lambda r: r["gap_start"])
    assert len(rows) == 2
    stale_row, collector_down_row = rows

    assert stale_row["reason"] == "stale_feed"
    assert stale_row["gap_start"] == t0
    assert stale_row["gap_end"] == stale_gap_end

    assert collector_down_row["reason"] == "collector_down"
    assert collector_down_row["gap_start"] == stale_gap_end
    assert collector_down_row["gap_end"] == first_new_snapshot

    _assert_no_collision_warning(caplog)
