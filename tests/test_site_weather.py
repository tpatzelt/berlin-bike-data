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

import re
import shutil

import pytest

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.weather_effect import COLD_C_THRESHOLD, RAIN_MM_THRESHOLD, weather_effect
from berlinbikes.site import build_site
from berlinbikes.site.charts import CHART_FONT_SIZE
from tests.helpers.svg import assert_axes_conventions, polyline_dasharrays
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


def _weather_table(root, caption_prefix: str, kind: str):
    for table in _find_all(root, "table"):
        captions = _find_all(table, "caption")
        if captions and _text(captions[0]).strip() == f"{caption_prefix}, {kind}":
            return table
    raise AssertionError(f"no weather table found for kind={kind!r}")


def actual_labels(table):
    return list(_table_values(table))


def _table_values(table):
    """{(row_label, hour): displayed_text} for every data cell in ``table``."""
    body_rows = _find_all(_find_all(table, "tbody")[0], "tr")
    values = {}
    for row in body_rows:
        header = _find_all(row, "th")[0]
        assert not _find_all(header, "span"), "row labels must be plain single-language text"
        row_label = _text(header).strip()
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


_LABELS = {
    "de": {"rainy": "regnerisch", "dry": "trocken", "cold": "kalt", "warm": "warm"},
    "en": {"rainy": "rainy", "dry": "dry", "cold": "cold", "warm": "warm"},
}
_CAPTIONS = {
    "de": ("Anteil leerer Stationen je Uhrzeit", {"rain": "Regen", "temperature": "Kälte"}),
    "en": ("Share of empty stations by local hour", {"rain": "rain", "temperature": "temperature"}),
}


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize(
    ("kind", "active", "other"),
    [
        ("rain", "rainy", "dry"),
        ("temperature", "cold", "warm"),
    ],
)
def test_table_matches_weather_effect_rows(synthetic_data_dir, tmp_path, kind, active, other, lang):
    data_dir, site_dir = _build_site_with_weather(synthetic_data_dir, tmp_path)
    html = (site_dir / ("index.html" if lang == "de" else "index.en.html")).read_text()
    labels = _LABELS[lang]
    active_label_de, other_label_de = labels[active], labels[other]

    result = weather_effect(connect(data_dir), kind)
    assert result.status == "ok"

    expected: dict[tuple[str, int], str] = {}
    label_by_bucket = labels
    for bucket, local_hour, _mean, share, _n_snapshots, _n_hours in result.rows:
        if bucket == "excluded":
            continue
        expected[(label_by_bucket[bucket], local_hour)] = f"{share * 100:.1f}"

    root = _parse(html)
    prefix, kinds = _CAPTIONS[lang]
    table = _weather_table(root, prefix, kinds[kind])
    # the other language's labels must not leak into this page's row labels
    other_labels = set(_LABELS["en" if lang == "de" else "de"].values()) - set(labels.values())
    assert not {label for label, _hour in actual_labels(table)} & other_labels
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
    assert "liegen noch keine stunden vor" in lowered
    assert "no hours classified as" not in lowered
    en_lowered = (site_dir / "index.en.html").read_text().lower()
    assert "no hours classified as" in en_lowered
    assert "liegen noch keine stunden vor" not in en_lowered
    for de_label in ("regnerisch", "trocken", "kalt"):
        assert f"„{de_label}“" in html.lower()
        assert f"„{de_label}“" not in en_lowered
    for en_label in ("rainy", "dry", "cold"):
        assert f"“{en_label}”" in en_lowered
        assert f"“{en_label}”" not in lowered


def test_insufficient_data_shows_not_enough_data_and_no_weather_chart(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "site"
    build_site(data_dir, site_dir)

    html = (site_dir / "index.html").read_text()
    root = _parse(html)
    assert not _weather_svgs(root)

    lowered = html.lower()
    assert "noch nicht genug daten" in lowered
    assert "not enough data yet" not in lowered
    en_lowered = (site_dir / "index.en.html").read_text().lower()
    assert "not enough data yet" in en_lowered
    assert "noch nicht genug daten" not in en_lowered
    assert "0/14" in html or "0 / 14" in html


def _weather_svg_html(html: str) -> list[str]:
    return re.findall(r'<svg[^>]*class="chart weather".*?</svg>', html, flags=re.S)


def _number(text: str) -> float:
    return float(re.search(r"(\d+[.,]\d)", text).group(1).replace(",", "."))


@pytest.mark.parametrize("lang", ["de", "en"])
def test_weather_charts_have_shared_axes_dashes_and_labels(synthetic_data_dir, tmp_path, lang):
    data_dir, site_dir = _build_site_with_weather(synthetic_data_dir, tmp_path)
    html = (site_dir / ("index.html" if lang == "de" else "index.en.html")).read_text()
    svgs = _weather_svg_html(html)
    assert len(svgs) == 2
    y_title = "Leere Stationen (%)" if lang == "de" else "Empty stations (%)"
    labels = _LABELS[lang]
    ticks = []
    for svg, (kind, active, other) in zip(svgs, [("rain", "rainy", "dry"), ("temperature", "cold", "warm")]):
        els = assert_axes_conventions(svg)
        titles = [e for e in els if "axis-title-y" in e["classes"]]
        assert titles[0]["text"] == y_title
        ticks.append([e["text"] for e in els if "tick" in e["classes"] and "axis-y" in e["groups"]])
        # active bucket dashed, baseline solid, both labelled directly on the chart
        dashes = polyline_dasharrays(els)
        assert dashes[0] not in ("none", "") and dashes[1] == "none"
        series_labels = [e["text"] for e in els if "series-label" in e["classes"]]
        assert series_labels == [labels[active], labels[other]]
        # each label sits at its own line's last point, and the two never overprint
        polys = [e for e in els if e["tag"] == "polyline"]
        texts = [e for e in els if "series-label" in e["classes"]]
        positions = [(float(t["attrs"]["x"]), float(t["attrs"]["y"])) for t in texts]
        assert positions[0] != positions[1]
        assert abs(positions[0][1] - positions[1][1]) >= CHART_FONT_SIZE
        for poly, (lx, _ly) in zip(polys, positions):
            last_x = float(poly["attrs"]["points"].split()[-1].split(",")[0])
            assert abs(lx - last_x) <= 2 * CHART_FONT_SIZE
        assert "chart-legend" not in svg
        # headline: both plotted 8:00 values
        result = weather_effect(connect(data_dir), kind)
        at_8 = {b: share * 100 for b, h, _m, share, _s, _n in result.rows if h == 8 and b != "excluded"}
        label = [e for e in els if e["tag"] == "text" and "headline" in e["groups"]][0]["text"]
        assert label.count("%") == 2
        assert labels[active] in label and labels[other] in label
        assert _number(label.split("·")[0]) == pytest.approx(round(at_8[active], 1))
        assert _number(label.split("·")[1]) == pytest.approx(round(at_8[other], 1))
        assert len([e for e in els if e["tag"] == "circle" and "headline" in e["groups"]]) == 2
    assert ticks[0] == ticks[1], "both small multiples share one y scale"


def test_missing_bucket_marks_only_the_present_one():
    from berlinbikes.site.charts import _weather_kind_chart, build_axes

    axes = build_axes(0, 20)
    by_bucket = {"dry": {h: 10.0 + h for h in range(24)}}
    chart = _weather_kind_chart("rain", by_bucket, 0, axes)
    assert [b.bucket for b in chart.buckets] == ["dry"]
    assert chart.missing_buckets == [("regnerisch", "rainy")]
    assert len(chart.headline_points) == 1
    assert chart.headline_points[0].value == 18.0
