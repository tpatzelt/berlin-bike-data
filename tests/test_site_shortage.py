"""Tests for the G4 article's 8:00 morning-shortage section (charts.shortage_chart).

``morning_shortage()``'s ``share_empty_at_0800`` comes from each weekday's
latest snapshot in local [07:50, 08:00] (T-0059) and is ``None`` when no
weekday has one. ``shortage_chart()`` once computed ``round(None * 100, 1)``
in that case and crashed the whole nightly ``build_site()``; it must drop
the headline sentence instead while still rendering the bar chart and
table.
"""

from __future__ import annotations

from berlinbikes.analysis import MetricResult
from berlinbikes.analysis.db import connect
from berlinbikes.analysis.empty import morning_shortage
from berlinbikes.site import build_site
from berlinbikes.site import charts as charts_module
from tests.synthetic import EMPTY_STATION_ID, EMPTY_STATION_ORTSTEIL
from tests.test_site_article import _ancestors, _find_all, _parse, _preorder, _text


def _shortage_table(root):
    for table in _find_all(root, "table"):
        headers = [_text(th).strip() for th in _find_all(table, "th")]
        if "Ortsteil" in headers:
            return table
    raise AssertionError("no shortage table (an 'Ortsteil' column) found on the page")


def test_first_shortage_row_and_headline_percentage(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)
    html = (site_dir / "index.html").read_text()

    result = morning_shortage(connect(synthetic_data_dir))
    assert result.status == "ok"
    share = result.rows["share_empty_at_0800"]
    assert share is not None, "synthetic snapshots land on the exact 08:00 grid"
    expected_pct = f"{round(share * 100, 1):.1f}"
    assert expected_pct in html

    root = _parse(html)
    table = _shortage_table(root)
    body_rows = _find_all(_find_all(table, "tbody")[0], "tr")
    assert body_rows, "expected at least one ranked station row"
    first_cells = _find_all(body_rows[0], "th") + _find_all(body_rows[0], "td")
    assert _text(first_cells[0]).strip() == EMPTY_STATION_ID
    assert _text(first_cells[1]).strip() == EMPTY_STATION_ORTSTEIL


def test_shortage_svg_is_in_a_captioned_figure_followed_by_the_table(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)

    root = _parse((site_dir / "index.html").read_text())
    order: list = []
    _preorder(root, order)

    bar_svgs = [svg for svg in _find_all(root, "svg") if "bars" in (svg.attrs.get("class") or "").split()]
    assert len(bar_svgs) == 1
    svg = bar_svgs[0]
    assert svg.attrs.get("role") == "img"
    assert svg.attrs.get("aria-label")

    figure_ancestors = [a for a in _ancestors(svg) if a.tag == "figure"]
    assert figure_ancestors, "shortage svg must be inside a <figure>"
    figure = figure_ancestors[0]
    assert _find_all(figure, "figcaption"), "<figure> must have a <figcaption>"

    subtree: list = []
    _preorder(figure, subtree)
    fig_start = order.index(figure)
    fig_end = fig_start + len(subtree) - 1

    following_tables = [t for t in _find_all(root, "table") if order.index(t) > fig_end]
    assert following_tables, "a <table> fallback must follow the shortage chart's <figure>"


def test_empty_data_dir_shows_not_enough_data_and_no_shortage_chart(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)

    html = (site_dir / "index.html").read_text()
    lowered = html.lower()
    assert "noch nicht genug daten" in lowered
    assert "not enough data yet" not in lowered
    en_lowered = (site_dir / "index.en.html").read_text().lower()
    assert "not enough data yet" in en_lowered
    assert "noch nicht genug daten" not in en_lowered
    assert "0/14" in html or "0 / 14" in html

    root = _parse(html)
    bar_svgs = [svg for svg in _find_all(root, "svg") if "bars" in (svg.attrs.get("class") or "").split()]
    assert not bar_svgs, "no shortage bar chart should render below the 14-full-day minimum"


def test_build_site_survives_a_null_share_at_0800(monkeypatch, synthetic_data_dir, tmp_path):
    """Required fix: share_empty_at_0800=None must not crash build_site()."""
    fabricated_rows = {
        "stations": [
            ("S-X", "BZ-A", "OT-A1", 100.0, 10.0),
            ("S-Y", "BZ-B", "OT-B1", 50.0, 5.0),
        ],
        "ortsteile": [("OT-A1", "BZ-A", 100.0, 10.0)],
        "share_empty_at_0800": None,
    }

    def _fake_morning_shortage(con):
        return MetricResult(
            name="morning_shortage", full_days=17, status="ok", message=None, rows=fabricated_rows
        )

    monkeypatch.setattr(charts_module, "morning_shortage", _fake_morning_shortage)

    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)
    html = (site_dir / "index.html").read_text()

    assert "durchschnittlich" not in html, "no headline sentence should render when the share is None"
    assert "an average of" not in html
    assert "S-X" in html, "the bar chart/table must still render"
    assert "17" in html, "'based on N full days' must still show"


