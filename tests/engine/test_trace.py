"""Trace: from a result, a sample or a well back to the wells to look at.

Synthetic tests run in CI on a toy per-well table built here (all 18 per-well columns, dilution
standards and NTCs on every plate, one well per sample and gene at the same position on every
plate, as in the demo). The ``demo_data`` tests re-measure the plan's acceptance numbers with
engine code (see ``methods/trace.md``).
"""

import dataclasses
import hashlib
import json
import re
import subprocess
import sys
import textwrap

import numpy as np
import pandas as pd
import pytest

from qpilot.core.consequence import CLASSES, classify
from qpilot.core.facts import FACT_ID
from qpilot.core.validator import validate
from qpilot.explain.trace_text import (
    CARD_TEXT,
    NOT_RUN,
    TEMPLATES,
    render_trace,
    trace_set_aside_v1,
    trace_v1,
)
from qpilot.qpcr import trace as T
from qpilot.qpcr.curves import COLUMN_ORDER
from qpilot.qpcr.study import StudySettings, build_model
from qpilot.schemas import DecisionCard, GeneRobustness
from tests.timing import work_time

REFS = ("R1", "R2", "R3", "R4")
TOY = StudySettings(candidates=REFS, marker="M(1)", group_var="M_high", headline=("UP", "FLAT"))
EFF = 1.9
ROWS = "ABCDEFGH"
BANNED = re.compile(
    r"\b(diagnos\w*|root cause|detects inhibition|error found|validated|valid run|invalid run|"
    r"faulty instrument|compliant|IVD)\b",
    re.I,
)


def _cq(log2n0):
    return 40.0 - log2n0 / np.log2(EFF)


def _run(gene):
    return f"{gene.replace('(', '').replace(')', '')}_20260101"


def toy_table(seed=7, n=80):
    """A clean study: four references with independent noise, a marker and three genes."""
    rng = np.random.default_rng(seed)
    base = rng.normal(10, 0.3, n)
    marker = rng.normal(0, 1, n)
    genes = {
        "R1": base + rng.normal(0, 0.6, n),
        "R2": base + rng.normal(0, 0.7, n),
        "R3": base + rng.normal(0, 0.8, n),
        "R4": base + rng.normal(0, 0.9, n),
        "M(1)": base + 2 * marker,
        "UP": base + 2.5 * marker + rng.normal(0, 0.4, n),
        "DOWN": base - 2.5 * marker + rng.normal(0, 0.4, n),
        "FLAT": base + rng.normal(0, 0.5, n),
    }
    rows = []
    for gene, log2 in genes.items():
        run = _run(gene)

        def row(well, sample, kind, l2, run=run, gene=gene):
            ok = bool(np.isfinite(l2))
            return {
                "run_id": run,
                "well": well,
                "sample": sample,
                "sample_type": kind,
                "target": gene,
                "target_raw": run,
                "target_type": "ref" if gene in REFS else "toi",
                "excluded": "",
                "note": "",
                "baseline": 0.0,
                "eff_indiv": EFF + rng.normal(0, 0.004),
                "r2": 0.999,
                "eff_target": EFF,
                "eff_target_sd": 0.01,
                "cq": _cq(l2) if ok else np.nan,
                "n0": 2.0**l2 if ok else np.nan,
                "amplification": ok,
                "plateau": ok,
            }

        rows += [
            row(f"{ROWS[i // 12]}{i % 12 + 1}", f"s{i:02d}", "unkn", log2[i]) for i in range(n)
        ]
        for well, sample, copies in (
            ("H1", "STD_15", 15),
            ("H2", "STD_15", 15),
            ("H3", "STD_1500", 1500),
            ("H4", "STD_1500", 1500),
        ):
            rows.append(row(well, sample, "std", np.log2(copies)))
        rows += [row(well, "water", "ntc", np.nan) for well in ("H10", "H11", "H12")]
    return pd.DataFrame(rows)[list(COLUMN_ORDER)]


def plant(table, mask, cycles):
    """Shift Cq by ``cycles`` and N0 consistently (N0 / E**cycles)."""
    out = table.copy()
    out.loc[mask, "cq"] += cycles
    out.loc[mask, "n0"] = out.loc[mask, "n0"] / out.loc[mask, "eff_target"] ** cycles
    return out


def well_of(table, sample, gene):
    w = table[(table["sample"] == sample) & (table["target"] == gene)].iloc[0]
    return f"{w['run_id']}/{w['well']}"


def context(table, settings=TOY, **kw):
    return T.build_context(table, build_model(table, settings), **kw)


@pytest.fixture(scope="module")
def clean():
    table = toy_table()
    return table, context(table)


@pytest.fixture(scope="module")
def faulty():
    """The toy with one of each fault planted (S1, S2, S5, S6, S7) on different samples."""
    t = toy_table()
    t = plant(t, (t["sample"] == "s03") & (t["target"] == "R2"), 6.0)  # S1
    t = plant(t, (t["sample"] == "s15") & (t["sample_type"] == "unkn"), 3.0)  # S2
    note = (t["sample"] == "s11") & (t["target"] == "UP")
    t.loc[note, "note"] = "PCR efficiency outlier"  # S5 failure
    t.loc[(t["sample"] == "s12") & (t["target"] == "UP"), "note"] = "Ncopy < 10"  # information
    late = (t["sample"] == "s05") & (t["target"] == "FLAT")  # S6: a late well near the NTC
    t.loc[late, "cq"] = 36.0
    t.loc[late, "n0"] = 2.0 ** ((40.0 - 36.0) * np.log2(EFF))
    ntc = (t["run_id"] == _run("FLAT")) & (t["well"] == "H10")
    t.loc[ntc, ["cq", "n0", "amplification"]] = [39.0, 0.5, True]
    t.loc[ntc, "excluded"] = "amplification in negative control"
    empty = (t["sample"] == "s07") & (t["target"] == "R2")  # S7: an empty reference well
    t.loc[empty, ["cq", "n0", "amplification"]] = [np.nan, np.nan, False]
    t.loc[empty, "note"] = "no amplification;no TD0 found"
    gone = (t["sample"] == "s09") & (t["target"] == "M(1)")  # S7: an empty marker well
    t.loc[gone, ["cq", "n0", "amplification"]] = [np.nan, np.nan, False]
    return t, context(t)


