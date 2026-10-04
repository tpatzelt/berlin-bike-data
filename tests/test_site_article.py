"""Accessibility test for the index page's first real chart (G4).

The charter's G4 definition of done requires every chart to have a text or
table fallback, checked by an accessibility test. This renders the real site
from the synthetic dataset and checks that the citywide
``availability_by_hour`` chart is a plain SVG (no JS, no CDN) wrapped in a
``<figure>`` with a ``<figcaption>``, followed later in the document by a
``<table>`` holding the same 7 (weekday) x 24 (local hour) numbers as the
metric itself. It also checks the insufficient-data case renders the
"not enough data yet" message instead of a chart.
"""

from __future__ import annotations

from datetime import date
from html.parser import HTMLParser

import pytest

from berlinbikes.analysis.availability import availability_by_hour
from berlinbikes.analysis.db import connect
from berlinbikes.site import build_site
from tests.synthetic import build_dataset


class _Node:
    def __init__(self, tag: str, attrs=(), parent: "_Node | None" = None, text: str = "") -> None:
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children: list[_Node] = []
        self.text = text


class _TreeBuilder(HTMLParser):
    """Builds a minimal nested tree so ancestor/order relationships can be checked."""

    _VOID = {"meta", "link", "br", "img", "input", "hr"}

    def __init__(self) -> None:
        super().__init__()
        self.root = _Node("#root")
        self._stack = [self.root]

    def _append(self, node: _Node) -> None:
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self._append(node)
        if tag not in self._VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._append(_Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        if data.strip():
            self._append(_Node("#text", text=data))


def _parse(html_text: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed(html_text)
    return builder.root


def _find_all(node: _Node, tag: str) -> list[_Node]:
    found = []
    for child in node.children:
        if child.tag == tag:
            found.append(child)
        found.extend(_find_all(child, tag))
    return found


def _ancestors(node: _Node) -> list[_Node]:
    out = []
    current = node.parent
    while current is not None:
        out.append(current)
        current = current.parent
    return out


def _preorder(node: _Node, out: list[_Node]) -> None:
    out.append(node)
    for child in node.children:
        _preorder(child, out)


def _text(node: _Node) -> str:
    return "".join(t.text for t in _find_all(node, "#text"))


def test_chart_svg_is_in_a_captioned_figure_followed_by_a_table(tmp_path):
    data_dir = tmp_path / "data"
    build_dataset(data_dir, start_date=date(2026, 1, 5), days=28)
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)

    root = _parse((site_dir / "index.html").read_text())
    order: list[_Node] = []
    _preorder(root, order)

    svgs = _find_all(root, "svg")
    assert svgs, "expected at least one chart svg on the article page"

    for svg in svgs:
        assert svg.attrs.get("role") == "img"
        assert svg.attrs.get("aria-label")

        figure_ancestors = [a for a in _ancestors(svg) if a.tag == "figure"]
        assert figure_ancestors, "svg must be inside a <figure>"
        figure = figure_ancestors[0]
        assert _find_all(figure, "figcaption"), "<figure> must have a <figcaption>"

        subtree: list[_Node] = []
        _preorder(figure, subtree)
        fig_start = order.index(figure)
        fig_end = fig_start + len(subtree) - 1

        tables = _find_all(root, "table")
        following_tables = [t for t in tables if order.index(t) > fig_end]
        assert following_tables, "a <table> fallback must follow the chart's <figure>"


def test_table_fallback_has_matching_7x24_values(tmp_path):
    data_dir = tmp_path / "data"
    build_dataset(data_dir, start_date=date(2026, 1, 5), days=28)
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)

    result = availability_by_hour(connect(data_dir), by="city")
    assert result.status == "ok"
    expected = {(weekday, hour): mean for weekday, hour, mean, _n in result.rows}

    root = _parse((site_dir / "index.html").read_text())
    tables = _find_all(root, "table")
    assert tables
    table = tables[0]

    body_rows = _find_all(_find_all(table, "tbody")[0], "tr")
    assert len(body_rows) == 7

    total_data_cells = 0
    for weekday, row in enumerate(body_rows):
        cells = _find_all(row, "td")
        total_data_cells += len(cells)
        assert len(cells) == 24, weekday

    assert total_data_cells == 7 * 24

    chosen_weekday, chosen_hour = 2, 8
    row = body_rows[chosen_weekday]
    cell_text = _text(_find_all(row, "td")[chosen_hour])
    assert float(cell_text) == pytest.approx(expected[(chosen_weekday, chosen_hour)], abs=0.05)


def test_empty_data_dir_shows_not_enough_data_message_and_no_chart(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)

    text = (site_dir / "index.html").read_text()
    assert not _find_all(_parse(text), "svg")
    lowered = text.lower()
    assert "not enough data yet" in lowered
    assert "noch nicht genug daten" in lowered
    assert "0/14" in text or "0 / 14" in text
