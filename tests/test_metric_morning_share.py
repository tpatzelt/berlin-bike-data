"""Tests for berlinbikes.analysis.empty.morning_shortage's share_empty_at_0800 (G3).

Real snapshot timestamps come from the feed's ``last_updated`` and have
arbitrary seconds, so they almost never land on an exact local 08:00:00.
morning_shortage() must instead use the latest snapshot whose local time
falls in [07:50:00, 08:00:00], so a dataset whose snapshots are shifted a
few seconds or minutes early (but still inside that window) still produces
the same share_empty_at_0800 as the unshifted dataset. A shift that pushes
the nearest snapshot entirely outside the window must leave the share
``None`` without flipping the metric's status away from ``'ok'``.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.empty import morning_shortage
from tests.synthetic import build_dataset

_BUILD_KWARGS = {"start_date": date(2026, 1, 5), "days": 14, "n_stations": 6, "gap": False}
_SOURCE = "nextbike_bn"


def _shift_snapshot_ts(data_dir: Path, seconds: float, source: str = _SOURCE) -> None:
    for path in sorted((data_dir / source / "station_status").glob("date=*/part-*.parquet")):
        table = pq.read_table(path)
        index = table.schema.get_field_index("snapshot_ts")
        shifted = pc.add(table["snapshot_ts"], timedelta(seconds=seconds))
        table = table.set_column(index, "snapshot_ts", shifted)
        pq.write_table(table, path)


def test_seconds_offset_inside_window_matches_the_exact_match_share(tmp_path):
    build_dataset(tmp_path / "a", **_BUILD_KWARGS)
    build_dataset(tmp_path / "b", **_BUILD_KWARGS)
    _shift_snapshot_ts(tmp_path / "b", seconds=-23)

    exact = morning_shortage(connect(tmp_path / "a"))
    shifted = morning_shortage(connect(tmp_path / "b"))

    assert exact.status == "ok"
    assert shifted.status == "ok"
    assert exact.rows["share_empty_at_0800"] is not None
    assert shifted.rows["share_empty_at_0800"] is not None
    assert shifted.rows["share_empty_at_0800"] == pytest.approx(exact.rows["share_empty_at_0800"])


def test_offset_outside_window_leaves_share_none_but_status_ok(tmp_path):
    build_dataset(tmp_path, **_BUILD_KWARGS)
    _shift_snapshot_ts(tmp_path, seconds=-11 * 60)

    result = morning_shortage(connect(tmp_path))

    assert result.status == "ok"
    assert result.rows["share_empty_at_0800"] is None