# ---------- QpcrSpace what-if helpers (no behaviour change) ----------


def test_space_helpers_reproduce_evaluate_in_every_cell(clean):
    _, ctx = clean
    space = ctx.space
    from qpilot.core.robustness import cells

    for cell in cells(space):
        assert space.evaluate_with(cell) == space.evaluate(cell)
        values, refs = space.cell_arrays(cell)
        arrays = space.evaluate_arrays(values, refs, *space.group_masks(cell))
        assert arrays.results() == space.evaluate(cell)
    primary = space.evaluate(space.primary)
    for j, gene in enumerate(space.items):
        assert ctx.base.log2fc[j] == primary[gene].log2fc
        assert ctx.base.p[j] == primary[gene].p
        assert ctx.base.conclusion[j] == primary[gene].conclusion
    masks = space.group_masks()
    masks[0][:] = False  # copies: the space keeps its groups
    assert space.group_masks()[0].any()


def test_closed_forms_match_exact_evaluation(faulty):
    _, ctx = faulty
    for i in np.flatnonzero(ctx.used):
        exact = T._exact(ctx, ("drop", int(i)))
        v = ctx.valid[i]
        assert np.allclose(ctx.loo_log2fc[i][v], exact.log2fc[v], atol=1e-12)
        assert (ctx.loo_call[i][v] == exact.conclusion[v]).all()
        for r in range(len(ctx.refs)):
            exact = T._exact(ctx, ("ref", int(i), r))
            assert np.allclose(ctx.shift_log2fc[i, r][v], exact.log2fc[v], atol=1e-12)
            assert (ctx.shift_call[i, r][v] == exact.conclusion[v]).all()


# ---------- the fingerprints on planted faults ----------


def test_a_clean_study_has_nothing_to_look_at(clean):
    _, ctx = clean
    assert ctx.s1_flag == {}
    assert not ctx.tube["s2"].any() and not ctx.tube["s4"].any()
    assert ctx.absent == []
    for gene in ctx.items:
        out = T.trace_gene(ctx, gene)
        assert out.places == []
        assert out.answer in ("nothing_to_look_at", "choice_to_look_at")
        assert {"S1", "S2", "S4", "S5", "S7"} <= set(out.checked_nothing_found)
        assert len(out.influential_nothing_unusual) == T.TRACE_THRESHOLDS["influential_top"]


@pytest.mark.parametrize(
    ("sample", "ref", "cycles"),
    [("s03", "R2", 6.0), ("s21", "R1", 6.0), ("s40", "R3", 6.0), ("s10", "R4", 8.0)],
)
def test_planted_reference_well_ranks_first_in_its_sample(sample, ref, cycles):
    table = toy_table()
    table = plant(table, (table["sample"] == sample) & (table["target"] == ref), cycles)
    ctx = context(table)
    i = ctx.unit_row[sample]
    assert ctx.s1_flag[i] == ctx.refs.index(ref)
    assert len(ctx.s1_flag) <= 3  # a borderline clean sample can tip over the threshold
    out = T.trace_sample(ctx, sample)
    first = out.places[0]
    assert (first.role, first.target, first.checks) == ("reference_well", ref, ["S1"])
    assert first.well == well_of(table, sample, ref).split("/")[1]
    assert first.values_read == "high" and first.fold_off > 1
    assert first.feeds == len(ctx.items)
    assert first.detail["S1"]["other_refs_max_abs_z"] < T.TRACE_THRESHOLDS["z"]
    for gene in ctx.items:  # the same well is a place in every gene's trace
        places = T.trace_gene(ctx, gene, top=50).places
        assert any(p.sample == sample and p.target == ref for p in places)


def test_planted_low_input_fires_s2_not_s1():
    table = toy_table()
    for sample in ("s03", "s15", "s50"):
        planted = plant(table, (table["sample"] == sample) & (table["sample_type"] == "unkn"), 3.0)
        ctx = context(planted)
        assert ctx.tube.loc[sample, "s2"], sample
        assert ctx.tube["s2"].sum() == 1
        assert ctx.s1_flag == {}
        out = T.trace_sample(ctx, sample)
        assert [p.role for p in out.places] == ["sample"]
        assert out.places[0].checks == ["S2"]
        assert out.places[0].well is None
        assert out.places[0].detail["S2"]["median_cq_shift_cycles"] > 2.5


def test_s5_notes_fail_except_amount_information(faulty):
    _, ctx = faulty
    out = T.trace_gene(ctx, "UP", top=50)
    by_sample = {p.sample: p for p in out.places}
    assert by_sample["s11"].checks == ["S5"]
    assert by_sample["s11"].role == "target_well"
    assert by_sample["s11"].detail["S5"]["note_codes"] == ["efficiency_outlier"]
    assert set(by_sample["s11"].options) == {"keep", "set_aside_value", "set_aside"}
    assert "s12" not in by_sample  # "Ncopy < 10" is information, not a failed check


