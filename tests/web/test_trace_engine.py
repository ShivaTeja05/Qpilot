"""Trace's engine on small synthetic studies: every number equals a brute-force re-run.

The synthetic study has the demo's layout (one gene per plate, one well per sample and gene,
five control genes, groups from the top of a marker gene), built with a fixed seed. Each test
recomputes what Trace claims from scratch: the comparison without each sample (and pair), the
fewest samples that change a call, each control gene's share, and a planted fault in one
control-gene well (ranked first) or in every well of one sample (S2, not S1).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
import pytest

from qpilot.core.validator import validate
from qpilot.qpcr.contrast import conclude, welch
from qpilot.qpcr.study import StudySettings, build_model
from qpilot.trace import TraceError, build_context, trace_gene, trace_study, without_samples
from qpilot.trace.welch import CALL_NAMES

REFS = ("ALUsq(Eurogentec)", "HMBS", "HPRT1", "SDHA(1)", "UBC(2)")
MARKER = "MYCN(4)"
TARGETS = ("UPGENE", "EDGEGENE", "FLATGENE")
LEVEL = {"ALUsq(Eurogentec)": 22.0, "HMBS": 8.0, "HPRT1": 12.0, "SDHA(1)": 11.0, "UBC(2)": 14.0}
EFF = 1.9
ALL_FIVE = {"refs": "|".join(REFS)}  # a person's choice: normalise to every candidate


def synthetic_curves(
    n: int = 40,
    seed: int = 7,
    plant_ref: tuple[int, str, float] | None = None,
    plant_sample: tuple[int, float] | None = None,
) -> pd.DataFrame:
    """A per-well table: one plate per gene, each sample at the same well on every plate.

    ``plant_ref`` = (sample index, control gene, cycles later) delays one control-gene well;
    ``plant_sample`` = (sample index, cycles later) delays every well of one sample.
    """
    rng = np.random.default_rng(seed)
    samples = [f"T{i:03d}" for i in range(n)]
    high = np.arange(n) < max(3, round(0.15 * n))  # the top 15 % by the marker
    input_log2 = rng.normal(0.0, 0.5, n)
    effect = {MARKER: 3.0, "UPGENE": 1.6, "EDGEGENE": -1.02, "FLATGENE": 0.0}
    base = {**LEVEL, MARKER: 9.0, "UPGENE": 10.0, "EDGEGENE": 9.5, "FLATGENE": 11.0}
    rows = []
    for gene in (*REFS, MARKER, *TARGETS):
        noise = 0.25 if gene in REFS else 0.6
        values = base[gene] + input_log2 + rng.normal(0.0, noise, n) + effect.get(gene, 0.0) * high
        for i, sample in enumerate(samples):
            cycles = 0.0
            if plant_ref is not None and plant_ref[0] == i and plant_ref[1] == gene:
                cycles += plant_ref[2]
            if plant_sample is not None and plant_sample[0] == i:
                cycles += plant_sample[1]
            log2n0 = float(values[i]) - cycles * math.log2(EFF)
            rows.append(_well(gene, i, sample, "unkn", log2n0))
        rows.append(_well(gene, n, "NTC", "ntc", None))
        rows.append(_well(gene, n + 1, "STD_15", "std", math.log2(15)))
    return pd.DataFrame(rows)


def _well(gene: str, i: int, sample: str, kind: str, log2n0: float | None) -> dict:
    row, col = divmod(i, 24)
    n0 = None if log2n0 is None else 2.0**log2n0
    cq = None if log2n0 is None else 36.0 - log2n0 / math.log2(EFF)
    return {
        "run_id": f"{gene}_P1",
        "well": f"{'ABCDEFGHIJKLMNOP'[row]}{col + 1}",
        "sample": sample,
        "sample_type": kind,
        "target": gene,
        "cq": cq,
        "n0": n0,
        "eff_indiv": EFF + 0.002 * ((i * 7) % 5 - 2),
        "note": "",
    }


@pytest.fixture(scope="module")
def ctx():
    model = build_model(synthetic_curves(), StudySettings())
    return build_context(model, "synthetic", labels=("MYCN-high", "rest"))


def brute(ctx, j: int, drop: set[int]) -> tuple[float, float, str]:
    """Gene ``j``'s comparison recomputed from its values without ``drop`` (no closed form)."""
    used = ctx.comparison.used[:, j]
    x = ctx.relative[:, j]
    keep = np.array([i not in drop for i in range(len(x))])
    a = x[used & ctx.in_a & keep]
    b = x[used & ctx.in_b & keep]
    if len(a) < 2 or len(b) < 2:
        return float(np.mean(a) - np.mean(b)) if len(a) and len(b) else math.nan, math.nan, "none"
    w = welch(a, b)
    return w.diff, w.p, conclude(w.diff, w.p, ctx.rule)


def test_base_equals_the_engine(ctx):
    engine = ctx.model.space.evaluate(ctx.model.space.primary)
    for j, gene in enumerate(ctx.items):
        assert ctx.base.diff[j] == pytest.approx(engine[gene].log2fc, abs=1e-12)
        assert ctx.base.p[j] == pytest.approx(engine[gene].p, rel=1e-9)
        assert CALL_NAMES[int(ctx.base.call[j])] == engine[gene].conclusion


