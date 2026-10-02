"""Exponential backoff with full jitter, and a total Retry-After parser."""

from __future__ import annotations

import math
import random
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now = self._now + timedelta(seconds=seconds)


_DELTA_SECONDS_RE = re.compile(r"[0-9]+")


def parse_retry_after(value: str, now: datetime) -> float | None:
    """Parse a Retry-After header value. Never raises; returns None on failure."""
    if value.isascii() and _DELTA_SECONDS_RE.fullmatch(value):
        try:
            seconds = float(value)
        except (TypeError, ValueError, OverflowError, IndexError):
            return None
        if not math.isfinite(seconds):
            return None
        return seconds

    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        delta = (parsed - now).total_seconds()
    except (TypeError, ValueError, OverflowError, IndexError):
        return None

    if not math.isfinite(delta):
        return None
    return max(delta, 0.0)


class Backoff:
    def __init__(
        self,
        base: float = 120,
        factor: float = 2,
        cap: float = 1800,
        rng: random.Random | None = None,
    ) -> None:
        self.base = base
        self.factor = factor
        self.cap = cap
        self._rng = rng if rng is not None else random.Random()
        self.attempts = 0

    def next_delay(self, retry_after: float | None = None) -> float:
        bound = min(self.cap, self.base * (self.factor**self.attempts))
        self.attempts += 1
        computed = self._rng.uniform(0, bound)
        if retry_after is not None:
            computed = max(retry_after, computed)
        return min(computed, self.cap)

    def reset(self) -> None:
        self.attempts = 0