def test_s6_ntc_window_is_reported_per_plate(faulty):
    table, ctx = faulty
    out = T.trace_gene(ctx, "FLAT", top=50)
    near = [p for p in out.places if "S6" in p.checks]
    assert [(p.sample, p.well) for p in near] == [("s05", well_of(table, "s05", "FLAT")[-2:])]
    assert near[0].detail["S6"]["ntc_well"] == "H10"
    assert near[0].detail["S6"]["gap_cycles"] == pytest.approx(3.0)
    nothing = set(out.checked_nothing_found)
    assert f"S6:{_run('FLAT')}" not in nothing  # its NTC amplified
    assert {f"S6:{_run(r)}" for r in REFS} <= nothing  # their NTCs stayed clean
    assert out.summary["ntc_by_plate"][_run("FLAT")]["n_ntc_amplified"] == 1
    ntc = T.trace_well(ctx, f"{_run('FLAT')}:H10")
    assert ntc.summary["role"] == "ntc"
    assert [(p.sample, p.checks) for p in ntc.places] == [("s05", ["S6"])]
    assert ntc.summary["n_study_wells_in_window"] == 1
    clean_ntc = T.trace_well(ctx, f"{_run('UP')}/H11")
    assert clean_ntc.answer == "nothing_to_look_at"
    assert clean_ntc.places == []
    assert clean_ntc.checked_nothing_found == [f"S6:{_run('UP')}"]


def test_s7_absent_samples_and_restoring_them(faulty):
    table, ctx = faulty
    absent = {e["sample"]: e for e in ctx.absent}
    assert set(absent) == {"s07", "s09"}
    ref = absent["s07"]["reasons"]
    assert [(r["reason"], r["target"], r["well"]) for r in ref] == [
        ("empty_reference_well", "R2", well_of(table, "s07", "R2").split("/")[1])
    ]
    assert ref[0]["note_codes"] == ["no_amplification", "no_td0"]
    assert absent["s09"]["reasons"][0]["reason"] == "empty_marker_well"
    assert "restore" not in absent["s09"]  # the marker decides the group: nothing to restore
    assert set(ctx.restorable) == {"s07"}
    out = T.trace_sample(ctx, "s07")
    assert out.answer == "absent"
    assert out.places == []
    restore = out.absent[0]["restore"]
    assert restore["reference"] == "R2"
    assert restore["group"] in ("M_high", "rest")
    # the fill is the mean of the other references plus R2's usual offset
    i = ctx.unit_row["s07"]
    others = [ctx.ref_values[i, r] for r in (0, 2, 3)]
    assert restore["fill_log2"] == pytest.approx(np.mean(others) + ctx.s1_offset[1], abs=1e-9)
    well = T.trace_well(ctx, well_of(table, "s07", "R2"))
    assert well.answer == "absent"
    assert well.summary["feeds"] == 0
    gene = T.trace_gene(ctx, "UP")
    assert gene.summary["n_absent_study"] == 2
    assert "S7" not in gene.checked_nothing_found
    assert gene.summary["restore_all"]["n_samples"] == 1


def test_groups_stay_fixed_in_every_option(faulty):
    _, ctx = faulty
    hi, lo = ctx.in_hi.copy(), ctx.in_lo.copy()
    for gene in ctx.items:
        T.trace_gene(ctx, gene)
    for sample in ("s03", "s15", "s07"):
        T.trace_sample(ctx, sample)
    assert (ctx.in_hi == hi).all() and (ctx.in_lo == lo).all()
    assert (ctx.space.group_masks()[0] == hi).all()


def test_groups_from_a_design(faulty):
    """A confirmed design with named groups: no marker, the restored sample keeps its group."""
    from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign

    table, _ = faulty
    groups = {f"s{i:02d}": ("A" if i < 30 else "B") for i in range(80)}
    design = StudyDesign(
        design_id="toy",
        mode="groups",
        comparison=Comparison(group_a="A", group_b="B"),
        samples={s: SampleDesign(sample=s, group=g) for s, g in groups.items()},
        reference_candidates=REFS,
        headline=("UP",),
    )
    ctx = context(table, StudySettings.from_design(design))
    assert ctx.marker is None and ctx.labels == ("A", "B")
    assert "M(1)" in ctx.items  # without a marker it is an ordinary gene
    assert {e["sample"] for e in ctx.absent} == {"s07"}  # s09 has every reference
    assert ctx.absent[0]["restore"]["group"] == "A"
    assert ctx.s1_flag[ctx.unit_row["s03"]] == REFS.index("R2")
    out = T.trace_gene(ctx, "UP", top=50)
    assert any(p.sample == "s03" and p.checks == ["S1"] for p in out.places)
    assert render_trace(out).plain.startswith("UP.")
    assert T.trace_sample(ctx, "s07").answer == "absent"


# ---------- the result: ranking, graph, facts, answers ----------


def test_gene_trace_shape_and_ranking(faulty):
    _, ctx = faulty
    out = T.trace_gene(ctx, "UP", top=50)
    assert out.root == {"kind": "gene", "id": "UP"}
    keys = [(CLASSES.index(p.consequence), -p.effect_log2) for p in out.places]
    assert keys == sorted(keys)
    assert [p.rank for p in out.places] == list(range(1, len(out.places) + 1))
    for p in out.places:
        assert p.consequence == p.options[p.via]["class"]
        assert "keep" in p.options and "set_aside" in p.options
        if p.role == "reference_well":
            assert "read_from_other_refs" in p.options
    # the graph: root first, every place's address visited, every edge consistent
    nodes = {n.id: n for n in out.nodes}
    assert out.nodes[0].id == "conclusion:UP"
    assert set(out.nodes[0].worst_below) == {c for p in out.places for c in p.checks} | {"S7"}
    for n in out.nodes:
        for child in n.children:
            assert child in nodes
    for p in out.places:
        node_id = f"well:{p.plate}/{p.well}" if p.well else f"value:{p.sample}:UP"
        assert set(p.checks) <= set(nodes[node_id].checks)
    assert out.summary["n_nodes_pruned"] > 0
    assert out.summary["n_nodes_visited"] == len(out.nodes)
    # pruning never hides a failed check: every unit with a failed check is visited
    for i, below in enumerate(ctx.row_below):
        if below and ctx.valid[i, ctx.item_col["UP"]]:
            assert f"value:{ctx.units[i]}:UP" in nodes
    # n_loo_flips is the brute-force count
    j = ctx.item_col["UP"]
    flips = sum(
        T._exact(ctx, ("drop", int(i))).conclusion[j] != ctx.base.conclusion[j]
        for i in np.flatnonzero(ctx.valid[:, j])
    )
    assert out.summary["n_loo_flips"] == flips


