"""An exclusion made in Prism is applied exactly as its consequence showed it (review c1, c13).

The toy groups study (three units per group, three technical replicates each) is exported as a
nested table, one replicate is cleared in the table Prism sends back, and the proposal the round
trip makes is accepted. The engine's re-analysis must then equal the consequence the person saw:
one replicate leaves the unit's mean, never the whole unit. The proposal names the exact well
behind the cleared replicate, so the well excluded is the one the person cleared whatever the
amplification rule the export used and whatever was excluded since.
"""

import dataclasses

import pytest

from qpilot.core.proposals import ProposalStore
from qpilot.prism.roundtrip import diff, diff_to_proposals, read_sent_back, round_trip_proposals
from qpilot.prism.tables import build_bundle
from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS, apply_rule
from qpilot.qpcr.designs import design_from_proposals
from qpilot.qpcr.export import Choice, ExportInputs
from qpilot.qpcr.study import StudySettings, build_model, study_from_curves
from tests.engine.test_groups_study import INPUT, toy_design, toy_wells

NAN = float("nan")
LATE = {"cq": 38.5, "n0": 2.0**9}  # a low, late replicate: a value under LinRegPCR, none at 35


def _inputs(curves, design) -> ExportInputs:
    """What the Prism bridge exports for this study at its primary choices."""
    model = build_model(curves, StudySettings.from_design(design))
    data, units = model.inputs.primary_table, model.inputs.units or {}
    samples = sorted(set(data.loc[data["sample_type"] == "unkn", "sample"]))
    first, second = model.labels
    groups = {
        **{s: first for s in samples if units.get(s, s) in model.high},
        **{s: second for s in samples if units.get(s, s) in model.rest},
    }
    return ExportInputs(
        study_id="70y0000000c1",
        input_sha256=INPUT,
        data=data,
        refs=tuple(model.space.primary["refs"]),
        undetermined=model.space.primary["undetermined"],
        groups=groups,
        group_order=(first, second),
        units=units,
        genes=tuple(model.space.items),
        design=design,  # the consequence runs the engine again on this design
        curves=curves,
    )


def _inputs_at_rule(curves, design, rule) -> ExportInputs:
    """What the bridge exports once a person decided the amplification card at ``rule``.

    Built the way ``study_inputs`` builds it: the per-well table under the decided rule, the
    rule as the decided choice, everything else at the primary choices.
    """
    model = build_model(curves, StudySettings.from_design(design))
    assert rule in model.space.dimensions["amp_call"]
    data = apply_rule(model.inputs.table, rule, dict(design.well_calls))
    choice = Choice("card_amp_call", "amp_call", rule, "linregpcr", rule, "human", "decided")
    inputs = _inputs(curves, design)
    return dataclasses.replace(inputs, data=data, choices=(choice,), at_primary=False)


def _export(tmp_path, inputs, gene):
    """The nested bundle for ``gene`` (written once per ``tmp_path``)."""
    bundle_dir = tmp_path / "bundle"
    bundle = build_bundle(
        inputs,
        [gene],
        "nested_superplot",
        bundle_dir,
        record_ref="toy",
        chain_head="ab" * 32,
        design_hash="d0" * 32,
    )
    return bundle, bundle_dir


