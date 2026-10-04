"""GBFS 2.3 discovery and feed fetch, with error classification, ttl-aware
scheduling and per-feed backoff.

Never log or raise with the response body: a ``free_bike_status`` payload
carries rotating ``bike_id`` values the charter forbids writing anywhere but
the aggregated Parquet output, so ``FeedError`` and the module logger only
ever carry the feed name, HTTP status and timing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from berlinbikes.backoff import Backoff, Clock, SystemClock, parse_retry_after

logger = logging.getLogger(__name__)

REQUIRED_FEEDS = ("station_status", "station_information", "free_bike_status", "vehicle_types")

#: Backoff/last-result bookkeeping key for the discovery request, kept apart
#: from feed names so a missing-required-feed error never pollutes that
#: feed's own fetch backoff.
DISCOVER_KEY = "discover"

_RETRY_AFTER_STATUSES = {429, 503}


class FeedError(Exception):
    """Raised when a GBFS feed cannot be fetched or parsed into an envelope."""

    def __init__(
        self, feed: str, status: int | None, retry_after: float | None, reason: str
    ) -> None:
        self.feed = feed
        self.status = status
        self.retry_after = retry_after
        self.reason = reason
        super().__init__(f"{feed}: {reason} (status={status}, retry_after={retry_after})")


@dataclass(frozen=True)
class FeedResult:
    payload: Any
    last_updated: int
    ttl: int
    fetched_at: datetime


class GbfsClient:
    def __init__(
        self,
        root_url: str,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        clock: Clock = SystemClock(),
        backoff_factory: Callable[[], Backoff] = Backoff,
    ) -> None:
        self.root_url = root_url
        self.user_agent = user_agent
        self._client = httpx.Client(transport=transport, headers={"User-Agent": user_agent})
        self._clock = clock
        self._feed_urls: dict[str, str] | None = None
        self._backoff_factory = backoff_factory
        self._backoffs: dict[str, Backoff] = {}
        self._backoff_delays: dict[str, float] = {}
        self._last_results: dict[str, FeedResult] = {}

    def discover(self) -> dict[str, str]:
        try:
            envelope = self._get_envelope(DISCOVER_KEY, self.root_url)
            data = envelope["data"]
            if not isinstance(data, dict) or not data:
                raise FeedError(DISCOVER_KEY, None, None, "discovery data has no language blocks")
            block = data["de"] if "de" in data else next(iter(data.values()))
            feeds = block.get("feeds") if isinstance(block, dict) else None
            if not isinstance(feeds, list):
                raise FeedError(
                    DISCOVER_KEY, None, None, "discovery language block has no feeds list"
                )

            feed_urls = {
                feed["name"]: feed["url"]
                for feed in feeds
                if isinstance(feed, dict) and "name" in feed and "url" in feed
            }
            missing = [name for name in REQUIRED_FEEDS if name not in feed_urls]
            if missing:
                raise FeedError(
                    missing[0],
                    None,
                    None,
                    f"missing from discovery feed list: {', '.join(missing)}",
                )
        except FeedError as exc:
            self._record_failure(DISCOVER_KEY, exc)
            raise

        self._record_success(DISCOVER_KEY)
        self._feed_urls = feed_urls
        return feed_urls

    def fetch(self, feed_name: str) -> FeedResult:
        if self._feed_urls is None:
            self.discover()
        url = self._feed_urls[feed_name]
        try:
            envelope = self._get_envelope(feed_name, url)
        except FeedError as exc:
            self._record_failure(feed_name, exc)
            raise

        result = FeedResult(
            payload=envelope["data"],
            last_updated=envelope["last_updated"],
            ttl=envelope["ttl"],
            fetched_at=self._clock.now(),
        )
        self._record_success(feed_name)
        self._last_results[feed_name] = result
        return result

    def next_due(self, feed_name: str, min_interval_s: float) -> datetime | None:
        """When ``feed_name`` is next due, or ``None`` if it was never fetched."""
        result = self._last_results.get(feed_name)
        if result is None:
            return None
        last_updated = datetime.fromtimestamp(result.last_updated, tz=timezone.utc)
        return max(
            last_updated + timedelta(seconds=result.ttl),
            result.fetched_at + timedelta(seconds=min_interval_s),
        )

    def should_fetch(self, feed_name: str, min_interval_s: float) -> bool:
        """Whether ``feed_name`` is due now. A never-fetched feed is always due."""
        due = self.next_due(feed_name, min_interval_s)
        return due is None or self._clock.now() >= due

    def backoff_delay(self, key: str) -> float:
        """The delay from the most recent failure for ``key``, or 0 after success."""
        return self._backoff_delays.get(key, 0.0)

    def backoff_attempts(self, key: str) -> int:
        """The consecutive-failure count for ``key`` since its last reset()."""
        return self._backoff_for(key).attempts

    def _backoff_for(self, key: str) -> Backoff:
        if key not in self._backoffs:
            self._backoffs[key] = self._backoff_factory()
        return self._backoffs[key]

    def _record_failure(self, key: str, exc: FeedError) -> None:
        backoff = self._backoff_for(key)
        self._backoff_delays[key] = backoff.next_delay(exc.retry_after)

    def _record_success(self, key: str) -> None:
        self._backoff_for(key).reset()
        self._backoff_delays[key] = 0.0

    def _get_envelope(self, feed: str, url: str) -> dict:
        started = self._clock.now()
        try:
            response = self._client.get(url)
        except httpx.TransportError as exc:
            logger.warning("gbfs fetch failed feed=%s error=%s", feed, type(exc).__name__)
            raise FeedError(feed, None, None, f"transport error: {type(exc).__name__}") from exc
        elapsed = (self._clock.now() - started).total_seconds()

        if response.status_code >= 400:
            retry_after = None
            header = response.headers.get("Retry-After")
            if header and response.status_code in _RETRY_AFTER_STATUSES:
                retry_after = parse_retry_after(header, self._clock.now())
            logger.warning(
                "gbfs fetch error feed=%s status=%s elapsed=%.3f",
                feed,
                response.status_code,
                elapsed,
            )
            raise FeedError(feed, response.status_code, retry_after, "http error status")

        try:
            body = response.json()
        except ValueError as exc:
            raise FeedError(
                feed, response.status_code, None, "response body is not valid JSON"
            ) from exc

        if not isinstance(body, dict):
            raise FeedError(feed, response.status_code, None, "response root is not a JSON object")

        for key in ("last_updated", "ttl", "data"):
            if key not in body:
                raise FeedError(feed, response.status_code, None, f"envelope missing {key!r}")

        logger.info(
            "gbfs fetch ok feed=%s status=%s elapsed=%.3f", feed, response.status_code, elapsed
        )
        return body
