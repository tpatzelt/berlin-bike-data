"""Append-only, crash-safe Parquet storage for collected snapshots.

Layout::

    {data_dir}/{source}/{dataset}/date=YYYY-MM-DD/part-<stamp>.parquet

``date=`` is the UTC calendar date of the row's snapshot timestamp
(``gap_start`` for ``gaps``). ``<stamp>`` is that same timestamp formatted
``HHMMSSffffff``; for ``gaps`` the feed is prefixed: ``part-<feed>-<stamp>``.

A write never overwrites: the table is staged to a file in the target
partition directory whose name starts with ``.tmp-`` (so it never matches
the ``part-*.parquet`` glob every reader uses), fsynced, then published with
a create-exclusive ``os.link`` + unlink of the staging file. A crash between
those two steps leaves only a ``.tmp-*`` file behind, which readers ignore
and the next ``write()`` deletes before doing anything else.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from berlinbikes.schemas import GAP_REASONS, SCHEMAS

_PART_GLOB = "part-*.parquet"
_TMP_PREFIX = ".tmp-"


class DuplicateSnapshotError(ValueError):
    """Raised when a write's dedupe key already exists on disk."""


class SnapshotFileCollisionError(RuntimeError):
    """Raised when the computed destination file already exists."""


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError(f"timestamp {ts!r} is not timezone-aware")
    return ts.astimezone(timezone.utc)


def _stamp(ts: datetime) -> str:
    return _as_utc(ts).strftime("%H%M%S%f")


def _check_single_source(table: pa.Table, source: str) -> None:
    values = set(table.column("source").to_pylist())
    extra = values - {source}
    if extra:
        raise ValueError(
            f"table contains source value(s) {sorted(extra)!r}, expected only {source!r}"
        )


def _check_gap_reasons(table: pa.Table) -> None:
    values = set(table.column("reason").to_pylist())
    bad = values - GAP_REASONS
    if bad:
        raise ValueError(f"gaps.reason has invalid value(s) {sorted(bad)!r}")


def _snapshot_key_and_date(dataset: str, table: pa.Table):
    """Return the single dedupe key and partition date for one write() call.

    A write is one snapshot: every row must share the same ``snapshot_ts``
    (or, for ``gaps``, the same ``(feed, gap_start)`` pair), since that is
    also what the destination filename encodes.
    """
    if dataset == "gaps":
        feeds = table.column("feed").to_pylist()
        starts = [_as_utc(ts) for ts in table.column("gap_start").to_pylist()]
        keys = set(zip(feeds, starts))
        if len(keys) != 1:
            raise ValueError(
                f"write() requires exactly one (feed, gap_start) per call, got {sorted(keys)}"
            )
        feed, gap_start = next(iter(keys))
        return (feed, gap_start), gap_start.date()

    snaps = [_as_utc(ts) for ts in table.column("snapshot_ts").to_pylist()]
    keys = set(snaps)
    if len(keys) != 1:
        raise ValueError(
            f"write() requires exactly one snapshot_ts per call, got {sorted(keys)}"
        )
    snap = next(iter(keys))
    return snap, snap.date()


class Storage:
    """A Parquet-backed snapshot store rooted at ``data_dir``."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    def _dataset_dir(self, source: str, dataset: str) -> Path:
        return self.data_dir / source / dataset

    def _partition_dir(self, source: str, dataset: str, day: date) -> Path:
        return self._dataset_dir(source, dataset) / f"date={day.isoformat()}"

    def _clean_leftover_tmp_files(self, partition_dir: Path) -> None:
        if not partition_dir.is_dir():
            return
        for path in partition_dir.glob(f"{_TMP_PREFIX}*"):
            if path.is_file():
                path.unlink()

    def existing_snapshots(self, source: str, dataset: str, day: date) -> set:
        """Dedupe keys already written for ``source``/``dataset``/``day``.

        Returns a set of ``snapshot_ts`` values for snapshot datasets, or a
        set of ``(feed, gap_start)`` tuples for ``gaps``. Only finished files
        (``part-*.parquet``) are read; staging files are never considered.
        """
        partition_dir = self._partition_dir(source, dataset, day)
        if not partition_dir.is_dir():
            return set()

        keys: set = set()
        for path in sorted(partition_dir.glob(_PART_GLOB)):
            if dataset == "gaps":
                table = pq.read_table(path, columns=["feed", "gap_start"])
                feeds = table.column("feed").to_pylist()
                starts = (_as_utc(ts) for ts in table.column("gap_start").to_pylist())
                keys.update(zip(feeds, starts))
            else:
                table = pq.read_table(path, columns=["snapshot_ts"])
                keys.update(_as_utc(ts) for ts in table.column("snapshot_ts").to_pylist())
        return keys

    def latest_snapshot(self, source: str, dataset: str):
        """The most recent dedupe key written, or ``None`` if there is none.

        For ``gaps`` this is the latest ``gap_start``. Only the newest
        ``date=`` partition that actually has a finished part file is
        scanned, so restart cost stays bounded by one partition.
        """
        dataset_dir = self._dataset_dir(source, dataset)
        if not dataset_dir.is_dir():
            return None

        partition_dirs = sorted(
            (p for p in dataset_dir.iterdir() if p.is_dir() and p.name.startswith("date=")),
            reverse=True,
        )
        for partition_dir in partition_dirs:
            if not any(partition_dir.glob(_PART_GLOB)):
                continue
            day = date.fromisoformat(partition_dir.name.removeprefix("date="))
            keys = self.existing_snapshots(source, dataset, day)
            if not keys:
                continue
            if dataset == "gaps":
                return max(gap_start for _feed, gap_start in keys)
            return max(keys)
        return None

    def write(self, dataset: str, source: str, table: pa.Table) -> Path:
        """Write ``table`` as one new, finished Parquet file.

        Raises ``DuplicateSnapshotError`` if the write's dedupe key already
        exists, ``SnapshotFileCollisionError`` if the destination file
        exists despite that (leaving it untouched), and ``ValueError`` if
        the table's ``source`` column disagrees with ``source``, a
        ``gaps.reason`` is invalid, or the rows don't share one partition
        key.
        """
        schema = SCHEMAS[dataset]
        _check_single_source(table, source)
        if dataset == "gaps":
            _check_gap_reasons(table)
        key, day = _snapshot_key_and_date(dataset, table)

        partition_dir = self._partition_dir(source, dataset, day)
        partition_dir.mkdir(parents=True, exist_ok=True)
        self._clean_leftover_tmp_files(partition_dir)

        if key in self.existing_snapshots(source, dataset, day):
            raise DuplicateSnapshotError(f"snapshot key already written: {key!r}")

        if dataset == "gaps":
            feed, gap_start = key
            filename = f"part-{feed}-{_stamp(gap_start)}.parquet"
        else:
            filename = f"part-{_stamp(key)}.parquet"

        final_path = partition_dir / filename
        if final_path.exists():
            raise SnapshotFileCollisionError(f"{final_path} already exists")

        tmp_path = partition_dir / f"{_TMP_PREFIX}{uuid.uuid4().hex}.partial"
        cast_table = table.cast(schema)
        try:
            with open(tmp_path, "wb") as fh:
                pq.write_table(cast_table, fh)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.link(tmp_path, final_path)
            except FileExistsError as exc:
                raise SnapshotFileCollisionError(f"{final_path} already exists") from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        return final_path