def test_top_limits_places_not_counts(faulty):
    _, ctx = faulty
    full = T.trace_gene(ctx, "UP", top=50)
    short = T.trace_gene(ctx, "UP", top=1)
    assert len(short.places) == 1
    assert short.places[0] == full.places[0]
    assert short.summary["n_places"] == full.summary["n_places"] == len(full.places)
    assert short.summary["n_more"] == len(full.places) - 1


def test_facts_cover_every_number_and_address(faulty):
    _, ctx = faulty
    for out in (
        T.trace_gene(ctx, "UP", top=50),
        T.trace_sample(ctx, "s03"),
        T.trace_sample(ctx, "s07"),
        T.trace_well(ctx, well_of(faulty[0], "s03", "R2")),
    ):
        assert out.facts
        prefix = "f_trace_" + T._root_slug(out.root) + "_"
        for fid, fact in out.facts.items():
            assert FACT_ID.match(fid) and fid.startswith(prefix)
            assert fact.id == fid and fact.value not in (None, "")
        for n, p in enumerate(out.places, start=1):
            assert out.facts[f"{prefix}{n}_sample"].value == p.sample
            assert isinstance(out.facts[f"{prefix}{n}_sample"].value, str)
            if p.well:
                assert out.facts[f"{prefix}{n}_well"].value == p.well
                assert out.facts[f"{prefix}{n}_plate"].value == p.plate
            if p.z is not None:
                assert out.facts[f"{prefix}{n}_z"].value == p.z


def test_answers(clean, faulty):
    table, ctx = clean
    gene = "FLAT"
    fake = {
        g: GeneRobustness(
            target=g,
            conclusion=ctx.baseline[g].call,
            fc=1.0,
            holds=1.0,
            n_cells=1,
            impact={"refs": {"flips": g == gene, "max_delta_log2fc": 0.0}},
        )
        for g in ctx.items
    }
    with_choice = T.build_context(table, build_model(table, TOY), robustness=fake)
    assert T.trace_gene(with_choice, gene).answer == "choice_to_look_at"
    assert T.trace_gene(with_choice, gene).summary["choice_flips"] == ["refs"]
    assert T.trace_gene(with_choice, "UP").answer == "nothing_to_look_at"
    _, bad = faulty
    flagged = T.trace_sample(bad, "s03")
    assert flagged.answer == (
        "place_to_look"
        if flagged.places[0].consequence != "changes_nothing"
        else "nothing_to_look_at"
    )
    assert T.trace_sample(bad, "s07").answer == "absent"


def test_trace_well_variants(faulty):
    table, ctx = faulty
    ref = well_of(table, "s03", "R2")
    a = T.trace_well(ctx, ref)
    b = T.trace_well(ctx, ref.replace("/", ":"))
    assert a.to_json() == b.to_json()
    assert a.summary["role"] == "reference_well"
    assert a.places[0].feeds == len(ctx.items)
    assert a.places[0].checks == ["S1"]
    assert set(a.places[0].options) == {"keep", "read_from_other_refs", "set_aside"}
    target = T.trace_well(ctx, well_of(table, "s20", "UP"))
    assert target.summary["role"] == "target_well"
    assert target.places[0].feeds == 1
    assert "single_target_well" in target.cannot_show
    std = T.trace_well(ctx, f"{_run('UP')}/H1")
    assert (std.answer, std.summary["role"], std.summary["feeds"]) == (
        "nothing_to_look_at",
        "control",
        0,
    )
    marker = T.trace_well(ctx, well_of(table, "s20", "M(1)"))
    assert marker.summary["role"] == "marker" and marker.summary["feeds"] == 0


def test_target_well_trace_says_it_cannot_tell_from_biology(faulty):
    table, ctx = faulty
    key = well_of(table, "s20", "UP")
    out = T.trace_well(ctx, key)
    assert out.summary["limit"] == "single_target_well"
    assert out.facts[f"f_trace_{T._root_slug(out.root)}_limit"].value == "single_target_well"
    assert "cannot tell from biology without replicates" in render_trace(out).plain
    assert "limit" not in T.trace_well(ctx, well_of(table, "s20", "R1")).summary
    # with a replicate well the limit is the replicate check that is not built (S9)
    extra = table[(table["sample"] == "s20") & (table["target"] == "UP")].assign(well="H9")
    replicated = pd.concat([table, extra], ignore_index=True)
    rep = T.trace_well(context(replicated), key)
    assert rep.summary["limit"] == "S9"
    text = render_trace(rep).plain
    assert "replicate wells are not compared yet" in text
    assert not BANNED.search(text)


def test_errors(clean):
    _, ctx = clean
    with pytest.raises(T.TraceError, match="unknown gene"):
        T.trace_gene(ctx, "NOPE")
    with pytest.raises(T.TraceError, match="control gene"):
        T.trace_gene(ctx, "R1")
    with pytest.raises(T.TraceError, match="unknown sample"):
        T.trace_sample(ctx, "s999")
    with pytest.raises(T.TraceError, match="no well"):
        T.trace_well(ctx, "NOPE_20260101:A1")
    for bad in ("A1", "a/b/c", "", "P:Q:R"):
        with pytest.raises(T.TraceError):
            T.trace_well(ctx, bad)
    for top in (0, -1, True, 1.5):
        with pytest.raises(T.TraceError):
            T.trace_gene(ctx, "UP", top=top)
    with pytest.raises(T.TraceError):
        T.trace_store(None, "x")
    with pytest.raises(T.TraceError):
        T.trace_store(None, "x", gene="UP", sample="s01")
    with pytest.raises(T.TraceError):
        T.trace_store(None, "x", gene=True)
    with pytest.raises(T.TraceError, match="unknown sample"):
        T.exclusion_effect(ctx, drop_samples=["s999"])
    with pytest.raises(T.TraceError, match="no well"):
        T.exclusion_effect(ctx, impute=["NOPE/A1"])
    no_table = dataclasses.replace(build_model(toy_table(), TOY), inputs=None)
    with pytest.raises(T.TraceError, match="columns"):
        T.build_context(pd.DataFrame({"run_id": []}), no_table)


