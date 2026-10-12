"""i18n catalog and bilingual page build (G1)."""

from __future__ import annotations

import string
from html.parser import HTMLParser

import pytest

from berlinbikes.site import PAGES, build_site
from berlinbikes.site.builder import page_url
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


class _Title(HTMLParser):
    """Collect the text of every ``<title>``, so len == 1 also catches a duplicate."""

    def __init__(self) -> None:
        super().__init__()
        self.titles: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
            self.titles.append("")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.titles[-1] += data


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("lang", ("de", "en"))
def test_titles_come_from_catalog(built_empty_site, page, lang):
    parser = _Title()
    parser.feed((built_empty_site / page_url(page, lang)).read_text())
    assert len(parser.titles) == 1
    expected = STRINGS[f"title.{page.removesuffix('.html')}"][lang]
    assert parser.titles[0].strip() == expected


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
        self.h2: dict[str, list[str]] = {}
        self._current = None
        self._h2_depth = 0
        self._anchor_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "article":
            self._current = a.get("id")
            self.article_ids.append(self._current)
            self.langs[self._current] = []
            self.h2[self._current] = []
        elif self._current:
            if a.get("lang"):
                self.langs[self._current].append(a["lang"])
            if tag == "h2":
                self._h2_depth += 1
                self.h2[self._current].append("")
            elif self._h2_depth and tag == "a":
                self._anchor_depth += 1

    def handle_endtag(self, tag):
        if tag == "article":
            self._current = None
        elif tag == "h2" and self._h2_depth:
            self._h2_depth -= 1
            self.h2[self._current][-1] = self.h2[self._current][-1].strip()
        elif tag == "a" and self._anchor_depth:
            self._anchor_depth -= 1

    def handle_data(self, data):
        if self._h2_depth and not self._anchor_depth:
            self.h2[self._current][-1] += data


@pytest.fixture(scope="module")
def synthetic_site_dir(built_synthetic_site):
    return built_synthetic_site


@pytest.mark.parametrize("which", ("empty", "synthetic"))
@pytest.mark.parametrize("name", ("index.html", "index.en.html"))
def test_all_six_articles_are_single_language(which, name, site, synthetic_site_dir):
    root = site[0] if which == "empty" else synthetic_site_dir
    p = _ArticleLangs()
    p.feed((root / name).read_text())
    assert p.article_ids == ["availability", "shortage", "bezirke", "flow", "weather", "footprint"]
    for article in p.article_ids:
        assert [lang for lang in p.langs[article] if lang != p.html_lang] == []
    lang = p.html_lang
    other = "en" if lang == "de" else "de"
    assert lang in ("de", "en")
    for article in p.article_ids:
        assert p.h2[article] == [STRINGS[f"{article}.heading"][lang]]
        assert STRINGS[f"{article}.heading"][other] not in p.h2[article]


class _ColumnHeaders(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.headers: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "th" and dict(attrs).get("scope") == "col":
            self._depth += 1
            self.headers.append("")

    def handle_endtag(self, tag):
        if tag == "th" and self._depth:
            self._depth -= 1
            self.headers[-1] = self.headers[-1].strip()

    def handle_data(self, data):
        if self._depth:
            self.headers[-1] += data


@pytest.mark.parametrize(
    "name,lang",
    (("index.html", "de"), ("index.en.html", "en"), ("map.html", "de"), ("map.en.html", "en")),
)
def test_column_headers_come_from_catalog(name, lang, synthetic_site_dir):
    p = _ColumnHeaders()
    p.feed((synthetic_site_dir / name).read_text())
    assert p.headers
    catalog = {v[lang] for v in STRINGS.values()}
    for header in p.headers:
        is_hour = header.removesuffix(":00").isdigit()
        assert is_hour or header in catalog, header
    if name.startswith("map"):
        want = [STRINGS["map.table.hour"][lang], STRINGS["map.table.bikes"][lang]]
        assert p.headers == want


def test_strings_has_no_duplicate_keys():
    import ast
    import inspect

    import berlinbikes.site.i18n as mod

    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "STRINGS":
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            assert len(keys) == len(set(keys))
            return
    raise AssertionError("STRINGS literal not found")


class _VisibleText(HTMLParser):
    """Visible body text with script/style/head and the language switch removed."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self.foreign_langs: list[str] = []
        self.html_lang = None
        self._skip = 0
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        is_switch = tag == "a" and "lang-switch" in (a.get("class") or "")
        if tag in ("script", "style", "head", "title") or is_switch:
            self._skip += 1
            self._skip_stack.append(tag)
        elif a.get("lang") and a["lang"] != self.html_lang:
            self.foreign_langs.append(a["lang"])

    def handle_endtag(self, tag):
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def _norm(text: str) -> str:
    import html
    import re

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _differing_values() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"de": [], "en": []}
    for key, entry in STRINGS.items():
        if entry["de"] == entry["en"]:
            continue
        for lang in ("de", "en"):
            value = _norm(entry[lang])
            if "{" not in value and len(value.split()) >= 2:
                out[lang].append(value)
    return out


@pytest.fixture(scope="module")
def sweep_sites(built_empty_site, built_synthetic_site):
    return {"empty": built_empty_site, "synthetic": built_synthetic_site}


@pytest.mark.parametrize("which", ("empty", "synthetic"))
@pytest.mark.parametrize("lang", ("de", "en"))
@pytest.mark.parametrize("page", PAGES)
def test_sweep_no_other_language_body_copy(sweep_sites, which, lang, page):
    root = sweep_sites[which]
    name = page if lang == "de" else _en(page)
    raw = (root / name).read_text()
    p = _VisibleText()
    p.feed(raw)
    assert p.html_lang == lang
    # check 1: no foreign lang attribute outside the header switch
    assert p.foreign_langs == []
    # check 2: no differing multi-word catalog value of the other language
    text = _norm(" ".join(p.chunks))
    other = "en" if lang == "de" else "de"
    mine = set(_differing_values()[lang])
    leaked = [v for v in _differing_values()[other] if v not in mine and v in text]
    assert leaked == []
    # check 3: counterpart link and alternates
    parsed = _parse(root / name)
    counterpart = _en(page) if lang == "de" else page
    assert [s["href"] for s in parsed.switches] == [counterpart]
    assert set(parsed.alternates) == {"de", "en", "x-default"}
    for href in parsed.alternates.values():
        assert (root / href).exists()


def test_sweep_detects_a_leaked_english_value():
    values = _differing_values()
    assert len(values["en"]) > 20 and len(values["de"]) > 20
    leaked = "Hallo " + values["en"][0]
    assert values["en"][0] in _norm(leaked)
