"""Axes, gridlines, titles, dashes and the 8:00 headline of the availability chart."""

from __future__ import annotations

import re
from datetime import date

import pytest

from berlinbikes.analysis.availability import availability_by_hour
from berlinbikes.analysis.db import connect
from berlinbikes.site import build_site
from berlinbikes.site import charts
from berlinbikes.site.charts import CHART_FONT_SIZE, VIEW_WIDTH, WEEKDAY_NAMES, nice_ticks
from tests.helpers.svg import (
    assert_axes_conventions,
    assert_distinct_dasharrays,
    chart_count,
    chart_elements,
    main_html,
    polyline_dasharrays,
    root_font_size,
)
from tests.synthetic import build_dataset


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("charts")
    data_dir = root / "data"
    build_dataset(data_dir, start_date=date(2026, 1, 5), days=28)
    build_site(data_dir, root / "site")
    return data_dir, root / "site"


def test_nice_ticks_use_round_steps_and_cover_range():
    ticks = nice_ticks(3.2, 97.0)
    assert ticks[0] <= 3.2 and ticks[-1] >= 97.0
    steps = {round(b - a, 9) for a, b in zip(ticks, ticks[1:])}
    assert len(steps) == 1
    step = steps.pop()
    assert step in (1, 2, 5, 10, 20, 50, 100)
    assert nice_ticks(5, 5)[0] <= 5 <= nice_ticks(5, 5)[-1]
    assert nice_ticks(0, 0.7)[-1] >= 0.7


def test_font_size_is_legible_at_360px_viewport():
    assert CHART_FONT_SIZE * 328 / VIEW_WIDTH >= 11


@pytest.mark.parametrize("name", ["index.html", "index.en.html"])
def test_availability_chart_axes_conventions(site, name):
    _data, site_dir = site
    html = (site_dir / name).read_text()
    els = assert_axes_conventions(html)
    assert_distinct_dasharrays(els, 7)
    assert root_font_size(html) == CHART_FONT_SIZE
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", "".join(str(e["attrs"]) for e in els))


def test_axis_titles_are_in_one_language(site):
    _data, site_dir = site
    de = [e["text"] for e in chart_elements((site_dir / "index.html").read_text()) if "axis-title" in e["classes"]]
    en = [e["text"] for e in chart_elements((site_dir / "index.en.html").read_text()) if "axis-title" in e["classes"]]
    assert de == ["Uhrzeit (Uhr, Europe/Berlin)", "Verfügbare Räder (Anzahl)"]
    assert en == ["Local hour (h, Europe/Berlin)", "Bikes available (count)"]


def test_legend_is_inside_figure_with_dashed_swatches(site):
    _data, site_dir = site
    html = (site_dir / "index.html").read_text()
    figure = html[html.index("<figure>") : html.index("</figure>")]
    legend = figure[figure.index('class="chart-legend"') :]
    assert legend.count("swatch-line") == 7
    assert len(set(re.findall(r'stroke-dasharray="([^"]+)"', legend))) == 7


def test_headline_marks_lowest_weekday_value_between_6_and_10(site):
    data_dir, site_dir = site
    result = availability_by_hour(connect(data_dir), by="city")
    candidates = {(wd, h): m for wd, h, m, _n in result.rows if wd <= 4 and 6 <= h <= 10}
    (_wd, hour), value = min(candidates.items(), key=lambda kv: kv[1])

    chart = charts.availability_chart(data_dir)
    assert chart.headline.hour == hour
    assert chart.headline.value == pytest.approx(value)

    de = [e for e in chart_elements((site_dir / "index.html").read_text()) if "headline" in e["groups"] and e["tag"] == "text"]
    en = [e for e in chart_elements((site_dir / "index.en.html").read_text()) if "headline" in e["groups"] and e["tag"] == "text"]
    assert de[0]["text"] == f"{value:.0f} Räder um {hour}:00"
    assert en[0]["text"] == f"{value:.0f} bikes at {hour}:00"


def test_all_ticks_and_labels_fit_inside_viewbox(site):
    data_dir, _ = site
    chart = charts.availability_chart(data_dir)
    axes = chart.axes
    height = float(axes.view_box.split()[3])
    assert all(0 <= t.pos <= VIEW_WIDTH for t in axes.x_ticks)
    assert all(axes.top <= t.pos <= axes.bottom for t in axes.y_ticks)
    assert axes.y_min <= min(min(w.hours) for w in chart.weekdays)
    assert axes.y_max >= max(max(w.hours) for w in chart.weekdays)
    assert axes.x_title_y <= height and axes.y_title_x - CHART_FONT_SIZE / 2 >= 0


def test_headline_label_sits_inside_plot_box(site):
    data_dir, _ = site
    chart = charts.availability_chart(data_dir)
    assert chart.axes.top < chart.headline.label_y < chart.axes.bottom


_UNIT_TOKENS = ("%", "Uhr", "Räder", "Anzahl", "Minuten", "Tag", "Bikes", "bikes", "count", "minutes", "day", "o'clock", "(h,")
_PAGES = ["index.html", "index.en.html"]


@pytest.mark.parametrize("name", _PAGES)
def test_every_server_rendered_chart_meets_the_g2_conventions(site, name):
    """G2 sweep: axes, unit titles, headline, weekday dashes/direct labels and a table fallback."""
    html = (site[1] / name).read_text()
    main = main_html(html)
    n = chart_count(main)
    assert n >= 5, f"expected the availability, shortage, bezirk, flow and footprint charts, got {n}"
    for i in range(1, n + 1):
        els = chart_elements(main, i)
        svg = els[0]
        assert svg["tag"] == "svg" and "chart" in svg["classes"]
        label = f"{name} chart #{i} {svg['attrs'].get('aria-label')}"
        for axis in ("axis-x", "axis-y"):
            ticks = [e for e in els if e["tag"] == "text" and "tick" in e["classes"] and axis in e["groups"]]
            assert ticks and all(e["text"].strip() for e in ticks), f"{label}: no tick labels on {axis}"
        x_titles = [e["text"] for e in els if "axis-title-x" in e["classes"]]
        y_titles = [e["text"] for e in els if "axis-title-y" in e["classes"]]
        assert len(x_titles) == 1, label
        if "bars" in svg["classes"]:
            assert not y_titles, f"{label}: bar y axis is categorical"
        else:
            assert len(y_titles) == 1, label
        assert any(u in t for t in x_titles + y_titles for u in _UNIT_TOKENS), f"{label}: no unit in {x_titles + y_titles}"
        assert any(e["tag"] == "text" and "headline" in e["groups"] and e["text"].strip() for e in els), label
        lines = polyline_dasharrays(els)
        if len(lines) == len(WEEKDAY_NAMES):  # weekday series; Bezirk series differ by colour and legend
            direct = [e for e in els if e["tag"] == "text" and "series-label" in e["classes"]]
            assert len(set(lines)) == len(lines) or len(direct) >= len(lines), f"{label}: series are not distinguishable"

    # Every chart figure is followed directly by its <details> table fallback.
    figures = re.findall(r"</figure>\s*(<\w+)", main)
    assert len(figures) == n, (len(figures), n)
    assert all(tag == "<details" for tag in figures), figures
    assert main.count("<details") >= n