# ---------- the card and the exclusion effect ----------


def test_card_for_a_reference_well(faulty):
    table, ctx = faulty
    out = T.trace_gene(ctx, "UP", top=50)
    rank = next(p.rank for p in out.places if p.sample == "s03")
    card = out.card(rank)
    assert card.kind == "trace_set_aside"
    assert card.id == "card_trace_s03_r2_20260101_" + well_of(table, "s03", "R2")[-2:].lower()
    assert [o.id for o in card.options] == ["keep", "read_from_other_refs", "set_aside"]
    assert card.recommended == "keep" and card.status == "open"
    assert card.rationale_template == "trace_set_aside_v1"
    for option in card.options:
        assert set(option.per_gene) == set(ctx.items)
    keep = {g: r for g, r in card.options[0].per_gene.items()}
    assert keep == ctx.space.evaluate(ctx.space.primary)
    read = card.options[1].per_gene
    effect = T.exclusion_effect(ctx, impute=[well_of(table, "s03", "R2")])
    assert {g: (r.log2fc, r.conclusion) for g, r in read.items()} == effect
    aside = card.options[2].per_gene
    effect = T.exclusion_effect(ctx, drop_samples=["s03"])
    assert {g: (r.log2fc, r.conclusion) for g, r in aside.items()} == effect
    changed = set()
    for option in card.options[1:]:
        cons = classify(
            ctx.baseline, {g: (r.log2fc, r.conclusion) for g, r in option.per_gene.items()}
        )
        changed |= set(cons.changed_calls)
    assert card.impact["flips"] is bool(changed)
    assert card.impact["n_genes_flipped"] == len(changed)
    assert card.impact["flips_anywhere"] is bool(changed)
    assert card.evidence["checks"] == ["S1"] and card.evidence["groups"] == "held fixed"
    # the same place traced from another gene gives the same card
    other = T.trace_gene(ctx, "DOWN", top=50)
    rank = next(p.rank for p in other.places if p.sample == "s03")
    assert other.card(rank) == card
    # the card kind is registered (core/card_kinds.py), so the card validates
    assert DecisionCard.model_validate(card.model_dump()) == card
    json.dumps(card.model_dump(mode="json"))


def test_card_errors(faulty):
    _, ctx = faulty
    out = T.trace_gene(ctx, "UP")
    with pytest.raises(T.TraceError):
        out.card(0)
    with pytest.raises(T.TraceError):
        out.card(len(out.places) + 1)
    loaded = T.TraceResult.model_validate_json(out.to_json())
    with pytest.raises(T.TraceError, match="context"):
        loaded.card(1)


def test_exclusion_effect(faulty):
    table, ctx = faulty
    base = {g: (b.log2fc, b.call) for g, b in ctx.baseline.items()}
    assert T.exclusion_effect(ctx) == base
    # wells that feed nothing change nothing
    ignored = [f"{_run('UP')}/H1", f"{_run('UP')}/H10", well_of(table, "s09", "UP")]
    assert T.exclusion_effect(ctx, impute=ignored) == base
    assert T.exclusion_effect(ctx, drop_samples=["s07"]) == base
    # a target well is left out: only its gene moves
    out = T.exclusion_effect(ctx, impute=[well_of(table, "s20", "UP")])
    assert [g for g in ctx.items if out[g] != base[g]] == ["UP"]
    # every reference of a sample imputed: the sample is set aside
    every = [well_of(table, "s20", r) for r in REFS]
    assert T.exclusion_effect(ctx, impute=every) == T.exclusion_effect(ctx, drop_samples=["s20"])
    # two references of one sample: each read from the remaining two
    two = T.exclusion_effect(ctx, impute=[well_of(table, "s20", "R1"), well_of(table, "s20", "R2")])
    assert two != base
    assert T.baseline(ctx) == ctx.baseline


# ---------- determinism, JSON, text ----------


def test_json_is_byte_deterministic(faulty):
    table, ctx = faulty
    other = context(table.copy())
    for gene in ctx.items:
        a, b = T.trace_gene(ctx, gene).to_json(), T.trace_gene(other, gene).to_json()
        assert a == b
        assert "NaN" not in a and "Infinity" not in a
        again = T.TraceResult.model_validate_json(a)
        assert again.to_json() == a
    assert T.trace_sample(ctx, "s07").to_json() == T.trace_sample(other, "s07").to_json()


def test_render_trace_validates_for_every_root(faulty):
    table, ctx = faulty
    results = [T.trace_gene(ctx, g) for g in ctx.items]
    results += [T.trace_sample(ctx, s) for s in ("s03", "s07", "s09", "s15", "s20")]
    results += [
        T.trace_well(ctx, k)
        for k in (
            well_of(table, "s03", "R2"),
            well_of(table, "s20", "UP"),
            well_of(table, "s07", "R2"),
            f"{_run('FLAT')}/H10",
            f"{_run('UP')}/H1",
        )
    ]
    for out in results:
        text = render_trace(out)
        assert validate(
            text.tokens, out.facts, [out.root["id"]] if out.root["kind"] == "gene" else []
        ).ok
        assert "{{" not in text.plain and "{{" not in text.html
        assert set(text.fact_ids) <= set(out.facts)
        assert not BANNED.search(text.plain), text.plain
    s03 = render_trace(T.trace_sample(ctx, "s03")).plain
    assert "s03" in s03 and "R2" in s03
    absent = render_trace(T.trace_sample(ctx, "s07")).plain
    assert "no comparison" in absent and "no amplification" in absent


