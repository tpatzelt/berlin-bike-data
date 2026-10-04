"""Per-feed polling: fetch one feed, convert it to its schemas.py table, write it.

Only the single-feed step lives here. The run loop, scheduling, gap rows and
backoff sleeps that drive repeated polling are later tasks; this module just
has to be a safe building block for them: re-polling a feed whose
``last_updated`` has not advanced, or restarting on a data dir that already
has the snapshot, must both be harmless no-ops.
"""

from __future__ import annotations

import logging
import math
import threading
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa

from berlinbikes.backoff import Clock
from berlinbikes.cells import aggregate_free_bikes
from berlinbikes.gbfs import FeedResult, GbfsClient
from berlinbikes.schemas import (
    GAPS_SCHEMA,
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

#: A feed whose last_updated hasn't advanced for longer than this multiple
#: of its poll interval is considered stale.
STALE_FACTOR = 3

#: Feeds with this interval are only fetched once per Europe/Berlin day.
DAILY_INTERVAL_S = 86400

BERLIN_TZ = ZoneInfo("Europe/Berlin")


def _next_berlin_midnight_utc(after: datetime) -> datetime:
    """The next Europe/Berlin local midnight strictly after ``after``, in UTC."""
    local = after.astimezone(BERLIN_TZ)
    next_midnight_local = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=BERLIN_TZ)
    return next_midnight_local.astimezone(timezone.utc)


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
        #: gap_start of the current open outage for a feed (a run of
        #: consecutive failures, or downtime discovered on resume).
        self._outage_start: dict[str, datetime] = {}
        self._outage_attempts: dict[str, int] = {}
        #: gaps.reason the open outage will be written with: "fetch_error"
        #: for one opened by a failed poll, "collector_down" for one opened
        #: by _resume() finding a stale-on-disk snapshot.
        self._outage_reason: dict[str, str] = {}
        #: last_written value a stale_feed row was already recorded for.
        self._stale_gap_written: dict[str, datetime] = {}
        self._resumed = False

    def run(self, stop: threading.Event | None = None, max_iterations: int | None = None) -> None:
        """Poll every due feed, sleep until the next one is due, repeat.

        Stops when ``stop`` is set or after ``max_iterations`` passes over
        the feed list, whichever comes first. A ``FeedError`` or any other
        exception from one feed is logged as a warning; the other feeds keep
        being polled. ``clock.sleep`` is the only sleep used, never
        ``time.sleep``, so tests can simulate time with a fake clock. Any
        outage still open when the loop stops is flushed as a gap row.
        """
        if stop is None:
            stop = threading.Event()

        if not self._resumed:
            self._resume()
            self._resumed = True

        try:
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
                        logger.warning(
                            "poll failed, will retry later feed=%s", feed_name, exc_info=True
                        )
                        self._handle_poll_failure(feed_name)
                    else:
                        self._retry_at.pop(feed_name, None)
                        self._handle_poll_success(feed_name)

                iterations += 1
                if (max_iterations is not None and iterations >= max_iterations) or stop.is_set():
                    return

                sleep_for = self._seconds_until_due()
                if sleep_for > 0:
                    self.clock.sleep(sleep_for)
        finally:
            self._flush_open_outages()

    def _resume(self) -> None:
        """Restore in-memory state from what is already on disk.

        For each feed, the latest stored snapshot becomes ``_last_written``
        so the first poll after a restart reports ``UNCHANGED`` instead of
        relying on storage's own dedupe. A daily feed whose stored
        snapshot's Europe/Berlin calendar date is today's is not re-fetched
        until the next Berlin midnight; "today" is judged by the stored
        snapshot_ts (the feed's last_updated), not fetched_at.

        For a feed polled every ``FEED_INTERVALS_S[feed_name]`` seconds, a
        gap between the stored snapshot and now longer than twice that
        interval means the process itself was down for that stretch (not
        just a quick restart), so a ``collector_down`` outage is opened,
        clamped to start no earlier than the latest gap already recorded
        for that feed so it can never collide with a gap an earlier process
        already wrote at the stored snapshot's timestamp.
        """
        now = self.clock.now()
        for feed_name in self.source.feeds:
            stored = self.storage.latest_snapshot(self.source.name, FEED_TO_DATASET[feed_name])
            if stored is None:
                continue
            self._last_written[feed_name] = stored
            interval = FEED_INTERVALS_S[feed_name]
            if interval == DAILY_INTERVAL_S:
                if stored.astimezone(BERLIN_TZ).date() == now.astimezone(BERLIN_TZ).date():
                    self._retry_at[feed_name] = _next_berlin_midnight_utc(now)
                continue
            if (now - stored).total_seconds() > 2 * interval:
                start = stored
                latest_gap_end = self.storage.latest_gap_end(self.source.name, feed_name)
                if latest_gap_end is not None and latest_gap_end > start:
                    start = latest_gap_end
                self._outage_start[feed_name] = start
                self._outage_reason[feed_name] = "collector_down"

    def _set_retry(self, feed_name: str) -> None:
        floor = min(FEED_INTERVALS_S[feed_name], MAX_RETRY_FLOOR_S)
        delay = max(floor, self.client.backoff_delay(feed_name))
        # Round up to a multiple of the floor so retries stay on the same
        # wake-up grid as healthy feeds instead of waking early on jitter.
        delay = math.ceil(delay / floor) * floor
        self._retry_at[feed_name] = self.clock.now() + timedelta(seconds=delay)

    def _handle_poll_failure(self, feed_name: str) -> None:
        if self._outage_start.get(feed_name) is None:
            start = self._last_written.get(feed_name) or self.clock.now()
            # Avoid colliding with a stale_feed row already written at this
            # key: start the outage at the first failed attempt instead.
            if self._stale_gap_written.get(feed_name) == start:
                start = self.clock.now()
            self._outage_start[feed_name] = start
            self._outage_reason[feed_name] = "fetch_error"
            logger.warning("feed outage starting feed=%s", feed_name)
        # A failure during an already-open outage (including a
        # collector_down one opened by _resume()) just adds an attempt
        # instead of opening a second row.
        self._outage_attempts[feed_name] = self._outage_attempts.get(feed_name, 0) + 1
        self._set_retry(feed_name)

    def _handle_poll_success(self, feed_name: str) -> None:
        outage_start = self._outage_start.get(feed_name)
        if outage_start is not None:
            reason = self._outage_reason.get(feed_name, "fetch_error")
            last_written = self._last_written.get(feed_name)
            closes = last_written is not None and last_written > outage_start
            if reason == "collector_down" and not closes:
                # A resumed outage stays open until the feed produces a
                # genuinely new snapshot, so a poll that merely succeeds
                # while the feed is itself still stale can't make the
                # downtime vanish. It is flushed at shutdown otherwise.
                return
            attempts = self._outage_attempts.pop(feed_name, 0)
            self._outage_reason.pop(feed_name, None)
            self._outage_start.pop(feed_name, None)
            if closes:
                self._write_gap(feed_name, outage_start, last_written, reason, attempts)
            else:
                logger.info("skipping zero-length %s gap feed=%s", reason, feed_name)
        self._check_stale(feed_name)

    def _check_stale(self, feed_name: str) -> None:
        last_ts = self._last_written.get(feed_name)
        if last_ts is None:
            return
        if self._stale_gap_written.get(feed_name) == last_ts:
            return
        threshold = STALE_FACTOR * FEED_INTERVALS_S[feed_name]
        now = self.clock.now()
        if (now - last_ts).total_seconds() <= threshold:
            return
        # Avoid colliding with a gap an earlier process already wrote
        # ending at or after last_ts (for example a stale_feed row from
        # before a restart): start no earlier than that.
        start = last_ts
        latest_gap_end = self.storage.latest_gap_end(self.source.name, feed_name)
        if latest_gap_end is not None and latest_gap_end > start:
            start = latest_gap_end
        self._stale_gap_written[feed_name] = last_ts
        if now > start:
            self._write_gap(feed_name, start, now, "stale_feed", attempts=0)
        else:
            logger.info("skipping zero-length stale_feed gap feed=%s", feed_name)

    def _flush_open_outages(self) -> None:
        now = self.clock.now()
        for feed_name in list(self._outage_start):
            outage_start = self._outage_start.pop(feed_name)
            attempts = self._outage_attempts.pop(feed_name, 0)
            reason = self._outage_reason.pop(feed_name, "fetch_error")
            if now > outage_start:
                self._write_gap(feed_name, outage_start, now, reason, attempts)
            else:
                logger.info("skipping zero-length %s gap at shutdown feed=%s", reason, feed_name)

    def _write_gap(
        self, feed_name: str, gap_start: datetime, gap_end: datetime, reason: str, attempts: int
    ) -> None:
        table = pa.Table.from_pylist(
            [
                {
                    "source": self.source.name,
                    "feed": feed_name,
                    "gap_start": gap_start,
                    "gap_end": gap_end,
                    "reason": reason,
                    "attempts": attempts,
                }
            ],
            schema=GAPS_SCHEMA,
        )
        try:
            self.storage.write("gaps", self.source.name, table)
        except DuplicateSnapshotError:
            logger.warning(
                "gap write collided with an existing key, skipping feed=%s gap_start=%s",
                feed_name,
                gap_start,
            )

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
                "num_docks_available": station.get("num_docks_available"),
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
