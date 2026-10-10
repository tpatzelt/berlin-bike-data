"""Reusable assertions for the axis/grid/headline conventions of site charts."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _Svg(HTMLParser):
    """Collects the first <svg class="chart"> subtree as (tag, attrs, class-path, text) rows."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[dict] = []
        self._stack: list[tuple[str, list[str]]] = []
        self._svg_depth = 0
        self._current_text: dict | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "svg":
            self._svg_depth += 1
        if self._svg_depth:
            groups = [c for _t, cs in self._stack for c in cs]
            el = {"tag": tag, "attrs": attrs, "classes": classes, "groups": groups, "text": ""}
            self.elements.append(el)
            if tag == "text":
                self._current_text = el
        if tag not in ("line", "circle", "polyline", "br"):
            self._stack.append((tag, classes))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("line", "circle", "polyline", "br") and self._stack:
            self._stack.pop()

    def handle_endtag(self, tag):
        if tag == "text":
            self._current_text = None
        if tag == "svg":
            self._svg_depth -= 1
        if self._stack and self._stack[-1][0] == tag:
            self._stack.pop()

    def handle_data(self, data):
        if self._current_text is not None:
            self._current_text["text"] += data


def chart_elements(html: str, first_n: int = 1) -> list[dict]:
    """Elements of the first ``<svg class="chart">`` in ``html``."""
    parser = _Svg()
    parser.feed(html)
    out: list[dict] = []
    seen = 0
    for el in parser.elements:
        if el["tag"] == "svg" and "chart" in el["classes"]:
            seen += 1
        if seen == first_n:
            out.append(el)
    return out


def assert_axes_conventions(html: str, n: int = 1) -> list[dict]:
    """Tick labels on both axes, gridlines, titles with a unit in parentheses, a headline."""
    els = chart_elements(html, n)
    assert els, "no chart svg"
    for axis in ("axis-x", "axis-y"):
        ticks = [e for e in els if e["tag"] == "text" and "tick" in e["classes"] and axis in e["groups"]]
        assert len(ticks) >= 3, f"{axis}: expected tick labels, got {len(ticks)}"
        assert all(e["text"].strip() for e in ticks)
    assert any(e["tag"] == "line" and "grid" in e["classes"] for e in els), "no gridlines"
    for which in ("x", "y"):
        titles = [e for e in els if "axis-title" in e["classes"] and f"axis-title-{which}" in e["classes"]]
        assert len(titles) == 1, which
        assert "(" in titles[0]["text"] and ")" in titles[0]["text"], titles[0]["text"]
    headline = [e for e in els if e["tag"] == "text" and "headline" in e["groups"]]
    assert headline and headline[0]["text"].strip(), "no headline label"
    assert any(e["tag"] == "circle" and "headline" in e["groups"] for e in els), "no headline marker"
    return els


def polyline_dasharrays(els: list[dict]) -> list[str]:
    return [e["attrs"].get("stroke-dasharray", "") for e in els if e["tag"] == "polyline"]


def assert_distinct_dasharrays(els: list[dict], n: int) -> None:
    dashes = polyline_dasharrays(els)
    assert len(dashes) == n
    assert all(dashes), "every series needs a stroke-dasharray"
    assert len(set(dashes)) == n, dashes


def root_font_size(html: str) -> float:
    m = re.search(r'<svg[^>]*class="chart"[^>]*font-size="([\d.]+)"', html)
    assert m, "root svg font-size missing"
    return float(m.group(1))
