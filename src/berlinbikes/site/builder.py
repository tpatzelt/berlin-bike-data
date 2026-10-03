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
    shortage_chart,
)
from berlinbikes.site.sources import DATA_SOURCES

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

PAGES = ("index.html", "methodology.html", "impressum.html", "datenschutz.html")


def build_site(data_dir: str | Path, site_dir: str | Path) -> list[Path]:
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
    context = {
        "availability_chart": availability_chart(Path(data_dir)),
        "bezirk_availability_chart": bezirk_availability_chart(Path(data_dir)),
        "flow_chart": flow_chart(Path(data_dir)),
        "shortage_chart": shortage_chart(Path(data_dir)),
        "data_sources": DATA_SOURCES,
        "min_full_days": MIN_FULL_DAYS,
        "rain_mm_threshold": RAIN_MM_THRESHOLD,
        "cold_c_threshold": COLD_C_THRESHOLD,
    }

    written = []
    for page in PAGES:
        out_path = site_dir / page
        out_path.write_text(env.get_template(page).render(**context))
        written.append(out_path)

    css_dst = site_dir / "site.css"
    css_dst.write_text((_STATIC_DIR / "site.css").read_text())
    written.append(css_dst)

    return written
