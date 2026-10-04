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
    assert "not enough data yet" in lowered
    assert "noch nicht genug daten" in lowered
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