def test_text_degrades_without_trace_facts(fixture_facts, fixture_cards):
    for key, template in TEMPLATES.items():
        text = template(fixture_facts, None, None)
        assert validate(text, fixture_facts).ok, key
        assert not any(ch.isdigit() for ch in text)
    assert trace_v1(fixture_facts, None, "ODC1") == NOT_RUN
    assert trace_v1({}, None, None) == NOT_RUN
    assert trace_set_aside_v1({}, fixture_cards[0], None) == CARD_TEXT
    empty = T.TraceResult(
        root={"kind": "gene", "id": "X"},
        answer="nothing_to_look_at",
        places=[],
        influential_nothing_unusual=[],
        checked_nothing_found=[],
        cannot_show=[],
        not_applicable=[],
        absent=[],
        summary={},
        nodes=[],
        facts={},
    )
    assert not any(ch.isdigit() for ch in render_trace(empty).plain)


def test_card_text_and_template_names():
    assert set(TEMPLATES) == {"trace_v1", "trace_set_aside_v1"}
    assert not any(ch.isdigit() for ch in CARD_TEXT)
    for check in T.CHECKS.values():
        for words in check.values():
            assert not any(ch.isdigit() for ch in words)
            assert not BANNED.search(words)


def test_method_card():
    card = T.METHOD_CARD
    assert {"id", "version", "inputs", "outputs", "acceptance_tests", "licence"} <= set(card)
    assert card["thresholds"] is T.TRACE_THRESHOLDS
    names = {t.split("::")[1] for t in card["acceptance_tests"]}
    assert names <= set(globals())


# =============================================================================================
# The demo study: the plan's acceptance numbers, re-measured with engine code
# =============================================================================================


@pytest.fixture(scope="module")
def demo(demo_curves):
    model = build_model(demo_curves, StudySettings())
    return demo_curves, model, T.build_context(demo_curves, model)


@pytest.mark.demo_data
def test_demo_camta2_ranking(demo):
    *_, ctx = demo
    out = T.trace_gene(ctx, "CAMTA2", top=50)
    assert out.answer == "place_to_look"
    top3 = [(p.sample, p.plate, p.well) for p in out.places[:3]]
    assert top3 == [
        ("2016", "HMBS_20080318", "K22"),
        ("1924", "HPRT1_20080303", "F23"),
        ("1772", "UBC(2)_20080220", "O13"),
    ]
    for p in out.places[:3]:
        assert (p.consequence, p.via, p.checks) == ("changes_call", "read_from_other_refs", ["S1"])
        assert p.options["read_from_other_refs"]["new_call"] == "down"
    first = out.places[0]
    assert first.cq == pytest.approx(46.055, abs=1e-3)
    assert first.fold_off == pytest.approx(5.552, abs=1e-3)
    assert first.plate_context["lowest_standard_cq"] == pytest.approx(34.67, abs=0.01)
    assert first.plate_context["n_ntc_amplified"] == 0
    assert first.plate_context["cq_rank_latest"] == 1
    assert first.plate_context["n_study_wells_with_cq"] == 351
    assert first.plate_context["same_position_late_on"] == ["HMBS_20080318", "NHLH2_20080222"]
    assert out.places[1].fold_off == pytest.approx(2.712, abs=1e-3)
    assert out.places[2].fold_off == pytest.approx(2.215, abs=1e-3)
    # 15 places: 3 change the call (the plan's "+ 8 more" counted S1 alone)
    assert out.summary["n_places"] == 15
    assert out.summary["n_places_by_class"] == {
        "changes_call": 3,
        "beyond_ci": 0,
        "changes_nothing": 12,
    }
    infl = out.influential_nothing_unusual
    assert infl[0]["sample"] == "2530"
    assert infl[0]["delta_log2"] == pytest.approx(0.0747, abs=1e-4)
    # truthful summary: 15 single samples each flip the call (not "no single tumour decides")
    assert out.summary["n_loo_flips"] == 15
    assert out.summary["loo_flip_samples"] == sorted(
        "111 1136 1496 1498 1687 1784 1820 1834 1850 1955 2016 2112 2166 2660 2784".split()
    )
    assert out.summary["max_single_effect_sample"] == "2530"
    s = out.summary
    assert (s["call"], s["n_hi"], s["n_lo"]) == ("none", 53, 294)
    assert s["log2fc"] == pytest.approx(-0.98483, abs=1e-5)
    assert s["p"] == pytest.approx(2.928e-5, rel=1e-3)
    # "NTCs clean" is claimed only for the plates where it is true
    nothing = set(out.checked_nothing_found)
    assert {"S6:HMBS_20080318", "S6:HPRT1_20080303", "S6:UBC(2)_20080220"} <= nothing
    assert "S6:CAMTA2_20080227" not in nothing and "S4" in nothing
    assert s["ntc_by_plate"]["CAMTA2_20080227"]["n_ntc_amplified"] == 2
    tube = {p.sample for p in out.places if p.role == "sample"}
    assert tube == {"2714", "2748"}
    text = render_trace(out).plain
    assert "15 different samples" in text
    assert "No single sample changes this call" not in text


