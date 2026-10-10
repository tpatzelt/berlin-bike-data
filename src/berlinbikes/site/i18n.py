"""String catalog for the site shell: every key carries both languages."""

from __future__ import annotations

from markupsafe import Markup

LANGS = ("de", "en")

STRINGS: dict[str, dict[str, str]] = {
    "site.title": {"de": "Wie Berlin radelt", "en": "How Berlin Rides"},
    "nav.label": {"de": "Hauptnavigation", "en": "Main navigation"},
    "nav.home": {"de": "Start", "en": "Home"},
    "nav.map": {"de": "Karte", "en": "Map"},
    "nav.methodology": {"de": "Methodik", "en": "Methodology"},
    "nav.impressum": {"de": "Impressum", "en": "Legal notice"},
    "nav.privacy": {"de": "Datenschutz", "en": "Privacy"},
    "lang.switch": {"de": "English", "en": "Deutsch"},
    "title.index": {"de": "Wie Berlin radelt", "en": "How Berlin Rides"},
    "title.map": {"de": "Karte – Wie Berlin radelt", "en": "Map – How Berlin Rides"},
    "title.methodology": {"de": "Methodik", "en": "Methodology"},
    "title.impressum": {"de": "Impressum", "en": "Legal notice"},
    "title.datenschutz": {"de": "Datenschutzerklärung", "en": "Privacy policy"},
}


def t(key: str, lang: str, **kwargs: object) -> Markup:
    """Return the catalog string for ``key`` in ``lang``; raises KeyError if absent."""
    if lang not in LANGS:
        raise KeyError(f"unknown language: {lang!r}")
    return Markup(STRINGS[key][lang]).format(**kwargs)
