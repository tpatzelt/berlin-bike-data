"""Tests for Collector gap rows: fetch_error and stale_feed episodes.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/nextbike_bn/ (the autouse socket guard in
conftest.py would fail the test if it tried to reach the network). Backoff
randomness is made deterministic with an upper-bound RNG, so the recorded
sleeps and gap bounds are exact, not just "greater than".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import pyarrow.parquet as pq

from berlinbikes.backoff import Backoff, FakeClock
from berlinbikes.collector import Collector
from berlinbikes.config import Settings
from berlinbikes.gbfs import GbfsClient
from berlinbikes.sources import NextbikeSource
from berlinbikes.storage import Storage

from tests.helpers import fixture_replay_transport, load_fixture

SOURCE_NAME = "nextbike_bn"

BASE_LAST_UPDATED = load_fixture(SOURCE_NAME, "station_status")["last_updated"]
NOW = datetime.fromtimestamp(BASE_LAST_UPDATED, tz=timezone.utc)


class _UpperBoundRng:
    """A stand-in for random.Random that always returns the upper bound.

    Makes Backoff.next_delay() deterministic (120, 240, 480, ...) so gap
    bounds and recorded sleeps can be asserted exactly.
    """

    def uniform(self, a: float, b: float) -> float:
        return b


def _backoff_factory() -> Backoff:
    return Backoff(rng=_UpperBoundRng())


@dataclass
class StubSource:
    """A single-feed Source stub, so a test's schedule depends on one feed only."""

    name: str
    gbfs_url: str
    feeds: tuple[str, ...]


def _source(feeds: tuple[str, ...] = ("station_status",)) -> StubSource:
    return StubSource(name=SOURCE_NAME, gbfs_url="https://example.invalid/gbfs.json", feeds=feeds)


def _settings(tmp_path) -> Settings:
    return Settings.from_env(
        {
            "BIKES_DATA_DIR": str(tmp_path),
            "BIKES_USER_AGENT": "berlinbikes-test/1.0",
        }
    )


def _envelope(feed_name: str, last_updated: int, ttl: int = 60) -> dict:
    body = load_fixture(SOURCE_NAME, feed_name)
    return {**body, "last_updated": last_updated, "ttl": ttl}


def _make_collector(tmp_path, source, transport, clock) -> Collector:
    settings = _settings(tmp_path)
    client = GbfsClient(
        source.gbfs_url,
        settings.user_agent,
        transport=transport,
        clock=clock,
        backoff_factory=_backoff_factory,
    )
    storage = Storage(tmp_path)
    return Collector(source, client, storage, clock)


def _gap_rows(tmp_path, feed_name: str | None = None) -> list[dict]:
    dataset_dir = tmp_path / SOURCE_NAME / "gaps"
    if not dataset_dir.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(dataset_dir.glob("date=*/part-*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    if feed_name is not None:
        rows = [row for row in rows if row["feed"] == feed_name]
    return rows


# -- (1) N failures -> one fetch_error gap with correct bounds, attempts, and
#        backoff-shaped sleeps ------------------------------------------------
def test_outage_writes_one_fetch_error_gap_with_growing_backoff_sleeps(tmp_path):
    clock = FakeClock(NOW)
    source = _source()
    recovery_ts: dict[str, datetime] = {}

    def _respond(request: httpx.Request, call_count: int) -> httpx.Response:
        if call_count == 0:
            return httpx.Response(200, json=_envelope("station_status", BASE_LAST_UPDATED))
        if call_count in (1, 2, 3):
            return httpx.Response(503)
        # The feed's own last_updated advances with real time, so recovery
        # is reported at "now", not at a value picked independently of the
        # backoff sleeps that elapsed during the outage.
        last_updated = int(clock.now().timestamp())
        recovery_ts["value"] = datetime.fromtimestamp(last_updated, tz=timezone.utc)
        return httpx.Response(200, json=_envelope("station_status", last_updated))

    transport = fixture_replay_transport(SOURCE_NAME, {"station_status": _respond})
    collector = _make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=5)

    assert clock.sleeps == [120.0, 120.0, 240.0, 480.0]

    rows = _gap_rows(tmp_path, "station_status")
    assert len(rows) == 1
    row = rows[0]
    assert row["reason"] == "fetch_error"
    assert row["attempts"] == 3
    assert row["gap_start"] == datetime.fromtimestamp(BASE_LAST_UPDATED, tz=timezone.utc)
    assert row["gap_end"] == recovery_ts["value"]


# -- (2) last_updated unchanged for > 3x the interval -> one stale_feed row --
def test_stale_feed_unchanged_for_over_3x_interval_writes_one_gap_row(tmp_path):
    clock = FakeClock(NOW)
    source = _source()

    transport = fixture_replay_transport(
        SOURCE_NAME, {"station_status": httpx.Response(200, json=_envelope("station_status", BASE_LAST_UPDATED))}
    )
    collector = _make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=6)

    rows = _gap_rows(tmp_path, "station_status")
    assert len(rows) == 1
    row = rows[0]
    assert row["reason"] == "stale_feed"
    assert row["gap_start"] == datetime.fromtimestamp(BASE_LAST_UPDATED, tz=timezone.utc)