def test_leave_one_out_equals_a_rerun_without_each_sample(ctx):
    loo = ctx.loo
    for j in range(len(ctx.items)):
        for i in np.flatnonzero(ctx.comparison.used[:, j]):
            diff, p, call = brute(ctx, j, {int(i)})
            assert loo.after.diff[i, j] == pytest.approx(diff, abs=1e-10)
            assert loo.after.p[i, j] == pytest.approx(p, rel=1e-8, abs=1e-300)
            assert CALL_NAMES[int(loo.after.call[i, j])] == call


def test_pairs_equal_a_rerun_without_each_pair(ctx):
    j = ctx.items.index("EDGEGENE")
    rows, diff, call = ctx.comparison.pairs(j)
    for u, v in itertools.combinations(range(len(rows)), 2):
        d, _, c = brute(ctx, j, {int(rows[u]), int(rows[v])})
        assert diff[u, v] == pytest.approx(d, abs=1e-10)
        assert CALL_NAMES[int(call[u, v])] == c


def test_the_smallest_flip_set_is_the_smallest(ctx):
    for gene in ctx.items:
        traced = trace_gene(ctx, gene).data
        j = ctx.items.index(gene)
        base_call = traced.call.conclusion
        used = [int(i) for i in np.flatnonzero(ctx.comparison.used[:, j])]
        singles = [i for i in used if brute(ctx, j, {i})[2] != base_call]
        assert traced.n_flip_single == len(singles)
        flip = traced.flip
        if singles:
            assert flip.k == 1 and flip.exact
        else:
            pairs = [
                p for p in itertools.combinations(used, 2) if brute(ctx, j, set(p))[2] != base_call
            ]
            if pairs:
                assert flip.k == 2 and flip.exact
            else:
                assert flip.k is None or (flip.k >= 3 and not flip.exact)
        if flip.k is not None:
            rows = {ctx.unit_index(u) for u in flip.units}
            diff, _, call = brute(ctx, j, rows)
            assert call == flip.call_after != base_call
            assert flip.log2fc_after == pytest.approx(diff, abs=1e-10)


def test_each_samples_influence_is_listed_exactly(ctx):
    traced = trace_gene(ctx, "UPGENE").data
    j = ctx.items.index("UPGENE")
    assert traced.n_used == len(traced.samples) == int(ctx.comparison.used[:, j].sum())
    for s in traced.samples:
        diff, p, call = brute(ctx, j, {ctx.unit_index(s.unit)})
        assert s.log2fc_without == pytest.approx(diff, abs=1e-10)
        assert s.d_log2fc == pytest.approx(diff - traced.call.log2fc, abs=1e-10)
        assert s.call_without == call and s.flips == (call != traced.call.conclusion)
    ranks = [abs(s.d_log2fc) for s in traced.samples]
    assert ranks == sorted(ranks, reverse=True)


def test_control_gene_shares_add_up_to_the_fold_change(ctx):
    traced = trace_gene(ctx, "UPGENE").data
    j = ctx.items.index("UPGENE")
    used = ctx.comparison.used[:, j]
    values = ctx.values[:, j]
    target = values[used & ctx.in_a].mean() - values[used & ctx.in_b].mean()
    shares = sum(r.share_log2 for r in traced.references)
    assert target + shares == pytest.approx(traced.call.log2fc, abs=1e-10)
    for ref in traced.references:  # normalised to the other control genes only, re-run in full
        others = [r for r in ctx.refs if r != ref.gene]
        m = ctx.matrix
        rel = m["UPGENE"] - m[others].mean(axis=1)
        ok = m[others].notna().all(axis=1) & rel.notna()
        a = rel[ok & ctx.in_a].to_numpy()
        b = rel[ok & ctx.in_b].to_numpy()
        assert ref.log2fc_without == pytest.approx(welch(a, b).diff, abs=1e-10)


def test_without_samples_equals_a_rerun(ctx):
    traced = trace_gene(ctx, "EDGEGENE").data
    names = [s.unit for s in traced.samples[:3]]
    out = without_samples(ctx, "EDGEGENE", names)
    diff, p, call = brute(ctx, ctx.items.index("EDGEGENE"), {ctx.unit_index(u) for u in names})
    assert out.after.log2fc == pytest.approx(diff, abs=1e-10)
    assert out.after.p == pytest.approx(p, rel=1e-8)
    assert out.after.conclusion == call
    assert out.changes_call == (call != out.before.conclusion)
    with pytest.raises(TraceError):
        without_samples(ctx, "EDGEGENE", ["no such sample"])
    with pytest.raises(TraceError):
        without_samples(ctx, "HMBS", names)


def test_every_sentence_cites_its_numbers(ctx):
    for gene in ctx.items:
        out = trace_gene(ctx, gene)
        for tid, text in out.texts.items():
            check = validate(text, out.facts)
            assert check.ok, (gene, tid, check)
        assert {"summary", "flip", "look_first"} <= set(out.texts)
    study = trace_study(ctx)
    assert validate(study.texts["summary"], study.facts).ok


