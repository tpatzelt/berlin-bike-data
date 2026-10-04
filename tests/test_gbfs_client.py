"""Tests for berlinbikes.gbfs: discovery, fetch and error classification.

All HTTP is replayed through httpx.MockTransport against the committed
fixtures under tests/fixtures/gbfs/nextbike_bn/; nothing here touches the
network (the autouse socket guard in conftest.py would fail the test if it
tried).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from berlinbikes.backoff import FakeClock
from berlinbikes.config import Settings
from berlinbikes.gbfs import REQUIRED_FEEDS, FeedError, GbfsClient

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gbfs" / "nextbike_bn"
ROOT_URL = "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/gbfs.json"
NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)
SENTINEL_BIKE_ID = "SENTINEL-BIKE-ID-42"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


def _path_name(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1].removesuffix(".json")


def _fixture_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_fixture(_path_name(request)))


def _recording_handler(seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_fixture(_path_name(request)))

    return handler


def _make_client(handler, **kwargs) -> GbfsClient:
    kwargs.setdefault("clock", FakeClock(NOW))
    transport = httpx.MockTransport(handler)
    return GbfsClient(ROOT_URL, "berlinbikes-test/1.0", transport=transport, **kwargs)


# -- discover() ---------------------------------------------------------------


def test_discover_resolves_all_required_feeds():
    client = _make_client(_fixture_handler)
    feed_urls = client.discover()

    de_feeds = {f["name"]: f["url"] for f in _fixture("gbfs")["data"]["de"]["feeds"]}
    for name in REQUIRED_FEEDS:
        assert feed_urls[name] == de_feeds[name]


def test_discover_raises_feed_error_when_a_required_feed_is_missing():
    gbfs = _fixture("gbfs")
    gbfs["data"]["de"]["feeds"] = [
        f for f in gbfs["data"]["de"]["feeds"] if f["name"] != "vehicle_types"
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=gbfs)

    client = _make_client(handler)
    with pytest.raises(FeedError) as exc_info:
        client.discover()
    assert exc_info.value.feed == "vehicle_types"


# -- fetch() --------------------------------------------------------------


@pytest.mark.parametrize("feed_name", REQUIRED_FEEDS)
def test_fetch_returns_last_updated_and_ttl_from_fixture(feed_name):
    client = _make_client(_fixture_handler)
    result = client.fetch(feed_name)

    expected = _fixture(feed_name)
    assert result.last_updated == expected["last_updated"]
    assert result.ttl == expected["ttl"]
    assert result.payload == expected["data"]


def test_fetch_calls_discover_lazily():
    client = _make_client(_fixture_handler)
    assert client._feed_urls is None
    client.fetch("station_status")
    assert client._feed_urls is not None


# -- User-Agent -----------------------------------------------------------


def test_every_request_carries_the_configured_user_agent(tmp_path):
    settings = Settings.from_env(
        {
            "BIKES_DATA_DIR": str(tmp_path),
            "BIKES_USER_AGENT": (
                "berlinbikes-test/1.0 (+https://github.com/tpatzelt/berlin-bike-data)"
            ),
        }
    )
    seen: list[httpx.Request] = []
    client = GbfsClient(
        ROOT_URL,
        settings.user_agent,
        transport=httpx.MockTransport(_recording_handler(seen)),
        clock=FakeClock(NOW),
    )

    for feed_name in REQUIRED_FEEDS:
        client.fetch(feed_name)

    assert seen
    for request in seen:
        assert request.headers["User-Agent"] == settings.user_agent


# -- FeedError classification ----------------------------------------------


@dataclass
class ErrorCase:
    id: str
    response: httpx.Response | None = None
    raises: Exception | None = None
    expected_status: int | None = None
    expected_retry_after: float | None = None


def _missing_ttl_response() -> httpx.Response:
    body = dict(_fixture("station_status"))
    del body["ttl"]
    return httpx.Response(200, json=body)


ERROR_CASES = [
    ErrorCase("503", response=httpx.Response(503), expected_status=503),
    ErrorCase(
        "429_retry_after",
        response=httpx.Response(429, headers={"Retry-After": "120"}),
        expected_status=429,
        expected_retry_after=120.0,
    ),
    ErrorCase("404", response=httpx.Response(404), expected_status=404),
    ErrorCase(
        "garbage_body", response=httpx.Response(200, content=b"not json"), expected_status=200
    ),
    ErrorCase(
        "json_array_root", response=httpx.Response(200, json=[1, 2, 3]), expected_status=200
    ),
    ErrorCase("missing_ttl", response=_missing_ttl_response(), expected_status=200),
    ErrorCase("connect_error", raises=httpx.ConnectError("boom")),
    ErrorCase("read_timeout", raises=httpx.ReadTimeout("boom")),
]


@pytest.mark.parametrize("case", ERROR_CASES, ids=[c.id for c in ERROR_CASES])
def test_fetch_classifies_feed_errors(case: ErrorCase):
    def handler(request: httpx.Request) -> httpx.Response:
        if _path_name(request) != "station_status":
            return _fixture_handler(request)
        if case.raises is not None:
            raise case.raises
        return case.response

    client = _make_client(handler)
    with pytest.raises(FeedError) as exc_info:
        client.fetch("station_status")

    assert exc_info.value.feed == "station_status"
    assert exc_info.value.status == case.expected_status
    assert exc_info.value.retry_after == case.expected_retry_after


# -- bike_id never leaks into logs or errors -------------------------------


def test_sentinel_bike_id_never_reaches_logs_or_feed_errors(caplog):
    free_bike_status = _fixture("free_bike_status")
    free_bike_status["data"]["bikes"][0]["bike_id"] = SENTINEL_BIKE_ID

    def ok_handler(request: httpx.Request) -> httpx.Response:
        if _path_name(request) == "free_bike_status":
            return httpx.Response(200, json=free_bike_status)
        return _fixture_handler(request)

    with caplog.at_level(logging.DEBUG):
        client = _make_client(ok_handler)
        result = client.fetch("free_bike_status")
    assert any(bike["bike_id"] == SENTINEL_BIKE_ID for bike in result.payload["bikes"])
    assert SENTINEL_BIKE_ID not in caplog.text

    malformed = {**free_bike_status}
    del malformed["ttl"]

    def error_handler(request: httpx.Request) -> httpx.Response:
        if _path_name(request) == "free_bike_status":
            return httpx.Response(200, json=malformed)
        return _fixture_handler(request)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        client = _make_client(error_handler)
        with pytest.raises(FeedError) as exc_info:
            client.fetch("free_bike_status")
    assert SENTINEL_BIKE_ID not in caplog.text
    assert SENTINEL_BIKE_ID not in str(exc_info.value)
