"""GBFS 2.3 discovery and feed fetch, with error classification.

Only discovery, fetching and error classification live here. TTL scheduling
(``next_due``/``should_fetch``) and per-feed ``Backoff`` wiring belong to the
follow-up task that builds on this client.

Never log or raise with the response body: a ``free_bike_status`` payload
carries rotating ``bike_id`` values the charter forbids writing anywhere but
the aggregated Parquet output, so ``FeedError`` and the module logger only
ever carry the feed name, HTTP status and timing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from berlinbikes.backoff import Clock, SystemClock, parse_retry_after

logger = logging.getLogger(__name__)

REQUIRED_FEEDS = ("station_status", "station_information", "free_bike_status", "vehicle_types")

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
    ) -> None:
        self.root_url = root_url
        self.user_agent = user_agent
        self._client = httpx.Client(transport=transport, headers={"User-Agent": user_agent})
        self._clock = clock
        self._feed_urls: dict[str, str] | None = None

    def discover(self) -> dict[str, str]:
        envelope = self._get_envelope("discover", self.root_url)
        data = envelope["data"]
        if not isinstance(data, dict) or not data:
            raise FeedError("discover", None, None, "discovery data has no language blocks")
        block = data["de"] if "de" in data else next(iter(data.values()))
        feeds = block.get("feeds") if isinstance(block, dict) else None
        if not isinstance(feeds, list):
            raise FeedError("discover", None, None, "discovery language block has no feeds list")

        feed_urls = {
            feed["name"]: feed["url"]
            for feed in feeds
            if isinstance(feed, dict) and "name" in feed and "url" in feed
        }
        missing = [name for name in REQUIRED_FEEDS if name not in feed_urls]
        if missing:
            raise FeedError(
                missing[0], None, None, f"missing from discovery feed list: {', '.join(missing)}"
            )

        self._feed_urls = feed_urls
        return feed_urls

    def fetch(self, feed_name: str) -> FeedResult:
        if self._feed_urls is None:
            self.discover()
        url = self._feed_urls[feed_name]
        envelope = self._get_envelope(feed_name, url)
        return FeedResult(
            payload=envelope["data"],
            last_updated=envelope["last_updated"],
            ttl=envelope["ttl"],
            fetched_at=self._clock.now(),
        )

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