def test_a_persons_options_are_traced_as_the_engine_computes_them(ctx):
    """At a decided choice (every candidate as control genes), the base is the engine's cell."""
    other = build_context(ctx.model, "synthetic", ALL_FIVE)
    assert not other.planned and other.refs == REFS
    engine = ctx.model.space.evaluate(other.cell)
    for j, gene in enumerate(other.items):
        assert other.base.diff[j] == pytest.approx(engine[gene].log2fc, abs=1e-12)
    with pytest.raises(TraceError, match="not one qPilot checks"):
        build_context(ctx.model, "synthetic", {"refs": "HMBS|NOT_A_GENE"})


def test_names_that_are_not_results_say_why(ctx):
    for name, word in (("HMBS", "control gene"), (MARKER, "marker"), ("NOPE", "no compared gene")):
        with pytest.raises(TraceError, match=word):
            trace_gene(ctx, name)


def test_the_trace_is_deterministic(ctx):
    first = trace_gene(ctx, "EDGEGENE")
    again = trace_gene(build_context(ctx.model, "synthetic", labels=ctx.labels), "EDGEGENE")
    assert first.data.model_dump_json() == again.data.model_dump_json()
    assert first.texts == again.texts


def test_a_late_control_gene_well_is_the_place_to_look_first():
    """Plant +6 cycles in one control-gene well of a high sample: Trace points at that well."""
    curves = synthetic_curves(plant_ref=(2, "HPRT1", 6.0))
    model = build_model(curves, StudySettings())
    ctx = build_context(model, "planted", ALL_FIVE, labels=("MYCN-high", "rest"))
    unit = "T002"
    assert "HPRT1" in ctx.refs
    flagged = [ctx.units[i] for i in np.flatnonzero(ctx.ref.flagged.any(axis=1))]
    assert unit in flagged
    for gene in TARGETS:
        traced = trace_gene(ctx, gene).data
        assert traced.places, gene
        top = traced.places[0]
        assert top.kind == "reference_well" and top.unit == unit, (gene, top)
        well = next(w for w in top.wells if "reference_pull" in w.flags)
        assert (well.gene, well.plate) == ("HPRT1", "HPRT1_P1")
        # the well reads ~6 cycles late, so the sample's values are ~(1.9^6)^(1/5) too high
        assert well.pull_log2 == pytest.approx(6 * math.log2(EFF) / len(ctx.refs), abs=0.25)
        sample = next(s for s in traced.samples if s.unit == unit)
        assert "reference_pull" in sample.flags and sample.wells
        read = top.options[0]
        assert read.id == "read_from_other_references"
    study = trace_study(ctx).data
    suspect = next(s for s in study.suspects if s.unit == unit)
    assert "reference_pull" in suspect.flags
    assert any(w.key == "HPRT1_P1/" + well.well for w in suspect.wells)


def test_a_sample_late_on_every_gene_is_an_input_shift_not_a_control_gene_well():
    """Plant +3 cycles in every well of one sample: S2 fires, S1 does not."""
    curves = synthetic_curves(plant_sample=(20, 3.0))
    model = build_model(curves, StudySettings())
    ctx = build_context(model, "late", ALL_FIVE, labels=("MYCN-high", "rest"))
    i = ctx.unit_index("T020")
    assert not ctx.ref.flagged[i].any()
    assert abs(ctx.input_z[i]) > 3.5
    traced = trace_gene(ctx, "FLATGENE").data
    sample = next(s for s in traced.samples if s.unit == "T020")
    assert "input_shift" in sample.flags and "reference_pull" not in sample.flags
    assert any(p.kind == "sample" and p.unit == "T020" and "S2" in p.checks for p in traced.places)


def test_nothing_unusual_says_so():
    ctx = build_context(build_model(synthetic_curves(seed=11), StudySettings()), "calm")
    traced = trace_gene(ctx, "UPGENE")
    look = traced.data.look_first
    assert not traced.data.places and look.kind == "influential"
    assert look.unit == traced.data.samples[0].unit and look.well is not None
    assert look.well.gene == "UPGENE" and look.well.unit == look.unit
    words = traced.plain("look_first")
    assert words.startswith("Nothing unusual sits behind this result.")
    assert "keep it" in words or "cannot be told apart from biology" in words


def test_a_fold_near_the_line_never_rounds_onto_it():
    from qpilot.trace.words import Facts, near_line_fmt

    assert near_line_fmt(1.9996, 2.0) == "{:.4f}" and near_line_fmt(2.0, 2.0) == "{:.2f}"
    assert near_line_fmt(1.98, 2.0) == "{:.2f}" and near_line_fmt(3.594, 2.0) == "{:.2f}"
    facts = Facts("x", 2.0)
    token = facts.change("near", math.log2(1 / 1.99962))  # 1.99962-fold lower: no call
    assert token.endswith(" lower")
    fid = facts.fid("near")
    assert facts.facts[fid].fmt.format(facts.facts[fid].value) == "1.9996"
