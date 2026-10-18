"""An exclusion made in Prism is applied exactly as its consequence showed it (review c1, c13).

The toy groups study (three units per group, three technical replicates each) is exported as a
nested table, one replicate is cleared in the table Prism sends back, and the proposal the round
trip makes is accepted. The engine's re-analysis must then equal the consequence the person saw:
one replicate leaves the unit's mean, never the whole unit.
"""

import pytest

from qpilot.prism.roundtrip import diff, diff_to_proposals, read_sent_back
from qpilot.prism.tables import build_bundle
from qpilot.qpcr.designs import design_from_proposals
from qpilot.qpcr.export import ExportInputs
from qpilot.qpcr.study import StudySettings, build_model, study_from_curves
from tests.engine.test_groups_study import INPUT, toy_design, toy_wells

NAN = float("nan")


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
    )


def _cleared(tmp_path, inputs, gene, row, column):
    """The proposal made when ``row`` of ``column`` is cleared in the nested table sent back."""
    bundle_dir, sent = tmp_path / "bundle", tmp_path / "sent_back"
    bundle = build_bundle(
        inputs,
        [gene],
        "nested_superplot",
        bundle_dir,
        record_ref="toy",
        chain_head="ab" * 32,
        design_hash="d0" * 32,
    )
    sent.mkdir()
    lines = (bundle_dir / f"{gene}.csv").read_text().splitlines()
    position = lines[0].split(",").index(column)
    for i, line in enumerate(lines):
        cells = line.split(",")
        if cells[0] == row:
            cells[position] = ""
            lines[i] = ",".join(cells)
    (sent / f"{gene}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    items = diff(bundle, read_sent_back(sent), bundle_dir=bundle_dir)
    assert [(i.kind, i.row, i.column) for i in items] == [("missing", row, column)]
    (proposal,) = diff_to_proposals(items, inputs.study_id, inputs, bundle=bundle)
    return proposal.model_copy(update={"status": "accepted", "decided_by": "human"})


def _engine_matches_consequence(curves, design, proposal):
    accepted = design_from_proposals(design, [proposal], curves)
    result = study_from_curves(curves, INPUT, StudySettings.from_design(accepted))[0]
    shown = proposal.consequence
    after = result.contrasts[shown["gene"]]
    assert after.log2fc == pytest.approx(shown["log2fc_after"], rel=1e-9, abs=1e-12)
    assert after.p == pytest.approx(shown["p_after"], rel=1e-9)
    assert [after.n_hi, after.n_lo] == shown["n_units_after"]
    assert after.conclusion == shown["conclusion_after"]
    return accepted


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
    assert proposal.consequence["n_units_after"] == [3, 3]
    accepted = _engine_matches_consequence(curves, design, proposal)
    assert accepted.excluded_wells == (well,)


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