@pytest.mark.demo_data
def test_demo_absent_sample_1846(demo):
    *_, ctx = demo
    out = T.trace_sample(ctx, "1846")
    assert out.answer == "absent"
    (reason,) = out.absent[0]["reasons"]
    assert (reason["reason"], reason["plate"], reason["well"], reason["target"]) == (
        "empty_reference_well",
        "HMBS_20080318",
        "A22",
        "HMBS",
    )
    assert "no_amplification" in reason["note_codes"]
    assert out.absent[0]["restore"]["group"] == "rest"
    assert out.absent[0]["restore"]["changed_calls"] == []
    assert len(ctx.absent) == 19
    one_ref = [
        e for e in ctx.absent if [r["reason"] for r in e["reasons"]] == ["empty_reference_well"]
    ]
    assert len(one_ref) == 14 == len(ctx.restorable)
    assert sum(e["reasons"][0]["plate"] == "HMBS_20080318" for e in one_ref) == 12
    restore = T.trace_gene(ctx, "PAICS").summary["restore_all"]
    assert restore["changed_calls"] == ["PAICS"]
    assert restore["n_to_first_group"] == 2
    assert ctx.baseline["PAICS"].log2fc + restore["root_delta"] == pytest.approx(1.014, abs=1e-3)
    assert "LinRegPCR found no amplification" in render_trace(out).plain


@pytest.mark.demo_data
def test_demo_well_k22(demo):
    *_, ctx = demo
    out = T.trace_well(ctx, "HMBS_20080318:K22")
    assert out.answer == "place_to_look"
    place = out.places[0]
    assert place.feeds == 58
    assert place.pull_log2 == pytest.approx(-2.473, abs=1e-3)
    assert place.fold_off == pytest.approx(5.552, abs=1e-3)
    assert place.z == pytest.approx(-9.24, abs=0.01)
    assert place.via == "read_from_other_refs"
    assert place.options["read_from_other_refs"]["changed_calls"] == ["CAMTA2", "IGSF4"]
    assert place.options["set_aside"]["changed_calls"] == ["CAMTA2"]
    effect = T.exclusion_effect(ctx, impute=["HMBS_20080318/K22"])
    assert effect["CAMTA2"][0] == pytest.approx(-1.0315, abs=1e-4)
    assert effect["IGSF4"][0] == pytest.approx(-1.0041, abs=1e-4)


@pytest.mark.demo_data
def test_demo_study_counts(demo):
    *_, ctx = demo
    base = ctx.base
    loo_flips = [
        g
        for j, g in enumerate(ctx.items)
        if (ctx.loo_call[ctx.valid[:, j], j] != base.conclusion[j]).any()
    ]
    assert loo_flips == ["CAMTA2", "DPYSL3", "IGSF4", "PRKACB_bis"]
    delta = np.abs(np.where(ctx.valid, ctx.loo_log2fc - base.log2fc, np.nan))
    assert np.nanmax(delta) == pytest.approx(0.2948, abs=1e-4)
    j, i = np.unravel_index(np.nanargmax(delta), delta.shape)[::-1]
    assert (ctx.items[j], ctx.units[i]) == ("CDH5", "1758")
    assert np.median(np.nanmax(delta, axis=0)) == pytest.approx(0.0953, abs=1e-4)
    assert (len(ctx.s1_flag), int(ctx.used.sum())) == (11, 347)
    zs = [abs(ctx.s1_z[i, r]) for i, r in ctx.s1_flag.items()]
    assert sum(z > 5 for z in zs) == 3
    offsets = dict(zip(ctx.refs, ctx.s1_offset, strict=True))
    assert offsets["HMBS"] == pytest.approx(-10.441, abs=1e-3)
    assert offsets["ALUsq(Eurogentec)"] == pytest.approx(15.850, abs=1e-3)
    # S4: nothing worth showing (the robust z alone would flag four)
    assert int(ctx.tube["s4"].sum()) == 0
    assert int((ctx.tube["z_eff"].abs() > 3.5).sum()) == 4
    assert ctx.tube["deff"].min() == pytest.approx(-0.020, abs=1e-3)
    assert ctx.tube["deff"].max() == pytest.approx(0.032, abs=1e-3)
    # S2: 7 at z > 3.5 (2 of them compared), 46 more than two cycles late
    assert int(ctx.tube["s2"].sum()) == 7
    assert int((ctx.tube["dcq"] > 2).sum()) == 46
    # S6: 21 study wells on 7 plates; 23 NTCs amplified on 11 plates
    s6 = ctx.wells[ctx.wells["s6"]]
    assert (len(s6), s6["run_id"].nunique()) == (21, 7)
    amplified = [p for p in ctx.plates.values() if p["n_ntc_amplified"]]
    assert (sum(p["n_ntc_amplified"] for p in amplified), len(amplified)) == (23, 11)
    # all 11 S1 wells read from their samples' other references at once: 5 calls change
    wells = [ctx.cells[(ctx.units[i], ctx.refs[r])][0] for i, r in ctx.s1_flag.items()]
    cons = classify(ctx.baseline, T.exclusion_effect(ctx, impute=wells))
    assert cons.changed_calls == ("CAMTA2", "IGSF4", "MTSS1", "PRKACB_bis", "PRKCZ")
    # S5: "Ncopy < 10" is information (tumour 2530's CAMTA2 well carries it)
    key = ctx.cells[("2530", "CAMTA2")][0]
    assert ctx.wells.loc[key, "note"] == "Ncopy < 10" and not ctx.wells.loc[key, "s5"]


@pytest.mark.demo_data
def test_demo_igsf4_and_card(demo):
    *_, ctx = demo
    igsf4 = T.trace_gene(ctx, "IGSF4")
    assert (igsf4.places[0].sample, igsf4.places[0].via) == ("1924", "set_aside")
    camta2 = T.trace_gene(ctx, "CAMTA2")
    card = camta2.card(1)
    assert card.id == "card_trace_2016_hmbs_20080318_k22"
    assert [o.id for o in card.options] == ["keep", "read_from_other_refs", "set_aside"]
    assert all(len(o.per_gene) == 58 for o in card.options)
    assert card.impact["flipped_genes"] == ["CAMTA2", "IGSF4"]
    assert card.impact["n_genes_flipped"] == 2 and card.impact["flips"]
    rank = next(p.rank for p in igsf4.places if p.sample == "2016")
    assert igsf4.card(rank) == card


