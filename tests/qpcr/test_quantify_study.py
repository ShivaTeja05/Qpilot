"""A study whose purpose is to quantify samples (``design.purpose`` quantify), engine and Studio.

Real data: the StepOne RDML export (RNase P, five standards whose quantities the file declares,
two populations as unknowns). The design is a person's: quantify samples, no comparison and no
reference gene. Every number is the engine's (:mod:`qpilot.qpcr.absolute`).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from qpilot.core.record import rerun_compare, verify, write_record
from qpilot.core.store import StudyStore
from qpilot.qpcr import absolute as ab
from qpilot.qpcr import quantify_study as qs
from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
from qpilot.qpcr.design_checks import check_with_facts
from qpilot.qpcr.design_rules import purpose_field
from qpilot.qpcr.designs import (
    DesignError,
    design_from_proposals,
    is_legacy_design,
    purpose_of,
    vermeulen_design,
)
from qpilot.qpcr.inspect import file_facts
from qpilot.qpcr.study import StudySettings, run_study
from qpilot.schemas_studio import DesignField, MadeBy, MarkerSplit, Proposal, StudyDesign

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
STEPONE = CORPUS / "rdml" / "stepone-2.3-rdml-1.0" / "stepone_std.rdml"


def quantify_design(**update) -> StudyDesign:
    return StudyDesign(
        design_id="studio", mode="groups", purpose="quantify", amp_calls=STUDIO_AMP_CALLS, **update
    )


def accepted(kind: str, subject: str, payload: dict, n: int = 1) -> Proposal:
    return Proposal(
        id=f"p_{n}",
        study_id="0" * 12,
        kind=kind,
        subject=subject,
        payload=payload,
        made_by=MadeBy(kind="person"),
        status="accepted",
    )


# ---- the design field ------------------------------------------------------------------------


def test_purpose_is_absent_by_default_so_every_design_hash_is_unchanged():
    demo = vermeulen_design()
    assert demo.purpose is None and "purpose" not in demo.canonical()
    assert is_legacy_design(demo)
    with_none = demo.model_copy(update={"purpose": None})
    assert with_none.design_hash() == demo.design_hash()


def test_a_quantification_design_compares_no_groups():
    design = quantify_design()
    assert '"purpose":"quantify"' in design.canonical()
    with pytest.raises(ValueError, match="compares no groups"):
        quantify_design(comparison={"group_a": "A", "group_b": "B"})
    with pytest.raises(ValueError, match="mode 'groups'"):
        StudyDesign(mode="marker_split", marker_split=MarkerSplit(marker="X"), purpose="quantify")
    with pytest.raises(ValueError, match="needs a comparison"):  # comparing groups still does
        StudyDesign(mode="groups")


def test_the_purpose_sets_the_comparison_aside_in_any_order():
    base = StudyDesign(design_id="blank", mode="marker_split", marker_split=MarkerSplit(marker=""))
    group = [
        accepted("design.group", s, {"group": g}, i)
        for i, (s, g) in enumerate((("a1", "A"), ("a2", "A"), ("b1", "B"), ("b2", "B")), 1)
    ]
    comparison = accepted("design.comparison", "comparison", {"group_a": "A", "group_b": "B"}, 9)
    purpose = accepted("design.purpose", "purpose", {"purpose": "quantify"}, 10)
    first = design_from_proposals(base, [*group, purpose, comparison])
    last = design_from_proposals(base, [*group, comparison, purpose])
    assert first == last and first.purpose == "quantify" and first.comparison is None
    assert first.samples["a1"].group == "A"  # groups stay: they sort and label the samples
    back = accepted("design.purpose", "purpose", {"purpose": "compare"}, 11)
    again = design_from_proposals(base, [*group, comparison, purpose, back])
    assert again.purpose is None and again.comparison is not None  # the comparison comes back
    assert purpose_of([purpose]) == "quantify" and purpose_of([purpose, back]) == "compare"
    with pytest.raises(DesignError, match="purpose"):
        design_from_proposals(base, [accepted("design.purpose", "purpose", {"purpose": "x"})])


# ---- classes and what changes what is reported ----------------------------------------------


def _estimate(n_detected=3, log10_q=2.0, flags=()) -> ab.UnknownEstimate:
    return ab.UnknownEstimate(
        unit="u",
        target="T",
        samples=("u",),
        wells=(),
        curves=("T @ r",),
        n_wells=3,
        n_detected=n_detected,
        mean_cq=30.0 if n_detected else None,
        log10_quantity=log10_q,
        log10_low=None,
        log10_high=None,
        flags=tuple(flags),
    )


@pytest.mark.parametrize(
    ("kwargs", "cls"),
    [
        ({}, "quantified"),
        (
            {"n_detected": 0, "log10_q": None, "flags": ("not_detected", "below_lod")},
            "not_detected",
        ),
        ({"log10_q": None}, "no_curve"),
        ({"flags": ("below_lowest", "below_lod")}, "below_lod"),
        ({"flags": ("below_lowest", "below_loq")}, "below_loq"),
        ({"flags": ("below_lowest",)}, "below_lowest"),
        ({"flags": ("above_top",)}, "above_top"),
        ({"flags": ("some_not_detected",)}, "quantified"),
    ],
)
def test_each_sample_result_has_one_class(kwargs, cls):
    assert qs.class_of(_estimate(**kwargs)) == cls
    assert cls in qs.CLASSES and qs.CLASS_WORDS[cls]


def test_a_reported_result_changes_with_its_class_or_more_than_twofold():
    q = qs.Reported("quantified", 2.0)
    assert not q.changes(qs.Reported("quantified", 2.0 + math.log10(1.9)))
    assert q.changes(qs.Reported("quantified", 2.0 + math.log10(2.1)))
    assert q.changes(qs.Reported("below_lod", 2.0))
    low = qs.Reported("below_loq", 0.5)
    assert not low.changes(qs.Reported("below_loq", 2.0))  # not reported as a number


# ---- the study on a real file ----------------------------------------------------------------


@pytest.fixture(scope="module")
def stepone():
    design = quantify_design()
    result, cards, grid = run_study(STEPONE, StudySettings.from_design(design))
    return design, result, cards, grid


def test_a_stepone_quantification_study(stepone):
    design, result, cards, grid = stepone
    assert qs.is_quantify_result(result) and not result.contrasts and not result.robustness
    facts = {k: f.value for k, f in result.facts.items()}
    assert facts["f_qn_items"] == 2 and facts["f_qn_quantified"] == 2 and facts["f_qn_assays"] == 1
    inputs = qs.inputs_for(STEPONE, _curves(design), design)  # the engine's own numbers
    found = ab.quantify(
        inputs.table, declared=inputs.declared, rule_id="linregpcr", quantities=inputs.quantities
    )
    first = grid[(grid["amp_call_idx"] == 0) & (grid["loq_cv_idx"] == 0)].set_index("item")
    for u in found.unknowns:
        assert first.loc[qs.item_key(u.target, u.unit), "log10_quantity"] == u.log10_quantity
    assert len(grid) == 2 * len(STUDIO_AMP_CALLS) * len(qs.LOQ_OPTIONS)
    by_id = {c.id: c for c in cards}
    assert set(by_id) == set(qs.CARD_IDS.values())
    for card in cards:  # nothing on this clean run changes what is reported
        assert card.status == "auto_decided" and card.decided_by == "system"
        assert card.reason == qs.AUTO and not card.impact["flips"]


def _curves(design):
    from qpilot.qpcr.curves import analyse_study

    settings = StudySettings.from_design(design)
    return analyse_study(STEPONE, settings.experiment_id, settings.candidates, settings.curves)


def test_a_quantification_study_is_deterministic_and_its_record_reruns(stepone, tmp_path):
    design, result, cards, grid = stepone
    again = run_study(STEPONE, StudySettings.from_design(design))
    assert again[0] == result and again[1] == cards and again[2].equals(grid)
    store = StudyStore(tmp_path / "studies")
    study_id = store.ensure_study(STEPONE, design=design)
    assert study_id == result.study_id
    write_record(store, study_id, tmp_path / "record")
    assert verify(tmp_path / "record").ok
    report = rerun_compare(tmp_path / "record", tmp_path / "rerun")
    assert report.same, report.differs
    assert "grid.csv" in report.compared


def test_the_analysis_in_use_follows_the_cards():
    from qpilot.schemas import DecisionCard

    design = quantify_design()
    decided = DecisionCard(
        id=qs.CARD_IDS["amp_call"],
        kind=qs.AMP_KIND,
        rank=1,
        impact={"flips": True},
        evidence={},
        options=[],
        recommended="linregpcr",
        rationale_template=qs.TEMPLATES["amp_call"],
        facts=[],
        status="decided",
        decision="cq_le_35",
    )
    loq = decided.model_copy(
        update={"id": qs.CARD_IDS["loq_cv"], "kind": qs.LOQ_KIND, "decision": "loq_cv_25"}
    )
    assert qs.analysis_in_use(design, []) == {"amp_call": "linregpcr", "loq_cv": "0.35"}
    assert qs.analysis_in_use(design, [decided, loq]) == {"amp_call": "cq_le_35", "loq_cv": "0.25"}


# ---- what the design needs, checks and the rules' proposal (blind: no Cq read) ----------------


def test_standards_with_quantities_are_what_a_quantification_needs():
    facts = file_facts(STEPONE)
    assert qs.standards_needed(quantify_design(), facts) is None  # the file declares them

    class NoQuantities:
        wells = facts.wells
        sample_quantities: dict = {}

    found = qs.standards_needed(quantify_design(), NoQuantities())
    assert found is not None and found.startswith("no standards with a quantity yet")

    class NoStandards:
        wells = facts.wells.assign(sample_type="unkn")
        sample_quantities: dict = {}

    assert qs.standards_needed(quantify_design(), NoStandards()) == qs.NO_STANDARDS


def test_d_purpose_never_decides_for_a_person():
    facts = file_facts(STEPONE)
    probe = Proposal(
        study_id="0" * 12,
        kind="design.purpose",
        subject="purpose",
        payload={"purpose": "quantify"},
        made_by=MadeBy(kind="rule"),
    )
    check = check_with_facts(probe, facts)
    assert check.status == "cannot_check" and check.rule_ids == ["D-PURPOSE"]
    assert check.details == {"n_standards": 5, "n_with_quantity": 5}
    bare = type("Facts", (), {})()
    bare.wells, bare.sample_types, bare.sample_quantities = facts.wells, {}, {}
    bare.summary = facts.summary
    refuted = check_with_facts(probe, bare)
    assert refuted.status == "contradicted" and "no standards" in refuted.note
    compare = check_with_facts(probe.model_copy(update={"payload": {"purpose": "compare"}}), facts)
    assert compare.status == "cannot_check"


def test_d_nguard_does_not_apply_to_a_quantification():
    facts = file_facts(STEPONE)
    comparison = Proposal(
        study_id="0" * 12,
        kind="design.comparison",
        subject="comparison",
        payload={"group_a": "A", "group_b": "B"},
        made_by=MadeBy(kind="person"),
    )
    purpose = accepted("design.purpose", "purpose", {"purpose": "quantify"})
    check = check_with_facts(comparison, facts, accepted=[purpose])
    assert check.status == "cannot_check" and check.note.startswith("not applicable")
    plain = check_with_facts(comparison, facts)  # comparing groups: the n-guard itself
    assert plain.rule_ids == ["D-NGUARD"] and not plain.note.startswith("not applicable")


def test_the_rules_propose_quantify_only_from_declared_quantities_and_no_groups():
    facts = file_facts(STEPONE)
    samples = {s: q[0][0] for s, q in facts.sample_quantities.items() if q}
    series = DesignField(
        kind="design.dilution_series",
        subject="STD",
        value={"experiment_id": "e", "samples": samples},
        cites=[],
    )
    proposed = purpose_field([series], facts)
    assert proposed is not None and proposed.value == {"purpose": "quantify"}
    assert proposed.alternatives == [{"purpose": "compare"}] and proposed.level == "Moderate"
    group = DesignField(kind="design.group", subject="x", value={"group": "A"}, cites=[])
    assert purpose_field([series, group], facts) is None  # a sheet names groups
    named = series.model_copy(
        update={"value": {"experiment_id": "e", "samples": {"STD_10": 10, "STD_100": 100}}}
    )
    assert purpose_field([named], facts) is None  # names alone are no sign
    assert purpose_field([series], None) is None
