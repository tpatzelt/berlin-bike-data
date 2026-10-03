"""Builds the citywide availability-by-hour line chart as plain-SVG chart data.

Renders no HTML itself: it returns the scaled points and the raw per-hour
means that ``index.html`` draws as SVG ``<polyline>``s and a ``<table>``
fallback. Colors are assigned by weekday (Monday first) to the
``--series-1``..``--series-7`` custom properties defined in ``site.css``,
following the validated categorical order from the project's data-viz
palette (blue, orange, aqua, yellow, magenta, green, violet).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from berlinbikes.analysis.availability import availability_by_hour
from berlinbikes.analysis.db import connect

WEEKDAY_NAMES = (
    ("Mo", "Mon"),
    ("Di", "Tue"),
    ("Mi", "Wed"),
    ("Do", "Thu"),
    ("Fr", "Fri"),
    ("Sa", "Sat"),
    ("So", "Sun"),
)

VIEW_WIDTH = 480
VIEW_HEIGHT = 240
_PAD_LEFT = 32
_PAD_RIGHT = 10
_PAD_TOP = 10
_PAD_BOTTOM = 20


@dataclass(frozen=True)
class WeekdaySeries:
    index: int
    name_de: str
    name_en: str
    points: str
    hours: list[float]


@dataclass(frozen=True)
class AvailabilityChart:
    status: str
    full_days: int
    message: str | None
    view_box: str
    weekdays: list[WeekdaySeries] | None


def _scale_x(hour: int) -> float:
    return _PAD_LEFT + hour / 23 * (VIEW_WIDTH - _PAD_LEFT - _PAD_RIGHT)


def _scale_y(value: float, y_min: float, y_span: float) -> float:
    plot_height = VIEW_HEIGHT - _PAD_TOP - _PAD_BOTTOM
    return VIEW_HEIGHT - _PAD_BOTTOM - (value - y_min) / y_span * plot_height


def availability_chart(data_dir: str | Path) -> AvailabilityChart:
    """Citywide mean bikes available, one series per weekday, hour 0-23.

    Returns ``status="insufficient_data"`` with no ``weekdays`` below the
    14-full-day minimum, same as :func:`availability_by_hour` itself.
    """
    result = availability_by_hour(connect(data_dir), by="city")
    if result.status != "ok":
        return AvailabilityChart(
            status=result.status,
            full_days=result.full_days,
            message=result.message,
            view_box=f"0 0 {VIEW_WIDTH} {VIEW_HEIGHT}",
            weekdays=None,
        )

    grid: dict[tuple[int, int], float] = {
        (weekday, hour): mean for weekday, hour, mean, _n in result.rows
    }
    all_values = [mean for _weekday, _hour, mean, _n in result.rows]
    y_min, y_max = min(all_values), max(all_values)
    y_span = (y_max - y_min) or 1.0

    weekdays = []
    for index, (name_de, name_en) in enumerate(WEEKDAY_NAMES):
        hours = [grid[(index, hour)] for hour in range(24)]
        points = " ".join(
            f"{_scale_x(hour):.1f},{_scale_y(value, y_min, y_span):.1f}"
            for hour, value in enumerate(hours)
        )
        weekdays.append(
            WeekdaySeries(index=index, name_de=name_de, name_en=name_en, points=points, hours=hours)
        )

    return AvailabilityChart(
        status="ok",
        full_days=result.full_days,
        message=None,
        view_box=f"0 0 {VIEW_WIDTH} {VIEW_HEIGHT}",
        weekdays=weekdays,
    )
