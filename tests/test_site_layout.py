"""HTML-structure tests for the site skeleton (G4)."""

from __future__ import annotations

import re
import subprocess
from html.parser import HTMLParser

import pytest

from berlinbikes.site import PAGES, build_site

TOKENS = ("--bg", "--fg", "--accent", "--muted")


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


def _strip_media_blocks(css_text: str) -> str:
    out, i = [], 0
    while i < len(css_text):
        if css_text.startswith("@media", i):
            depth, k = 1, css_text.index("{", i) + 1
            while depth and k < len(css_text):
                depth += {"{": 1, "}": -1}.get(css_text[k], 0)
                k += 1
            i = k
        else:
            out.append(css_text[i])
            i += 1
    return "".join(out)


def _git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def empty_site(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)
    return site_dir


@pytest.fixture
def synthetic_site(synthetic_data_dir, tmp_path):
    site_dir = tmp_path / "site_full"
    build_site(synthetic_data_dir, site_dir)
    return site_dir


def test_build_site_writes_every_page_and_css(empty_site):
    for name in (*PAGES, "site.css"):
        assert (empty_site / name).exists(), name


def test_build_site_never_writes_outside_site_dir(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    before = _git_status()
    build_site(data_dir, tmp_path / "out")
    assert _git_status() == before


@pytest.mark.parametrize("page", PAGES)
def test_pages_have_viewport_meta_and_lang(empty_site, page):
    parsed = _parse((empty_site / page).read_text())
    assert parsed.html_attrs.get("lang")
    assert any(
        m.get("name") == "viewport" and "width=device-width" in (m.get("content") or "")
        for m in parsed.meta
    )


@pytest.mark.parametrize("page", PAGES)
def test_footer_links_resolve_to_generated_files(empty_site, page):
    parsed = _parse((empty_site / page).read_text())
    local_hrefs = [href for href in parsed.hrefs if not href.startswith("http")]
    assert set(local_hrefs) >= set(PAGES)
    for href in local_hrefs:
        assert (empty_site / href).exists(), href


def test_empty_data_dir_shows_not_enough_data_state(empty_site):
    text = (empty_site / "index.html").read_text().lower()
    assert "not enough data yet" in text
    assert "noch nicht genug daten" in text


def test_synthetic_data_dir_does_not_show_not_enough_data_state(synthetic_site):
    text = (synthetic_site / "index.html").read_text().lower()
    assert "not enough data yet" not in text
    assert "noch nicht genug daten" not in text


def test_css_defines_theme_tokens_in_light_and_dark(empty_site):
    css_text = (empty_site / "site.css").read_text()
    root_match = re.search(r":root\s*{([^}]*)}", css_text)
    assert root_match
    dark_match = re.search(
        r"@media\s*\(prefers-color-scheme:\s*dark\)\s*{.*?:root\s*{([^}]*)}", css_text, re.S
    )
    assert dark_match
    for token in TOKENS:
        assert token in root_match.group(1)
        assert token in dark_match.group(1)


def test_css_has_no_fixed_px_widths_outside_media_queries(empty_site):
    css_text = (empty_site / "site.css").read_text()
    stripped = _strip_media_blocks(css_text)
    assert not re.search(r"\bwidth\s*:\s*\d+px", stripped)
