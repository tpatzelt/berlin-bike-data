"""Known-value and accessibility tests for the G4 daily-footprint section.

G3's ``daily_footprint`` metric (stations, bikes, e-bike versus pedal
bikes) must land on the article page as a stacked-bar-per-day chart with a
table fallback. ``synthetic_data_dir`` builds with ``n_stations=30`` and
``n_bikes=None`` (``tests.synthetic.build_dataset`` defaults), so
``tests.synthetic.expected_totals(30, None)`` gives the exact per-day
e-bike/pedal/free-floating split (52/232/0, per ADR-0020): the fixture's
background bike counts are constant across every snapshot, so every full
day's mean equals that same total.
"""

from __future__ import annotations

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.footprint import daily_footprint
from berlinbikes.site import build_site
from tests.synthetic import expected_totals
from tests.test_site_article import _ancestors, _find_all, _parse, _preorder, _text

_EXPECTED = expected_totals(30, None)


def _footprint_table(root):
    for table in _find_all(root, "table"):
        captions = _find_all(table, "caption")
        if captions and "System's daily footprint" in _text(captions[0]):
            return table
    raise AssertionError("no footprint table found")


def _footprint_svg(root):
    svgs = [svg for svg in _find_all(root, "svg") if "footprint" in (svg.attrs.get("class") or "").split()]
    assert len(svgs) == 1, "expected exactly one footprint bar-chart svg"
    return svgs[0]


def _table_rows(table):
    """[(date, n_stations, bikes_at_stations, free_floating, ebikes, pedal, unknown), ...] as displayed text."""
    body_rows = _find_all(_find_all(table, "tbody")[0], "tr")
    rows = []
    for row in body_rows:
        header = _find_all(row, "th")[0]
        cells = _find_all(row, "td")
        assert len(cells) == 6
        rows.append((_text(header).strip(), *[_text(c).strip() for c in cells]))
    return rows


def test_table_has_one_row_per_full_day_matching_daily_footprint(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)
    html = (site_dir / "index.html").read_text()

    result = daily_footprint(connect(synthetic_data_dir))
    assert result.status == "ok"

    root = _parse(html)
    table = _footprint_table(root)
    actual_rows = _table_rows(table)
    assert len(actual_rows) == len(result.rows) == result.full_days

    for (local_date, n_stations, at_stations, free_floating, ebikes, pedal, unknown), actual in zip(
        result.rows, actual_rows, strict=True
    ):
        expected = (
            local_date.isoformat(),
            str(n_stations),
            f"{at_stations:.1f}",
            f"{free_floating:.1f}",
            f"{ebikes:.1f}",
            f"{pedal:.1f}",
            f"{unknown:.1f}",
        )
        assert actual == expected


def test_ebike_and_pedal_columns_match_expected_totals(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)
    html = (site_dir / "index.html").read_text()

    root = _parse(html)
    table = _footprint_table(root)
    actual_rows = _table_rows(table)
    assert actual_rows, "expected at least one full day"

    for _date, _n_stations, _at_stations, free_floating, ebikes, pedal, _unknown in actual_rows:
        assert ebikes == f"{_EXPECTED['stations_ebike']:.1f}"
        assert pedal == f"{_EXPECTED['stations_pedal']:.1f}"
        assert free_floating == f"{_EXPECTED['free_floating']:.1f}"


def test_svg_is_in_a_captioned_figure_followed_by_the_table(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)

    root = _parse((site_dir / "index.html").read_text())
    order: list = []
    _preorder(root, order)

    svg = _footprint_svg(root)
    assert svg.attrs.get("role") == "img"
    assert svg.attrs.get("aria-label")

    figure_ancestors = [a for a in _ancestors(svg) if a.tag == "figure"]
    assert figure_ancestors, "footprint svg must be inside a <figure>"
    figure = figure_ancestors[0]
    assert _find_all(figure, "figcaption"), "<figure> must have a <figcaption>"

    subtree: list = []
    _preorder(figure, subtree)
    fig_start = order.index(figure)
    fig_end = fig_start + len(subtree) - 1

    following_tables = [t for t in _find_all(root, "table") if order.index(t) > fig_end]
    assert following_tables, "a <table> fallback must follow the footprint chart's <figure>"


def test_empty_data_dir_shows_not_enough_data_and_no_footprint_chart(tmp_path):
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
    bar_svgs = [svg for svg in _find_all(root, "svg") if "footprint" in (svg.attrs.get("class") or "").split()]
    assert not bar_svgs, "no footprint bar chart should render below the 14-full-day minimum"
