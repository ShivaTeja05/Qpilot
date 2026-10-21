"""The consequence test on a toy decision space: classes, triage, cards and determinism.

``ToyGateSpace`` (``tests/gate/wells.py``) says exactly what leaving each well out does, so every
class of the scientist spec §3 is checked without the qPCR engine: ``none``, ``magnitude``,
``flip`` (a primary call changes, or a gene can no longer be compared), ``unknown``, and the
flip "elsewhere" (at other settings of the grid only).
"""

from __future__ import annotations

import json

import pytest

from qpilot.core import gate as core_gate
from qpilot.core.card_kinds import card_kind
from qpilot.core.decisions import needs_human
from qpilot.core.facts import FactRegistry
from qpilot.schemas import DecisionCard
from tests.gate.wells import ToyGateSpace, rule_eval

LABELS = {"exclude_flagged": "Leave out the flagged wells", "drop_sample": "Leave out the sample"}


def base() -> core_gate.Baseline:
    return core_gate.baseline(ToyGateSpace())


def variant(keys):
    return ToyGateSpace(keys)


def consequence(keys, **kwargs) -> core_gate.OptionConsequence:
    out, _ = core_gate.compare("exclude_flagged", keys, base(), ToyGateSpace(keys), **kwargs)
    return out


# ---------- one option ----------


def test_the_baseline_is_the_analysis_as_it_stands():
    b = base()
    assert b.items == ["g1", "g2", "g3"]
    assert b.calls == {"g1": "up", "g2": "up", "g3": "down"}
    assert b.agreement == {"g1": 1.0, "g2": 1.0, "g3": 0.5}  # g3 is down only where a == 0


def test_nothing_that_matters_is_none():
    out = consequence(["P/small"])
    assert out.consequence == "none" and out.n_flipped == 0 and out.n_flipped_anywhere == 0
    assert out.max_delta_log2fc == pytest.approx(0.1)
    assert [c.item for c in out.changed] == ["g1"]


def test_a_moved_fold_change_without_a_flip_is_magnitude():
    out = consequence(["P/big"])
    assert out.consequence == "magnitude" and out.n_flipped == 0
    assert out.max_delta_log2fc == pytest.approx(0.8)
    # the threshold is the pack's: at 1.0 log2 the same move is nothing that matters
    assert consequence(["P/big"], magnitude_log2=1.0).consequence == "none"


def test_a_changed_primary_call_is_a_flip():
    out = consequence(["P/flip"])
    assert out.consequence == "flip" and out.flipped == ["g2"] and out.n_flipped == 1
    change = next(c for c in out.changed if c.item == "g2")
    assert (change.call_keep, change.call_option) == ("up", "none")
    assert out.flipped_anywhere == ["g2"]  # the primary cell is one of the grid's cells


def test_a_gene_that_can_no_longer_be_compared_is_a_flip():
    out = consequence(["P/gone"])
    assert out.consequence == "flip" and out.flipped == ["g2"]
    change = next(c for c in out.changed if c.item == "g2")
    assert change.call_option == core_gate.WITHHELD and change.log2fc_option is None


def test_a_flip_at_other_settings_only_is_reported_but_is_not_a_primary_flip():
    out = consequence(["P/elsewhere"])
    assert out.n_flipped == 0 and out.flipped_anywhere == ["g3"]
    # g3's agreement goes from 0.5 to 1.0: a magnitude change in the grid
    assert out.max_delta_agreement == pytest.approx(0.5) and out.consequence == "magnitude"


def test_an_agreement_shift_of_a_tenth_is_magnitude():
    out = consequence(["P/elsewhere"], magnitude_agreement=0.5)
    assert out.consequence == "magnitude"
    assert consequence(["P/elsewhere"], magnitude_agreement=0.51).consequence == "none"


# ---------- classes and triage ----------


def test_the_worst_option_decides_the_class_and_the_triage():
    none, mag, flip = consequence(["P/small"]), consequence(["P/big"]), consequence(["P/flip"])
    unknown = core_gate.unknown("x", ["P/a"], "The analysis cannot be re-run without them.")
    assert core_gate.classify([]) == ("none", "ignore", None)
    assert core_gate.classify([none]) == ("none", "ignore", None)
    assert core_gate.classify([none, unknown]) == ("unknown", "defer", None)
    assert core_gate.classify([unknown, flip]) == ("flip", "human", None)
    small_mag = consequence(["P/elsewhere"]).model_copy(update={"option": "small"})
    big_mag = mag.model_copy(update={"option": "big"})
    # rescue: the option that keeps every call and moves log2FC least
    assert core_gate.classify([big_mag, small_mag, none]) == ("magnitude", "rescue", "small")


