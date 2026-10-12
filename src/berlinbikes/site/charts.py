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

``flow_chart`` draws the per-Bezirk net-flow-by-hour line chart (weekday mean
per day), one ``<polyline>`` per Bezirk sorted by name around a visible zero
baseline, colored the same way as ``bezirk_availability_chart``.

``weather_effect_chart`` draws the two G3-x-G2 rain and temperature small
multiples: for each of ``weather_effect(con, "rain")`` and
``weather_effect(con, "temperature")``, one ``<polyline>`` per bucket
(``rainy``/``dry`` or ``cold``/``warm``) of ``empty_station_share`` (as a
percentage) over local hours, colored via ``--series-1`` (the baseline
bucket: dry/warm) and ``--series-2`` (the active bucket: rainy/cold). The
``"excluded"`` row is never drawn, but its ``n_hours`` is surfaced on the
chart for the caption. A bucket with no rows at all (for example no rainy
hours yet) is left out of the drawing and reported in ``missing_buckets``
instead of crashing.

``footprint_chart`` draws the G3 daily-footprint headline and a vertical
stacked-bar chart, one bar per full day, of the e-bike/pedal/unknown split
of bikes in the system that day, colored via ``--series-1`` (e-bike),
``--series-2`` (pedal) and ``--series-3`` (unknown).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from berlinbikes.analysis.availability import availability_by_hour
from berlinbikes.analysis.db import connect
from berlinbikes.analysis.empty import MORNING_WINDOW, morning_shortage
from berlinbikes.analysis.flow import net_flow_by_bezirk
from berlinbikes.analysis.footprint import daily_footprint
from berlinbikes.analysis.weather_effect import weather_effect

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


#: Root font-size (viewBox units) of charts drawn with :class:`Axes`. At the
#: 328px content width of a 360px viewport it renders at
#: ``CHART_FONT_SIZE * 328 / VIEW_WIDTH`` px, which must stay >= 11.
CHART_FONT_SIZE = 16.5

#: Number of ``--series-N`` colour tokens in site.css; series colours cycle through them.
SERIES_COLOR_COUNT = 7

#: One stroke-dasharray per weekday (Monday solid), so the lines differ by more than color.
WEEKDAY_DASHARRAYS = ("none", "7 4", "2 3", "9 3 2 3", "12 5", "3 2 1 2", "1 4")

#: Rough glyph width as a fraction of the font size, for fitting headline labels.
HEADLINE_CHAR_WIDTH = 0.55

#: Line spacing of two-line headline labels, in em.
HEADLINE_LINE_HEIGHT = 1.1

#: Local hours between which the headline looks for the Mon-Fri dip.
HEADLINE_HOURS = (6, 10)

_AXES_PAD_LEFT = 68
_AXES_PAD_RIGHT = 12
_AXES_PAD_TOP = 14
_AXES_PAD_BOTTOM = 62
_AXES_VIEW_HEIGHT = 300


#: Approximate number of y-axis intervals; map.js reads it to build the same ticks.
Y_TICK_TARGET = 5


def nice_ticks(lo: float, hi: float, target: int = Y_TICK_TARGET) -> list[float]:
    """Round tick values (step 1/2/5 x 10^n) covering ``[lo, hi]``; first <= lo, last >= hi."""
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(target, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= raw)
    first = math.floor(lo / step + 1e-9)
    last = math.ceil(hi / step - 1e-9)
    return [round(i * step, 10) for i in range(first, last + 1)]


@dataclass(frozen=True)
class Tick:
    pos: float
    label: str


@dataclass(frozen=True)
class Axes:
    """Geometry of a framed line chart: plot box, ticks, and title positions (in viewBox units)."""

    view_box: str
    font_size: float
    left: float
    right: float
    top: float
    bottom: float
    x_ticks: list[Tick]
    y_ticks: list[Tick]
    y_min: float
    y_max: float
    x_title_x: float
    x_title_y: float
    y_title_x: float
    y_title_y: float

    def scale_y(self, value: float) -> float:
        return self.bottom - (value - self.y_min) / (self.y_max - self.y_min) * (self.bottom - self.top)


def _fmt_tick(value: float) -> str:
    return f"{value:g}"


