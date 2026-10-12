"""Methodology-page tests for the G4 site generator.

The charter's G4 definition of done requires the methodology page to name
every data source and license. :data:`berlinbikes.site.sources.DATA_SOURCES`
is the single source of truth for those, so this test renders the real site
and checks the page textually contains each one, alongside the snapshot
approach, the rotating-id limitation and the documented thresholds.
"""

from __future__ import annotations

import dataclasses
import html
import re
from html.parser import HTMLParser

import pytest

from berlinbikes.analysis import MIN_FULL_DAYS
from berlinbikes.analysis.weather_effect import COLD_C_THRESHOLD, RAIN_MM_THRESHOLD
from berlinbikes.site import PAGES
from berlinbikes.site.i18n import STRINGS
from berlinbikes.site.sources import DATA_SOURCES, DataSource


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_attrs: dict[str, str | None] = {}
        self.meta: list[dict[str, str | None]] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag == "html":
            self.html_attrs = attr_dict
        elif tag == "meta":
            self.meta.append(attr_dict)
        elif tag == "a" and "href" in attr_dict:
            self.hrefs.append(attr_dict["href"])


def _parse(html_text: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html_text)
    return parser


@pytest.fixture
def site_dir(built_empty_site):
    return built_empty_site


@pytest.fixture
def methodology_html(site_dir) -> str:
    return (site_dir / "methodology.html").read_text()


@pytest.fixture
def methodology_en_html(site_dir) -> str:
    return (site_dir / "methodology.en.html").read_text()


@pytest.fixture(params=("methodology.html", "methodology.en.html"))
def either_page(request, site_dir) -> str:
    return (site_dir / request.param).read_text()


def test_every_data_source_name_and_license_is_named(methodology_html, methodology_en_html):
    for source in DATA_SOURCES:
        assert source.name in methodology_html, source.name
        assert source.name in methodology_en_html, source.name
        assert source.license_de in methodology_html, source.license_de
        assert source.license_en in methodology_en_html, source.license_en


def test_license_and_url_note_are_in_the_page_language(methodology_html, methodology_en_html):
    for source in DATA_SOURCES:
        assert source.license_de and source.license_en, source.name
        if source.license_de != source.license_en:
            assert source.license_en not in methodology_html, source.license_en
            assert source.license_de not in methodology_en_html, source.license_de
        if source.url_note_de or source.url_note_en:
            assert source.url_note_de and source.url_note_en, source.name
            assert source.url_note_de in methodology_html, source.name
            assert source.url_note_en in methodology_en_html, source.name
            if source.url_note_de != source.url_note_en:
                assert source.url_note_en not in methodology_html, source.name
                assert source.url_note_de not in methodology_en_html, source.name
    assert any(s.url_note_de for s in DATA_SOURCES)
    assert any(s.license_de != s.license_en for s in DATA_SOURCES)


def test_used_for_column_is_in_the_page_language(methodology_html, methodology_en_html):
    for source in DATA_SOURCES:
        assert source.used_for_de in methodology_html
        assert source.used_for_en not in methodology_html
        assert source.used_for_en in methodology_en_html
        assert source.used_for_de not in methodology_en_html


def test_every_de_en_field_pair_shows_only_its_own_language(methodology_html, methodology_en_html):
    names = {f.name for f in dataclasses.fields(DataSource)}
    de = {n[:-3] for n in names if n.endswith("_de")}
    en = {n[:-3] for n in names if n.endswith("_en")}
    assert de == en, f"unpaired _de/_en fields: {sorted(de ^ en)}"
    assert {"license", "used_for", "url_note"} <= de
    page_de, page_en = html.unescape(methodology_html), html.unescape(methodology_en_html)
    for source in DATA_SOURCES:
        for field in sorted(de):
            msg = f"{source.name}.{field}"
            value_de = getattr(source, f"{field}_de")
            value_en = getattr(source, f"{field}_en")
            assert bool(value_de) == bool(value_en), msg
            if not value_de:
                continue
            assert value_de in page_de, msg
            assert value_en in page_en, msg
            if value_de != value_en:
                assert value_en not in page_de, msg
                assert value_de not in page_en, msg


