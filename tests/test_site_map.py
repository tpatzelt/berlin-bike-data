"""Tests for the interactive map page (G4) and its data/profiles.json."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from berlinbikes.analysis import MIN_FULL_DAYS
from berlinbikes.analysis.db import connect
from berlinbikes.analysis.profiles import station_profiles
from berlinbikes.site import build_site
from berlinbikes.site.charts import CHART_FONT_SIZE, HEADLINE_CHAR_WIDTH, MAP_DEFAULT_HOUR, map_profile_chart
from berlinbikes.site.profiles import profiles_payload
from tests.helpers.svg import (
    assert_axes_conventions,
    assert_no_overlaps_and_inside,
    chart_elements,
    text_boxes,
)
from tests.synthetic import EMPTY_STATION_ID


@pytest.fixture(scope="module")
def map_site(synthetic_data_dir, tmp_path_factory):
    site_dir = tmp_path_factory.mktemp("map_site")
    build_site(synthetic_data_dir, site_dir, {"name": "Erika Muster", "address": "Musterstr. 1", "email": "e@example.com"})
    return site_dir


def test_map_page_structure(map_site):
    html = (map_site / "map.html").read_text()
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert 'href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"' in html
    assert 'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="' in html
    assert 'src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"' in html
    assert 'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="' in html
    for control in ("pick-station", "pick-ortsteil", "pick-weekday"):
        assert f'<label for="{control}">' in html
        assert f'<select id="{control}">' in html
    assert '<table id="profile-table">' in html
    assert "<noscript>" in html and 'href="data/profiles.json"' in html
    assert "openstreetmap.org/copyright" in html


def test_every_page_links_the_map(map_site):
    for page in ("index.html", "methodology.html", "impressum.html", "datenschutz.html", "map.html"):
        assert 'href="map.html"' in (map_site / page).read_text()


def test_map_js_is_copied_and_reads_profiles(map_site):
    assert "data/profiles.json" in (map_site / "map.js").read_text()


def test_profiles_json_matches_the_metric(map_site, synthetic_data_dir):
    payload = json.loads((map_site / "data" / "profiles.json").read_text())
    assert payload["status"] == "ok"
    rows = station_profiles(connect(synthetic_data_dir)).rows
    assert len(payload["stations"]) == len({r[0] for r in rows})
    station = next(s for s in payload["stations"] if s["id"] == EMPTY_STATION_ID)
    expected = {(r[5], r[6]): r[7] for r in rows if r[0] == EMPTY_STATION_ID}
    assert station["curve"][0][7] == round(expected[(0, 7)], 1)
    assert station["curve"][0][8] == round(expected[(0, 8)], 1)
    for entry in payload["stations"] + payload["ortsteile"]:
        assert len(entry["curve"]) == 7 and all(len(day) == 24 for day in entry["curve"])
    assert "bike_id" not in json.dumps(payload)


def test_profiles_json_stays_small_at_berlin_scale(map_site):
    payload = json.loads((map_site / "data" / "profiles.json").read_text())
    per_station = len(json.dumps(payload["stations"][0], separators=(",", ":")).encode())
    # About 1,050 stations at real scale.
    assert per_station * 1_050 < 3_000_000


def test_profiles_json_without_data(tmp_path):
    (tmp_path / "data").mkdir()
    build_site(tmp_path / "data", tmp_path / "site")
    payload = json.loads((tmp_path / "site" / "data" / "profiles.json").read_text())
    assert payload["status"] == "insufficient_data"
    assert payload["full_days"] == 0
    assert payload["min_full_days"] == MIN_FULL_DAYS
    js = (tmp_path / "site" / "map.js").read_text()
    assert js and not re.search(r"\b14\b", js)


def test_legal_pages_render_operator_details_and_third_parties(map_site, tmp_path):
    impressum = (map_site / "impressum.html").read_text()
    assert "Erika Muster" in impressum and "Musterstr. 1" in impressum and "[NAME]" not in impressum
    privacy = (map_site / "datenschutz.html").read_text()
    assert "tile.openstreetmap.org" in privacy and "unpkg.com" in privacy and "Cloudflare" in privacy
    privacy_en = (map_site / "datenschutz.en.html").read_text()
    assert "tile.openstreetmap.org" in privacy_en and "unpkg.com" in privacy_en and "Cloudflare" in privacy_en

    (tmp_path / "d").mkdir()
    build_site(tmp_path / "d", tmp_path / "s")
    assert "[NAME]" in (tmp_path / "s" / "impressum.html").read_text()


class _LangCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.html_lang = None
        self.nested_langs = []
        self.i18n_json = None
        self._in_i18n = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        elif a.get("lang") and not (tag == "a" and "lang-switch" in (a.get("class") or "")):
            self.nested_langs.append(a["lang"])
        if tag == "script" and a.get("id") == "map-i18n":
            self._in_i18n = True

    def handle_data(self, data):
        if self._in_i18n:
            self.i18n_json = (self.i18n_json or "") + data

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_i18n = False


def _collect(path):
    c = _LangCollector()
    c.feed(path.read_text())
    return c


def test_map_pages_are_single_language(map_site):
    de, en = _collect(map_site / "map.html"), _collect(map_site / "map.en.html")
    assert (de.html_lang, en.html_lang) == ("de", "en")
    assert de.nested_langs == [] and en.nested_langs == []
    for page in ("map.html", "map.en.html"):
        assert " / " not in (map_site / page).read_text().split("<main", 1)[1].split("</main>")[0].replace("14", "")


def test_map_i18n_json_is_per_language_and_complete(map_site):
    de = json.loads(_collect(map_site / "map.html").i18n_json)
    en = json.loads(_collect(map_site / "map.en.html").i18n_json)
    assert set(de) == set(en) == {"days", "ortsteil_title", "load_error", "hour", "plot", "axis_x", "axis_y", "headline", "x_ticks", "y_tick_target", "ortsteil_button"}
    assert de["days"] == "({n} Tage)" and en["days"] == "({n} days)"
    assert de["load_error"].startswith("Daten") and en["load_error"].startswith("Could not")
    assert en["ortsteil_title"] == "District {name}"


def test_map_js_has_no_inline_bilingual_strings():
    js = (Path(__file__).parent.parent / "src/berlinbikes/site/static/map.js").read_text()
    js = "\n".join(line for line in js.splitlines() if not line.lstrip().startswith("//"))
    for fragment in ("Tage", " days", "Could not", "Daten konnten", "Ortsteil ", "data.message"):
        assert fragment not in js
    assert "map-i18n" in js


def test_map_weekday_options_follow_page_language(map_site):
    assert "<option value=\"0\" selected>Montag</option>" in (map_site / "map.html").read_text()
    assert "<option value=\"6\">Sunday</option>" in (map_site / "map.en.html").read_text()


def test_legal_pages_are_one_language_each_with_operator_block(map_site):
    for page in ("impressum", "datenschutz"):
        de = (map_site / f"{page}.html").read_text()
        en = (map_site / f"{page}.en.html").read_text()
        assert "<section" not in de and "<section" not in en
        for html in (de, en):
            assert "<address>" in html and "Musterstr. 1" in html
    imp_de = (map_site / "impressum.html").read_text()
    imp_en = (map_site / "impressum.en.html").read_text()
    assert "Angaben gemäß § 5 DDG" in imp_de and "A private, non-commercial" not in imp_de
    assert "A private, non-commercial" in imp_en and "Angaben gemäß" not in imp_en
    ds_de = (map_site / "datenschutz.html").read_text()
    ds_en = (map_site / "datenschutz.en.html").read_text()
    assert "Ihre Rechte" in ds_de and "Ihre Rechte" not in ds_en
    assert "No cookies, no analytics" in ds_en and "No cookies, no analytics" not in ds_de


class _Options(HTMLParser):
    """Option values per <select id>, the selected one, plus the profile table's body rows."""

    def __init__(self):
        super().__init__()
        self.select = None
        self.options: dict[str, list[tuple[str, bool]]] = {}
        self.rows: list[list[str]] = []
        self._in_tbody = False
        self._cells: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "select":
            self.select = a["id"]
            self.options[self.select] = []
        elif tag == "option" and self.select:
            self.options[self.select].append((a.get("value", ""), "selected" in a))
        elif tag == "tbody":
            self._in_tbody = True
        elif tag == "tr" and self._in_tbody:
            self._cells = []

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "tr" and self._cells is not None:
            self.rows.append(self._cells)
            self._cells = None

    def handle_data(self, data):
        if self._cells is not None and data.strip():
            self._cells.append(data.strip())