@pytest.mark.demo_data
def test_demo_ntc_well_and_render(demo):
    *_, ctx = demo
    ntc = T.trace_well(ctx, "CAMTA2_20080227/P22")
    assert [(p.sample, p.well, p.checks) for p in ntc.places] == [("2748", "H2", ["S6"])]
    assert ntc.summary["n_study_wells_in_window"] == 4
    for gene in ctx.items:
        out = T.trace_gene(ctx, gene)
        assert validate(render_trace(out).tokens, out.facts, [gene]).ok


@pytest.mark.demo_data
def test_demo_planted_reference_well_ranks_first_in_its_sample(demo):
    """The plan says a planted +6 cycles "ranks first"; true within the sample's own trace.

    Study-wide it is never first at +6 cycles: the real faults (2016, 1924, 2753) are larger.
    """
    curves, model, ctx0 = demo
    real = {ctx0.units[i] for i in ctx0.s1_flag}
    pool = sorted((model.high | model.rest) - real)
    refs = list(ctx0.refs)
    rng = np.random.default_rng(20261018)
    unknown = curves["sample_type"] == "unkn"
    flagged = first_in_sample = first_study = 0
    for _ in range(10):
        sample, ref = str(rng.choice(pool)), str(rng.choice(refs))
        planted = plant(
            curves, unknown & (curves["sample"] == sample) & (curves["target"] == ref), 6.0
        )
        ctx = T.build_context(planted, build_model(planted, StudySettings()))
        i = ctx.unit_row[sample]
        if ctx.s1_flag.get(i) == refs.index(ref):
            flagged += 1
            p = T.trace_sample(ctx, sample).places[0]
            first_in_sample += (p.role, p.target) == ("reference_well", ref)
            top = max(ctx.s1_flag.items(), key=lambda kv: abs(ctx.s1_z[kv[0], kv[1]]))
            first_study += top[0] == i
    assert (flagged, first_in_sample, first_study) == (7, 7, 0)  # measured, seed 20261018


@pytest.mark.demo_data
def test_demo_planted_low_input_rarely_fires_s2(demo):
    """The plan says +3 cycles on every well fires S2; on the demo it needs over 4.3 cycles.

    The demo's whole-sample lateness spreads widely (46 tumours are over two cycles late), so
    +3 cycles is not unusual there (7 of 50 seeded cases in the prototype; 0 of these 10, drawn
    from tumours not already flagged). S1 never fires, as the plan says.
    """
    curves, model, ctx0 = demo
    flagged_before = {ctx0.units[i] for i in ctx0.s1_flag} | set(ctx0.tube.index[ctx0.tube["s2"]])
    pool = sorted((model.high | model.rest) - flagged_before)
    rng = np.random.default_rng(3)
    unknown = curves["sample_type"] == "unkn"
    fired = s1 = 0
    z = []
    for sample in rng.choice(pool, size=10, replace=False):
        planted = plant(curves, unknown & (curves["sample"] == sample), 3.0)
        ctx = T.build_context(planted, build_model(planted, StudySettings()))
        fired += bool(ctx.tube.loc[sample, "s2"])
        s1 += ctx.unit_row[sample] in ctx.s1_flag
        z.append(float(ctx.tube.loc[sample, "z_late"]))
    assert (fired, s1) == (0, 0)
    assert 1.5 < min(z) and max(z) < T.TRACE_THRESHOLDS["z"]


@pytest.mark.demo_data
def test_demo_trace_store_reads_only(demo_rdml_path, tmp_studies_dir, demo):
    from qpilot.core.store import StudyStore

    store = StudyStore(tmp_studies_dir)
    sid = store.ensure_study(demo_rdml_path)
    ws = store.workspace(sid)
    before = {p.name: p.read_bytes() for p in ws.iterdir() if p.is_file()}
    out = T.trace_store(store, sid, gene="CAMTA2")
    *_, ctx = demo
    assert out.to_json() == T.trace_gene(ctx, "CAMTA2").to_json()
    assert T.trace_store(store, sid, well="HMBS_20080318:K22").answer == "place_to_look"
    assert T.trace_store(store, sid, sample="1846").answer == "absent"
    after = {p.name: p.read_bytes() for p in ws.iterdir() if p.is_file()}
    assert after == before


@pytest.mark.demo_data
def test_demo_json_is_byte_deterministic_across_processes(demo):
    script = textwrap.dedent(
        """
        import hashlib
        from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir
        from qpilot.qpcr import trace as T
        from qpilot.qpcr.curves import analyse_study
        from qpilot.qpcr.study import StudySettings, build_model
        curves = analyse_study(default_cache_dir() / VERMEULEN_FILENAME)
        ctx = T.build_context(curves, build_model(curves, StudySettings()))
        text = "".join(r.to_json() for r in T.trace_all_genes(ctx).values())
        text += T.trace_sample(ctx, "1846").to_json()
        text += T.trace_well(ctx, "HMBS_20080318:K22").to_json()
        print(hashlib.sha256(text.encode()).hexdigest())
        """
    )
    runs = [
        subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
        for _ in range(2)
    ]
    first, second = (r.stdout.strip() for r in runs)
    assert first == second and len(first) == 64
    *_, ctx = demo
    here = "".join(r.to_json() for r in T.trace_all_genes(ctx).values())
    here += T.trace_sample(ctx, "1846").to_json() + T.trace_well(ctx, "HMBS_20080318:K22").to_json()
    assert hashlib.sha256(here.encode()).hexdigest() == first


@pytest.mark.demo_data
def test_demo_full_trace_under_one_second(demo):
    curves, model, _ = demo
    timings = []
    for _ in range(3):
        with work_time() as spent:
            ctx = T.build_context(curves, model)
            text = "".join(r.to_json() for r in T.trace_all_genes(ctx).values())
        timings.append(spent)
    assert text
    assert min(t.seconds for t in timings) < 1.0, timings