# -- (3) stale, then an outage with no new snapshot in between: no crash, and
#        both episodes are recorded on non-colliding keys --------------------
def test_stale_then_outage_with_no_new_snapshot_does_not_collide(tmp_path):
    clock = FakeClock(NOW)
    source = _source()
    recovery_ts: dict[str, datetime] = {}

    def _respond(request: httpx.Request, call_count: int) -> httpx.Response:
        if call_count <= 4:
            return httpx.Response(200, json=_envelope("station_status", BASE_LAST_UPDATED))
        if call_count in (5, 6, 7):
            return httpx.Response(503)
        last_updated = int(clock.now().timestamp())
        recovery_ts["value"] = datetime.fromtimestamp(last_updated, tz=timezone.utc)
        return httpx.Response(200, json=_envelope("station_status", last_updated))

    transport = fixture_replay_transport(SOURCE_NAME, {"station_status": _respond})
    collector = _make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=9)

    rows = sorted(_gap_rows(tmp_path, "station_status"), key=lambda r: r["gap_start"])
    assert len(rows) == 2

    stale_row, outage_row = rows
    assert stale_row["reason"] == "stale_feed"
    assert stale_row["gap_start"] == datetime.fromtimestamp(BASE_LAST_UPDATED, tz=timezone.utc)

    assert outage_row["reason"] == "fetch_error"
    assert outage_row["attempts"] == 3
    # The second gap must not reuse the stale row's (feed, gap_start) key.
    assert outage_row["gap_start"] != stale_row["gap_start"]
    assert outage_row["gap_end"] == recovery_ts["value"]


# -- (4) an outage still open at shutdown is flushed --------------------------
def test_outage_still_open_at_shutdown_is_flushed(tmp_path):
    clock = FakeClock(NOW)
    source = _source()

    def _respond(request: httpx.Request, call_count: int) -> httpx.Response:
        if call_count == 0:
            return httpx.Response(200, json=_envelope("station_status", BASE_LAST_UPDATED))
        return httpx.Response(503)

    transport = fixture_replay_transport(SOURCE_NAME, {"station_status": _respond})
    collector = _make_collector(tmp_path, source, transport, clock)

    collector.run(max_iterations=4)

    rows = _gap_rows(tmp_path, "station_status")
    assert len(rows) == 1
    row = rows[0]
    assert row["reason"] == "fetch_error"
    assert row["attempts"] == 3
    assert row["gap_start"] == datetime.fromtimestamp(BASE_LAST_UPDATED, tz=timezone.utc)
    assert row["gap_end"] == clock.now()
    assert "station_status" not in collector._outage_start


# -- (5) recovery with an unchanged last_updated writes no zero-length gap ---
def test_recovery_with_unchanged_last_updated_skips_zero_length_gap(tmp_path, caplog):
    clock = FakeClock(NOW)
    source = _source()

    def _respond(request: httpx.Request, call_count: int) -> httpx.Response:
        if call_count == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=_envelope("station_status", BASE_LAST_UPDATED))

    transport = fixture_replay_transport(SOURCE_NAME, {"station_status": _respond})
    collector = _make_collector(tmp_path, source, transport, clock)

    with caplog.at_level("INFO"):
        collector.run(max_iterations=3)

    assert _gap_rows(tmp_path, "station_status") == []
    assert any("skipping zero-length" in record.message for record in caplog.records)


# -- (6) the outage warning log carries no fixture bike_id -------------------
def test_outage_warning_log_contains_no_fixture_bike_id(tmp_path, caplog):
    clock = FakeClock(NOW)
    settings = _settings(tmp_path)
    source = NextbikeSource(settings)

    def _always_503(request: httpx.Request, call_count: int) -> httpx.Response:
        return httpx.Response(503)

    transport = fixture_replay_transport(SOURCE_NAME, {"vehicle_types": _always_503})
    collector = _make_collector(tmp_path, source, transport, clock)

    with caplog.at_level("WARNING"):
        collector.run(max_iterations=3)

    assert any("feed outage starting" in record.message for record in caplog.records)

    free_bike_status = load_fixture(SOURCE_NAME, "free_bike_status")
    bike_ids = [bike["bike_id"] for bike in free_bike_status["data"]["bikes"]]
    assert bike_ids
    for record in caplog.records:
        for bike_id in bike_ids:
            assert bike_id not in record.getMessage()
