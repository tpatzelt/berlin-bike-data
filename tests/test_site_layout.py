"""HTML-structure tests for the site skeleton (G4)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from html.parser import HTMLParser

import pytest

from berlinbikes.analysis import MIN_FULL_DAYS
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
def empty_site(built_empty_site):
    return built_empty_site


@pytest.fixture
def synthetic_site(built_synthetic_site):
    return built_synthetic_site


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
@pytest.mark.parametrize("lang", ("de", "en"))
def test_footer_links_resolve_to_generated_files(empty_site, page, lang):
    name = page if lang == "de" else page.replace(".html", ".en.html")
    parsed = _parse((empty_site / name).read_text())
    local_hrefs = [href for href in parsed.hrefs if not href.startswith(("http", "mailto:"))]
    expected = {p if lang == "de" else p.replace(".html", ".en.html") for p in PAGES}
    assert set(local_hrefs) >= expected
    for href in local_hrefs:
        assert (empty_site / href).exists(), href


def test_empty_data_dir_shows_not_enough_data_state(empty_site):
    text = (empty_site / "index.html").read_text().lower()
    assert "noch nicht genug daten" in text
    assert "not enough data yet" not in text
    en_text = (empty_site / "index.en.html").read_text().lower()
    assert "not enough data yet" in en_text
    assert "noch nicht genug daten" not in en_text


def test_synthetic_data_dir_does_not_show_not_enough_data_state(synthetic_site):
    for name in ("index.html", "index.en.html"):
        text = (synthetic_site / name).read_text().lower()
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


_COLOR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color)\(", re.I
)
_NAMED_COLORS = re.compile(
    r"(?<![\w-])(?:white|black|red|green|blue|gray|grey|silver|orange|yellow|purple|pink|"
    r"brown|navy|teal|cyan|magenta|lime|maroon|olive|aqua|fuchsia|gold|transparent)(?![\w-])",
    re.I,
)


def _css_blocks(css_text: str) -> tuple[str, str, str]:
    """Return (light :root body, dark :root body, css with both blocks removed)."""
    root = re.search(r":root\s*{([^}]*)}", css_text)
    dark = re.search(
        r"@media\s*\(prefers-color-scheme:\s*dark\)\s*{\s*:root\s*{([^}]*)}\s*}", css_text
    )
    assert root and dark
    rest = css_text.replace(dark.group(0), "").replace(root.group(0), "")
    return root.group(1), dark.group(1), rest


def _declarations(body: str) -> dict[str, str]:
    return {
        m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)
    }


def _site_css(empty_site) -> str:
    path = empty_site / "site.css"
    assert path.exists()
    return path.read_text()


def test_root_declares_color_spacing_type_radius_and_font_tokens(empty_site):
    light, _, _ = _css_blocks(_site_css(empty_site))
    decls = _declarations(light)
    for prefix in ("--space-", "--step-", "--radius-"):
        assert [n for n in decls if n.startswith(prefix)], prefix
    assert len([n for n in decls if n.startswith("--space-")]) >= 6
    assert "--font-body" in decls and "system-ui" in decls["--font-body"]
    assert "url(" not in decls["--font-body"]
    for token in ("--surface", "--border", *TOKENS):
        assert token in decls


def test_dark_block_redefines_exactly_the_color_tokens(empty_site):
    light, dark, _ = _css_blocks(_site_css(empty_site))
    light_colors = {n for n, v in _declarations(light).items() if _COLOR_LITERAL.search(v)}
    dark_decls = _declarations(dark)
    assert len(light_colors) >= 10
    assert set(dark_decls) == light_colors
    assert all(_COLOR_LITERAL.search(v) for v in dark_decls.values())


def test_no_color_literal_outside_root_blocks(empty_site):
    _, _, rest = _css_blocks(_site_css(empty_site))
    assert "{" in rest  # the rules are still there
    assert not _COLOR_LITERAL.findall(rest)
    assert not _NAMED_COLORS.findall(rest)


class _HeaderParser(HTMLParser):
    """Collect the links inside <header><nav> and the header's language switch."""

    def __init__(self) -> None:
        super().__init__()
        self.in_header = self.in_nav = False
        self.nav_hrefs: list[str] = []
        self.header_hrefs: list[str] = []
        self.has_nav = False

    def handle_starttag(self, tag, attrs):
        if tag == "header":
            self.in_header = True
        elif tag == "nav" and self.in_header:
            self.in_nav = self.has_nav = True
        elif tag == "a" and self.in_header:
            href = dict(attrs).get("href", "")
            self.header_hrefs.append(href)
            if self.in_nav:
                self.nav_hrefs.append(href)

    def handle_endtag(self, tag):
        if tag == "header":
            self.in_header = False
        elif tag == "nav":
            self.in_nav = False


@pytest.fixture(scope="module")
def layout_site(built_empty_site):
    return built_empty_site


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("lang", ("de", "en"))
def test_header_has_nav_in_page_language_and_language_switch(layout_site, page, lang):
    def name(p, lg):
        return p if lg == "de" else p.replace(".html", ".en.html")

    path = layout_site / name(page, lang)
    assert path.exists()
    parser = _HeaderParser()
    parser.feed(path.read_text())
    assert parser.has_nav
    assert set(parser.nav_hrefs) == {name(p, lang) for p in ("index.html", "map.html", "methodology.html")}
    other = "en" if lang == "de" else "de"
    assert name(page, other) in parser.header_hrefs
    assert name(page, other) not in parser.nav_hrefs


def test_stylesheet_sets_ch_based_prose_measure(layout_site):
    css_text = (layout_site / "site.css").read_text()
    match = re.search(r"main\s*:is\(([^)]*)\)\s*{([^}]*)}", css_text)
    assert match
    selectors = {s.strip() for s in match.group(1).split(",")}
    assert {"p", "h2", "ul", "details"} <= selectors
    width = re.search(r"max-width:\s*(\d+)ch", match.group(2))
    assert width and 60 <= int(width.group(1)) <= 75
    assert not re.search(r"max-width:\s*\d+px", css_text)


def test_header_is_styled_and_footer_is_quiet(layout_site):
    css_text = (layout_site / "site.css").read_text()
    assert re.search(r"\.site-header\s*{[^}]*display:\s*flex[^}]*flex-wrap:\s*wrap", css_text)
    assert re.search(r"footer\s*{[^}]*color:\s*var\(--muted\)", css_text)


def test_not_enough_data_component_shows_progress_and_day_count(empty_site):
    for name, count in (("index.html", "0/14 Tage gesammelt"), ("index.en.html", "0/14 days collected")):
        html = (empty_site / name).read_text()
        blocks = re.findall(r'<p class="not-enough-data">(.*?)</p>', html, re.S)
        # the weather "missing label" message is a different state without progress
        blocks = [b for b in blocks if "<progress" in b]
        assert len(blocks) == 6, name
        for block in blocks:
            assert f'<progress value="0" max="{MIN_FULL_DAYS}">' in block
            assert count in block


def test_synthetic_site_has_no_progress_element(synthetic_site):
    for name in ("index.html", "index.en.html"):
        html = (synthetic_site / name).read_text()
        assert "<article" in html, name
        assert "<progress" not in html, name


def test_not_enough_data_css_has_no_border_box():
    css = (Path(__file__).parent.parent / "src/berlinbikes/site/static/site.css").read_text()
    rule = re.search(r"\.not-enough-data \{([^}]*)\}", css)
    assert rule and "border:" not in rule.group(1)
    assert "progress" in css