def _sent_back(tmp_path, bundle_dir, gene, cleared, name="sent_back"):
    """The table Prism sends back with every ``(row, column)`` of ``cleared`` emptied."""
    sent = tmp_path / name
    sent.mkdir()
    lines = (bundle_dir / f"{gene}.csv").read_text().splitlines()
    header = lines[0].split(",")
    for row, column in cleared:
        position = header.index(column)
        for i, line in enumerate(lines):
            cells = line.split(",")
            if cells[0] == row:
                cells[position] = ""
                lines[i] = ",".join(cells)
    (sent / f"{gene}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sent


def _accepted(proposal):
    return proposal.model_copy(update={"status": "accepted", "decided_by": "human"})


def _cleared(tmp_path, inputs, gene, row, column):
    """The proposal made when ``row`` of ``column`` is cleared in the nested table sent back."""
    bundle, bundle_dir = _export(tmp_path, inputs, gene)
    sent = _sent_back(tmp_path, bundle_dir, gene, [(row, column)])
    items = diff(bundle, read_sent_back(sent), bundle_dir=bundle_dir)
    assert [(i.kind, i.row, i.column) for i in items] == [("missing", row, column)]
    (proposal,) = diff_to_proposals(items, inputs.study_id, inputs, bundle=bundle)
    return _accepted(proposal)


def _engine_matches_consequence(curves, design, proposal, accepted=(), cell=None):
    """The engine after acceptance (at ``cell``, else the primary analysis) is what was shown."""
    design = design_from_proposals(design, [*accepted, proposal], curves)
    shown = proposal.consequence
    if cell is None:
        after = study_from_curves(curves, INPUT, StudySettings.from_design(design))[0]
        after = after.contrasts[shown["gene"]]
    else:
        space = build_model(curves, StudySettings.from_design(design)).space
        after = space.evaluate({**space.primary, **cell})[shown["gene"]]
    assert after.log2fc == pytest.approx(shown["log2fc_after"], rel=1e-9, abs=1e-12)
    assert after.p == pytest.approx(shown["p_after"], rel=1e-9)
    assert [after.n_hi, after.n_lo] == shown["n_units_after"]
    assert after.conclusion == shown["conclusion_after"]
    return design


@pytest.mark.parametrize(
    ("unit", "rep", "well"),
    [
        ("mA1", 2, "p1/A1"),  # the reviewers' case: rep 2 of mA1's wells A0, A1, A2
        ("mB1", 1, "p1/A10"),  # replicates are numbered in well-key order: A10, A11, A9
    ],
)
def test_one_cleared_replicate_excludes_exactly_that_well(tmp_path, unit, rep, well):
    curves, design = toy_wells(), toy_design()
    group = "treated" if unit.startswith("mA") else "control"
    proposal = _cleared(tmp_path, _inputs(curves, design), "T1", f"rep {rep}", f"{group}/{unit}")
    assert proposal.payload["well_rep"] == rep
    assert proposal.payload["well"] == well  # the exact well, resolved from the exported table
    assert proposal.subject == f"T1/{unit}/rep {rep}"
    assert proposal.payload["question"].startswith(f"Replicate {rep} of sample {unit} for T1 ")
    assert {"kind": "well", "ref": well} in [
        e.model_dump(include={"kind", "ref"}) for e in proposal.evidence
    ]
    assert proposal.consequence["well"] == well
    assert proposal.consequence["n_units_after"] == [3, 3]
    accepted = _engine_matches_consequence(curves, design, proposal)
    assert accepted.excluded_wells == (well,)


def test_an_export_at_another_amplification_rule_excludes_the_well_it_showed(tmp_path):
    """Review c1 (1): under Cq <= 35 mA1's replicates are A1, A2; under LinRegPCR A0, A1, A2.

    The person cleared rep 2 of the table exported at Cq <= 35, which is well A2. Before the fix
    the engine counted the replicates under its primary rule and excluded A1.
    """
    curves = toy_wells(overrides={("sA1", "T1", 0): LATE, ("sA2", "T1", 0): LATE})
    design = toy_design(amp_calls=STUDIO_AMP_CALLS)
    inputs = _inputs_at_rule(curves, design, "cq_le_35")
    proposal = _cleared(tmp_path, inputs, "T1", "rep 2", "treated/mA1")
    assert (proposal.payload["well_rep"], proposal.payload["well"]) == (2, "p1/A2")
    cell = {"amp_call": "cq_le_35"}
    accepted = _engine_matches_consequence(curves, design, proposal, cell=cell)
    assert accepted.excluded_wells == ("p1/A2",)


def test_a_second_round_trip_of_the_same_export_excludes_the_well_it_showed(tmp_path):
    """Review c1 (2): rep 2 of mA1 (A1) was accepted; rep 3 (A2) is cleared in the same table.

    The second round trip compares against the same export, so rep 3 is still A2. Before the
    fix the rep-2 acceptance settled the whole unit (rep 3 was never asked about), and the
    engine, counting again on the design without A1, would have excluded A0 instead.
    """
    curves, design = toy_wells(), toy_design()
    inputs = _inputs(curves, design)
    bundle, bundle_dir = _export(tmp_path, inputs, "T1")
    first_sent = _sent_back(tmp_path, bundle_dir, "T1", [("rep 2", "treated/mA1")], "first")
    first_items = diff(bundle, read_sent_back(first_sent), bundle_dir=bundle_dir)
    (first,) = diff_to_proposals(first_items, inputs.study_id, inputs, bundle=bundle)
    first = _accepted(first)
    assert first.payload["well"] == "p1/A1"

    cleared = [("rep 2", "treated/mA1"), ("rep 3", "treated/mA1")]
    sent = _sent_back(tmp_path, bundle_dir, "T1", cleared, "second")
    items = diff(bundle, read_sent_back(sent), bundle_dir=bundle_dir)
    assert [(i.row, i.column) for i in items] == cleared
    (second,) = diff_to_proposals(items, inputs.study_id, inputs, bundle=bundle, accepted=[first])
    assert second.subject == "T1/mA1/rep 3"  # rep 2 is settled: not asked about again
    assert (second.payload["well_rep"], second.payload["well"]) == (3, "p1/A2")
    accepted = _engine_matches_consequence(curves, design, _accepted(second), accepted=[first])
    assert accepted.excluded_wells == ("p1/A1", "p1/A2")


def test_two_cleared_replicates_of_one_unit_both_reach_the_inbox(tmp_path):
    """Review c1: two replicates of one unit shared a subject, so the store superseded one."""
    curves, design = toy_wells(), toy_design()
    inputs = _inputs(curves, design)
    bundle, bundle_dir = _export(tmp_path, inputs, "T1")
    cleared = [("rep 1", "treated/mA1"), ("rep 3", "treated/mA1")]
    sent = _sent_back(tmp_path, bundle_dir, "T1", cleared)
    items = diff(bundle, read_sent_back(sent), bundle_dir=bundle_dir)
    proposals, combined = round_trip_proposals(items, inputs.study_id, inputs, bundle=bundle)
    assert [p.subject for p in proposals] == ["T1/mA1/rep 1", "T1/mA1/rep 3"]
    assert [p.payload["well"] for p in proposals] == ["p1/A0", "p1/A2"]
    assert [p.payload["question"][:31] for p in proposals] == [
        "Replicate 1 of sample mA1 for T",
        "Replicate 3 of sample mA1 for T",
    ]
    assert [e["well"] for e in combined["exclusions"]] == ["p1/A0", "p1/A2"]
    inbox = ProposalStore.at(tmp_path / "session", INPUT)
    for proposal in proposals:  # as Studio's round trip proposes them
        outcome = inbox.propose(proposal.model_copy(update={"study_id": inbox.study_id}), "system")
        assert outcome.status == "proposed", outcome.reason
    assert sorted(p.status for p in inbox.proposals()) == ["proposed", "proposed"]
    both = design_from_proposals(design, [_accepted(p) for p in proposals], curves)
    assert both.excluded_wells == ("p1/A0", "p1/A2")


def test_a_changed_replicate_names_its_well_and_its_replicate(tmp_path):
    curves, design = toy_wells(), toy_design()
    inputs = _inputs(curves, design)
    bundle, bundle_dir = _export(tmp_path, inputs, "T1")
    sent = tmp_path / "sent_back"
    sent.mkdir()
    lines = (bundle_dir / "T1.csv").read_text().splitlines()
    position = lines[0].split(",").index("control/mB1")
    cells = lines[2].split(",")  # rep 2
    cells[position] = "0.25"
    lines[2] = ",".join(cells)
    (sent / "T1.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    items = diff(bundle, read_sent_back(sent), bundle_dir=bundle_dir)
    (edit,) = diff_to_proposals(items, inputs.study_id, inputs, bundle=bundle)
    assert edit.kind == "prism.value_edit"
    assert edit.subject == "T1/mB1/rep 2"
    assert (edit.payload["well_rep"], edit.payload["well"]) == (2, "p1/A11")
    assert "replicate 2 of sample mB1" in edit.payload["question"]


def test_the_last_measured_replicate_leaves_the_unit_out(tmp_path):
    """Two of mA2's T1 wells are undetermined, so its one value is a single replicate."""
    nan = {"n0": NAN, "cq": NAN}
    curves = toy_wells(overrides={("sA2", "T1", 0): nan, ("sA2", "T1", 2): nan})
    design = toy_design()
    proposal = _cleared(tmp_path, _inputs(curves, design), "T1", "rep 1", "treated/mA2")
    assert proposal.consequence["n_units_after"] == [2, 3]
    accepted = _engine_matches_consequence(curves, design, proposal)
    # the value is left out, never capped: every T1 well of mA2 is excluded
    assert accepted.excluded_wells == ("p1/A3", "p1/A4", "p1/A5")
    space = build_model(curves, StudySettings.from_design(accepted)).space
    capped = space.evaluate({**space.primary, "undetermined": "cap"})["T1"]
    assert (capped.n_hi, capped.n_lo) == (2, 3)


def test_a_cleared_unit_in_the_column_layout_still_excludes_every_replicate(tmp_path):
    curves, design = toy_wells(), toy_design()
    inputs = _inputs(curves, design)
    bundle_dir, sent = tmp_path / "bundle", tmp_path / "sent_back"
    bundle = build_bundle(
        inputs,
        ["T1"],
        "two_groups_log2",
        bundle_dir,
        record_ref="toy",
        chain_head="ab" * 32,
        design_hash="d0" * 32,
    )
    sent.mkdir()
    lines = (bundle_dir / "T1.csv").read_text().splitlines()
    lines = ["mA1,," if line.split(",")[0] == "mA1" else line for line in lines]
    (sent / "T1.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    items = diff(bundle, read_sent_back(sent), bundle_dir=bundle_dir)
    (proposal,) = diff_to_proposals(items, inputs.study_id, inputs, bundle=bundle)
    proposal = proposal.model_copy(update={"status": "accepted", "decided_by": "human"})
    assert proposal.payload["well_rep"] == 0
    accepted = _engine_matches_consequence(curves, design, proposal)
    assert accepted.excluded_wells == ("p1/A0", "p1/A1", "p1/A2")


def test_excluding_one_target_of_a_multiplex_well_is_refused_not_widened():
    """A duplex well (REF and T1 measured in the same well): excluding T1 alone would drop REF."""
    from qpilot.qpcr.designs import DesignError
    from qpilot.schemas_studio import MadeBy, Proposal

    curves = toy_wells()
    gene = next(t for t in curves["target"].unique() if t != "REF")
    ref_plate = curves.loc[curves["target"] == "REF", "run_id"].iloc[0]
    curves.loc[curves["target"] == gene, "run_id"] = ref_plate  # same plate, same well names
    sample = curves.loc[curves["target"] == gene, "sample"].iloc[0]
    exclusion = Proposal(
        study_id="70y0000000c1",
        kind="prism.exclusion_reason",
        subject=f"{gene}/{sample}",
        payload={"gene": gene, "sample": sample, "action": "exclude", "well_rep": 0},
        made_by=MadeBy(kind="rule"),
        status="accepted",
        decided_by="human",
    )
    with pytest.raises(DesignError, match="multiplex"):
        design_from_proposals(toy_design(), [exclusion], curves)
