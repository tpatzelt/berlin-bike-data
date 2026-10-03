"""Shared contract for every G3 metric: a day-count guard and a result shape.

The charter requires every metric to report how many days of data it is
based on and to refuse to publish below a minimum (ADR-0003 sets it at 14
full days, see :mod:`berlinbikes.analysis.coverage`). :func:`guard` is the
single place that rule is enforced, so metric code never computes on
insufficient data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

MIN_FULL_DAYS = 14

NOT_ENOUGH_DATA_MESSAGE = "not enough data yet / noch nicht genug Daten"


@dataclass(frozen=True)
class MetricResult:
    name: str
    full_days: int
    status: str
    message: str | None
    rows: Any


def guard(name: str, n_days: int, compute: Callable[[], Any]) -> MetricResult:
    """Run ``compute`` for metric ``name`` unless ``n_days`` is below the minimum.

    Below :data:`MIN_FULL_DAYS`, returns ``status="insufficient_data"`` with
    ``rows=None`` without calling ``compute``. Otherwise calls ``compute``
    and returns its result as ``rows`` with ``status="ok"``.
    """
    if n_days < MIN_FULL_DAYS:
        return MetricResult(
            name=name,
            full_days=n_days,
            status="insufficient_data",
            message=NOT_ENOUGH_DATA_MESSAGE,
            rows=None,
        )
    return MetricResult(name=name, full_days=n_days, status="ok", message=None, rows=compute())
