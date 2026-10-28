"""A figure per gene: dots are biological units, the bar the group mean and 95 % CI, the call the
engine's, the caption the engine's facts; the SVG is deterministic, editable and safe."""

from __future__ import annotations

import math
import re
import struct
from dataclasses import replace

import pytest
from scipy import stats

from qpilot.report import figures as F
from qpilot.report.tables import build_tables

GENE = "1-Mar"


@pytest.fixture
def tables(walked):
    return build_tables(walked["store"], walked["study"])


def test_dots_are_units_and_the_numbers_are_the_engines(walked, tables):
    fig = F.gene_figure(tables, GENE)
    con = walked["store"].get(walked["study"]).contrasts[GENE]
    assert [g.name for g in fig.groups] == ["KO", "WT"]
    assert [g.n for g in fig.groups] == [2, 2]  # 2 units each, not the 6 wells behind them
    assert (fig.fc, fig.p, fig.n_a, fig.n_b) == (con.fc, con.p, con.n_hi, con.n_lo)
    units = {
        (u["group"], u["biological_unit"]): u["log2_rq"]
        for u in tables.decided.per_unit.records()
        if u["gene"] == GENE
    }
    for g in fig.groups:
        assert {(g.name, u): v for u, v in g.points} == {k: v for k, v in units.items()
                                                       if k[0] == g.name}  # fmt: skip
        values = [v for _, v in g.points]
        mean = sum(values) / 2
        half = stats.t.ppf(0.975, 1) * stats.tstd(values) / math.sqrt(2)
        assert g.mean == pytest.approx(mean) and g.ci_lo == pytest.approx(mean - half)
    caption = fig.caption
    for words in (
        "KO n = 2",
        "WT n = 2",
        "never counted as n",
        "Welch's t test",
        "No correction for multiple testing across the 1 genes compared",
        "reference genes GAPDH",
        "efficiency: LinRegPCR",
        "Analysis: as decided",
    ):
        assert words in caption, words
    assert F.fmt.fold(con.fc) in caption


def test_svg_structure_is_deterministic_editable_and_safe(tables):
    fig = F.gene_figure(tables, GENE)
    svg = F.figure_svg(fig)
    assert svg == F.figure_svg(F.gene_figure(tables, GENE))
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns=')
    assert 'width="85mm"' in svg and "<script" not in svg and "href" not in svg
    assert len(re.findall(r'<circle class="unit"', svg)) == 4
    assert len(re.findall(r'class="mean"', svg)) == 2
    assert len(re.findall(r'class="ci"', svg)) == 6  # a line and two caps per group
    assert re.search(r'<text class="gene"[^>]*>1-Mar</text>', svg)  # text stays text
    assert re.search(r'<text class="group"[^>]*>KO</text>', svg)
    assert '<polygon class="call-glyph"' not in svg  # no call: an open circle, not a triangle
    assert '<circle class="call-glyph"' in svg and ">no call · " in svg
    assert f'<desc id="fig-desc">{F._e(fig.caption)}</desc>' in svg
    for colour in (F.PALETTE[0], F.PALETTE[1]):
        assert colour in svg
    hostile = replace(fig, gene='<script>alert(1)</script>"', caption="<b>&")
    bad = F.figure_svg(hostile)
    assert "<script>" not in bad and "&lt;script&gt;" in bad and "&lt;b&gt;&amp;" in bad


def test_png_is_300_dpi_one_journal_column_wide(tables):
    fig = F.gene_figure(tables, GENE)
    png = F.figure_png(fig)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert width == pytest.approx(85 / 25.4 * 300, abs=2)
    assert height == pytest.approx(85 / 25.4 * 300 * F.H / F.W, abs=2)
    assert b"Software" not in png[:4096]  # no tool or time stamp
    panel = F.panel_png([fig, fig])
    assert struct.unpack(">I", panel[16:20])[0] == pytest.approx(2 * width, abs=3)


def test_source_csv_has_one_row_per_dot(tables):
    fig = F.gene_figure(tables, GENE)
    text = F.figure_csv(fig)
    lines = text.strip().split("\n")
    assert lines[0] == ",".join(F.SOURCE_COLUMNS)
    assert len(lines) == 1 + 4
    first = dict(zip(F.SOURCE_COLUMNS, lines[1].split(","), strict=True))
    unit = fig.groups[0].points[0]
    assert first["biological_unit"] == unit[0] and float(first["log2_rq"]) == unit[1]
    assert first["group_n"] == "2" and first["analysis"] == "as_decided"


def test_recommended_basis_and_unknown_genes(walked):
    store, study = walked["store"], walked["study"]
    store.append_decision(study, "card_undetermined", "cap", "very low, not missing", "human", None)
    tables = build_tables(store, study)
    fig = F.gene_figure(tables, GENE, "recommended")
    assert fig.basis == "recommended" and "every Decision Card at its recommended option" in (
        fig.caption
    )
    decided = F.gene_figure(tables, GENE).caption
    label = next(o.label for o in store.card(study, "card_undetermined").options if o.id == "cap")
    assert f"Analysis: as decided (what to do with wells that never amplified: {label})" in decided
    with pytest.raises(F.FigureError, match="not a gene compared"):
        F.gene_figure(tables, "GAPDH")  # the reference gene is not compared
    with pytest.raises(F.FigureError, match="no comparison"):
        F.gene_figure(tables, GENE, comparison="A vs B")


def test_swarm_keeps_dots_apart_and_inside_the_band():
    ys = [100.0] * 7 + [101.0, 103.0, 150.0]
    xs = F.swarm(ys, 2.0, 50.0)
    for i in range(len(ys)):
        for j in range(i):
            assert math.hypot(xs[i] - xs[j], ys[i] - ys[j]) >= 4.0 - 1e-6
    assert xs[-1] == 0.0  # alone at its height: on the centre line
    squeezed = F.swarm([100.0] * 40, 2.0, 10.0)
    assert max(abs(x) for x in squeezed) == pytest.approx(10.0)


def test_p_in_words():
    assert F._plain(F.p_words(2.3e-8)) == "p = 2.3 × 10⁻⁸"
    assert F._plain(F.p_words(0.0496)) == "p = 0.0496"  # never rounded across 0.05
    assert F._plain(F.p_words(0.2)) == "p = 0.20"
    assert F._plain(F.p_words(None)) == "p not computed"
