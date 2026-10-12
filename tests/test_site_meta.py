"""Skip link, favicon, Open Graph / Twitter meta and the preview image on every page (G5)."""

from __future__ import annotations

import re
import struct
from html.parser import HTMLParser
from pathlib import Path

import pytest

from berlinbikes.config import Settings
from berlinbikes.site import PAGES, build_site, i18n
from berlinbikes.site.builder import page_url

STATIC = Path(__file__).parent.parent / "src" / "berlinbikes" / "site" / "static"
ALL_PAGES = [page_url(p, lang) for p in PAGES for lang in i18n.LANGS]


class _Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.links, self.focusable, self.main_ids = [], [], [], []
        self.in_body = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "body":
            self.in_body = True
        elif tag == "meta":
            self.meta.append(a)
        elif tag == "link":
            self.links.append(a)
        if self.in_body and tag in ("a", "button", "input", "select", "textarea") and not a.get("disabled"):
            self.focusable.append((tag, a))
        if tag == "main":
            self.main_ids.append(a.get("id"))


def _parse(path: Path) -> _Head:
    assert path.exists(), path
    p = _Head()
    p.feed(path.read_text())
    return p


def _prop(p: _Head, key: str) -> str:
    vals = [m["content"] for m in p.meta if m.get("property") == key or m.get("name") == key]
    assert len(vals) == 1, (key, vals)
    return vals[0]


@pytest.fixture(scope="module")
def abs_site(tmp_path_factory, synthetic_data_dir):
    out = tmp_path_factory.mktemp("abs_site")
    build_site(synthetic_data_dir, out, base_url="https://example.org/")
    return out


@pytest.mark.parametrize("state", ["built_empty_site", "built_synthetic_site"])
@pytest.mark.parametrize("name", ALL_PAGES)
def test_every_page_has_meta(request, state, name):
    site = request.getfixturevalue(state)
    p = _parse(site / name)
    lang = "en" if name.endswith(".en.html") else "de"
    first = p.focusable[0]
    assert first[0] == "a" and first[1]["href"] == "#main" and "skip-link" in first[1]["class"]
    assert p.main_ids == ["main"]
    assert any(l.get("rel") == "icon" and l.get("type") == "image/svg+xml" and l["href"] == "favicon.svg" for l in p.links)
    assert _prop(p, "og:locale") == {"de": "de_DE", "en": "en_GB"}[lang]
    assert _prop(p, "og:type") == "website"
    assert _prop(p, "og:title") and _prop(p, "og:description")
    assert _prop(p, "og:image") == "og-image.png"
    assert _prop(p, "og:url") == name
    assert (_prop(p, "og:image:width"), _prop(p, "og:image:height")) == ("1200", "630")
    assert _prop(p, "og:image:alt") == i18n.t("meta.image_alt", lang)
    assert _prop(p, "twitter:card") == "summary_large_image"
    assert i18n.t("nav.skip", lang) in (site / name).read_text()


@pytest.mark.parametrize("name", ["index.html", "map.en.html"])
def test_base_url_makes_urls_absolute(abs_site, name):
    p = _parse(abs_site / name)
    assert _prop(p, "og:image") == "https://example.org/og-image.png"
    assert _prop(p, "og:url") == f"https://example.org/{name}"


def test_assets_copied_and_valid(built_empty_site):
    png = (built_empty_site / "og-image.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (1200, 630)
    assert png == (STATIC / "og-image.png").read_bytes()
    assert len(png) < 200_000
    assert "<svg" in (built_empty_site / "favicon.svg").read_text()


def test_skip_link_strings_in_both_languages():
    for key in ("nav.skip", "meta.description", "meta.image_alt"):
        assert all(i18n.STRINGS[key][lang] for lang in i18n.LANGS)


def test_skip_link_hidden_until_focused():
    css = (STATIC / "site.css").read_text()
    assert ".skip-link:focus" in css and "translateY" in css


def test_site_base_url_config(monkeypatch):
    env = {"BIKES_DATA_DIR": "d", "BIKES_USER_AGENT": "ua"}
    assert Settings.from_env(env).site_base_url == ""
    assert Settings.from_env({**env, "BIKES_SITE_BASE_URL": " https://example.org/ "}).site_base_url == "https://example.org"


def _rule_body(css: str, selector_part: str) -> str:
    m = re.search(r"(?m)^[^{}\n]*" + re.escape(selector_part) + r"[^{}]*\{([^}]*)\}", css)
    assert m, f"no rule for {selector_part}"
    return m.group(1)


def test_focus_visible_outline():
    css = (STATIC / "site.css").read_text()
    sel = re.search(r"(?m)^([^{}\n]*:focus-visible[^{}]*)\{", css)
    assert sel
    for el in ("a", "button", "select", "input", "summary"):
        assert f"{el}:focus-visible" in sel.group(1)
    body = _rule_body(css, "a:focus-visible")
    assert "outline: 2px solid var(--accent)" in body and "outline-offset" in body


def test_touch_targets_44px():
    css = (STATIC / "site.css").read_text()
    for part in (".site-header nav a", ".lang-switch", "footer a", ".map-controls select", ".map-controls input", ".show-ortsteil"):
        m = re.search(r"min-height:\s*([\d.]+)rem", _rule_body_containing(css, part))
        assert m and float(m.group(1)) >= 2.75, part


def test_leaflet_zoom_buttons_44px():
    css = (STATIC / "site.css").read_text()
    rules = [m for m in re.finditer(r"(?m)^([^{}\n]+)\{([^}]*)\}", css) if ".leaflet-bar a" in m.group(1)]
    assert rules, "no site.css rule for .leaflet-bar a"
    sel, body = rules[0].group(1), rules[0].group(2)
    # must beat Leaflet's `.leaflet-touch .leaflet-bar a` (two classes, one element)
    assert sel.count(".") >= 3, sel
    for prop in ("width", "height", "min-width", "min-height", "line-height"):
        m = re.search(rf"(?<![\w-]){prop}:\s*([\d.]+)rem", body)
        assert m and float(m.group(1)) >= 2.75, prop


def _rule_body_containing(css: str, part: str) -> str:
    for m in re.finditer(r"(?m)^([^{}\n]+)\{([^}]*)\}", css):
        if part in m.group(1) and "min-height" in m.group(2):
            return m.group(2)
    raise AssertionError(f"no min-height rule for {part}")


def test_reduced_motion_block():
    css = (STATIC / "site.css").read_text()
    m = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}", css, re.S)
    assert m
    body = m.group(1)
    assert "transition: none" in body and "animation: none" in body and "scroll-behavior: auto" in body
    assert "*" in body.split("{")[0]


def test_show_ortsteil_hidden_override():
    css = (STATIC / "site.css").read_text()
    assert "display: inline-flex" in _rule_body_containing(css, ".show-ortsteil")
    m = re.search(r"(?m)^\.show-ortsteil\[hidden\]\s*\{([^}]*)\}", css)
    assert m and "display: none" in m.group(1)


def test_build_site_ignores_env_base_url(tmp_path, synthetic_data_dir, monkeypatch):
    monkeypatch.setenv("BIKES_SITE_BASE_URL", "https://example.invalid")
    out = tmp_path / "site"
    build_site(synthetic_data_dir, out)
    html = (out / "index.html").read_text()
    assert "example.invalid" not in html
    assert re.search(r'<meta property="og:image" content="(?!https?:)', html)
