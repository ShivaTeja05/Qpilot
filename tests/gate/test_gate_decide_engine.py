"""A person's choice on a Run Gate card, below the web route: the engine's side.

* ``curve.exclude_well`` in the design: a well left out of, or put back into, the analysis, by
  the latest acceptance; its engine check refutes only the form (no such well, not true/false);
* the gate of a design that already leaves an option's wells out says so without a re-run;
* Studio's plan for a choice: which wells change, which waiting requests the click answers, and
  what "keep every well" leaves alone (a Prism round trip's exclusions, another card's requests).
"""

from __future__ import annotations

import pandas as pd
import pytest

from qpilot.core.proposals import InboxView
from qpilot.qpcr.design_checks import exclusion_check
from qpilot.qpcr.designs import DesignError, design_from_proposals
from qpilot.schemas_studio import MadeBy, MarkerSplit, Proposal, StudyDesign
from qpilot.studio_service import Assembly, GateChoice, _gate_plan, gate_card_of, leaves_out

CARD = "card_gate_0123456789ab"


def exclusion(well: str, excluded: bool, card: str | None = CARD, **update) -> Proposal:
    consequence = {"matters": True}
    if card is not None:
        consequence["gate"] = {"card_id": card, "option": "drop_sample", "study_id": "s"}
    base = Proposal(
        id=f"p_{abs(hash((well, excluded, card, str(update)))) % 10**16:016d}",
        study_id="abc",
        kind="curve.exclude_well",
        subject=well,
        payload={"excluded": excluded},
        consequence=consequence,
        made_by=MadeBy(kind="rule"),
        status="accepted",
    )
    return base.model_copy(update=update)


def design(excluded: tuple[str, ...] = ()) -> StudyDesign:
    return StudyDesign(
        design_id="t",
        mode="marker_split",
        marker_split=MarkerSplit(marker=""),
        excluded_wells=excluded,
    )


# ---- the design ------------------------------------------------------------------------------


def test_a_well_is_left_out_and_put_back_by_the_latest_acceptance():
    out = design_from_proposals(design(), [exclusion("run1/A1", True), exclusion("run1/A2", True)])
    assert out.excluded_wells == ("run1/A1", "run1/A2")
    back = design_from_proposals(
        design(),
        [exclusion("run1/A1", True), exclusion("run1/A2", True), exclusion("run1/A1", False)],
    )
    assert back.excluded_wells == ("run1/A2",)
    # putting back a well that is in changes nothing; pending or rejected ones never apply
    same = design_from_proposals(
        design(),
        [exclusion("run1/A3", False), exclusion("run1/A4", True, status="rejected")],
    )
    assert same.excluded_wells == ()


@pytest.mark.parametrize(
    "subject, payload",
    [("run1/A1", {"excluded": "yes"}), ("A1", {"excluded": True}), ("run1/A1", {"out": True})],
)
def test_a_malformed_exclusion_is_refused(subject, payload):
    bad = exclusion("run1/A1", True).model_copy(update={"subject": subject, "payload": payload})
    with pytest.raises(DesignError):
        design_from_proposals(design(), [bad])


def test_the_engine_check_refutes_only_the_form():
    wells = pd.DataFrame(
        {
            "run_id": ["run1", "run1"],
            "well": ["A1", "A2"],
            "target": ["GAPDH", "GAPDH"],
            "sample": ["S1", "NTC"],
            "sample_type": ["unkn", "ntc"],
        }
    )
    ok = exclusion_check("run1/A1", {"excluded": True}, wells)
    assert ok.status == "consistent" and ok.rule_ids == ["D-COVER"]
    assert ok.details == {"well_found": True, "targets": ["GAPDH"], "declared_type": "unkn"}
    assert exclusion_check("run1/A2", {"excluded": False}, wells).status == "consistent"
    for subject, payload in (
        ("run1/B9", {"excluded": True}),
        ("S1", {"excluded": True}),
        ("run1/A1", {"excluded": 1}),
    ):
        assert exclusion_check(subject, payload, wells).status == "contradicted"


# ---- Studio's plan for a choice --------------------------------------------------------------


def choice(option: str, wells: tuple[str, ...], universe: tuple[str, ...]) -> GateChoice:
    return GateChoice(
        study_id="s",
        card_id=CARD,
        rule_id="G-REP",
        verdict="warn",
        where="Replicate spread: plate run1, target GAPDH, sample S1",
        option=option,
        label=option,
        wells=wells,
        universe=universe,
        matters=True,
        pack="research-default 1.0.0",
    )


def plan(excluded, proposals, chosen):
    accepted = [p for p in proposals if p.status in ("accepted", "edited")]
    view = InboxView(head="h", proposals=proposals, accepted=accepted)
    return _gate_plan(Assembly(design(excluded), [], "d", "c"), view, chosen)


ALL = ("run1/A1", "run1/A2", "run1/A3")


def test_leaving_a_sample_out_and_answering_the_waiting_requests():
    asked = exclusion("run1/A2", True, status="proposed", made_by=MadeBy(kind="agent"))
    wrong = exclusion("run1/A1", False, status="proposed", made_by=MadeBy(kind="agent"))
    other = exclusion("run1/A3", False, card="card_gate_ffffffffffff", status="proposed")
    loose = exclusion("run1/A3", True, card=None, status="proposed", made_by=MadeBy(kind="agent"))
    got = plan((), [asked, wrong, other, loose], choice("drop_sample", ALL, ALL))
    assert got.changes == [("run1/A1", True), ("run1/A2", True), ("run1/A3", True)]
    # the agent asked for A2 and A3 (one through no card): theirs are accepted, not remade
    assert got.new == [("run1/A1", True)]
    assert sorted(got.settle) == sorted(
        [(asked.id, "accept"), (loose.id, "accept"), (wrong.id, "reject")]
    )
    assert other.id not in {pid for pid, _ in got.settle}  # another card's request stays
    assert got.elsewhere == []


def test_keeping_every_well_puts_back_only_what_a_person_left_out_here():
    mine = exclusion("run1/A1", True)  # accepted through a gate card
    got = plan(("run1/A1", "run1/A2"), [mine], choice("keep", (), ALL))
    assert got.changes == [("run1/A1", False)] and got.new == [("run1/A1", False)]
    assert got.elsewhere == ["run1/A2"]  # left out by a Prism round trip: it stays out
    assert plan((), [], choice("keep", (), ALL)).changes == []


def test_a_narrower_option_puts_the_cards_other_wells_back():
    left = [exclusion(w, True) for w in ALL]
    got = plan(ALL, left, choice("drop_outlier_well", ("run1/A2",), ALL))
    assert got.changes == [("run1/A1", False), ("run1/A3", False)]


def test_the_card_a_proposal_came_from():
    assert gate_card_of(exclusion("run1/A1", True)) == CARD
    assert gate_card_of(exclusion("run1/A1", True, card=None)) is None
    assert leaves_out(exclusion("run1/A1", True)) and not leaves_out(exclusion("run1/A1", False))
    edited = exclusion("run1/A1", True, status="edited", edits={"excluded": False})
    assert not leaves_out(edited)