@pytest.mark.parametrize("page", ["map.html", "map.en.html"])
def test_map_page_without_js_has_options_curve_and_table(map_site, synthetic_data_dir, page):
    html = (map_site / page).read_text()
    payload = profiles_payload(synthetic_data_dir)
    parsed = _Options()
    parsed.feed(html)
    stations = parsed.options["pick-station"]
    assert [v for v, _ in stations[1:]] == [s["id"] for s in payload["stations"]]
    assert [v for v, sel in stations if sel] == [payload["stations"][0]["id"]]
    assert [v for v, _ in parsed.options["pick-ortsteil"][1:]] == [o["name"] for o in payload["ortsteile"]]
    assert len(parsed.rows) == 24 and all(len(r) == 2 for r in parsed.rows)
    curve = payload["stations"][0]["curve"][0]
    assert [r[1] for r in parsed.rows] == ["–" if v is None else str(v) for v in curve]
    els = assert_axes_conventions(html)
    assert any(e["tag"] == "polyline" for e in els)
    figure = html[html.index('<svg id="profile-chart"') :]
    assert chart_elements(figure)[0]["attrs"]["id"] == "profile-chart"
    assert f"{MAP_DEFAULT_HOUR}:00" in next(e["text"] for e in els if e["tag"] == "text" and "headline" in e["groups"])