def test_shortage_aria_label_keeps_the_weekday_range_in_both_languages(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)
    for name, expected in (("index.html", "Mo-Fr 7:30-8:30"), ("index.en.html", "Mon-Fri 7:30-8:30")):
        root = _parse((site_dir / name).read_text())
        bar_svgs = [s for s in _find_all(root, "svg") if "bars" in (s.attrs.get("class") or "").split()]
        assert len(bar_svgs) == 1
        assert expected in bar_svgs[0].attrs["aria-label"]


def _bars_svg(html):
    from tests.helpers.svg import chart_by_class

    els = chart_by_class(html, "bars")
    assert els
    return els


def test_shortage_axes_ticks_gridlines_titles_and_headline(synthetic_data_dir, tmp_path):
    from berlinbikes.site.charts import shortage_chart

    build_site(synthetic_data_dir, tmp_path / "site")
    chart = shortage_chart(synthetic_data_dir)
    top = max(b.minutes_per_day for b in chart.bars)
    for name, title, unit in (
        ("index.html", "Leere Minuten pro Tag (Mo–Fr 7:30–8:30)", "Min."),
        ("index.en.html", "Empty minutes per day (Mon–Fri 7:30–8:30)", "min"),
    ):
        els = _bars_svg((tmp_path / "site" / name).read_text())
        ticks = [e for e in els if e["tag"] == "text" and "tick" in e["classes"] and "axis-x" in e["groups"]]
        assert len(ticks) >= 3 and all(t["text"].strip() for t in ticks)
        assert float(ticks[-1]["text"]) >= top
        assert [e for e in els if e["tag"] == "line" and "grid" in e["classes"]]
        titles = [e for e in els if "axis-title-x" in e["classes"]]
        assert [t["text"] for t in titles] == [title]
        cats = [e["text"] for e in els if "tick" in e["classes"] and "axis-y" in e["groups"]]
        assert len(cats) == len(chart.bars) and EMPTY_STATION_ID in cats[0]
        head = [e for e in els if e["tag"] == "text" and "headline" in e["groups"]]
        assert [h["text"] for h in head] == [f"{top:.1f} {unit}"]
        assert any(e["tag"] == "circle" and "headline" in e["groups"] for e in els)


def test_shortage_text_is_legible_and_never_overlaps(synthetic_data_dir, tmp_path):
    from berlinbikes.site.charts import CHART_FONT_SIZE, HEADLINE_CHAR_WIDTH, shortage_chart
    from tests.helpers.svg import assert_no_overlaps_and_inside, svg_font_size

    build_site(synthetic_data_dir, tmp_path / "site")
    html = (tmp_path / "site" / "index.html").read_text()
    css_path = tmp_path / "site" / "site.css"
    assert css_path.exists()
    css = css_path.read_text()
    assert "font-size" in css
    assert 'font-size="10px"' not in html and "font-size: 10px" not in css
    chart = shortage_chart(synthetic_data_dir)
    width, height = (float(v) for v in chart.view_box.split()[2:])
    assert CHART_FONT_SIZE * 328 / width >= 11
    els = _bars_svg(html)
    assert svg_font_size(html, "bars") == CHART_FONT_SIZE
    from tests.helpers.svg import text_boxes

    assert_no_overlaps_and_inside(text_boxes(els, CHART_FONT_SIZE, HEADLINE_CHAR_WIDTH), width, height)


def test_build_site_survives_an_ok_result_with_no_stations(monkeypatch, synthetic_data_dir, tmp_path):
    def _fake(con):
        return MetricResult(
            name="morning_shortage",
            full_days=17,
            status="ok",
            message=None,
            rows={"stations": [], "ortsteile": [], "share_empty_at_0800": None},
        )

    monkeypatch.setattr(charts_module, "morning_shortage", _fake)
    build_site(synthetic_data_dir, tmp_path / "site")
    assert "headline" not in " ".join(
        " ".join(e["classes"] + e["groups"]) for e in _bars_svg((tmp_path / "site" / "index.html").read_text())
    )
