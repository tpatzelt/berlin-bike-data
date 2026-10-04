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
from berlinbikes.site import PAGES, build_site
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
def methodology_html(tmp_path) -> str:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)
    return (site_dir / "methodology.html").read_text()


def test_every_data_source_name_and_license_is_named(methodology_html):
    for source in DATA_SOURCES:
        assert source.name in methodology_html, source.name
        assert source.license in methodology_html, source.license


def test_page_has_viewport_meta_and_lang(methodology_html):
    parsed = _parse(methodology_html)
    assert parsed.html_attrs.get("lang")
    assert any(
        m.get("name") == "viewport" and "width=device-width" in (m.get("content") or "")
        for m in parsed.meta
    )


def test_footer_links_to_methodology_page(methodology_html):
    parsed = _parse(methodology_html)
    assert "methodology.html" in parsed.hrefs


def test_footer_links_resolve_to_other_generated_pages(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)
    parsed = _parse((site_dir / "methodology.html").read_text())
    local_hrefs = [href for href in parsed.hrefs if not href.startswith("http")]
    assert set(local_hrefs) >= set(PAGES)
    for href in local_hrefs:
        assert (site_dir / href).exists(), href


def test_explains_snapshot_approach_in_german_and_english(methodology_html):
    lowered = methodology_html.lower()
    assert "momentaufnahme" in lowered or "snapshot" in lowered
    assert "2 minuten" in lowered
    assert "2 minutes" in lowered


def test_explains_rotating_bike_id_limitation_in_german_and_english(methodology_html):
    lowered = methodology_html.lower()
    assert "bike_id" in lowered
    assert "wechselt" in lowered or "rotiert" in lowered
    assert "rotates" in lowered


def test_explains_h3_aggregation(methodology_html):
    assert "H3" in methodology_html
    assert "ADR-0001" in methodology_html


def test_states_min_full_days_threshold(methodology_html):
    assert str(MIN_FULL_DAYS) in methodology_html


def test_states_weather_thresholds(methodology_html):
    assert str(RAIN_MM_THRESHOLD) in methodology_html
    assert str(COLD_C_THRESHOLD) in methodology_html
    assert "ADR-0017" in methodology_html


def test_mentions_europe_berlin_timezone(methodology_html):
    assert "Europe/Berlin" in methodology_html


def test_mentions_proportional_bezirk_flow_inference(methodology_html):
    lowered = methodology_html.lower()
    assert "bezirk" in lowered
    assert "proportional" in lowered
