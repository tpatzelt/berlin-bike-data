"""Tests for the interactive map page (G4) and its data/profiles.json."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.profiles import station_profiles
from berlinbikes.site import build_site
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
    assert set(de) == set(en) == {"days", "ortsteil_title", "not_enough_data", "load_error"}
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