def test_run_consequences_skips_passes_and_rules_without_options_and_reuses_a_rerun():
    calls = []

    def build(keys):
        calls.append(tuple(keys))
        return ToyGateSpace(keys)

    evals = [
        rule_eval({"exclude_flagged": ["P/flip"]}),
        rule_eval({"exclude_flagged": ["P/flip"]}, scope={"plate": "Q", "target": "T"}),
        rule_eval({}, verdict="warn"),
        rule_eval({"exclude_flagged": ["P/big"]}, verdict="pass"),
    ]
    done = core_gate.run_consequences(evals, base(), build)
    assert [c.scope["plate"] for _, c, _ in done] == ["P", "Q"]
    assert calls == [("P/flip",)]  # the same wells left out are re-run once
    assert all(c.consequence == "flip" and c.triage == "human" for _, c, _ in done)


def test_options_the_plugin_answers_without_a_rerun():
    def build(keys):
        if "P/control" in keys:
            return core_gate.unchanged("", keys, "These wells are not study samples.")
        return core_gate.unknown("", keys, "The analysis cannot be re-run without them.")

    ev = rule_eval({"drop_sample": ["P/control"], "exclude_flagged": ["P/x"]})
    ((_, c, results),) = core_gate.run_consequences([ev], base(), build)
    by = {o.option: o for o in c.options}
    assert by["drop_sample"].consequence == "none" and by["drop_sample"].reason
    assert by["exclude_flagged"].consequence == "unknown"
    assert (c.consequence, c.triage) == ("unknown", "defer")
    # an unchanged option shows the analysis as it stands; an unknown one shows nothing
    assert results["drop_sample"] == base().results and results["exclude_flagged"] == {}


# ---------- cards ----------


def report(evals, headline=("g1",)):
    b = base()
    done = core_gate.run_consequences(evals, b, variant)
    return core_gate.build_report(
        {"pack": "toy", "version": "1", "hash": "0" * 64},
        {"P": "gated"},
        evals,
        done,
        b,
        {},
        LABELS,
        headline,
    )


def test_an_option_that_flips_a_call_is_an_open_card_only_a_person_decides():
    r = report([rule_eval({"exclude_flagged": ["P/flip"]})])
    (card,) = r.cards
    assert card.kind == "gate.rule" and card.status == "open" and card.decision is None
    assert card.recommended == core_gate.KEEP and card.rank == 1
    assert [o.id for o in card.options] == ["keep", "exclude_flagged"]
    assert card.options[1].label == LABELS["exclude_flagged"]
    keep, out = card.options
    assert list(keep.per_gene) == ["g2", "g1"]  # what changes first, then the headline
    assert keep.per_gene["g2"].conclusion == "up" and out.per_gene["g2"].conclusion == "none"
    assert card.impact["flips"] and card.impact["n_genes_flipped"] == 1
    assert needs_human(card)
    assert card.evidence["consequence"] == "flip" and card.evidence["flagged"] == ["P/flip"]
    (c,) = r.consequences
    assert c.card_id == card.id == core_gate.card_id_for(r.evals[0])
    assert r.triage == {"ignore": 0, "rescue": 0, "human": 1, "defer": 0}


def test_a_flip_elsewhere_is_decided_automatically_to_keep_but_still_needs_a_person():
    r = report([rule_eval({"exclude_flagged": ["P/elsewhere"]})])
    (card,) = r.cards
    assert card.status == "auto_decided" and card.decision == "keep"
    assert card.decided_by == "system" and card.reason == core_gate.AUTO_REASON_GATE
    assert not card.impact["flips"] and card.impact["flips_anywhere"]
    assert needs_human(card)  # an agent asking to apply the option must ask a person
    assert r.consequences[0].triage == "rescue"  # magnitude in the grid, no primary flip


@pytest.mark.parametrize("keys", [["P/small"], ["P/big"]])
def test_no_card_when_nothing_can_change_a_conclusion(keys):
    r = report([rule_eval({"exclude_flagged": keys})])
    assert r.cards == [] and r.consequences[0].card_id is None


