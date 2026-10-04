"""Tests for berlinbikes.weather: WeatherClient and WeatherCache.

All HTTP is replayed through httpx.MockTransport against Bright Sky-shaped
JSON payloads built in this file; nothing here touches the network (the
autouse socket guard in conftest.py would fail the test if it tried).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pyarrow.parquet as pq
import pytest

from berlinbikes.backoff import FakeClock
from berlinbikes.weather import (
    BERLIN_LAT,
    BERLIN_LON,
    WeatherCache,
    WeatherClient,
    WeatherFetchError,
)

USER_AGENT = "berlinbikes-test/1.0 (+https://github.com/tpatzelt/berlin-bike-data)"
NOW = datetime(2026, 1, 10, 3, 0, tzinfo=timezone.utc)


def _hour_payload(day: date, hours: int = 24, extra_hours: int = 0) -> dict:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    records = []
    for i in range(hours + extra_hours):
        ts = start + timedelta(hours=i)
        records.append(
            {
                "timestamp": ts.isoformat(),
                "source_id": 1,
                "precipitation": 0.0,
                "temperature": float(i),
                "condition": "dry",
            }
        )
    return {"weather": records, "sources": [{"id": 1, "dwd_station_id": "00430"}]}


def _fixture_handler(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    day = date.fromisoformat(params["date"])
    return httpx.Response(200, json=_hour_payload(day))


def _recording_handler(seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _fixture_handler(request)

    return handler


def _make_client(handler, **kwargs) -> WeatherClient:
    kwargs.setdefault("clock", FakeClock(NOW))
    transport = httpx.MockTransport(handler)
    return WeatherClient(USER_AGENT, transport=transport, **kwargs)


# -- (a) User-Agent -----------------------------------------------------------


def test_user_agent_header_equals_configured_value():
    seen: list[httpx.Request] = []
    client = _make_client(_recording_handler(seen))
    client.fetch_day(date(2026, 1, 1))

    assert seen
    for request in seen:
        assert request.headers["User-Agent"] == USER_AGENT


# -- (b) request query shape ---------------------------------------------------


def test_request_query_has_expected_date_last_date_tz_lat_lon():
    seen: list[httpx.Request] = []
    client = _make_client(_recording_handler(seen))
    day = date(2026, 1, 5)
    client.fetch_day(day)

    assert len(seen) == 1
    params = dict(seen[0].url.params)
    assert params["date"] == "2026-01-05"
    assert params["last_date"] == "2026-01-06"
    assert params["tz"] == "UTC"
    assert float(params["lat"]) == BERLIN_LAT
    assert float(params["lon"]) == BERLIN_LON
    assert seen[0].url.path == "/weather"


# -- (g) only the requested date's 24 rows are kept ----------------------------


def test_response_with_extra_next_day_hours_writes_only_the_requested_date():
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        day = date.fromisoformat(params["date"])
        return httpx.Response(200, json=_hour_payload(day, hours=24, extra_hours=24))

    client = _make_client(handler)
    day = date(2026, 1, 5)
    table = client.fetch_day(day)

    assert table.num_rows == 24
    hour_ts = table.column("hour_ts").to_pylist()
    assert all(
        datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        <= ts
        < datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)
        for ts in hour_ts
    )


# -- WeatherFetchError classification ------------------------------------------


def test_http_error_status_and_retry_after_are_captured_without_the_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503, headers={"Retry-After": "600"}, content=b"secret upstream body"
        )

    client = _make_client(handler)
    with pytest.raises(WeatherFetchError) as exc_info:
        client.fetch_day(date(2026, 1, 5))

    assert exc_info.value.status == 503
    assert exc_info.value.retry_after == 600.0
    assert "secret upstream body" not in str(exc_info.value)


def test_timeout_raises_weather_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("boom")

    client = _make_client(handler)
    with pytest.raises(WeatherFetchError):
        client.fetch_day(date(2026, 1, 5))


def test_unparseable_payload_raises_weather_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"weather": "not-a-list"})

    client = _make_client(handler)
    with pytest.raises(WeatherFetchError):
        client.fetch_day(date(2026, 1, 5))


# -- WeatherCache ---------------------------------------------------------------


def _cache_file(tmp_path, day: date):
    return tmp_path / "weather" / f"date={day.isoformat()}" / "weather.parquet"


def test_second_collect_missing_makes_zero_requests(tmp_path):
    seen: list[httpx.Request] = []
    clock = FakeClock(NOW)
    client = WeatherClient(
        USER_AGENT,
        transport=httpx.MockTransport(_recording_handler(seen)),
        clock=clock,
    )
    cache = WeatherCache(tmp_path, client, clock)

    assert cache.collect_missing(days_back=7) is None
    requested_dates = sorted(dict(r.url.params)["date"] for r in seen)
    today = NOW.date()
    expected = [(today - timedelta(days=d)).isoformat() for d in range(7, 1, -1)]
    assert requested_dates == sorted(expected)
    for day_str in expected:
        assert _cache_file(tmp_path, date.fromisoformat(day_str)).is_file()

    seen.clear()
    assert cache.collect_missing(days_back=7) is None
    assert seen == []


def test_503_with_retry_after_stops_and_returns_delay_without_writing_later_days(tmp_path):
    clock = FakeClock(NOW)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        requested.append(params["date"])
        today = NOW.date()
        failing_day = today - timedelta(days=7)
        if date.fromisoformat(params["date"]) == failing_day:
            return httpx.Response(503, headers={"Retry-After": "600"})
        return _fixture_handler(request)

    client = WeatherClient(
        USER_AGENT, transport=httpx.MockTransport(handler), clock=clock
    )
    cache = WeatherCache(tmp_path, client, clock)

    result = cache.collect_missing(days_back=7)

    assert result is not None
    assert result >= 600
    today = NOW.date()
    failing_day = today - timedelta(days=7)
    assert not _cache_file(tmp_path, failing_day).is_file()
    # Only the failing day was requested; later days were never attempted.
    assert requested == [failing_day.isoformat()]


def test_500_then_success_writes_file_and_resets_backoff_attempts(tmp_path):
    clock = FakeClock(NOW)
    today = NOW.date()
    target_day = today - timedelta(days=7)
    fail_next = {"value": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if fail_next["value"]:
            return httpx.Response(500)
        return _fixture_handler(request)

    client = WeatherClient(
        USER_AGENT, transport=httpx.MockTransport(handler), clock=clock
    )
    cache = WeatherCache(tmp_path, client, clock)

    first_result = cache.collect_missing(days_back=7)
    assert first_result is not None
    assert cache._backoff.attempts == 1

    fail_next["value"] = False
    second_result = cache.collect_missing(days_back=7)

    assert second_result is None
    assert cache._backoff.attempts == 0
    assert pq.read_table(_cache_file(tmp_path, target_day)).num_rows == 24


def test_existing_cache_file_is_never_overwritten(tmp_path):
    clock = FakeClock(NOW)
    today = NOW.date()
    target_day = today - timedelta(days=7)
    path = _cache_file(tmp_path, target_day)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"sentinel-existing-cache-bytes")
    original_mtime = path.stat().st_mtime_ns
    original_bytes = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params["date"] == target_day.isoformat():
            raise AssertionError("must not request a day that already has a cache file")
        return _fixture_handler(request)

    client = WeatherClient(
        USER_AGENT, transport=httpx.MockTransport(handler), clock=clock
    )
    cache = WeatherCache(tmp_path, client, clock)

    result = cache.collect_missing(days_back=7)

    assert result is None
    assert path.stat().st_mtime_ns == original_mtime
    assert path.read_bytes() == original_bytes
