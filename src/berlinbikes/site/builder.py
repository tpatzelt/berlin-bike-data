"""Renders the jinja2 site templates into ``site_dir``.

The real charts land in later tasks; for now ``index.html`` only switches
between its content and a "not enough data yet" state, based on whether any
Parquet data has been collected under ``data_dir``.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from berlinbikes.analysis import MIN_FULL_DAYS
from berlinbikes.analysis.weather_effect import COLD_C_THRESHOLD, RAIN_MM_THRESHOLD
from berlinbikes.site.charts import (
    availability_chart,
    bezirk_availability_chart,
    flow_chart,
    footprint_chart,
    MAP_BINS,
    MAP_DEFAULT_HOUR,
    MAP_NO_DATA_RADIUS,
    map_profile_chart,
    Y_TICK_TARGET,
    shortage_chart,
    weather_effect_chart,
)
from berlinbikes.site.i18n import LANGS, t
from berlinbikes.site.profiles import profiles_payload, write_profiles_json
from berlinbikes.site.sources import DATA_SOURCES

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

PAGES = ("index.html", "map.html", "methodology.html", "impressum.html", "datenschutz.html")


def page_url(page: str, lang: str) -> str:
    """File name of ``page`` (a German ``PAGES`` entry) in ``lang``."""
    if lang == "de":
        return page
    if lang == "en":
        return page.removesuffix(".html") + ".en.html"
    raise KeyError(f"unknown language: {lang!r}")


DEFAULT_OPERATOR = {"name": "[NAME]", "address": "[ANSCHRIFT]", "email": "[E-MAIL]"}


def build_site(data_dir: str | Path, site_dir: str | Path, operator: dict[str, str] | None = None) -> list[Path]:
    """Render ``PAGES`` and copy static assets into ``site_dir``.

    Writes only under ``site_dir``; never touches the repository.
    """
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    map_payload = profiles_payload(data_dir)
    map_default = map_payload["stations"][0] if map_payload["status"] == "ok" and map_payload["stations"] else None
    context = {
        "map_payload": map_payload,
        "map_default": map_default,
        "map_default_hour": MAP_DEFAULT_HOUR,
        "map_bins": [{"min": lo, "radius": r, "label_key": f"map.bin.{i}"} for i, (lo, r) in enumerate(MAP_BINS)],
        "map_no_data_radius": MAP_NO_DATA_RADIUS,
        "map_y_tick_target": Y_TICK_TARGET,
        "map_chart": map_profile_chart(map_default["curve"]) if map_default else None,
        "availability_chart": availability_chart(Path(data_dir)),
        "bezirk_availability_chart": bezirk_availability_chart(Path(data_dir)),
        "flow_chart": flow_chart(Path(data_dir)),
        "shortage_chart": shortage_chart(Path(data_dir)),
        "weather_chart": weather_effect_chart(Path(data_dir)),
        "footprint_chart": footprint_chart(Path(data_dir)),
        "data_sources": DATA_SOURCES,
        "min_full_days": MIN_FULL_DAYS,
        "rain_mm_threshold": RAIN_MM_THRESHOLD,
        "cold_c_threshold": COLD_C_THRESHOLD,
        "operator": operator or DEFAULT_OPERATOR,
    }

    written = []
    for page in PAGES:
        for lang in LANGS:
            out_path = site_dir / page_url(page, lang)
            page_context = {
                **context,
                "lang": lang,
                "page": page,
                "t": lambda key, _lang=lang, **kw: t(key, _lang, **kw),
                "url": lambda target, _lang=lang: page_url(target, _lang),
                "page_urls": {other: page_url(page, other) for other in LANGS},
                "counterpart_lang": "en" if lang == "de" else "de",
                "counterpart_url": page_url(page, "en" if lang == "de" else "de"),
            }
            out_path.write_text(env.get_template(page).render(**page_context))
            written.append(out_path)

    for asset in ("site.css", "map.js"):
        asset_dst = site_dir / asset
        asset_dst.write_text((_STATIC_DIR / asset).read_text())
        written.append(asset_dst)

    written.append(write_profiles_json(data_dir, site_dir))

    return written
