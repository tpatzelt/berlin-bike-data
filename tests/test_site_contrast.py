"""WCAG AA contrast of every colour token against its backgrounds, light and dark (G5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import berlinbikes.site as site_pkg
from berlinbikes.site.charts import MAP_BINS
from tests.helpers.svg import blend, contrast_ratio, css_token_blocks

SITE_DIR = Path(site_pkg.__file__).parent
CSS = (SITE_DIR / "static" / "site.css").read_text()
LIGHT, DARK = css_token_blocks(CSS)
MODES = {"light": LIGHT, "dark": DARK}
#: fill-opacity of map markers and legend swatches (map.js, site.css).
MARKER_OPACITY = 0.85

TEXT_ON_BG = ["--fg", "--muted", "--accent"]
TEXT_ON_SURFACE = ["--fg", "--muted", "--accent"]
GRAPHIC_ON_BG = ["--fg", *[f"--series-{i}" for i in range(1, 8)], *[f"--avail-{i}" for i in range(len(MAP_BINS))]]


def _used_tokens() -> set[str]:
    used: set[str] = set()
    for path in [*SITE_DIR.glob("templates/*.html"), *SITE_DIR.glob("static/*.js"), SITE_DIR / "charts.py"]:
        used |= set(re.findall(r"var\((--(?:series|avail)-\d+)\)", path.read_text()))
    used |= set(re.findall(r"^\s*(--(?:series|avail)-\d+):", CSS, re.M))
    return used


def test_every_used_series_and_avail_token_is_checked():
    assert _used_tokens() <= set(GRAPHIC_ON_BG)
    for tokens in MODES.values():
        assert _used_tokens() <= set(tokens)


@pytest.mark.parametrize("mode", MODES)
def test_text_tokens_meet_4_5_on_backgrounds(mode):
    t = MODES[mode]
    for name in TEXT_ON_BG:
        assert contrast_ratio(t[name], t["--bg"]) >= 4.5, (mode, name)
    for name in TEXT_ON_SURFACE:
        assert contrast_ratio(t[name], t["--surface"]) >= 4.5, (mode, name, "surface")


@pytest.mark.parametrize("mode", MODES)
def test_series_and_avail_tokens_meet_3_on_bg(mode):
    t = MODES[mode]
    for name in GRAPHIC_ON_BG:
        assert name in t, (mode, name)
        assert contrast_ratio(t[name], t["--bg"]) >= 3, (mode, name)


@pytest.mark.parametrize("mode", MODES)
def test_avail_markers_meet_3_when_blended_at_marker_opacity(mode):
    t = MODES[mode]
    for i in range(len(MAP_BINS)):
        shown = blend(t[f"--avail-{i}"], t["--bg"], MARKER_OPACITY)
        assert contrast_ratio(shown, t["--bg"]) >= 3, (mode, i)


def test_marker_opacity_matches_the_code():
    assert f"fill-opacity: {MARKER_OPACITY}" in CSS
    assert f"fillOpacity: {MARKER_OPACITY}" in (SITE_DIR / "static" / "map.js").read_text()