def build_axes(y_lo: float, y_hi: float, x_tick_hours: tuple[int, ...] = (0, 4, 8, 12, 16, 20, 23)) -> Axes:
    """Axes for a 0-23 local-hour x axis and a y axis rounded outward to nice ticks."""
    y_values = nice_ticks(y_lo, y_hi)
    y_min, y_max = y_values[0], y_values[-1]
    left, right = _AXES_PAD_LEFT, VIEW_WIDTH - _AXES_PAD_RIGHT
    top, bottom = _AXES_PAD_TOP, _AXES_VIEW_HEIGHT - _AXES_PAD_BOTTOM
    axes = Axes(
        view_box=f"0 0 {VIEW_WIDTH} {_AXES_VIEW_HEIGHT}",
        font_size=CHART_FONT_SIZE,
        left=left,
        right=right,
        top=top,
        bottom=bottom,
        x_ticks=[Tick(left + h / 23 * (right - left), str(h)) for h in x_tick_hours],
        y_ticks=[],
        y_min=y_min,
        y_max=y_max,
        x_title_x=(left + right) / 2,
        x_title_y=_AXES_VIEW_HEIGHT - 6,
        y_title_x=CHART_FONT_SIZE,
        y_title_y=(top + bottom) / 2,
    )
    y_ticks = [Tick(axes.scale_y(v), _fmt_tick(v)) for v in y_values]
    return Axes(**{**axes.__dict__, "y_ticks": y_ticks})


def _headline_label_y(axes: Axes, point_y: float, lines: int = 1) -> float:
    """First-line baseline: below the marker, or above it when that would reach the x tick row."""
    extra = (lines - 1) * CHART_FONT_SIZE * HEADLINE_LINE_HEIGHT
    below = point_y + 22
    if below + extra > axes.bottom - CHART_FONT_SIZE:
        below = point_y - 12 - extra
    return max(axes.top + CHART_FONT_SIZE, min(below, axes.bottom - 4 - extra))


@dataclass(frozen=True)
class Headline:
    """The marked point: pixel position, plotted value and local hour."""

    x: float
    y: float
    value: float
    hour: int
    anchor: str
    label_x: float
    label_y: float
    name: str = ""


def _make_headline(axes: Axes, value: float, hour: int, name: str = "", chars: int = 0) -> Headline:
    """Marker plus label placement; ``chars`` is the longest label line, to keep it in the plot box.

    With ``chars=0`` the label goes right of the marker before 14:00, left after.
    """
    point_y = axes.scale_y(value)
    x = axes.left + hour / 23 * (axes.right - axes.left)
    width = chars * HEADLINE_CHAR_WIDTH * CHART_FONT_SIZE
    if chars == 0:
        anchor = "start" if hour < 14 else "end"
    elif x + 10 + width <= axes.right:
        anchor = "start"
    elif x - 10 - width >= axes.left:
        anchor = "end"
    else:
        anchor = "middle"
    label_x = {
        "start": x + 10,
        "end": x - 10,
        "middle": min(max(x, axes.left + width / 2), axes.right - width / 2),
    }[anchor]
    return Headline(
        x=x,
        y=point_y,
        value=value,
        hour=hour,
        anchor=anchor,
        label_x=label_x,
        label_y=_headline_label_y(axes, point_y, 2 if name else 1),
        name=name,
    )


@dataclass(frozen=True)
class WeekdaySeries:
    index: int
    name_de: str
    name_en: str
    points: str
    hours: list[float]
    dasharray: str = "none"


@dataclass(frozen=True)
class AvailabilityChart:
    status: str
    full_days: int
    message: str | None
    view_box: str
    weekdays: list[WeekdaySeries] | None
    axes: Axes | None = None
    headline: Headline | None = None


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
    axes = build_axes(min(all_values), max(all_values))

    def x_of(hour: int) -> float:
        return axes.left + hour / 23 * (axes.right - axes.left)

    weekdays = []
    for index, (name_de, name_en) in enumerate(WEEKDAY_NAMES):
        hours = [grid[(index, hour)] for hour in range(24)]
        points = " ".join(f"{x_of(hour):.1f},{axes.scale_y(value):.1f}" for hour, value in enumerate(hours))
        weekdays.append(
            WeekdaySeries(
                index=index,
                name_de=name_de,
                name_en=name_en,
                points=points,
                hours=hours,
                dasharray=WEEKDAY_DASHARRAYS[index],
            )
        )

    # The lowest Mon-Fri value in the morning window, from the plotted values only.
    lo_hour, hi_hour = HEADLINE_HOURS
    dip_value, dip_hour = min(
        (weekdays[d].hours[h], h) for d in range(5) for h in range(lo_hour, hi_hour + 1)
    )
    headline = _make_headline(axes, dip_value, dip_hour)

    return AvailabilityChart(
        status="ok",
        full_days=result.full_days,
        message=None,
        view_box=axes.view_box,
        weekdays=weekdays,
        axes=axes,
        headline=headline,
    )


@dataclass(frozen=True)
class BezirkSeries:
    index: int
    color_index: int
    name: str
    points: str
    hours: list[float | None]
    dasharray: str = "none"


