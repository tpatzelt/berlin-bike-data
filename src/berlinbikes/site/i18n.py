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
    "common.show_table": {"de": "Werte als Tabelle anzeigen", "en": "Show values as a table"},
    "common.not_enough_data": {"de": "noch nicht genug Daten", "en": "not enough data yet"},
    "common.table.day": {"de": "Tag", "en": "Day"},
    "common.table.station": {"de": "Station", "en": "Station"},
    "common.table.min_per_day": {"de": "Min./Tag", "en": "Min/day"},
    "weekday.short.0": {"de": "Mo", "en": "Mon"},
    "weekday.short.1": {"de": "Di", "en": "Tue"},
    "weekday.short.2": {"de": "Mi", "en": "Wed"},
    "weekday.short.3": {"de": "Do", "en": "Thu"},
    "weekday.short.4": {"de": "Fr", "en": "Fri"},
    "weekday.short.5": {"de": "Sa", "en": "Sat"},
    "weekday.short.6": {"de": "So", "en": "Sun"},
    "availability.heading": {"de": "Verfügbarkeit in Berlin", "en": "Availability in Berlin"},
    "availability.intro": {
        "de": "Mittlere Anzahl verfügbarer Räder in Berlin, je Wochentag und Uhrzeit (Europe/Berlin).",
        "en": "Mean number of bikes available citywide, by weekday and local hour (Europe/Berlin).",
    },
    "availability.aria": {
        "de": "Mittlere Anzahl verfügbarer Räder in Berlin je Wochentag und Uhrzeit (0-23 Uhr, Europe/Berlin)",
        "en": "Mean bikes available in Berlin by weekday and local hour (0-23, Europe/Berlin)",
    },
    "availability.caption": {
        "de": "Verfügbare Räder je Uhrzeit (0–23 Uhr, Europe/Berlin) und Wochentag (Mo–So), auf Basis von {full_days} vollen Tagen.",
        "en": "Bikes available by local hour (0–23, Europe/Berlin) and weekday (Mon–Sun), based on {full_days} full days.",
    },
    "availability.table.caption": {
        "de": "Verfügbare Räder je Wochentag und Uhrzeit",
        "en": "Bikes available by weekday and local hour",
    },
    "shortage.heading": {"de": "Der Morgen-Engpass um 8 Uhr", "en": "The 8am morning shortage"},
    "shortage.summary": {
        "de": "An Wochentagen waren um 8:00 Uhr durchschnittlich {share_pct}% der Stationen leer.",
        "en": "On weekdays, an average of {share_pct}% of stations were empty at 8:00.",
    },
    "shortage.aria": {
        "de": "Leerstehende Stationen am Morgen, Mo-Fr 7:30-8:30 Uhr, Top {n}",
        "en": "Stations empty in the morning, Mon-Fri 7:30-8:30, top {n}",
    },
    "shortage.caption": {
        "de": "Stationen mit den meisten leeren Minuten pro Tag im Morgenfenster (Mo–Fr 7:30–8:30 Uhr), auf Basis von {full_days} vollen Tagen.",
        "en": "Stations with the most empty minutes per day in the morning window (Mon–Fri 7:30–8:30), based on {full_days} full days.",
    },
    "shortage.table.caption": {
        "de": "Leere Minuten pro Tag im Morgenfenster, nach Station",
        "en": "Empty minutes per day in the morning window, by station",
    },
    "bezirke.heading": {"de": "Verfügbarkeit je Bezirk", "en": "Availability by Bezirk"},
    "bezirke.intro": {
        "de": "Mittlere Anzahl verfügbarer Räder je Bezirk, Mo-Fr, nach Uhrzeit (Europe/Berlin).",
        "en": "Mean number of bikes available by Bezirk, Mon-Fri, by local hour (Europe/Berlin).",
    },
    "bezirke.aria": {
        "de": "Mittlere Anzahl verfügbarer Räder je Bezirk, Mo-Fr, nach Uhrzeit (0-23 Uhr, Europe/Berlin)",
        "en": "Mean bikes available by Bezirk, Mon-Fri, by local hour (0-23, Europe/Berlin)",
    },
    "bezirke.caption": {
        "de": "Verfügbare Räder je Bezirk, Mo-Fr, je Uhrzeit (0–23 Uhr, Europe/Berlin), auf Basis von {full_days} vollen Tagen.",
        "en": "Bikes available by Bezirk, Mon-Fri, by local hour (0–23, Europe/Berlin), based on {full_days} full days.",
    },
    "bezirke.table.caption": {
        "de": "Verfügbare Räder je Bezirk und Uhrzeit (Mo-Fr)",
        "en": "Bikes available by Bezirk and local hour (Mo-Fr)",
    },
}


def t(key: str, lang: str, **kwargs: object) -> Markup:
    """Return the catalog string for ``key`` in ``lang``; raises KeyError if absent."""
    if lang not in LANGS:
        raise KeyError(f"unknown language: {lang!r}")
    return Markup(STRINGS[key][lang]).format(**kwargs)
