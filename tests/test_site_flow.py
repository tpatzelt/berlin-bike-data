"""Tests for the G4 article's net-flow-between-Bezirke section (charts.flow_chart).

Net flow between Bezirke by local hour (weekday mean per day), following the
same plain-SVG-plus-table-fallback pattern as the per-Bezirk availability
chart tested in ``tests/test_site_bezirk.py``. ``net_flow_by_bezirk``'s
``day_type='weekday'`` rows already carry the mean per weekday date (it
divides by the number of weekday dates in ``full_days(con)`` internally), so
the expected table values are the metric's own ``net`` values, with an
(bezirk, hour) that has no row filled in as 0 rather than left blank --
mirroring the "BZ-C cancels to zero at 7/8" and "BZ-A negative in the morning,
positive in the evening" scripted shape from ``tests/synthetic.py``.
"""

from __future__ import annotations

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.flow import net_flow_by_bezirk
from berlinbikes.site import build_site
from tests.synthetic import BEZIRKE, EMPTY_STATION_BEZIRK, FLOW_STATION_A_BEZIRK
from tests.test_site_article import _ancestors, _find_all, _parse, _preorder, _text


def _flow_article(root):
    for article in _find_all(root, "article"):
        headings = [_text(h2) for h2 in _find_all(article, "h2")]
        if any("Net flow between Bezirke" in h or "Netto-Fluss zwischen Bezirken" in h for h in headings):
            return article
    raise AssertionError("no article with a 'Net flow between Bezirke' heading found")


def _flow_table(root):
    for table in _find_all(root, "table"):
        captions = _find_all(table, "caption")
        if captions and "Bezirk" in _text(captions[0]) and "gained" in _text(captions[0]).lower():
            return table
    raise AssertionError("no table with a Bezirk/gained-lost caption found")


def _expected_weekday_net_by_hour(con) -> dict[tuple[str, int], float]:
    result = net_flow_by_bezirk(con)
    assert result.status == "ok"
    return {
        (bezirk, hour): net
        for day_type, hour, bezirk, _gains, _losses, net in result.rows
        if day_type == "weekday"
    }


def test_flow_table_matches_metric_and_svg_precedes_it(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)
    html = (site_dir / "index.html").read_text()

    expected = _expected_weekday_net_by_hour(connect(synthetic_data_dir))

    root = _parse(html)
    order: list = []
    _preorder(root, order)

    article = _flow_article(root)

    table = _flow_table(root)
    body_rows = _find_all(_find_all(table, "tbody")[0], "tr")
    assert len(body_rows) == len(BEZIRKE)

    expected_names = sorted(BEZIRKE)
    for name, row in zip(expected_names, body_rows):
        row_header = _find_all(row, "th")
        assert row_header, "expected a row header naming the Bezirk"
        assert _text(row_header[0]).strip() == name

        cells = _find_all(row, "td")
        assert len(cells) == 24

        for hour, cell in enumerate(cells):
            value = expected.get((name, hour), 0.0)
            assert _text(cell).strip() == f"{value:.1f}", (name, hour)

    svgs = [svg for svg in _find_all(article, "svg") if "chart" in (svg.attrs.get("class") or "").split()]
    assert len(svgs) == 1
    svg = svgs[0]
    assert svg.attrs.get("role") == "img"
    assert svg.attrs.get("aria-label")

    polylines = _find_all(svg, "polyline")
    assert len(polylines) == len(BEZIRKE)

    lines = _find_all(svg, "line")
    assert lines, "expected a visible zero baseline"

    figure_ancestors = [a for a in _ancestors(svg) if a.tag == "figure"]
    assert figure_ancestors, "flow svg must be inside a <figure>"
    figure = figure_ancestors[0]
    assert _find_all(figure, "figcaption"), "<figure> must have a <figcaption>"

    subtree: list = []
    _preorder(figure, subtree)
    fig_start = order.index(figure)
    fig_end = fig_start + len(subtree) - 1

    assert order.index(table) > fig_end, "the table fallback must follow the chart's <figure>"


def test_bz_c_cancels_to_zero_and_bz_a_reverses_morning_evening(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)
    html = (site_dir / "index.html").read_text()

    expected = _expected_weekday_net_by_hour(connect(synthetic_data_dir))

    root = _parse(html)
    table = _flow_table(root)
    body_rows = _find_all(_find_all(table, "tbody")[0], "tr")
    rows_by_name = {}
    for row in body_rows:
        name = _text(_find_all(row, "th")[0]).strip()
        rows_by_name[name] = [_text(cell).strip() for cell in _find_all(row, "td")]

    bz_c_cells = rows_by_name[EMPTY_STATION_BEZIRK]
    for hour in range(24):
        assert bz_c_cells[hour] == f"{expected.get((EMPTY_STATION_BEZIRK, hour), 0.0):.1f}"
    assert bz_c_cells[7] == "0.0"
    assert bz_c_cells[8] == "0.0"

    bz_a_cells = rows_by_name[FLOW_STATION_A_BEZIRK]
    assert any(float(bz_a_cells[h]) < 0 for h in (7, 8))
    assert any(float(bz_a_cells[h]) > 0 for h in (17, 18))


def test_empty_data_dir_shows_not_enough_data_and_no_flow_chart(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)

    root = _parse((site_dir / "index.html").read_text())
    article = _flow_article(root)

    not_enough = [p for p in _find_all(article, "p") if p.attrs.get("class") == "not-enough-data"]
    assert len(not_enough) == 1
    assert "0/14" in _text(not_enough[0]) or "0 / 14" in _text(not_enough[0])

    assert not _find_all(article, "svg"), "no flow chart should render below the 14-full-day minimum"