def test_an_unknown_option_defers_without_a_card():
    def build(keys):
        return core_gate.unknown("", keys, "No contrast is defined yet.")

    b = base()
    ev = rule_eval({"exclude_flagged": ["P/x"]})
    done = core_gate.run_consequences([ev], b, build)
    r = core_gate.build_report({}, {}, [ev], done, b, {}, LABELS)
    assert r.cards == [] and r.triage["defer"] == 1


def test_every_gate_card_kind_escalates_and_setting_a_plate_aside_is_always_a_persons_call():
    assert card_kind("gate.rule").owner == "gate" and not card_kind("gate.rule").always_human
    assert card_kind("gate.invalidate_plate").always_human
    plate = DecisionCard(
        id="card_gate_plate",
        kind="gate.invalidate_plate",
        rank=1,
        impact={"flips": False, "n_genes_flipped": 0, "max_delta_log2fc": 0.0},
        evidence={},
        options=[],
        recommended="keep",
        rationale_template="gate_rule_v1",
        facts=[],
    )
    assert needs_human(plate)


def test_the_report_registers_every_options_counts_as_facts():
    r = report([rule_eval({"exclude_flagged": ["P/flip"], "drop_sample": ["P/big"]})])
    (c,) = r.consequences
    registry = FactRegistry(r.facts.values())  # ids follow the convention, values unique
    for option in ("exclude_flagged", "drop_sample"):
        stem = f"{core_gate.eval_id(r.evals[0])}_{option}"
        for name in ("nflip", "nflipany", "dlog2", "nexcl"):
            assert f"f_gate_{name}_{stem}" in registry
            assert f"f_gate_{name}_{stem}" in c.facts
    stem = f"{core_gate.eval_id(r.evals[0])}_exclude_flagged"
    assert r.facts[f"f_gate_nflip_{stem}"].value == 1
    assert r.facts[f"f_gate_dlog2_{stem}"].value == pytest.approx(1.1)
    assert set(c.facts) <= set(r.cards[0].facts)


def test_the_report_is_deterministic_and_strict_json():
    evals = [
        rule_eval({"exclude_flagged": ["P/flip"]}),
        rule_eval({"exclude_flagged": ["P/big"]}, scope={"plate": "Q", "target": "T"}),
        rule_eval({"exclude_flagged": ["P/elsewhere"]}, scope={"plate": "R", "target": "T"}),
    ]
    one, two = report(evals), report(evals)
    assert json.dumps(one.gate_data(), sort_keys=True) == json.dumps(
        two.gate_data(), sort_keys=True
    )
    assert one.evals_data() == two.evals_data()
    assert [c.model_dump() for c in one.cards] == [c.model_dump() for c in two.cards]
    json.dumps(one.gate_data(), allow_nan=False)  # NaN never reaches gate.json
    assert one.gate_data()["schema"] == core_gate.GATE_SCHEMA
    assert [c.rank for c in one.cards] == [1, 2]
    assert one.cards[0].impact["flips"]  # cards that flip a primary call rank first
    assert core_gate._clean({"a": float("nan"), "b": [float("inf"), 1.0]}) == {
        "a": None,
        "b": [None, 1.0],
    }


# ---------- the analysis in use ----------


def test_the_analysis_in_use_can_be_another_cell_of_the_same_grid():
    """After a person's decision moves the analysis (a == 1), the gate compares there."""
    at = core_gate.at_cell(ToyGateSpace(), {"a": 1, "not_a_dimension": 3})
    assert at.primary == {"a": 1, "b": "x"} and at.dimensions == ToyGateSpace().dimensions
    b = core_gate.baseline(at)
    assert b.calls["g3"] == "none"  # g3 is down only where a == 0
    out, _ = core_gate.compare(
        "exclude_flagged",
        ["P/elsewhere"],
        b,
        core_gate.at_cell(ToyGateSpace(["P/elsewhere"]), {"a": 1}),
    )
    assert out.consequence == "flip" and out.flipped == ["g3"]  # a primary flip there
    assert core_gate.at_cell(ToyGateSpace(), None).primary == {"a": 0, "b": "x"}
    # an option the space does not have is ignored (the space's own primary stays)
    assert core_gate.at_cell(ToyGateSpace(), {"a": 7}).primary == {"a": 0, "b": "x"}
