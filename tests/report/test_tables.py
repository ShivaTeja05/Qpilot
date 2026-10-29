"""The study's numbers as tables: the engine's values, per gene, per biological unit, per well.

Checked independently of the tables' code: the results against the stored engine output, the
per-unit values against the Prism bridge's own table, ΔCq against the per-well Cq, and the
analysis as decided against :class:`qpilot.qpcr.export.Reanalysis` at the chosen options.
"""

from __future__ import annotations

import math

import pytest

from qpilot.core.store import StudyStore
from qpilot.qpcr.contrast import welch
from qpilot.qpcr.export import Reanalysis, study_inputs
from qpilot.report.tables import (
    AS_DECIDED,
    RECOMMENDED,
    Comparison,
    build_tables,
    comparisons,
)
from tests.report.conftest import LEFT_OUT, REASON


def by_gene(table):
    return {r["gene"]: r for r in table.records()}


def test_results_are_the_engines_numbers_as_numbers(walked):
    store, study = walked["store"], walked["study"]
    tables = build_tables(store, study)
    assert tables.bases == (AS_DECIDED,) and tables.recommended is None
    result = store.get(study)
    rows = by_gene(tables.decided.results)
    assert set(rows) == set(result.contrasts)
    for gene, con in result.contrasts.items():
        row = rows[gene]
        assert row["comparison"] == "KO vs WT" and (row["group_a"], row["group_b"]) == ("KO", "WT")
        assert row["fold_change"] == con.fc and row["log2_fold_change"] == con.log2fc
        assert (row["ci95_low"], row["ci95_high"]) == (con.ci[0], con.ci[1])
        assert row["p"] == con.p and (row["n_a"], row["n_b"]) == (con.n_hi, con.n_lo)
        assert row["call"] == {"up": "up", "down": "down", "none": "no call"}[con.conclusion]
        for key in ("fold_change", "ci95_low", "ci95_high", "p"):
            assert isinstance(row[key], float)
        assert isinstance(row["n_a"], int)


def test_per_unit_rows_are_biological_units_never_wells(walked):
    store, study = walked["store"], walked["study"]
    tables = build_tables(store, study)
    units = tables.decided.per_unit.records()
    wells = tables.decided.per_well.records()
    inputs = study_inputs(store, study, read_only=True)
    bridge = inputs.table("column")
    expected = {(r.gene, r.biological_unit): r.log2_rq for r in bridge.itertuples()}
    assert {(u["gene"], u["biological_unit"]): u["log2_rq"] for u in units} == expected
    assert {u["biological_unit"] for u in units} == {"KO_1", "KO_2", "WT_1", "WT_2"}
    refs = set(inputs.refs)
    for u in units:
        assert u["wells"] == 3  # technical triplicates: one row, three wells behind it
        assert u["rq"] == pytest.approx(2 ** u["log2_rq"], rel=1e-15)
        mine = [
            w["cq"]
            for w in wells
            if w["biological_unit"] == u["biological_unit"] and w["target"] == u["gene"]
        ]
        assert u["cq_gene"] == pytest.approx(sum(mine) / len(mine), abs=1e-12)
        ref = [
            sum(c) / len(c)
            for r in sorted(refs)
            if (c := [w["cq"] for w in wells
                      if w["biological_unit"] == u["biological_unit"] and w["target"] == r])
        ]  # fmt: skip
        assert u["cq_reference"] == pytest.approx(sum(ref) / len(ref), abs=1e-12)
        assert u["delta_cq"] == pytest.approx(u["cq_gene"] - u["cq_reference"], abs=1e-12)
    # The test on these per-unit values is the engine's result.
    result = store.get(study)
    for gene, con in result.contrasts.items():
        a = [u["log2_rq"] for u in units if u["gene"] == gene and u["group"] == "KO"]
        b = [u["log2_rq"] for u in units if u["gene"] == gene and u["group"] == "WT"]
        assert welch(a, b).p == pytest.approx(con.p, rel=1e-9)


def test_per_well_has_every_well_and_the_person_s_exclusion_with_their_reason(excluded):
    store, study = excluded["store"], excluded["study"]
    tables = build_tables(store, study)
    wells = tables.decided.per_well.records()
    assert len(wells) == 60
    out = [w for w in wells if w["left_out"]]
    assert [f"{w['plate']}/{w['well']}" for w in out] == [LEFT_OUT]
    assert out[0]["left_out_reason"].startswith(REASON) and out[0]["n0_in_use"] is None
    assert out[0]["amplified"] is True and out[0]["reference_gene"] is True
    kept = [w for w in wells if not w["left_out"] and w["role"] == "unkn"]
    assert all(w["n0_in_use"] == w["n0"] for w in kept)
    unit = next(
        u for u in tables.decided.per_unit.records()
        if u["biological_unit"] == "WT_1" and u["gene"] != "GAPDH"
    )  # fmt: skip
    assert unit["wells"] == 3  # the gene's own wells; the left-out reference well is not one
    decisions = tables.decisions.records()
    accepted = [d for d in decisions if d["kind"] == "Proposal accepted"]
    assert any(d["what"].endswith(LEFT_OUT) and d["why"] == REASON for d in accepted)


