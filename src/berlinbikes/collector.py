"""Per-feed polling: fetch one feed, convert it to its schemas.py table, write it.

Only the single-feed step lives here. The run loop, scheduling, gap rows and
backoff sleeps that drive repeated polling are later tasks; this module just
has to be a safe building block for them: re-polling a feed whose
``last_updated`` has not advanced, or restarting on a data dir that already
has the snapshot, must both be harmless no-ops.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import pyarrow as pa

from berlinbikes.backoff import Clock
from berlinbikes.cells import aggregate_free_bikes
from berlinbikes.gbfs import FeedResult, GbfsClient
from berlinbikes.schemas import (
    STATION_INFORMATION_SCHEMA,
    STATION_STATUS_SCHEMA,
    VEHICLE_TYPES_SCHEMA,
)
from berlinbikes.sources import Source
from berlinbikes.storage import DuplicateSnapshotError, Storage

logger = logging.getLogger(__name__)

FEED_TO_DATASET = {
    "station_status": "station_status",
    "station_information": "station_information",
    "vehicle_types": "vehicle_types",
    "free_bike_status": "free_bike_cells",
}

FEED_INTERVALS_S: dict[str, float] = {
    "station_status": 120,
    "free_bike_status": 120,
    "station_information": 86400,
    "vehicle_types": 86400,
}

#: Ceiling on the retry delay set after a failed poll, so a daily feed that
#: is failing is still retried within two minutes instead of a full day.
MAX_RETRY_FLOOR_S = 120


class PollResult(Enum):
    WRITTEN = "written"
    UNCHANGED = "unchanged"
    DUPLICATE = "duplicate"


class Collector:
    def __init__(self, source: Source, client: GbfsClient, storage: Storage, clock: Clock) -> None:
        self.source = source
        self.client = client
        self.storage = storage
        self.clock = clock
        self._last_written: dict[str, datetime] = {}
        self._retry_at: dict[str, datetime] = {}

    def run(self, stop: threading.Event | None = None, max_iterations: int | None = None) -> None:
        """Poll every due feed, sleep until the next one is due, repeat.

        Stops when ``stop`` is set or after ``max_iterations`` passes over
        the feed list, whichever comes first. A ``FeedError`` or any other
        exception from one feed is logged as a warning; the other feeds keep
        being polled. ``clock.sleep`` is the only sleep used, never
        ``time.sleep``, so tests can simulate time with a fake clock.
        """
        if stop is None:
            stop = threading.Event()

        iterations = 0
        while not stop.is_set():
            if max_iterations is not None and iterations >= max_iterations:
                return

            for feed_name in self.source.feeds:
                if stop.is_set():
                    return
                if not self._is_due(feed_name):
                    continue
                try:
                    self.poll_feed(feed_name)
                except Exception:
                    logger.warning("poll failed, will retry later feed=%s", feed_name, exc_info=True)
                    self._set_retry(feed_name)
                else:
                    self._retry_at.pop(feed_name, None)

            iterations += 1
            if (max_iterations is not None and iterations >= max_iterations) or stop.is_set():
                return

            sleep_for = self._seconds_until_due()
            if sleep_for > 0:
                self.clock.sleep(sleep_for)

    def _set_retry(self, feed_name: str) -> None:
        floor = min(FEED_INTERVALS_S[feed_name], MAX_RETRY_FLOOR_S)
        self._retry_at[feed_name] = self.clock.now() + timedelta(seconds=floor)

    def _effective_due(self, feed_name: str) -> datetime | None:
        """Later of the client's ttl/interval due time and a pending retry.

        ``None`` means never attempted, i.e. due now.
        """
        client_due = self.client.next_due(feed_name, FEED_INTERVALS_S[feed_name])
        retry_due = self._retry_at.get(feed_name)
        candidates = [due for due in (client_due, retry_due) if due is not None]
        if not candidates:
            return None
        return max(candidates)

    def _is_due(self, feed_name: str) -> bool:
        due = self._effective_due(feed_name)
        return due is None or self.clock.now() >= due

    def _seconds_until_due(self) -> float:
        now = self.clock.now()
        delays: list[float] = []
        for feed_name in self.source.feeds:
            due = self._effective_due(feed_name)
            if due is None:
                return 0.0
            delays.append((due - now).total_seconds())
        if not delays:
            return 0.0
        return max(0.0, min(delays))

    def poll_feed(self, feed_name: str) -> PollResult:
        """Fetch, convert and write one feed. Lets ``FeedError`` propagate."""
        result = self.client.fetch(feed_name)
        snapshot_ts = datetime.fromtimestamp(result.last_updated, tz=timezone.utc)

        if self._last_written.get(feed_name) == snapshot_ts:
            return PollResult.UNCHANGED

        table = self._convert(feed_name, result, snapshot_ts)
        dataset = FEED_TO_DATASET[feed_name]
        try:
            self.storage.write(dataset, self.source.name, table)
        except DuplicateSnapshotError:
            self._last_written[feed_name] = snapshot_ts
            return PollResult.DUPLICATE

        self._last_written[feed_name] = snapshot_ts
        return PollResult.WRITTEN

    def _convert(self, feed_name: str, result: FeedResult, snapshot_ts: datetime) -> pa.Table:
        if feed_name == "station_status":
            return self._station_status_table(result, snapshot_ts)
        if feed_name == "station_information":
            return self._station_information_table(result, snapshot_ts)
        if feed_name == "vehicle_types":
            return self._vehicle_types_table(result, snapshot_ts)
        if feed_name == "free_bike_status":
            return aggregate_free_bikes(result.payload, snapshot_ts, result.fetched_at, self.source.name)
        raise ValueError(f"unsupported feed: {feed_name!r}")

    def _station_status_table(self, result: FeedResult, snapshot_ts: datetime) -> pa.Table:
        rows: list[dict[str, Any]] = [
            {
                "snapshot_ts": snapshot_ts,
                "fetched_at": result.fetched_at,
                "source": self.source.name,
                "station_id": station["station_id"],
                "num_bikes_available": station["num_bikes_available"],
                "num_docks_available": station["num_docks_available"],
                "num_bikes_disabled": station.get("num_bikes_disabled"),
                "is_installed": station["is_installed"],
                "is_renting": station["is_renting"],
                "is_returning": station["is_returning"],
                "last_reported": datetime.fromtimestamp(station["last_reported"], tz=timezone.utc),
                "vehicle_types_available": station.get("vehicle_types_available"),
            }
            for station in result.payload["stations"]
        ]
        return pa.Table.from_pylist(rows, schema=STATION_STATUS_SCHEMA)

    def _station_information_table(self, result: FeedResult, snapshot_ts: datetime) -> pa.Table:
        rows = [
            {
                "snapshot_ts": snapshot_ts,
                "source": self.source.name,
                "station_id": station["station_id"],
                "name": station["name"],
                "lat": station["lat"],
                "lon": station["lon"],
                "capacity": station.get("capacity"),
            }
            for station in result.payload["stations"]
        ]
        return pa.Table.from_pylist(rows, schema=STATION_INFORMATION_SCHEMA)

    def _vehicle_types_table(self, result: FeedResult, snapshot_ts: datetime) -> pa.Table:
        rows = [
            {
                "snapshot_ts": snapshot_ts,
                "source": self.source.name,
                "vehicle_type_id": vehicle_type["vehicle_type_id"],
                "form_factor": vehicle_type["form_factor"],
                "propulsion_type": vehicle_type["propulsion_type"],
                "name": vehicle_type.get("name"),
            }
            for vehicle_type in result.payload["vehicle_types"]
        ]
        return pa.Table.from_pylist(rows, schema=VEHICLE_TYPES_SCHEMA)
