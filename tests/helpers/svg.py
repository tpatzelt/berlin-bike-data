"""Reusable assertions for the axis/grid/headline conventions of site charts."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from berlinbikes.site.charts import CHART_FONT_SIZE, HEADLINE_CHAR_WIDTH


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
    m = re.search(r'<svg[^>]*class="(?:[^"]* )?chart(?: [^"]*)?"[^>]*font-size="([\d.]+)"', html)
    assert m, "root svg font-size missing"
    return float(m.group(1))


def chart_by_class(html: str, cls: str) -> list[dict]:
    """Elements of the ``<svg>`` whose class list contains ``chart`` and ``cls``."""
    parser = _Svg()
    parser.feed(html)
    out: list[dict] = []
    inside = False
    for el in parser.elements:
        if el["tag"] == "svg":
            inside = "chart" in el["classes"] and cls in el["classes"]
        if inside:
            out.append(el)
    return out


def text_boxes(els: list[dict], font_size: float, char_width: float) -> list[tuple[str, float, float, float, float]]:
    """Estimated (text, x0, y0, x1, y1) of every positioned <text>; rotated titles are skipped."""
    boxes = []
    for e in els:
        a = e["attrs"]
        if e["tag"] != "text" or "x" not in a or "transform" in a:
            continue
        w = len(e["text"].strip()) * char_width * font_size
        x = float(a["x"])
        x0 = {"end": x - w, "middle": x - w / 2}.get(a.get("text-anchor"), x)
        y = float(a["y"])
        boxes.append((e["text"].strip(), x0, y - font_size * 0.8, x0 + w, y + font_size * 0.2))
    return boxes


def assert_no_overlaps_and_inside(boxes, width: float, height: float) -> None:
    for text, x0, y0, x1, y1 in boxes:
        assert x0 >= 0 and y0 >= 0 and x1 <= width and y1 <= height, (text, x0, y0, x1, y1)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert a[3] <= b[1] or b[3] <= a[1] or a[4] <= b[2] or b[4] <= a[2], (a[0], b[0])


def figure_html(html: str, article_id: str) -> str:
    """The first ``<figure>`` of ``<article id=article_id>``."""
    start = html.index(f'<article id="{article_id}">')
    figure = html[html.index("<figure>", start) :]
    return figure[: figure.index("</figure>")]


def label_fits(headline, text, axes) -> bool:
    """Both label lines (name, then value) stay inside the plot box."""
    width = max(len(line) for line in text.split()[:1] + [" ".join(text.split()[1:])]) * HEADLINE_CHAR_WIDTH * CHART_FONT_SIZE
    x = headline.label_x
    lo, hi = {"start": (x, x + width), "end": (x - width, x), "middle": (x - width / 2, x + width / 2)}[headline.anchor]
    return axes.left <= lo and hi <= axes.right + 1


def main_html(html: str) -> str:
    """The ``<main>`` element of a page."""
    assert "<main" in html and "</main>" in html, "page has no <main>"
    return html[html.index("<main") : html.index("</main>")]


def chart_count(html: str) -> int:
    parser = _Svg()
    parser.feed(html)
    return sum(1 for e in parser.elements if e["tag"] == "svg" and "chart" in e["classes"])


def svg_font_size(html: str, cls: str) -> float:
    """``font-size`` of the root ``<svg>`` whose class list contains ``chart`` and ``cls``."""
    els = chart_by_class(html, cls)
    assert els and els[0]["tag"] == "svg", f"no chart svg with class {cls}"
    return float(els[0]["attrs"]["font-size"])


ROOT_BLOCK_PATTERN = re.compile(r":root\s*{([^}]*)}")
DARK_BLOCK_PATTERN = re.compile(r"prefers-color-scheme:\s*dark\)\s*{\s*:root\s*{([^}]*)}")


def css_raw_token_blocks(css: str) -> tuple[str, str]:
    """Return the raw (:root, dark-mode :root) block texts of site.css."""
    root = ROOT_BLOCK_PATTERN.search(css)
    dark = DARK_BLOCK_PATTERN.search(css)
    assert root, f"no `:root {{ ... }}` block matched pattern {ROOT_BLOCK_PATTERN.pattern!r}"
    assert dark, f"no dark block matched pattern {DARK_BLOCK_PATTERN.pattern!r}"
    return root.group(1), dark.group(1)


def css_token_blocks(css: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return the (light, dark) custom-property maps parsed from site.css."""
    root_text, dark_text = css_raw_token_blocks(css)
    pat = re.compile(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;")
    color_like = re.compile(r"(--[\w-]+):\s*((?:#|rgba?\(|hsla?\()[^;]*);")
    for block in (root_text, dark_text):
        unparsed = {n for n, _ in color_like.findall(block)} - {n for n, _ in pat.findall(block)}
        assert not unparsed, f"colour tokens not written as 6-digit hex: {sorted(unparsed)}"
    light_tokens = dict(pat.findall(root_text))
    dark_tokens = {**light_tokens, **dict(pat.findall(dark_text))}
    return light_tokens, dark_tokens


def _channels(color: str) -> list[float]:
    return [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]


def blend(fg: str, bg: str, alpha: float) -> str:
    """Composite ``fg`` at ``alpha`` over ``bg``; returns #rrggbb."""
    mixed = [alpha * f + (1 - alpha) * b for f, b in zip(_channels(fg), _channels(bg))]
    return "#" + "".join(f"{round(c * 255):02x}" for c in mixed)


def relative_luminance(color: str) -> float:
    """WCAG 2.x relative luminance of a #rrggbb colour."""
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in _channels(color)]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast_ratio(a: str, b: str) -> float:
    hi, lo = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
