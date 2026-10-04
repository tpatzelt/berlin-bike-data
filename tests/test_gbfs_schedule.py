"""Tests for GbfsClient ttl scheduling and per-feed backoff.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/nextbike_bn/; nothing here touches the
network (the autouse socket guard in conftest.py would fail the test if it
tried).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from berlinbikes.backoff import Backoff, FakeClock
from berlinbikes.gbfs import DISCOVER_KEY, FeedError, GbfsClient

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gbfs" / "nextbike_bn"
ROOT_URL = "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/gbfs.json"
NOW = datetime(2026, 10, 2, 5, 4, 30, tzinfo=timezone.utc)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


def _path_name(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1].removesuffix(".json")


def _fixture_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_fixture(_path_name(request)))


def _make_client(handler, **kwargs) -> GbfsClient:
    kwargs.setdefault("clock", FakeClock(NOW))
    transport = httpx.MockTransport(handler)
    return GbfsClient(ROOT_URL, "berlinbikes-test/1.0", transport=transport, **kwargs)


class _UpperBoundRandom(random.Random):
    """A Random whose uniform() always returns the upper bound, for deterministic backoff."""

    def uniform(self, a: float, b: float) -> float:
        return b


# -- next_due() / should_fetch() ----------------------------------------------


@dataclass
class ScheduleCase:
    id: str
    min_interval_s: float
    expected_due: datetime


STATION_STATUS = _fixture("station_status")
LAST_UPDATED_DT = datetime.fromtimestamp(STATION_STATUS["last_updated"], tz=timezone.utc)
TTL_DUE = LAST_UPDATED_DT + timedelta(seconds=STATION_STATUS["ttl"])

SCHEDULE_CASES = [
    # fetched_at (NOW) + 10s is well before last_updated + ttl: the ttl term wins.
    ScheduleCase("ttl_term_wins", min_interval_s=10, expected_due=TTL_DUE),
    # fetched_at (NOW) + 120s is after last_updated + ttl: the min_interval term wins.
    ScheduleCase(
        "min_interval_term_wins", min_interval_s=120, expected_due=NOW + timedelta(seconds=120)
    ),
]


@pytest.mark.parametrize("case", SCHEDULE_CASES, ids=[c.id for c in SCHEDULE_CASES])
def test_next_due_takes_the_max_of_ttl_and_min_interval(case: ScheduleCase):
    client = _make_client(_fixture_handler)
    client.fetch("station_status")

    assert client.next_due("station_status", case.min_interval_s) == case.expected_due


@pytest.mark.parametrize("case", SCHEDULE_CASES, ids=[c.id for c in SCHEDULE_CASES])
def test_should_fetch_flips_at_next_due(case: ScheduleCase):
    clock = FakeClock(NOW)
    client = _make_client(_fixture_handler, clock=clock)
    client.fetch("station_status")

    clock._now = case.expected_due - timedelta(seconds=1)
    assert client.should_fetch("station_status", case.min_interval_s) is False

    clock._now = case.expected_due
    assert client.should_fetch("station_status", case.min_interval_s) is True


def test_a_never_fetched_feed_is_always_due():
    client = _make_client(_fixture_handler)
    assert client.next_due("station_status", 120) is None
    assert client.should_fetch("station_status", 120) is True


# -- per-feed backoff -----------------------------------------------------


def _handler_failing(feed_name: str, response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        if _path_name(request) != feed_name:
            return _fixture_handler(request)
        return response

    return handler


def test_consecutive_503s_grow_the_delay_and_cap_at_1800():
    client = _make_client(
        _handler_failing("station_status", httpx.Response(503)),
        backoff_factory=lambda: Backoff(rng=_UpperBoundRandom()),
    )

    delays = []
    for _ in range(3):
        with pytest.raises(FeedError):
            client.fetch("station_status")
        delays.append(client.backoff_delay("station_status"))
    assert delays == [120, 240, 480]

    for _ in range(5):
        with pytest.raises(FeedError):
            client.fetch("station_status")
    assert client.backoff_delay("station_status") == 1800


def test_bad_envelope_repeated_grows_attempts_and_delay_without_resetting():
    missing_ttl = dict(_fixture("station_status"))
    del missing_ttl["ttl"]
    client = _make_client(
        _handler_failing("station_status", httpx.Response(200, json=missing_ttl)),
        backoff_factory=lambda: Backoff(rng=_UpperBoundRandom()),
    )

    with pytest.raises(FeedError):
        client.fetch("station_status")
    assert client.backoff_attempts("station_status") == 1
    delay_1 = client.backoff_delay("station_status")

    with pytest.raises(FeedError):
        client.fetch("station_status")
    assert client.backoff_attempts("station_status") == 2
    delay_2 = client.backoff_delay("station_status")

    assert delay_2 > delay_1


def test_retry_after_header_sets_a_floor_on_the_delay():
    client = _make_client(
        _handler_failing(
            "station_status", httpx.Response(429, headers={"Retry-After": "900"})
        )
    )

    with pytest.raises(FeedError):
        client.fetch("station_status")

    assert client.backoff_delay("station_status") >= 900


def test_reset_only_happens_on_full_success():
    responses = iter(
        [httpx.Response(503), httpx.Response(503), None, httpx.Response(503)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if _path_name(request) != "station_status":
            return _fixture_handler(request)
        response = next(responses)
        return response if response is not None else _fixture_handler(request)

    client = _make_client(handler)

    with pytest.raises(FeedError):
        client.fetch("station_status")
    with pytest.raises(FeedError):
        client.fetch("station_status")
    assert client.backoff_attempts("station_status") == 2

    client.fetch("station_status")
    assert client.backoff_delay("station_status") == 0

    with pytest.raises(FeedError):
        client.fetch("station_status")
    assert client.backoff_attempts("station_status") == 1


def test_discover_backoff_is_isolated_from_feed_backoffs():
    gbfs = _fixture("gbfs")
    gbfs["data"]["de"]["feeds"] = [
        f for f in gbfs["data"]["de"]["feeds"] if f["name"] != "vehicle_types"
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if _path_name(request) == "gbfs":
            return httpx.Response(200, json=gbfs)
        return _fixture_handler(request)

    client = _make_client(handler)
    with pytest.raises(FeedError):
        client.discover()

    assert client.backoff_attempts(DISCOVER_KEY) == 1
    assert client.backoff_attempts("vehicle_types") == 0
