"""Methodology-page tests for the G4 site generator.

The charter's G4 definition of done requires the methodology page to name
every data source and license. :data:`berlinbikes.site.sources.DATA_SOURCES`
is the single source of truth for those, so this test renders the real site
and checks the page textually contains each one, alongside the snapshot
approach, the rotating-id limitation and the documented thresholds.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from berlinbikes.analysis import MIN_FULL_DAYS
from berlinbikes.analysis.weather_effect import COLD_C_THRESHOLD, RAIN_MM_THRESHOLD
from berlinbikes.site import PAGES
from berlinbikes.site.sources import DATA_SOURCES


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


def test_every_data_source_name_and_license_is_named(either_page):
    for source in DATA_SOURCES:
        assert source.name in either_page, source.name
        assert source.license in either_page, source.license


def test_used_for_column_is_in_the_page_language(methodology_html, methodology_en_html):
    for source in DATA_SOURCES:
        assert source.used_for_de in methodology_html
        assert source.used_for_en not in methodology_html
        assert source.used_for_en in methodology_en_html
        assert source.used_for_de not in methodology_en_html


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


def test_page_has_exactly_one_h1_before_the_h2(either_page):
    assert either_page.count("<h1>") == 1
    assert either_page.index("<h1>") < either_page.index("<h2>")


def test_first_paragraph_is_the_shared_lead(either_page):
    assert either_page.index('<p class="lead-text">') == either_page.index("<p")


def test_sources_table_carries_the_class(either_page):
    assert either_page.count('<table class="sources-table">') == 1


def _css_rule(css: str, selector: str) -> str:
    start = css.index(selector)
    return css[start : css.index("}", start)]


def test_sources_table_css_left_aligns_and_wraps(site_dir):
    css = (site_dir / "static" / "site.css").read_text() if (site_dir / "static").exists() else None
    if css is None:
        css = next(site_dir.rglob("site.css")).read_text()
    rule = _css_rule(css, ".sources-table th, .sources-table td")
    assert "text-align: left" in rule
    assert "overflow-wrap: anywhere" in rule
    assert "border-bottom" in _css_rule(css, ".sources-table thead th")
    assert "text-align: right" in _css_rule(css, "th, td {")
