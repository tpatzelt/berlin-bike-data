"""Tests for the G4 article's per-Bezirk availability section (charts.bezirk_availability_chart).

Rework of parked T-0061: the article shows bikes-available-by-hour not just
citywide but per Bezirk (Mon-Fri mean), as a plain-SVG line chart with a
table fallback, following the same pattern as the citywide chart tested in
``tests/test_site_article.py`` and the shortage chart tested in
``tests/test_site_shortage.py``.
"""

from __future__ import annotations

from berlinbikes.analysis.availability import availability_by_hour
from berlinbikes.analysis.db import connect
from berlinbikes.site import build_site
from tests.synthetic import BEZIRKE
from tests.test_site_article import _ancestors, _find_all, _parse, _preorder, _text


def _bezirk_article(root):
    for article in _find_all(root, "article"):
        headings = [_text(h2) for h2 in _find_all(article, "h2")]
        if any("Availability by Bezirk" in h or "Verfügbarkeit je Bezirk" in h for h in headings):
            return article
    raise AssertionError("no article with an 'Availability by Bezirk' heading found")


def _bezirk_table(root):
    for table in _find_all(root, "table"):
        captions = _find_all(table, "caption")
        if captions and "Bezirk" in _text(captions[0]) and "Mo-Fr" in _text(captions[0]):
            return table
    raise AssertionError("no table with a Bezirk/Mo-Fr caption found")


def _expected_bezirk_hour_means(con) -> dict[tuple[str, int], float]:
    """Unweighted mean of weekday 0-4 values per (bezirk, hour), same rule as bezirk_availability_chart."""
    result = availability_by_hour(con, by="bezirk")
    assert result.status == "ok"
    weekday_values: dict[tuple[str, int], list[float]] = {}
    for weekday, hour, bezirk, mean, _n in result.rows:
        if weekday <= 4:
            weekday_values.setdefault((bezirk, hour), []).append(mean)
    return {key: sum(values) / len(values) for key, values in weekday_values.items()}


def test_bezirk_table_matches_metric_and_svg_precedes_it(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)
    html = (site_dir / "index.html").read_text()

    expected = _expected_bezirk_hour_means(connect(synthetic_data_dir))

    root = _parse(html)
    order: list = []
    _preorder(root, order)

    article = _bezirk_article(root)

    table = _bezirk_table(root)
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
            value = expected.get((name, hour))
            expected_text = "–" if value is None else f"{value:.1f}"
            assert _text(cell).strip() == expected_text, (name, hour)

    svgs = [svg for svg in _find_all(article, "svg") if "chart" in (svg.attrs.get("class") or "").split()]
    assert len(svgs) == 1
    svg = svgs[0]
    assert svg.attrs.get("role") == "img"
    assert svg.attrs.get("aria-label")

    polylines = _find_all(svg, "polyline")
    assert len(polylines) == len(BEZIRKE)

    figure_ancestors = [a for a in _ancestors(svg) if a.tag == "figure"]
    assert figure_ancestors, "bezirk svg must be inside a <figure>"
    figure = figure_ancestors[0]
    assert _find_all(figure, "figcaption"), "<figure> must have a <figcaption>"

    subtree: list = []
    _preorder(figure, subtree)
    fig_start = order.index(figure)
    fig_end = fig_start + len(subtree) - 1

    assert order.index(table) > fig_end, "the table fallback must follow the chart's <figure>"


def test_empty_data_dir_shows_not_enough_data_and_no_bezirk_chart(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)

    root = _parse((site_dir / "index.html").read_text())
    article = _bezirk_article(root)

    not_enough = [p for p in _find_all(article, "p") if p.attrs.get("class") == "not-enough-data"]
    assert len(not_enough) == 1
    assert "0/14" in _text(not_enough[0]) or "0 / 14" in _text(not_enough[0])

    assert not _find_all(article, "svg"), "no bezirk chart should render below the 14-full-day minimum"