def test_pages_are_single_language(methodology_html, methodology_en_html):
    assert "<section" not in methodology_html and "<section" not in methodology_en_html
    assert "Datenquellen" in methodology_html and "Data sources" not in methodology_html
    assert "Data sources" in methodology_en_html and "Datenquellen" not in methodology_en_html


def test_page_has_viewport_meta_and_lang(either_page):
    parsed = _parse(either_page)
    assert parsed.html_attrs.get("lang")
    assert any(
        m.get("name") == "viewport" and "width=device-width" in (m.get("content") or "")
        for m in parsed.meta
    )


def test_footer_links_to_methodology_page(either_page):
    parsed = _parse(either_page)
    assert "methodology.html" in parsed.hrefs


def test_footer_links_resolve_to_other_generated_pages(site_dir):
    parsed = _parse((site_dir / "methodology.html").read_text())
    local_hrefs = [href for href in parsed.hrefs if not href.startswith(("http", "#"))]
    assert set(local_hrefs) >= set(PAGES)
    for href in local_hrefs:
        assert (site_dir / href).exists(), href


def test_explains_snapshot_approach_in_each_language(methodology_html, methodology_en_html):
    de, en = methodology_html.lower(), methodology_en_html.lower()
    assert "momentaufnahme" in de and "2 minuten" in de and "2 minutes" not in de
    assert "snapshot" in en and "2 minutes" in en and "2 minuten" not in en


def test_explains_rotating_bike_id_limitation_in_each_language(methodology_html, methodology_en_html):
    de, en = methodology_html.lower(), methodology_en_html.lower()
    assert "bike_id" in de and "bike_id" in en
    assert "wechselt" in de and "rotates" not in de
    assert "rotates" in en and "wechselt" not in en


def test_explains_h3_aggregation(either_page):
    assert "H3" in either_page
    assert "ADR-0001" in either_page


def test_states_min_full_days_threshold(either_page):
    assert str(MIN_FULL_DAYS) in either_page


def test_states_weather_thresholds(either_page):
    assert str(RAIN_MM_THRESHOLD) in either_page
    assert str(COLD_C_THRESHOLD) in either_page
    assert "ADR-0017" in either_page


def test_mentions_europe_berlin_timezone(either_page):
    assert "Europe/Berlin" in either_page


def test_mentions_proportional_bezirk_flow_inference(either_page):
    lowered = either_page.lower()
    assert "bezirk" in lowered
    assert "proportional" in lowered


class _OutlineParser(HTMLParser):
    """Collects headings in order, and the text of every .source-url span."""

    def __init__(self) -> None:
        super().__init__()
        self.headings: list[tuple[str, str, int]] = []  # tag, text, event index
        self.source_urls: list[str] = []
        self.first_p_index: int | None = None
        self.table_index: int | None = None
        self._events = 0
        self._open: str | None = None
        self._buf = ""
        self._open_index = 0

    def handle_starttag(self, tag, attrs):
        self._events += 1
        cls = (dict(attrs).get("class") or "").split()
        if tag == "p" and self.first_p_index is None:
            self.first_p_index = self._events
        elif tag == "table" and "sources-table" in cls:
            self.table_index = self._events
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._open, self._buf, self._open_index = tag, "", self._events
        elif tag == "span" and "source-url" in cls:
            self._open, self._buf = "span", ""

    def handle_data(self, data):
        if self._open:
            self._buf += data

    def handle_endtag(self, tag):
        if tag == self._open:
            if tag == "span":
                self.source_urls.append(self._buf)
            else:
                self.headings.append((tag, self._buf, self._open_index))
            self._open = None


def _outline(html_text: str) -> _OutlineParser:
    parser = _OutlineParser()
    parser.feed(html_text)
    return parser


