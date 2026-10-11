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
