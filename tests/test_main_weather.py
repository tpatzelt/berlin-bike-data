"""Tests for ``berlinbikes.__main__.run_weather``: the backoff loop that
drives ``WeatherCache.collect_missing`` for the ``weather`` subcommand.

All HTTP is replayed through httpx.MockTransport with payloads built the way
tests/test_weather_client.py does; nothing here touches the network (the
autouse socket guard in conftest.py would fail the test if it tried).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx

from berlinbikes.__main__ import run_weather
from berlinbikes.backoff import FakeClock

from tests.helpers import make_settings

NOW = datetime(2026, 1, 10, 3, 0, tzinfo=timezone.utc)
DAYS_BACK = 7


def _hour_payload(day: date) -> dict:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    records = [
        {
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "precipitation": 0.0,
            "temperature": float(i),
            "condition": "dry",
        }
        for i in range(24)
    ]
    return {"weather": records}


def _fixture_handler(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    day = date.fromisoformat(params["date"])
    return httpx.Response(200, json=_hour_payload(day))


def _expected_days() -> list[date]:
    today = NOW.date()
    return [today - timedelta(days=d) for d in range(DAYS_BACK, 1, -1)]


def _cache_file(data_dir, day: date):
    return data_dir / "weather" / f"date={day.isoformat()}" / "weather.parquet"


# -- (a) all days fetched and written, with the configured User-Agent -------


def test_all_missing_days_are_fetched_and_written_with_configured_user_agent(tmp_path):
    settings = make_settings(tmp_path, BIKES_USER_AGENT="berlinbikes-test/1.0 (+contact)")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _fixture_handler(request)

    clock = FakeClock(NOW)
    result = run_weather(settings, clock, days_back=DAYS_BACK, transport=httpx.MockTransport(handler))

    assert result == 0
    assert seen
    for request in seen:
        assert request.headers["User-Agent"] == settings.user_agent
    for day in _expected_days():
        assert _cache_file(tmp_path, day).is_file()


# -- (b) one 503 then success: one sleep, returns 0 -------------------------


def test_one_failure_then_success_sleeps_once_and_returns_zero(tmp_path):
    settings = make_settings(tmp_path)
    clock = FakeClock(NOW)
    failed_once = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if not failed_once["value"]:
            failed_once["value"] = True
            return httpx.Response(503, headers={"Retry-After": "1"})
        return _fixture_handler(request)

    result = run_weather(settings, clock, days_back=DAYS_BACK, transport=httpx.MockTransport(handler))

    assert result == 0
    assert len(clock.sleeps) == 1
    for day in _expected_days():
        assert _cache_file(tmp_path, day).is_file()


# -- (c) always fails: returns 1 after max_rounds, exactly max_rounds sleeps -


def test_always_failing_server_returns_one_after_max_rounds(tmp_path):
    settings = make_settings(tmp_path)
    clock = FakeClock(NOW)
    max_rounds = 3

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    result = run_weather(
        settings,
        clock,
        days_back=DAYS_BACK,
        transport=httpx.MockTransport(handler),
        max_rounds=max_rounds,
    )

    assert result == 1
    assert len(clock.sleeps) == max_rounds
    for day in _expected_days():
        assert not _cache_file(tmp_path, day).is_file()


# -- (d) days already cached are not re-fetched ------------------------------


def test_already_cached_days_are_not_fetched_again(tmp_path):
    settings = make_settings(tmp_path)
    clock = FakeClock(NOW)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _fixture_handler(request)

    first_result = run_weather(settings, clock, days_back=DAYS_BACK, transport=httpx.MockTransport(handler))
    assert first_result == 0
    assert len(seen) == len(_expected_days())

    seen.clear()
    second_result = run_weather(settings, clock, days_back=DAYS_BACK, transport=httpx.MockTransport(handler))

    assert second_result == 0
    assert seen == []
