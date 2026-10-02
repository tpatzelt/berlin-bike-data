"""Per-feed polling: fetch one feed, convert it to its schemas.py table, write it.

Only the single-feed step lives here. The run loop, scheduling, gap rows and
backoff sleeps that drive repeated polling are later tasks; this module just
has to be a safe building block for them: re-polling a feed whose
``last_updated`` has not advanced, or restarting on a data dir that already
has the snapshot, must both be harmless no-ops.
"""

from __future__ import annotations

from datetime import datetime, timezone
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

FEED_TO_DATASET = {
    "station_status": "station_status",
    "station_information": "station_information",
    "vehicle_types": "vehicle_types",
    "free_bike_status": "free_bike_cells",
}


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
