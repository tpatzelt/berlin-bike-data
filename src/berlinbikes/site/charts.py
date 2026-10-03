"""Builds plain-SVG chart data for the article page's charts.

Renders no HTML itself: it returns the scaled points/bars that
``index.html`` draws as SVG and a ``<table>`` fallback.

``availability_chart`` draws the citywide availability-by-hour line chart,
one ``<polyline>`` per weekday (Monday first), colored via the
``--series-1``..``--series-7`` custom properties defined in ``site.css``,
following the validated categorical order from the project's data-viz
palette (blue, orange, aqua, yellow, magenta, green, violet).

``shortage_chart`` draws the G4 8:00 morning-shortage headline and a
horizontal bar chart of the top stations by empty minutes per day in the
morning window, bars colored via ``--accent``.

``bezirk_availability_chart`` draws the per-Bezirk availability-by-hour line
chart (Mon-Fri only), one ``<polyline>`` per Bezirk sorted by name, colored
via ``--series-1``..``--series-7`` (cycling if there are more than 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from berlinbikes.analysis.availability import availability_by_hour
from berlinbikes.analysis.db import connect
from berlinbikes.analysis.empty import MORNING_WINDOW, morning_shortage

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


@dataclass(frozen=True)
class BezirkSeries:
    index: int
    color_index: int
    name: str
    points: str
    hours: list[float | None]


@dataclass(frozen=True)
class BezirkAvailabilityChart:
    status: str
    full_days: int
    message: str | None
    view_box: str
    bezirke: list[BezirkSeries] | None


def bezirk_availability_chart(data_dir: str | Path) -> BezirkAvailabilityChart:
    """Mean bikes available by local hour per Bezirk, Mon-Fri only, hour 0-23.

    Each Bezirk's hour value is the unweighted mean of its weekday (0-4)
    values that exist for that hour; an hour with no weekday value for a
    given Bezirk is left out of that Bezirk's polyline and shown as ``None``
    (rendered as '--' by the template). Returns ``status="insufficient_data"``
    with no ``bezirke`` below the 14-full-day minimum, same as
    :func:`availability_by_hour` itself.
    """
    result = availability_by_hour(connect(data_dir), by="bezirk")
    if result.status != "ok":
        return BezirkAvailabilityChart(
            status=result.status,
            full_days=result.full_days,
            message=result.message,
            view_box=f"0 0 {VIEW_WIDTH} {VIEW_HEIGHT}",
            bezirke=None,
        )

    weekday_values: dict[tuple[str, int], list[float]] = {}
    bezirk_names: set[str] = set()
    for weekday, hour, bezirk, mean, _n in result.rows:
        bezirk_names.add(bezirk)
        if weekday <= 4:
            weekday_values.setdefault((bezirk, hour), []).append(mean)

    hour_means = {key: sum(values) / len(values) for key, values in weekday_values.items()}

    all_values = list(hour_means.values())
    y_min, y_max = (min(all_values), max(all_values)) if all_values else (0.0, 1.0)
    y_span = (y_max - y_min) or 1.0

    bezirke = []
    for index, name in enumerate(sorted(bezirk_names)):
        hours: list[float | None] = []
        points_parts = []
        for hour in range(24):
            value = hour_means.get((name, hour))
            hours.append(value)
            if value is not None:
                points_parts.append(f"{_scale_x(hour):.1f},{_scale_y(value, y_min, y_span):.1f}")
        bezirke.append(
            BezirkSeries(
                index=index,
                color_index=(index % 7) + 1,
                name=name,
                points=" ".join(points_parts),
                hours=hours,
            )
        )

    return BezirkAvailabilityChart(
        status="ok",
        full_days=result.full_days,
        message=None,
        view_box=f"0 0 {VIEW_WIDTH} {VIEW_HEIGHT}",
        bezirke=bezirke,
    )


#: How many stations the morning-shortage bar chart shows.
SHORTAGE_TOP_N = 10

_BAR_VIEW_WIDTH = 480
_BAR_HEIGHT = 18
_BAR_GAP = 8
_BAR_PAD_LEFT = 150
_BAR_PAD_RIGHT = 54
_BAR_PAD_TOP = 8
_BAR_PAD_BOTTOM = 8
_BAR_MIN_VIEW_HEIGHT = 60

_WEEKDAY_ABBR_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
_WEEKDAY_ABBR_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _window_label(window) -> tuple[str, str]:
    """A short bilingual description of a morning-shortage ``Window``, e.g. ``Mo-Fr 7:30-8:30``."""
    weekdays, start, end = window
    days = sorted(weekdays)
    time_part = f"{start.hour}:{start.minute:02d}-{end.hour}:{end.minute:02d}"
    de = f"{_WEEKDAY_ABBR_DE[days[0]]}-{_WEEKDAY_ABBR_DE[days[-1]]} {time_part}"
    en = f"{_WEEKDAY_ABBR_EN[days[0]]}-{_WEEKDAY_ABBR_EN[days[-1]]} {time_part}"
    return de, en


@dataclass(frozen=True)
class ShortageBar:
    station_id: str
    ortsteil: str
    minutes_per_day: float
    bar_x: float
    bar_y: float
    bar_width: float
    bar_height: float
    label_y: float
    value_x: float


@dataclass(frozen=True)
class ShortageChart:
    status: str
    full_days: int
    message: str | None
    share_pct: float | None
    view_box: str
    aria_label: str
    bars: list[ShortageBar] | None


def _bar_view_height(n: int) -> float:
    n = max(n, 1)
    return _BAR_PAD_TOP + _BAR_PAD_BOTTOM + n * _BAR_HEIGHT + (n - 1) * _BAR_GAP


def shortage_chart(data_dir: str | Path) -> ShortageChart:
    """The G4 8:00 morning-shortage headline and its top-stations bar chart.

    Returns ``status="insufficient_data"`` with no ``bars`` below the
    14-full-day minimum, same as :func:`morning_shortage` itself. When
    enough data exists but no snapshot lands on exactly local 08:00:00 (as
    on real, non-synthetic data), ``morning_shortage`` reports
    ``share_empty_at_0800=None``; this is rendered as ``share_pct=None`` so
    the headline sentence is left out, while the bar chart and table (which
    do not depend on the exact-08:00 match) still render.
    """
    result = morning_shortage(connect(data_dir))
    de_label, en_label = _window_label(MORNING_WINDOW)
    if result.status != "ok":
        return ShortageChart(
            status=result.status,
            full_days=result.full_days,
            message=result.message,
            share_pct=None,
            view_box=f"0 0 {_BAR_VIEW_WIDTH} {_BAR_MIN_VIEW_HEIGHT}",
            aria_label="",
            bars=None,
        )

    share = result.rows["share_empty_at_0800"]
    share_pct = round(share * 100, 1) if share is not None else None

    top_stations = result.rows["stations"][:SHORTAGE_TOP_N]
    values = [minutes_per_day for *_rest, minutes_per_day in top_stations]
    max_value = max(values) if values else 1.0
    plot_width = _BAR_VIEW_WIDTH - _BAR_PAD_LEFT - _BAR_PAD_RIGHT

    bars = []
    for i, (station_id, _bezirk, ortsteil, _total, minutes_per_day) in enumerate(top_stations):
        bar_y = _BAR_PAD_TOP + i * (_BAR_HEIGHT + _BAR_GAP)
        bar_width = (minutes_per_day / max_value) * plot_width if max_value else 0.0
        bars.append(
            ShortageBar(
                station_id=station_id,
                ortsteil=ortsteil,
                minutes_per_day=minutes_per_day,
                bar_x=_BAR_PAD_LEFT,
                bar_y=bar_y,
                bar_width=bar_width,
                bar_height=_BAR_HEIGHT,
                label_y=bar_y + _BAR_HEIGHT * 0.65,
                value_x=_BAR_PAD_LEFT + bar_width + 4,
            )
        )

    aria_label = (
        f"Leerstehende Stationen am Morgen, {de_label} Uhr, Top {len(bars)} / "
        f"Stations empty in the morning, {en_label}, top {len(bars)}"
    )

    return ShortageChart(
        status="ok",
        full_days=result.full_days,
        message=None,
        share_pct=share_pct,
        view_box=f"0 0 {_BAR_VIEW_WIDTH} {_bar_view_height(len(bars))}",
        aria_label=aria_label,
        bars=bars,
    )
