"""Tests for exponential backoff with jitter and the Retry-After parser."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from berlinbikes.backoff import Backoff, FakeClock, SystemClock, parse_retry_after

UTC = timezone.utc


def _now() -> datetime:
    return datetime(2024, 1, 1, tzinfo=UTC)


class MaxRandom(random.Random):
    """A Random stub whose uniform() always returns the upper bound."""

    def uniform(self, a: float, b: float) -> float:
        return b


# -- Backoff.next_delay ------------------------------------------------------


def test_next_delay_seeded_sequence_matches_literal_floats():
    b = Backoff(rng=random.Random(42))
    expected = [
        76.73121581494605,
        6.002581253440065,
        132.01407281717724,
        214.28230862286983,
        1325.6481854952224,
    ]
    for want in expected:
        assert b.next_delay() == want


def test_next_delay_bounds_pinned_by_max_random_then_capped():
    b = Backoff(rng=MaxRandom())
    assert b.next_delay() == 120
    assert b.next_delay() == 240
    assert b.next_delay() == 480
    assert b.next_delay() == 960
    assert b.next_delay() == 1800
    # Bound now exceeds cap (120 * 2**5 = 3840); stays pinned at the cap.
    assert b.next_delay() == 1800
    assert b.next_delay() == 1800


def test_attempts_counts_calls_to_next_delay():
    b = Backoff(rng=random.Random(1))
    assert b.attempts == 0
    b.next_delay()
    assert b.attempts == 1
    b.next_delay()
    assert b.attempts == 2


def test_reset_restarts_sequence_after_success():
    b = Backoff(rng=MaxRandom())
    assert b.next_delay() == 120
    assert b.next_delay() == 240
    b.reset()
    assert b.attempts == 0
    assert b.next_delay() == 120


def test_retry_after_overrides_shorter_computed_delay():
    b = Backoff(rng=random.Random(0))
    delay = b.next_delay(retry_after=1000)
    assert delay == 1000


def test_retry_after_longer_than_cap_is_still_capped():
    b = Backoff(rng=MaxRandom())
    delay = b.next_delay(retry_after=1_000_000)
    assert delay == 1800


def test_retry_after_shorter_than_computed_does_not_shrink_it():
    b = Backoff(rng=MaxRandom())
    delay = b.next_delay(retry_after=1)
    assert delay == 120


# -- parse_retry_after: valid inputs -----------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", 0.0),
        ("120", 120.0),
        ("3600", 3600.0),
    ],
)
def test_parse_retry_after_delta_seconds(value, expected):
    assert parse_retry_after(value, _now()) == expected


def test_parse_retry_after_http_date():
    now = _now()
    future = now + timedelta(seconds=90)
    header = format_datetime(future, usegmt=True)
    assert parse_retry_after(header, now) == 90.0


def test_parse_retry_after_naive_http_date_treated_as_utc():
    now = _now()
    naive = "Mon, 01 Jan 2024 00:02:00"
    assert parse_retry_after(naive, now) == 120.0


def test_parse_retry_after_past_http_date_clamped_to_zero():
    now = _now()
    past = "Sun, 31 Dec 2023 00:00:00 GMT"
    assert parse_retry_after(past, now) == 0.0


# -- parse_retry_after: total contract, never raises -------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "abc",
        "-5",
        "1.5",
        "²",
        "١٢٠",
        "1" * 400,
        "Fri, 31 Dec 9999 23:59:59 -2359",
    ],
)
def test_parse_retry_after_invalid_inputs_return_none(value):
    assert parse_retry_after(value, _now()) is None


def test_parse_retry_after_leading_zero_year_is_not_none():
    # email.utils.parsedate_to_datetime applies RFC-822 2-digit-year pivoting
    # to any numeric year below 100, even one written with leading zeros
    # ("0001" parses as int 1 < 100 and is rewritten to 2001). That sidesteps
    # the underflow this value was meant to trigger, so it parses as a valid
    # (if surprising) past date rather than failing, and gets clamped to 0
    # like any other past date. See the "assumptions" note on this task.
    assert parse_retry_after("Mon, 01 Jan 0001 00:00:00 +2359", _now()) == 0.0


# -- Clock --------------------------------------------------------------------


def test_fake_clock_advances_now_on_sleep_without_waiting(monkeypatch):
    def fail_sleep(_seconds):
        raise AssertionError("time.sleep must not be called by FakeClock")

    monkeypatch.setattr("time.sleep", fail_sleep)

    start = _now()
    clock = FakeClock(start)
    assert clock.now() == start

    clock.sleep(30)

    assert clock.now() == start + timedelta(seconds=30)
    assert clock.sleeps == [30]


def test_system_clock_now_is_aware_utc():
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