@dataclass(frozen=True)
class BezirkAvailabilityChart:
    status: str
    full_days: int
    message: str | None
    view_box: str
    bezirke: list[BezirkSeries] | None
    axes: Axes | None = None
    headline: Headline | None = None


#: Hour of the Bezirk availability headline.
BEZIRK_HEADLINE_HOUR = 8


def cycle_dasharray(index: int) -> str:
    """Colors repeat every 7 series; each repetition gets its own dash pattern."""
    return WEEKDAY_DASHARRAYS[(index // 7) % len(WEEKDAY_DASHARRAYS)]


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

    all_values = list(hour_means.values()) or [0.0, 1.0]
    axes = build_axes(min(all_values), max(all_values))

    bezirke = []
    for index, name in enumerate(sorted(bezirk_names)):
        hours: list[float | None] = []
        points_parts = []
        for hour in range(24):
            value = hour_means.get((name, hour))
            hours.append(value)
            if value is not None:
                x = axes.left + hour / 23 * (axes.right - axes.left)
                points_parts.append(f"{x:.1f},{axes.scale_y(value):.1f}")
        bezirke.append(
            BezirkSeries(
                index=index,
                color_index=(index % SERIES_COLOR_COUNT) + 1,
                name=name,
                points=" ".join(points_parts),
                hours=hours,
                dasharray=cycle_dasharray(index),
            )
        )

    # The Bezirk with the lowest plotted value at 8:00.
    at_8 = [(s_.hours[BEZIRK_HEADLINE_HOUR], s_.name) for s_ in bezirke if s_.hours[BEZIRK_HEADLINE_HOUR] is not None]
    headline = None
    if at_8:
        value, name = min(at_8)
        headline = _make_headline(axes, value, BEZIRK_HEADLINE_HOUR, name, max(len(name), 20))

    return BezirkAvailabilityChart(
        status="ok",
        full_days=result.full_days,
        message=None,
        view_box=axes.view_box,
        bezirke=bezirke,
        axes=axes,
        headline=headline,
    )


@dataclass(frozen=True)
class FlowSeries:
    index: int
    color_index: int
    name: str
    points: str
    hours: list[float]
    dasharray: str = "none"


@dataclass(frozen=True)
class FlowChart:
    status: str
    full_days: int
    message: str | None
    view_box: str
    zero_y: float
    x_start: float
    x_end: float
    bezirke: list[FlowSeries] | None
    axes: Axes | None = None
    headline: Headline | None = None


def flow_chart(data_dir: str | Path) -> FlowChart:
    """Net bikes gained/lost per Bezirk by local hour, weekday mean per day.

    Uses :func:`net_flow_by_bezirk`'s ``day_type='weekday'`` rows, whose
    ``net`` value is already the mean per weekday date (the metric divides
    by the number of weekday dates in
    :func:`berlinbikes.analysis.coverage.full_days`). An (bezirk, hour) with
    no row (no attributable deltas) is drawn as 0, not left out of the
    polyline. Returns ``status="insufficient_data"`` with no ``bezirke``
    below the 14-full-day minimum, same as :func:`net_flow_by_bezirk` itself.
    """
    result = net_flow_by_bezirk(connect(data_dir))
    if result.status != "ok":
        return FlowChart(
            status=result.status,
            full_days=result.full_days,
            message=result.message,
            view_box=f"0 0 {VIEW_WIDTH} {VIEW_HEIGHT}",
            zero_y=0.0,
            x_start=0.0,
            x_end=0.0,
            bezirke=None,
        )

    net_by_key: dict[tuple[str, int], float] = {}
    bezirk_names: set[str] = set()
    for day_type, hour, bezirk, _gains, _losses, net in result.rows:
        if day_type != "weekday":
            continue
        bezirk_names.add(bezirk)
        net_by_key[(bezirk, hour)] = net

    all_values = list(net_by_key.values()) + [0.0]
    axes = build_axes(min(all_values), max(all_values))

    bezirke = []
    for index, name in enumerate(sorted(bezirk_names)):
        hours = [net_by_key.get((name, hour), 0.0) for hour in range(24)]
        points = " ".join(
            f"{axes.left + hour / 23 * (axes.right - axes.left):.1f},{axes.scale_y(value):.1f}"
            for hour, value in enumerate(hours)
        )
        bezirke.append(
            FlowSeries(
                index=index,
                color_index=(index % SERIES_COLOR_COUNT) + 1,
                name=name,
                points=points,
                hours=hours,
                dasharray=cycle_dasharray(index),
            )
        )

    # The largest net loss between 6:00 and 10:00; no headline if nothing is lost.
    lo_hour, hi_hour = HEADLINE_HOURS
    candidates = [
        (series.hours[h], h, series.name) for series in bezirke for h in range(lo_hour, hi_hour + 1)
    ]
    headline = None
    if candidates:
        loss, hour, name = min(candidates)
        if loss < 0:
            headline = _make_headline(axes, loss, hour, name, max(len(name), 24))

    return FlowChart(
        status="ok",
        full_days=result.full_days,
        message=None,
        view_box=axes.view_box,
        zero_y=axes.scale_y(0.0),
        x_start=axes.left,
        x_end=axes.right,
        bezirke=bezirke,
        axes=axes,
        headline=headline,
    )


#: How many stations the morning-shortage bar chart shows.
SHORTAGE_TOP_N = 10

_BAR_HEIGHT = 22
_BAR_GAP = 10
_BAR_PAD_LEFT = 172
_BAR_PAD_RIGHT = 96
_BAR_PAD_TOP = 14
_BAR_PAD_BOTTOM = 62
_BAR_MIN_VIEW_HEIGHT = 60

#: Longest station label (characters) that fits left of the bars at CHART_FONT_SIZE.
_BAR_LABEL_CHARS = 17

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
    label: str = ""
    label_x: float = 0.0
    is_top: bool = False


@dataclass(frozen=True)
class ShortageChart:
    status: str
    full_days: int
    message: str | None
    share_pct: float | None
    view_box: str
    aria_label: str
    bars: list[ShortageBar] | None
    font_size: float = CHART_FONT_SIZE
    left: float = 0.0
    right: float = 0.0
    top: float = 0.0
    bottom: float = 0.0
    x_ticks: list[Tick] | None = None
    x_title_x: float = 0.0
    x_title_y: float = 0.0
    headline: Headline | None = None


def _bar_view_height(n: int) -> float:
    n = max(n, 1)
    return _BAR_PAD_TOP + _BAR_PAD_BOTTOM + n * _BAR_HEIGHT + (n - 1) * _BAR_GAP


def _station_label(station_id: str, ortsteil: str) -> str:
    """``id (ortsteil)``, cut with an ellipsis to fit the label column; the table has the full text."""
    label = f"{station_id} ({ortsteil})"
    return label if len(label) <= _BAR_LABEL_CHARS else label[: _BAR_LABEL_CHARS - 1] + "…"


def shortage_chart(data_dir: str | Path) -> ShortageChart:
    """The G4 8:00 morning-shortage headline and its top-stations bar chart.

    Returns ``status="insufficient_data"`` with no ``bars`` below the
    14-full-day minimum, same as :func:`morning_shortage` itself. The
    headline share comes from each weekday's latest snapshot in local
    [07:50, 08:00]. When no weekday has one (for example after a collector
    outage over that window every day), ``morning_shortage`` reports
    ``share_empty_at_0800=None``; this is rendered as ``share_pct=None`` so
    the headline sentence is left out, while the bar chart and table still
    render.

    The value axis (empty minutes per day) is horizontal with round ticks and
    gridlines; the top station's value is the marked headline.
    """
    result = morning_shortage(connect(data_dir))
    de_label, en_label = _window_label(MORNING_WINDOW)
    if result.status != "ok":
        return ShortageChart(
            status=result.status,
            full_days=result.full_days,
            message=result.message,
            share_pct=None,
            view_box=f"0 0 {VIEW_WIDTH} {_BAR_MIN_VIEW_HEIGHT}",
            aria_label="",
            bars=None,
        )

    share = result.rows["share_empty_at_0800"]
    share_pct = round(share * 100, 1) if share is not None else None

    top_stations = result.rows["stations"][:SHORTAGE_TOP_N]
    values = [minutes_per_day for *_rest, minutes_per_day in top_stations]
    ticks = nice_ticks(0.0, max(values) if values else 1.0)
    x_max = ticks[-1]
    left, right = _BAR_PAD_LEFT, VIEW_WIDTH - _BAR_PAD_RIGHT
    plot_width = right - left
    view_height = _bar_view_height(len(top_stations))
    bottom = view_height - _BAR_PAD_BOTTOM
    top_index = values.index(max(values)) if values else -1

    bars = []
    headline = None
    for i, (station_id, _bezirk, ortsteil, _total, minutes_per_day) in enumerate(top_stations):
        bar_y = _BAR_PAD_TOP + i * (_BAR_HEIGHT + _BAR_GAP)
        bar_width = minutes_per_day / x_max * plot_width
        text_y = bar_y + _BAR_HEIGHT / 2 + CHART_FONT_SIZE * 0.35
        if i == top_index:
            headline = Headline(
                x=left + bar_width,
                y=bar_y + _BAR_HEIGHT / 2,
                value=minutes_per_day,
                hour=0,
                anchor="start",
                label_x=left + bar_width + 10,
                label_y=text_y,
            )
        bars.append(
            ShortageBar(
                station_id=station_id,
                ortsteil=ortsteil,
                minutes_per_day=minutes_per_day,
                bar_x=left,
                bar_y=bar_y,
                bar_width=bar_width,
                bar_height=_BAR_HEIGHT,
                label_y=text_y,
                value_x=left + bar_width + 4,
                label=_station_label(station_id, ortsteil),
                label_x=left - 6,
                is_top=i == top_index,
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
        view_box=f"0 0 {VIEW_WIDTH} {view_height}",
        aria_label=aria_label,
        bars=bars,
        left=left,
        right=right,
        top=_BAR_PAD_TOP,
        bottom=bottom,
        x_ticks=[Tick(left + t / x_max * plot_width, _fmt_tick(t)) for t in ticks],
        x_title_x=VIEW_WIDTH / 2,
        x_title_y=view_height - 6,
        headline=headline,
    )


#: bilingual (de, en) label per weather_effect() bucket name.
_WEATHER_BUCKET_LABELS: dict[str, tuple[str, str]] = {
    "rainy": ("regnerisch", "rainy"),
    "dry": ("trocken", "dry"),
    "cold": ("kalt", "cold"),
    "warm": ("warm", "warm"),
}

#: (active_bucket, other_bucket) per weather_effect() kind, same order as weather_effect.
_WEATHER_KIND_BUCKETS: dict[str, tuple[str, str]] = {
    "rain": ("rainy", "dry"),
    "temperature": ("cold", "warm"),
}


#: Hour of the weather headline, where both buckets' values are marked.
WEATHER_HEADLINE_HOUR = 8

#: Longest headline label (characters) the weather charts reserve room for.
WEATHER_HEADLINE_CHARS = 32

#: stroke-dasharray of the active bucket (rainy/cold); the baseline stays solid.
WEATHER_ACTIVE_DASHARRAY = "7 4"


@dataclass(frozen=True)
class WeatherBucketSeries:
    bucket: str
    label_de: str
    label_en: str
    color_index: int
    points: str
    hours: list[float | None]
    dasharray: str = "none"
    label_x: float = 0.0
    label_y: float = 0.0


@dataclass(frozen=True)
class WeatherKindChart:
    kind: str
    view_box: str
    excluded_n_hours: int
    buckets: list[WeatherBucketSeries]
    missing_buckets: list[tuple[str, str]]
    axes: Axes | None = None
    #: Markers of the plotted 8:00 values, one per bucket that has one.
    headline_points: list[Headline] | None = None
    #: The point carrying the label text (the lowest marker), or None.
    headline: Headline | None = None
    #: (label_de, label_en, value_de, value_en) per marked bucket, values at WEATHER_HEADLINE_HOUR
    #: formatted to one decimal (decimal comma in de).
    headline_values: list[tuple[str, str, str, str]] | None = None


@dataclass(frozen=True)
class WeatherEffectChart:
    status: str
    full_days: int
    message: str | None
    rain: WeatherKindChart | None
    temperature: WeatherKindChart | None


def _weather_values(rows) -> tuple[dict[str, dict[int, float]], int]:
    by_bucket: dict[str, dict[int, float]] = {}
    excluded_n_hours = 0
    for bucket, local_hour, _mean, share, _n_snapshots, n_hours in rows:
        if bucket == "excluded":
            excluded_n_hours = n_hours
            continue
        by_bucket.setdefault(bucket, {})[local_hour] = share * 100
    return by_bucket, excluded_n_hours


def text_box(x: float, y: float, chars: int, anchor: str) -> tuple[float, float, float, float]:
    """Estimated (left, top, right, bottom) of one text line with baseline ``y``."""
    width = chars * HEADLINE_CHAR_WIDTH * CHART_FONT_SIZE
    left = {"start": x, "end": x - width, "middle": x - width / 2}[anchor]
    return left, y - CHART_FONT_SIZE, left + width, y


def boxes_intersect(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _clear_of_series_labels(headline: Headline, points: list[Headline], buckets: list[WeatherBucketSeries]) -> Headline:
    """Move the headline label above the highest 8:00 marker when a series label would overprint it."""
    series_boxes = [text_box(b.label_x, b.label_y, len(b.label_de), "end") for b in buckets]
    series_boxes += [text_box(b.label_x, b.label_y, len(b.label_en), "end") for b in buckets]

    def hit(h: Headline) -> bool:
        box = text_box(h.label_x, h.label_y, WEATHER_HEADLINE_CHARS, h.anchor)
        return any(boxes_intersect(box, other) for other in series_boxes)

    if not hit(headline):
        return headline
    above = replace(headline, label_y=min(p.y for p in points) - 12)
    return above if not hit(above) else headline


def _weather_kind_chart(kind: str, by_bucket: dict[str, dict[int, float]], excluded_n_hours: int, axes: Axes) -> WeatherKindChart:
    active_bucket, other_bucket = _WEATHER_KIND_BUCKETS[kind]

    def x_of(hour: int) -> float:
        return axes.left + hour / 23 * (axes.right - axes.left)

    buckets: list[WeatherBucketSeries] = []
    missing_buckets: list[tuple[str, str]] = []
    for index, bucket in enumerate((active_bucket, other_bucket)):
        values = by_bucket.get(bucket, {})
        label_de, label_en = _WEATHER_BUCKET_LABELS[bucket]
        if not values:
            missing_buckets.append((label_de, label_en))
            continue
        hours: list[float | None] = []
        points_parts = []
        for hour in range(24):
            value = values.get(hour)
            hours.append(value)
            if value is not None:
                points_parts.append(f"{x_of(hour):.1f},{axes.scale_y(value):.1f}")
        buckets.append(
            WeatherBucketSeries(
                bucket=bucket,
                label_de=label_de,
                label_en=label_en,
                color_index=index + 1,
                points=" ".join(points_parts),
                hours=hours,
                dasharray=WEATHER_ACTIVE_DASHARRAY if bucket == active_bucket else "none",
            )
        )

    # Direct labels at each line's own last plotted point (anchored "end", so they stay inside the plot):
    # the higher end sits above its line, the lower below; ties put the active bucket above.
    ends = []
    for series in buckets:
        last = max(h for h, v in enumerate(series.hours) if v is not None)
        ends.append((axes.scale_y(series.hours[last]), last, series))
    labelled = []
    for y, last, series in ends:
        others = [oy for oy, _l, s in ends if s is not series]
        if series.bucket == active_bucket:
            above = all(y <= oy for oy in others)
        else:
            above = all(y < oy for oy in others)
        label_y = y - 8 if above else y + CHART_FONT_SIZE + 2
        label_y = max(axes.top + CHART_FONT_SIZE * 0.8, min(label_y, axes.bottom - 4))
        labelled.append(replace(series, label_x=x_of(last), label_y=label_y))
    # Clamping to the plot box can push the two labels together; keep them a line apart,
    # moving the lower one down and only moving the upper one up when the plot bottom is in the way.
    if len(labelled) == 2:
        top, bottom = sorted(labelled, key=lambda s: (s.label_y, s.bucket != active_bucket))
        if bottom.label_y - top.label_y < CHART_FONT_SIZE:
            bottom_y = min(top.label_y + CHART_FONT_SIZE, axes.bottom - 4)
            top_y = min(top.label_y, bottom_y - CHART_FONT_SIZE)
            labelled = [
                replace(s, label_y=top_y) if s is top else replace(s, label_y=bottom_y) for s in labelled
            ]
    buckets = [next(s for s in labelled if s.bucket == b.bucket) for b in buckets]

    # 8:00 markers from the plotted values only; the label sits at the lowest one.
    at_8 = [
        (series.hours[WEATHER_HEADLINE_HOUR], series)
        for series in buckets
        if series.hours[WEATHER_HEADLINE_HOUR] is not None
    ]
    headline_points = [
        _make_headline(axes, value, WEATHER_HEADLINE_HOUR, chars=WEATHER_HEADLINE_CHARS) for value, _s in at_8
    ]
    headline = min(headline_points, key=lambda p: p.value) if headline_points else None
    if headline is not None:
        moved = _clear_of_series_labels(headline, headline_points, buckets)
        headline_points = [moved if p is headline else p for p in headline_points]
        headline = moved

    return WeatherKindChart(
        kind=kind,
        view_box=axes.view_box,
        excluded_n_hours=excluded_n_hours,
        buckets=buckets,
        missing_buckets=missing_buckets,
        axes=axes,
        headline_points=headline_points,
        headline=headline,
        headline_values=[
            (series.label_de, series.label_en, f"{value:.1f}".replace(".", ","), f"{value:.1f}") for value, series in at_8
        ],
    )


def weather_effect_chart(data_dir: str | Path) -> WeatherEffectChart:
    """Availability on rainy/dry and cold/warm hours, by local hour.

    Returns ``status="insufficient_data"`` with no ``rain``/``temperature``
    below the 14-full-day minimum, same as :func:`weather_effect` itself
    (``kind="rain"`` and ``kind="temperature"`` share one day-count guard,
    so their status and full_days always agree). When enough data exists,
    each of ``rain``/``temperature`` carries its own two-bucket chart; a
    bucket with no rows (for example no rainy hours yet, as when no weather
    has been collected) is reported in that chart's ``missing_buckets``
    instead of being drawn.
    """
    con = connect(data_dir)
    rain_result = weather_effect(con, "rain")

    if rain_result.status != "ok":
        return WeatherEffectChart(
            status=rain_result.status,
            full_days=rain_result.full_days,
            message=rain_result.message,
            rain=None,
            temperature=None,
        )

    temperature_result = weather_effect(con, "temperature")

    # One y scale for both small multiples so they can be compared.
    rain_values, rain_excluded = _weather_values(rain_result.rows)
    temp_values, temp_excluded = _weather_values(temperature_result.rows)
    all_values = [0.0] + [v for by in (rain_values, temp_values) for vs in by.values() for v in vs.values()]
    axes = build_axes(min(all_values), max(all_values))

    return WeatherEffectChart(
        status="ok",
        full_days=rain_result.full_days,
        message=None,
        rain=_weather_kind_chart("rain", rain_values, rain_excluded, axes),
        temperature=_weather_kind_chart("temperature", temp_values, temp_excluded, axes),
    )


_FOOT_BAR_GAP = 1

#: Room right of the stacks for the direct segment labels (swatch + name).
_FOOT_LABEL_MARGIN = 104

#: Minimum horizontal distance between date tick labels, in viewBox units.
_FOOT_TICK_SPACING = 64

#: Headroom above the tallest stack, as a factor, so the headline row stays clear of the bars.
_FOOT_HEADROOM = 1.15

#: Vertical distance between direct segment labels, in em.
_FOOT_LABEL_LINE = 1.25


@dataclass(frozen=True)
class FootprintBar:
    date: str
    n_stations: int
    bikes_at_stations: float
    bikes_free_floating: float
    ebikes: float
    pedal_bikes: float
    unknown_type: float
    bar_x: float
    bar_width: float
    ebike_y: float
    ebike_height: float
    pedal_y: float
    pedal_height: float
    unknown_y: float
    unknown_height: float


@dataclass(frozen=True)
class SegmentLabel:
    """A direct label next to the last bar: ``key`` is ebike/pedal/unknown."""

    key: str
    x: float
    y: float


@dataclass(frozen=True)
class FootprintChart:
    status: str
    full_days: int
    message: str | None
    view_box: str
    latest_date: str | None
    latest_n_stations: int | None
    latest_bikes_total: float | None
    bars: list[FootprintBar] | None
    axes: Axes | None = None
    headline: Headline | None = None
    segment_labels: list[SegmentLabel] | None = None


def _segment_labels(axes: Axes, last: FootprintBar) -> list[SegmentLabel]:
    """Labels at the segments' mid-heights, pushed apart so no two overlap and kept inside the plot."""
    gap = CHART_FONT_SIZE * _FOOT_LABEL_LINE
    mids = [
        last.ebike_y + last.ebike_height / 2,
        last.pedal_y + last.pedal_height / 2,
        last.unknown_y + last.unknown_height / 2,
    ]
    ys = [m + CHART_FONT_SIZE * 0.35 for m in mids]  # baselines, bottom stack first
    for i in range(1, 3):
        ys[i] = min(ys[i], ys[i - 1] - gap)
    ys[2] = max(ys[2], axes.top + CHART_FONT_SIZE)
    for i in (1, 0):
        ys[i] = max(ys[i], ys[i + 1] + gap)
    x = last.bar_x + last.bar_width + 6
    return [SegmentLabel(key, x, y) for key, y in zip(("ebike", "pedal", "unknown"), ys, strict=True)]


def footprint_chart(data_dir: str | Path) -> FootprintChart:
    """The G3 daily-footprint headline and its stacked-bar-per-day chart.

    Returns ``status="insufficient_data"`` with no ``bars`` below the
    14-full-day minimum, same as :func:`daily_footprint` itself. Each bar
    stacks ``mean_ebikes`` (bottom, ``--series-1``), ``mean_pedal_bikes``
    (middle, ``--series-2``) and ``mean_unknown_type`` (top, ``--series-3``)
    for one full local day; the headline uses the latest full day's
    ``n_stations`` and that same three-way total.
    """
    result = daily_footprint(connect(data_dir))
    if result.status != "ok":
        return FootprintChart(
            status=result.status,
            full_days=result.full_days,
            message=result.message,
            view_box=f"0 0 {VIEW_WIDTH} {_AXES_VIEW_HEIGHT}",
            latest_date=None,
            latest_n_stations=None,
            latest_bikes_total=None,
            bars=None,
        )

    rows = result.rows
    totals = [ebikes + pedal_bikes + unknown for *_rest, ebikes, pedal_bikes, unknown in rows]
    y_top = (max(totals) if totals else 1.0) or 1.0
    base_axes = build_axes(0.0, y_top * _FOOT_HEADROOM)
    right = VIEW_WIDTH - _FOOT_LABEL_MARGIN
    n = len(rows)
    plot_width = right - base_axes.left
    bar_width = (plot_width - (n - 1) * _FOOT_BAR_GAP) / n if n else 0.0
    pitch = bar_width + _FOOT_BAR_GAP
    step = max(1, math.ceil(_FOOT_TICK_SPACING / pitch)) if pitch else 1
    dates = [row[0] for row in rows]
    # Ticks count back from the latest day; one whose label would reach the y tick labels is dropped.
    half_label = 5 * HEADLINE_CHAR_WIDTH * CHART_FONT_SIZE / 2
    x_ticks = [
        Tick(base_axes.left + i * pitch + bar_width / 2, dates[i].strftime("%m-%d"))
        for i in range(n - 1, -1, -step)[::-1]
        if base_axes.left + i * pitch + bar_width / 2 - half_label >= base_axes.left
    ]
    axes = replace(base_axes, right=right, x_ticks=x_ticks, x_title_x=(base_axes.left + right) / 2)

    bars = []
    for i, (local_date, n_stations, bikes_at_stations, bikes_free_floating, ebikes, pedal_bikes, unknown) in enumerate(
        rows
    ):
        ebike_y = axes.scale_y(ebikes)
        pedal_y = axes.scale_y(ebikes + pedal_bikes)
        unknown_y = axes.scale_y(ebikes + pedal_bikes + unknown)
        bars.append(
            FootprintBar(
                date=local_date.isoformat(),
                n_stations=n_stations,
                bikes_at_stations=bikes_at_stations,
                bikes_free_floating=bikes_free_floating,
                ebikes=ebikes,
                pedal_bikes=pedal_bikes,
                unknown_type=unknown,
                bar_x=axes.left + i * pitch,
                bar_width=bar_width,
                ebike_y=ebike_y,
                ebike_height=axes.bottom - ebike_y,
                pedal_y=pedal_y,
                pedal_height=ebike_y - pedal_y,
                unknown_y=unknown_y,
                unknown_height=pedal_y - unknown_y,
            )
        )

    latest = bars[-1]
    latest_total = latest.ebikes + latest.pedal_bikes + latest.unknown_type
    latest_x = latest.bar_x + latest.bar_width / 2
    headline = Headline(
        x=latest_x,
        y=axes.scale_y(latest_total),
        value=latest_total,
        hour=0,
        anchor="end",
        label_x=axes.right,
        label_y=axes.top + CHART_FONT_SIZE,
    )
    return FootprintChart(
        status="ok",
        full_days=result.full_days,
        message=None,
        view_box=axes.view_box,
        latest_date=latest.date,
        latest_n_stations=latest.n_stations,
        latest_bikes_total=latest_total,
        bars=bars,
        axes=axes,
        headline=headline,
        segment_labels=_segment_labels(axes, latest),
    )


#: Hour marked on the map page's profile curve (the visitor's "8:00" question).
MAP_DEFAULT_HOUR = 8
#: Weekday (Monday = 0) the map page shows before the visitor picks one.
MAP_DEFAULT_WEEKDAY = 0
#: Display bins of the mean bikes at the picked weekday and hour: (lower bound, marker radius).
#: A bin holds every mean >= its bound and below the next one. The bound 0.05 keeps a mean that
#: rounds to 0 in the first bin. The map legend and map.js both read this list.
MAP_BINS = ((0.0, 4), (0.05, 5), (1.0, 7), (3.0, 9))
#: Marker radius for a station without a value at that hour.
MAP_NO_DATA_RADIUS = 4


@dataclass(frozen=True)
class MapProfileChart:
    """One station's or Ortsteil's curve for one weekday, drawn with the shared axes."""

    view_box: str
    axes: Axes
    points: str
    hours: list[float | None]
    headline: Headline | None


def map_profile_chart(
    curve: list[list[float | None]], weekday: int = MAP_DEFAULT_WEEKDAY, hour: int = MAP_DEFAULT_HOUR
) -> MapProfileChart:
    """The map page's server-rendered curve: ``curve`` is 7 weekday lists of 24 hourly means (or None)."""
    hours = list(curve[weekday])
    present = [v for v in hours if v is not None]
    axes = build_axes(0, max([1.0, *present]))
    points = " ".join(
        f"{axes.left + h / 23 * (axes.right - axes.left):.1f},{axes.scale_y(v):.1f}"
        for h, v in enumerate(hours)
        if v is not None
    )
    value = hours[hour]
    headline = _make_headline(axes, value, hour) if value is not None else None
    return MapProfileChart(view_box=axes.view_box, axes=axes, points=points, hours=hours, headline=headline)