@pytest.mark.parametrize(
    ("page", "lang"), [("methodology.html", "de"), ("methodology.en.html", "en")]
)
def test_page_outline_is_h1_then_one_sources_h2_before_the_table(site_dir, page, lang):
    outline = _outline((site_dir / page).read_text())
    assert [tag for tag, _, _ in outline.headings] == ["h1", "h2"]
    (_, _, h1_index), (_, h2_text, h2_index) = outline.headings
    assert h2_text == STRINGS["methodology.h2"][lang]
    # The lead paragraph comes between the h1 and the h2, and the table follows the h2.
    assert outline.first_p_index is not None and outline.table_index is not None
    assert h1_index < outline.first_p_index < h2_index < outline.table_index


@pytest.mark.parametrize("page", ["methodology.html", "methodology.en.html"])
def test_source_url_spans_hold_only_a_bare_url(site_dir, page):
    urls = _outline((site_dir / page).read_text()).source_urls
    assert len(urls) == len(DATA_SOURCES) > 0
    for url in urls:
        assert url and not any(ch.isspace() for ch in url), url
    assert urls == [source.url for source in DATA_SOURCES]


def test_first_paragraph_is_the_shared_lead(either_page):
    assert either_page.index('<p class="lead-text">') == either_page.index("<p")


def test_sources_table_carries_the_class(either_page):
    assert either_page.count('<table class="sources-table">') == 1


def _css_rule(css: str, selector: str) -> str:
    start = css.index(selector)
    return css[start : css.index("}", start)]


def test_sources_table_css_left_aligns_and_wraps(site_dir):
    paths = list(site_dir.rglob("site.css"))
    assert paths
    css = paths[0].read_text()
    rule = _css_rule(css, ".sources-table th, .sources-table td")
    assert "text-align: left" in rule
    assert "hyphens: auto" in rule
    assert "overflow-wrap: break-word" in rule
    assert "anywhere" not in rule
    url_rule = _css_rule(css, ".sources-table .source-url")
    assert "overflow-wrap: anywhere" in url_rule
    assert "word-break: break-all" in url_rule
    assert "border-bottom" in _css_rule(css, ".sources-table thead th")
    assert "text-align: right" in _css_rule(css, "th, td {")


def test_lead_text_rule_uses_type_and_space_tokens(site_dir):
    paths = list(site_dir.rglob("site.css"))
    assert paths
    rule = _css_rule(paths[0].read_text(), ".lead-text {")
    assert "font-size: var(--step-" in rule
    assert "var(--space-" in rule
    assert "line-height" in rule


class _CellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.labels: list[str | None] = []

    def handle_starttag(self, tag, attrs):
        if tag == "table" and "sources-table" in (dict(attrs).get("class") or "").split():
            self.in_table = True
        elif tag == "td" and self.in_table:
            self.labels.append(dict(attrs).get("data-label"))

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False


@pytest.mark.parametrize(
    ("page", "lang"), [("methodology.html", "de"), ("methodology.en.html", "en")]
)
def test_every_sources_td_has_its_column_label(site_dir, page, lang):
    parser = _CellParser()
    parser.feed((site_dir / page).read_text())
    expected = [STRINGS[f"methodology.col.{k}"][lang] for k in ("source", "used_for", "license")]
    assert len(parser.labels) == 3 * len(DATA_SOURCES) > 0
    assert parser.labels == expected * len(DATA_SOURCES)
    assert all(parser.labels)


def test_sources_table_stacks_with_data_labels_on_narrow_screens(site_dir):
    paths = list(site_dir.rglob("site.css"))
    assert paths
    css = paths[0].read_text()
    blocks = [
        css[m.start() : css.index("\n}\n", m.start())] for m in re.finditer("@media", css)
    ]
    matching = [b for b in blocks if ".sources-table td::before" in b]
    assert len(matching) == 1, "no @media block styles .sources-table td::before"
    block = matching[0]
    assert "@media (max-width" in block.splitlines()[0]
    assert "content: attr(data-label)" in block
    stack_rule = (
        r"\.sources-table tbody,\s*\.sources-table tr,\s*\.sources-table td\s*"
        r"\{\s*display:\s*block;\s*\}"
    )
    assert re.search(stack_rule, block), "sources table cells are not stacked as blocks"
    assert "var(--muted)" in block