def test_as_decided_follows_the_card_and_the_recommended_analysis_comes_too(walked):
    store, study = walked["store"], walked["study"]
    card = store.card(study, "card_undetermined")
    assert card.recommended == "drop"
    store.append_decision(study, card.id, "cap", "count empty wells as very low", "human", None)
    tables = build_tables(store, study)
    assert tables.bases == (AS_DECIDED, RECOMMENDED)
    decided, recommended = tables.analysis(AS_DECIDED), tables.analysis(RECOMMENDED)
    assert decided.label == "As decided" and recommended.label == "Recommended analysis"
    assert decided.results.name == "results" and recommended.results.name == "results_recommended"
    inputs = study_inputs(store, study, read_only=True)
    assert inputs.undetermined == "cap"
    engine, _ = Reanalysis(inputs).results()
    rows = by_gene(decided.results)
    assert {g: rows[g]["fold_change"] for g in engine} == {g: c.fc for g, c in engine.items()}
    stored = store.get(study).contrasts
    rec = by_gene(recommended.results)
    assert {g: rec[g]["p"] for g in stored} == {g: c.p for g, c in stored.items()}
    settings = {r[0]: r for r in tables.settings.rows}
    row = settings["Decision Card: What to do with wells that never amplified"]
    assert row[2] == "Drop empty wells" and row[3] == "a person" and row[1] != row[2]
    decisions = tables.decisions.records()
    last = [d for d in decisions if d["kind"] == "Decision Card"][-1]
    assert last["why"] == "count empty wells as very low" and last["who"] == "a person"
    about = dict(tables.about("rid").rows)
    assert about["analysis"].startswith("As decided") and "recommended" in about["also_included"]
    assert about["decision_chain_head"] == store.chain_head(study)
    assert about["analysis_record_id"] == "rid"


def test_without_the_input_file_results_come_from_the_store(
    tmp_studies_dir, fixture_result, fixture_cards
):
    store = StudyStore(tmp_studies_dir)
    store.put(fixture_result, fixture_cards)
    study = store.list_studies()[0]
    tables = build_tables(store, study)
    assert not tables.decided.rebuilt and not tables.decided.per_unit.rows
    assert "input file" in tables.decided.per_unit.note
    rows = by_gene(tables.decided.results)
    assert rows["ODC1"]["fold_change"] == fixture_result.contrasts["ODC1"].fc
    assert any("per-unit and per-well tables are empty" in n for n in tables.notes)


def test_the_tables_iterate_over_every_comparison(walked):
    store, study = walked["store"], walked["study"]
    result = store.get(study)
    extra = Comparison(
        "KO vs HET",
        "KO",
        "HET",
        result.contrasts,
        q={g: 0.5 for g in result.contrasts},
        correction="Benjamini–Hochberg across genes",
    )
    comps = comparisons(("KO", "WT"), result.contrasts, extra=[extra])
    assert [c.name for c in comps] == ["KO vs WT", "KO vs HET"]
    from qpilot.report.tables import _results_table

    table = _results_table(AS_DECIDED, comps, result, ())
    names = [r["comparison"] for r in table.records()]
    assert names.count("KO vs WT") == names.count("KO vs HET") == len(result.contrasts)
    assert "q" in table.keys() and {
        r["q"] for r in table.records() if r["comparison"] != "KO vs WT"
    } == {0.5}
    assert all(math.isfinite(r["fold_change"]) for r in table.records())


def test_the_engine_s_several_comparisons_are_read_from_the_result(walked):
    """Agent compare's contract v1: ``StudyResult.comparisons`` (read by duck type)."""
    from types import SimpleNamespace

    from qpilot.qpcr.export import study_inputs
    from qpilot.report.tables import _per_unit_table, stored_comparisons

    store, study = walked["store"], walked["study"]
    result = store.get(study)
    genes = list(result.contrasts)
    outcome = lambda primary, a, b: SimpleNamespace(  # noqa: E731
        id=f"{a}_vs_{b}",
        group_a=a,
        group_b=b,
        label=f"{a} vs {b}",
        primary=primary,
        contrasts=result.contrasts,
        p_adjusted={g: 0.2 for g in genes},
        q_value={g: 0.3 for g in genes},
        not_tested={},
    )
    block = SimpleNamespace(
        test="welch",
        correction="holm",
        comparisons=[outcome(True, "KO", "WT"), outcome(False, "WT", "KO")],
    )
    (first,) = comparisons(("KO", "WT"), result.contrasts)
    groups = {"WT_1": "WT", "WT_2": "WT", "KO_1": "KO", "KO_2": "KO"}
    comps = stored_comparisons(SimpleNamespace(comparisons=block), first, at_primary=True,
                               groups_of=groups)  # fmt: skip
    assert [c.name for c in comps] == ["KO vs WT", "WT vs KO"]
    assert comps[0].q == {g: 0.3 for g in genes} and comps[0].p_adjusted == {g: 0.2 for g in genes}
    assert "Holm" in comps[0].correction and comps[1].units == groups
    later = stored_comparisons(SimpleNamespace(comparisons=block), first, at_primary=False)
    assert later[0].q is None and later[1].note == "at the recommended options"
    from qpilot.report.tables import _results_table

    table = _results_table(AS_DECIDED, comps, result, ())
    assert {"q", "p_adjusted"} <= set(table.keys())
    second = [r for r in table.records() if r["comparison"] == "WT vs KO"]
    assert second and all(r["same_call_share"] is None for r in second)
    inputs = study_inputs(store, study, read_only=True)
    units = _per_unit_table(AS_DECIDED, comps, inputs.table("column"), inputs).records()
    swapped = {(u["biological_unit"], u["group"]) for u in units if u["comparison"] == "WT vs KO"}
    assert swapped == {("WT_1", "WT"), ("WT_2", "WT"), ("KO_1", "KO"), ("KO_2", "KO")}
    a = {(u["gene"], u["biological_unit"]): u["log2_rq"] for u in units
         if u["comparison"] == "KO vs WT"}  # fmt: skip
    b = {(u["gene"], u["biological_unit"]): u["log2_rq"] for u in units
         if u["comparison"] == "WT vs KO"}  # fmt: skip
    assert a == b  # a unit's value does not depend on the comparison it is in