@pytest.mark.parametrize("page", ["map.html", "map.en.html"])
def test_map_chart_text_boxes_do_not_overlap(map_site, page):
    html = (map_site / page).read_text()
    start = html.index('<svg id="profile-chart"')
    tag = html[start : html.index(">", start)]
    width, height = (float(v) for v in re.search(r'viewBox="([^"]+)"', tag).group(1).split()[2:])
    boxes = text_boxes(chart_elements(html[start:]), CHART_FONT_SIZE, HEADLINE_CHAR_WIDTH)
    assert len(boxes) > 10
    assert any(f"{MAP_DEFAULT_HOUR}:00" in b[0] for b in boxes)
    assert_no_overlaps_and_inside(boxes, width, height)


def test_map_profile_chart_marks_the_hour_on_g2_axes():
    curve = [[float(h) for h in range(24)] for _ in range(7)]
    chart = map_profile_chart(curve, weekday=2, hour=10)
    assert chart.axes.y_min == 0 and chart.axes.y_max >= 23
    assert chart.headline.hour == 10 and chart.headline.value == 10.0
    assert len(chart.points.split()) == 24
    gappy = [[None] * 24 for _ in range(7)]
    gappy[0][3] = 4.0
    chart = map_profile_chart(gappy)
    assert chart.headline is None and len(chart.points.split()) == 1
    assert CHART_FONT_SIZE == chart.axes.font_size


def test_map_page_without_data_shows_not_enough_data(tmp_path):
    (tmp_path / "data").mkdir()
    build_site(tmp_path / "data", tmp_path / "site")
    html = (tmp_path / "site" / "map.html").read_text()
    assert 'class="not-enough-data"' in html and "<progress" in html
    assert 'id="profile-chart"' not in html
    parsed = _Options()
    parsed.feed(html)
    assert parsed.options["pick-station"] == [("", False)] and parsed.rows == []


def test_map_css_places_map_and_profile_side_by_side_on_wide_screens():
    css = (Path(__file__).parent.parent / "src/berlinbikes/site/static/site.css").read_text()
    assert re.search(r"@media \(min-width: [\d.]+rem\)\s*\{\s*\.map-layout\s*\{[^}]*grid-template-columns: repeat\(2", css)
    assert re.search(r"\.map-layout \{[^}]*grid-template-columns: minmax\(0, 1fr\)", css)


def test_map_js_replaces_prefilled_options():
    js = (Path(__file__).parent.parent / "src/berlinbikes/site/static/map.js").read_text()
    assert "fillSelect(" in js and "select.remove(1)" in js


_JS = Path(__file__).parent.parent / "src/berlinbikes/site/static/map.js"


def test_map_js_round_trips_the_selection_through_the_hash():
    assert _JS.exists()
    js = "\n".join(l for l in _JS.read_text().splitlines() if not l.lstrip().startswith("//"))
    assert "hashchange" in js and "history.replaceState" in js and "location.hash" in js
    assert "encodeURIComponent" in js and "decodeURIComponent" in js
    assert 'pick-hour' in js
    # the marked hour comes from the picker, never a literal
    assert not re.search(r"\[\s*8\s*\]|hour\s*[=:]\s*8\b|x\(\s*8\s*\)", js)
    assert "[0, 4, 8" not in js and "/ 23" not in js


def test_map_js_tick_values_come_from_the_server():
    js = _JS.read_text()
    assert "I18N.x_ticks" in js and "I18N.y_tick_target" in js and "niceTicks(" in js


@pytest.mark.parametrize("page,lang", [("map.html", "de"), ("map.en.html", "en")])
def test_map_page_has_hour_picker_search_and_ortsteil_button(map_site, page, lang):
    html = (map_site / page).read_text()
    assert '<select id="pick-hour">' in html and '<label for="pick-hour">' in html
    assert f'<option value="{MAP_DEFAULT_HOUR}" selected>' in html
    assert html.count('<option value="') >= 24
    assert '<label for="pick-search">' in html
    assert re.search(r'<input id="pick-search"[^>]*list="station-names"', html)
    assert '<datalist id="station-names">' in html
    label = {"de": "Station suchen", "en": "Search for a station"}[lang]
    assert label in html
    i18n = json.loads(_collect(map_site / page).i18n_json)
    assert i18n["ortsteil_button"] == {"de": "Ganzes Ortsteil zeigen", "en": "Show the whole Ortsteil"}[lang]
    assert i18n["x_ticks"][0] == 0 and i18n["y_tick_target"] >= 1
    assert 'id="show-ortsteil"' in html
