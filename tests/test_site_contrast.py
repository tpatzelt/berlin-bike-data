"""WCAG AA contrast of every colour token against its backgrounds, light and dark (G5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import berlinbikes.site as site_pkg
from berlinbikes.site.charts import MAP_BINS, SERIES_COLOR_COUNT
from tests.helpers.svg import blend, contrast_ratio, css_token_blocks

SITE_DIR = Path(site_pkg.__file__).parent
CSS = (SITE_DIR / "static" / "site.css").read_text()
LIGHT, DARK = css_token_blocks(CSS)
MODES = {"light": LIGHT, "dark": DARK}
#: fill-opacity of map markers and legend swatches (map.js, site.css).
MARKER_OPACITY = 0.85

TEXT_TOKENS = ["--fg", "--muted", "--accent"]
GRAPHIC_ON_BG = ["--fg", *[f"--series-{i}" for i in range(1, SERIES_COLOR_COUNT + 1)], *[f"--avail-{i}" for i in range(len(MAP_BINS))]]


def _used_tokens() -> set[str]:
    used: set[str] = set(re.findall(r"^\s*(--(?:series|avail)-\d+):", CSS, re.M))
    for path in [*SITE_DIR.glob("templates/*.html"), *SITE_DIR.glob("static/*.js"), SITE_DIR / "charts.py"]:
        text = path.read_text()
        used |= set(re.findall(r"var\((--(?:series|avail)-\d+)\)", text))
        # Dynamically built names (var(--series-{{ i }}), "var(--avail-" + i) use the whole family.
        families = set(re.findall(r"--(series|avail)-(?!\d)", text))
        if "series" in families:
            used |= {f"--series-{i}" for i in range(1, SERIES_COLOR_COUNT + 1)}
        if "avail" in families:
            used |= {f"--avail-{i}" for i in range(len(MAP_BINS))}
    return used


def test_every_used_series_and_avail_token_is_checked():
    assert _used_tokens() <= set(GRAPHIC_ON_BG)
    for tokens in MODES.values():
        assert _used_tokens() <= set(tokens)


@pytest.mark.parametrize("mode", MODES)
def test_text_tokens_meet_4_5_on_backgrounds(mode):
    t = MODES[mode]
    for name in TEXT_TOKENS:
        assert contrast_ratio(t[name], t["--bg"]) >= 4.5, (mode, name)
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


@pytest.mark.parametrize("block_pattern", [
    r":root\s*{([^}]*)}",
    r"prefers-color-scheme:\s*dark\)\s*{\s*:root\s*{([^}]*)}",
], ids=["light", "dark"])
def test_series_token_count_matches_charts_constant(block_pattern):
    # Count in the raw block: MODES['dark'] merges the light tokens in, hiding a dropped dark token.
    block = re.search(block_pattern, CSS)
    assert block, block_pattern
    declared = re.findall(r"(--series-\d+)\s*:", block.group(1))
    assert len(declared) == SERIES_COLOR_COUNT, declared


@pytest.mark.parametrize("css", [
    ":root{--bg:#fff;--fg:#000000;} @media (prefers-color-scheme: dark){:root{--bg:#000000;}}",
    ":root{--bg:#ffffff;} @media (prefers-color-scheme: dark){:root{--bg:rgb(0,0,0);}}",
])
def test_css_token_blocks_rejects_unparsed_colour_tokens(css):
    with pytest.raises(AssertionError, match="not written as 6-digit hex"):
        css_token_blocks(css)
