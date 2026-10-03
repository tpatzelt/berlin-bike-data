"""Accessibility and known-value tests for the G4 rain/cold availability section.

G4 requires the G3 ``weather_effect`` metric (availability on rainy versus
dry, and cold versus warm, hours) on the article page with a table
fallback, with the ``RAIN_MM_THRESHOLD``/``COLD_C_THRESHOLD`` thresholds
stated in the text. ``synthetic_data_dir`` has no weather at all (every
snapshot is "excluded"), so most of this file copies it into ``tmp_path``
and writes weather days with ``tests.test_metric_weather._write_weather_day``
to exercise the real rainy/dry and cold/warm buckets; one test uses the
unmodified, session-scoped ``synthetic_data_dir`` to check the no-weather
case does not crash the nightly build.
"""

from __future__ import annotations

import shutil

import pytest

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.weather_effect import COLD_C_THRESHOLD, RAIN_MM_THRESHOLD, weather_effect
from berlinbikes.site import build_site
from tests.test_metric_weather import _write_weather_day
from tests.test_site_article import _ancestors, _find_all, _parse, _preorder, _text

_SCRIPTED_UTC_HOURS = {6, 7}


def _build_site_with_weather(synthetic_data_dir, tmp_path):
    data_dir = tmp_path / "data"
    shutil.copytree(synthetic_data_dir, data_dir)

    con = connect(data_dir)
    utc_dates = [row[0] for row in con.execute("SELECT DISTINCT date FROM station_status ORDER BY date").fetchall()]
    for utc_date in utc_dates:
        scripted = _SCRIPTED_UTC_HOURS if utc_date.weekday() <= 4 else set()
        _write_weather_day(data_dir, utc_date, scripted)

    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)
    return data_dir, site_dir


def _weather_svgs(root):
    return [svg for svg in _find_all(root, "svg") if "weather" in (svg.attrs.get("class") or "").split()]


def _weather_table(root, kind_en: str):
    for table in _find_all(root, "table"):
        captions = _find_all(table, "caption")
        if captions and f"Share of empty stations by local hour, {kind_en}" in _text(captions[0]):
            return table
    raise AssertionError(f"no weather table found for kind={kind_en!r}")


def _table_values(table):
    """{(row_label, hour): displayed_text} for every data cell in ``table``."""
    body_rows = _find_all(_find_all(table, "tbody")[0], "tr")
    values = {}
    for row in body_rows:
        header = _find_all(row, "th")[0]
        de_spans = [s for s in _find_all(header, "span") if s.attrs.get("lang") == "de"]
        row_label = _text(de_spans[0]).strip() if de_spans else _text(header).strip()
        cells = _find_all(row, "td")
        assert len(cells) == 24
        for hour, cell in enumerate(cells):
            values[(row_label, hour)] = _text(cell).strip()
    return values


def test_thresholds_are_stated_in_the_text(synthetic_data_dir, tmp_path):
    _data_dir, site_dir = _build_site_with_weather(synthetic_data_dir, tmp_path)
    html = (site_dir / "index.html").read_text()

    assert f"{RAIN_MM_THRESHOLD:.1f}" in html
    assert f"{COLD_C_THRESHOLD:.1f}" in html


@pytest.mark.parametrize(
    ("kind", "kind_en", "active_label_de", "other_label_de"),
    [
        ("rain", "rain", "regnerisch", "trocken"),
        ("temperature", "temperature", "kalt", "warm"),
    ],
)
def test_table_matches_weather_effect_rows(
    synthetic_data_dir, tmp_path, kind, kind_en, active_label_de, other_label_de
):
    data_dir, site_dir = _build_site_with_weather(synthetic_data_dir, tmp_path)
    html = (site_dir / "index.html").read_text()

    result = weather_effect(connect(data_dir), kind)
    assert result.status == "ok"

    expected: dict[tuple[str, int], str] = {}
    label_by_bucket = {"rainy": "regnerisch", "dry": "trocken", "cold": "kalt", "warm": "warm"}
    for bucket, local_hour, _mean, share, _n_snapshots, _n_hours in result.rows:
        if bucket == "excluded":
            continue
        expected[(label_by_bucket[bucket], local_hour)] = f"{share * 100:.1f}"

    root = _parse(html)
    table = _weather_table(root, kind_en)
    actual = _table_values(table)

    assert (active_label_de, 8) in actual, "the active bucket (rainy/cold) must have a row"
    assert (other_label_de, 0) in actual, "the other bucket (dry/warm) must have a row"

    for (label, hour), expected_text in expected.items():
        assert (label, hour) in actual, (label, hour)
        assert actual[(label, hour)] == expected_text


def test_both_weather_figures_have_figcaptions_followed_by_tables(synthetic_data_dir, tmp_path):
    _data_dir, site_dir = _build_site_with_weather(synthetic_data_dir, tmp_path)
    html = (site_dir / "index.html").read_text()

    root = _parse(html)
    order: list = []
    _preorder(root, order)

    weather_svgs = _weather_svgs(root)
    assert len(weather_svgs) == 2, "expected one rain and one temperature weather svg"

    for svg in weather_svgs:
        assert svg.attrs.get("role") == "img"
        assert svg.attrs.get("aria-label")

        figure_ancestors = [a for a in _ancestors(svg) if a.tag == "figure"]
        assert figure_ancestors, "weather svg must be inside a <figure>"
        figure = figure_ancestors[0]
        assert _find_all(figure, "figcaption"), "<figure> must have a <figcaption>"

        subtree: list = []
        _preorder(figure, subtree)
        fig_start = order.index(figure)
        fig_end = fig_start + len(subtree) - 1

        following_tables = [t for t in _find_all(root, "table") if order.index(t) > fig_end]
        assert following_tables, "a <table> fallback must follow the weather chart's <figure>"


def test_uncopied_synthetic_data_dir_has_no_weather_and_does_not_crash(synthetic_data_dir, tmp_path):
    """synthetic_data_dir (session fixture, never written to) has no weather at all."""
    site_dir = tmp_path / "site"
    build_site(synthetic_data_dir, site_dir)

    result = weather_effect(connect(synthetic_data_dir), "rain")
    assert result.status == "ok", "28 full days is enough for the guard to compute"
    buckets = {bucket for bucket, *_rest in result.rows}
    assert buckets == {"excluded"}, "with no weather collected, every snapshot is excluded"

    html = (site_dir / "index.html").read_text()
    root = _parse(html)
    assert not _weather_svgs(root), "no weather chart should render when every bucket is empty"

    lowered = html.lower()
    assert "no hours classified as" in lowered
    assert "liegen noch keine stunden vor" in lowered


def test_insufficient_data_shows_not_enough_data_and_no_weather_chart(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)

    html = (site_dir / "index.html").read_text()
    root = _parse(html)
    assert not _weather_svgs(root)

    lowered = html.lower()
    assert "not enough data yet" in lowered
    assert "noch nicht genug daten" in lowered
    assert "0/14" in html or "0 / 14" in html
