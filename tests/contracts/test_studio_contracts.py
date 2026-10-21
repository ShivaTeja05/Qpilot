"""The Studio contracts round-trip through JSON and enforce their own consistency rules."""

import pytest
from pydantic import ValidationError

from qpilot.schemas_studio import (
    PROPOSAL_KINDS,
    AmpCallRule,
    Comparison,
    DesignProposal,
    Evidence,
    InspectSummary,
    MadeBy,
    MarkerSplit,
    PrismBundle,
    PrismDiffItem,
    PrismTable,
    Proposal,
    ProposalCheck,
    ProposalEntry,
    ProposalOutcome,
    QuarantineEntry,
    SampleDesign,
    StudyDesign,
    TargetDesign,
    WellCall,
)


def _roundtrip(model):
    again = type(model).model_validate_json(model.model_dump_json())
    assert again == model
    return again


def _proposal(**update) -> Proposal:
    base = Proposal(
        study_id="abc123def456",
        kind="design.well_role",
        subject="comp_50_NTC",
        payload={"role": "ntc"},
        evidence=[Evidence(kind="text", ref="t_0123456789ab", note="name pattern")],
        check=ProposalCheck(status="consistent", rule_ids=["D-NTC"], details={"n": 3}),
        level="Moderate",
        reasons=["name contains NTC"],
        made_by=MadeBy(kind="rule"),
        created_at="2026-10-17T21:00:00Z",
    )
    return base.model_copy(update=update)


def test_proposal_roundtrip_and_effective_payload():
    p = _roundtrip(_proposal(edits={"role": "nrt"}, status="edited", decided_by="human"))
    assert p.effective_payload() == {"role": "nrt"}
    assert p.stage == "design"


def test_proposal_rejects_unknown_kind_and_non_human_decider():
    with pytest.raises(ValidationError):
        _proposal().model_validate({**_proposal().model_dump(), "kind": "design.anything"})
    with pytest.raises(ValidationError):
        Proposal.model_validate({**_proposal().model_dump(), "decided_by": "agent"})


def test_every_kind_has_a_stage():
    stages = {"design", "curve", "choice", "prism", "stage"}
    assert {k.split(".")[0] for k in PROPOSAL_KINDS} == stages


def test_entry_and_outcome_roundtrip():
    entry = ProposalEntry(
        seq=1,
        prev_hash="0" * 64,
        action="propose",
        proposal_id="p_1",
        actor="agent",
        at="2026-10-17T21:00:00Z",
        proposal=_proposal(id="p_1"),
    )
    _roundtrip(entry)
    _roundtrip(ProposalOutcome(status="refused", head="0" * 64, reason="only a person accepts"))
    _roundtrip(QuarantineEntry(text_id="t_0123456789ab", origin="rdml:sample.id", value="x"))


def _groups_design() -> StudyDesign:
    return StudyDesign(
        mode="groups",
        comparison=Comparison(group_a="LPS", group_b="PBS"),
        samples={
            "A1": SampleDesign(sample="A1", group="LPS", biological_unit="mouse1"),
            "B1": SampleDesign(sample="B1", group="PBS"),
        },
        targets={"Il6": TargetDesign(target="Il6", symbol="IL6")},
        reference_candidates=("Hprt", "Tbp"),
    )


def test_design_roundtrip_and_hash_is_stable():
    design = _roundtrip(_groups_design())
    assert design.samples["B1"].unit() == "B1"
    assert design.samples["A1"].unit() == "mouse1"
    assert design.design_hash() == _groups_design().design_hash()
    other = design.model_copy(update={"excluded_wells": ("plate1/A1",)})
    assert other.design_hash() != design.design_hash()


def test_design_mode_rules():
    with pytest.raises(ValidationError):
        StudyDesign(mode="marker_split")
    with pytest.raises(ValidationError):
        StudyDesign(mode="groups")
    with pytest.raises(ValidationError):
        StudyDesign(
            mode="groups",
            comparison=Comparison(group_a="LPS", group_b="PBS"),
            samples={"A1": SampleDesign(sample="A1", group="LPS")},
        )
    marker = StudyDesign(mode="marker_split", marker_split=MarkerSplit(marker="MYCN(4)"))
    _roundtrip(marker)


def test_other_models_roundtrip():
    _roundtrip(AmpCallRule(id="cq_le_35", label="Cq at most 35", kind="cq_max", cq_max=35))
    _roundtrip(
        WellCall(
            run_id="r", well="A1", sample="s", target="t", sample_type="unkn", calls={"x": True}
        )
    )
    _roundtrip(
        InspectSummary(
            input_sha256="a" * 64,
            n_samples=0,
            declared_types={},
            experiments={},
            runs=[],
            samples=[],
            targets=[],
        )
    )
    _roundtrip(DesignProposal(fields=[]))
    table = PrismTable(
        name="ODC1",
        gene="ODC1",
        layout="column",
        title="ODC1 log2 RQ [qPilot 3f9a]",
        columns=["MYCN-high", "rest"],
        n_rows=294,
        csv="tables/ODC1.csv",
        csv_sha256="b" * 64,
    )
    _roundtrip(
        PrismBundle(
            study_id="abc",
            record_ref="3f9a",
            chain_head="c" * 64,
            design_hash="d" * 64,
            template_id="two_groups_log2",
            test="Welch t test on log2 relative quantities",
            tables=[table],
        )
    )
    _roundtrip(PrismDiffItem(kind="excluded", table="ODC1", gene="ODC1", row="1496"))


def test_text_id_formula_is_shared_and_stable():
    from qpilot.schemas_studio import TEXT_ID, text_id_for

    tid = text_id_for("rdml:sample.id", "comp_50_NTC")
    assert TEXT_ID.match(tid)
    assert tid == text_id_for("rdml:sample.id", "comp_50_NTC")
    assert tid != text_id_for("rdml:target.id", "comp_50_NTC")


def test_amp_call_is_a_card_kind():
    from qpilot.core.decisions import CardSpec

    CardSpec(
        card_id="card_amp_call",
        kind="amp_call",
        dimension="amp_call",
        options=[],
        recommended="linregpcr",
        rationale_template="ampcall_v1",
    )
