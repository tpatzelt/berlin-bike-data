"""i18n catalog and bilingual page build (G1)."""

from __future__ import annotations

import string
from html.parser import HTMLParser

import pytest

from berlinbikes.site import PAGES, build_site
from berlinbikes.site.i18n import STRINGS, t


def _en(page: str) -> str:
    return page.replace(".html", ".en.html")


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_lang = None
        self.alternates: dict[str, str] = {}
        self.switches: list[dict[str, str | None]] = []
        self.lang_attrs_in_header: list[str] = []
        self._in_header = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "header":
            self._in_header = True
        elif tag == "link" and a.get("rel") == "alternate":
            self.alternates[a["hreflang"]] = a["href"]
        elif tag == "a" and "lang-switch" in (a.get("class") or ""):
            self.switches.append(a)
        elif self._in_header and a.get("lang"):
            self.lang_attrs_in_header.append(a["lang"])

    def handle_endtag(self, tag):
        if tag == "header":
            self._in_header = False


def _parse(path):
    p = _Parser()
    p.feed(path.read_text())
    return p


@pytest.fixture
def site(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    out = tmp_path / "site"
    written = build_site(data_dir, out)
    return out, written


@pytest.mark.parametrize("page", PAGES)
def test_every_page_has_english_twin_with_matching_lang(site, page):
    out, written = site
    assert out / _en(page) in written
    assert _parse(out / page).html_lang == "de"
    assert _parse(out / _en(page)).html_lang == "en"


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("lang", ("de", "en"))
def test_hreflang_alternates_and_switch(site, page, lang):
    out, _ = site
    name = page if lang == "de" else _en(page)
    other = _en(page) if lang == "de" else page
    parsed = _parse(out / name)
    assert parsed.alternates == {"de": page, "en": _en(page), "x-default": page}
    assert len(parsed.switches) == 1
    switch = parsed.switches[0]
    assert switch["href"] == other
    assert switch["hreflang"] == switch["lang"] == ("en" if lang == "de" else "de")
    assert (out / switch["href"]).exists()
    assert set(parsed.lang_attrs_in_header) <= {switch["lang"]}


def test_titles_come_from_catalog(site):
    out, _ = site
    assert "<title>How Berlin Rides</title>" in (out / "index.en.html").read_text()
    assert "<title>Methodik</title>" in (out / "methodology.html").read_text()


def _placeholders(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}


@pytest.mark.parametrize("key", sorted(STRINGS))
def test_catalog_entries_are_complete(key):
    entry = STRINGS[key]
    assert set(entry) == {"de", "en"}
    assert entry["de"].strip() and entry["en"].strip()
    assert _placeholders(entry["de"]) == _placeholders(entry["en"])


def test_t_raises_on_unknown_key_or_language():
    with pytest.raises(KeyError):
        t("no.such.key", "de")
    with pytest.raises(KeyError):
        t("site.title", "fr")


def test_t_formats_placeholders_and_escapes():
    STRINGS["_test"] = {"de": "a {x}", "en": "b {x}"}
    try:
        assert str(t("_test", "en", x="<")) == "b &lt;"
    finally:
        del STRINGS["_test"]


class _ArticleLangs(HTMLParser):
    """Collect ``lang`` attributes of elements inside each ``<article id=...>``."""

    def __init__(self) -> None:
        super().__init__()
        self.html_lang = None
        self.article_ids: list[str] = []
        self.langs: dict[str, list[str]] = {}
        self._current = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "article":
            self._current = a.get("id")
            self.article_ids.append(self._current)
            self.langs[self._current] = []
        elif self._current and a.get("lang"):
            self.langs[self._current].append(a["lang"])

    def handle_endtag(self, tag):
        if tag == "article":
            self._current = None


@pytest.fixture(scope="module")
def synthetic_site_dir(tmp_path_factory, synthetic_data_dir):
    out = tmp_path_factory.mktemp("synthetic_site")
    build_site(synthetic_data_dir, out)
    return out


@pytest.mark.parametrize("which", ("empty", "synthetic"))
@pytest.mark.parametrize("name", ("index.html", "index.en.html"))
def test_first_three_articles_are_single_language(which, name, site, synthetic_site_dir):
    root = site[0] if which == "empty" else synthetic_site_dir
    p = _ArticleLangs()
    p.feed((root / name).read_text())
    assert p.article_ids == ["availability", "shortage", "bezirke", "flow", "weather", "footprint"]
    for article in ("availability", "shortage", "bezirke"):
        assert [lang for lang in p.langs[article] if lang != p.html_lang] == []
    if which == "synthetic":
        text = (root / name).read_text()
        marker = "Verfügbarkeit in Berlin" if name == "index.html" else "Availability in Berlin"
        other = "Availability in Berlin" if name == "index.html" else "Verfügbarkeit in Berlin"
        assert marker in text and other not in text
