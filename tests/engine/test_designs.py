"""Step 3.1: designs from a preset, from files and from accepted proposals only."""

import logging
from pathlib import Path

import pandas as pd
import pytest

from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.designs import (
    HEADLINE_GENES,
    MAX_FILE_BYTES,
    DesignError,
    design_curves,
    design_from_proposals,
    is_legacy_design,
    load_design,
    read_sample_sheet,
    study_key,
    vermeulen_design,
)
from qpilot.qpcr.quant import EXCLUDED
from qpilot.qpcr.study import StudySettings
from qpilot.schemas_studio import (
    Comparison,
    MadeBy,
    Proposal,
    SampleDesign,
    StudyDesign,
    TargetDesign,
)

REPO = Path(__file__).resolve().parents[2]
SHA = "ab" * 32


# ---------- the demo preset ----------


def test_vermeulen_preset_is_the_legacy_default():
    design = vermeulen_design()
    assert design.design_id == "vermeulen_expression_defined" and design.mode == "marker_split"
    assert design.marker_split.marker == "MYCN(4)" and design.marker_split.cut == 0.15
    assert design.marker_split.cuts == (0.10, 0.15, 0.20)
    assert design.reference_candidates == REFERENCE_TARGETS
    assert design.headline == HEADLINE_GENES and design.amp_calls == ("linregpcr",)
    assert StudySettings.from_design(design) == StudySettings()
    assert is_legacy_design(design) and is_legacy_design(None)


def test_demo_yaml_is_the_preset():
    design = load_design(REPO / "demo" / "vermeulen.study.yaml")
    assert design == vermeulen_design()
    assert design.design_hash() == vermeulen_design().design_hash()


def test_study_key_names_the_workspace():
    assert study_key(SHA, vermeulen_design()) == SHA and study_key(SHA, None) == SHA
    other = vermeulen_design().model_copy(update={"amp_calls": STUDIO_AMP_CALLS})
    key = study_key(SHA, other)
    assert len(key) == 64 and key != SHA and int(key, 16) >= 0
    assert key == study_key(SHA, other)  # stable
    settings = StudySettings.from_design(other)
    assert settings.design == other and settings.studio_facts
    assert settings.amp_calls == STUDIO_AMP_CALLS and settings.cut == 0.15


# ---------- files ----------

YAML_GROUPS = """
design_id: lps_mice
experiment_id: plate_set
mode: groups
comparison: {group_a: LPS, group_b: PBS}
reference_candidates: [Hprt, Tbp]
headline: [Il6]
targets:
  Il6: {symbol: IL6}
"""

SHEET = """Sample,Group,biological_unit,notes
A1,LPS,mouse1,first
A2,LPS,mouse2,
B1,PBS,mouse3,
B2,PBS,mouse4,
STD1,,,dilution
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_yaml_and_sample_sheet(tmp_path, caplog):
    yaml_path = _write(tmp_path, "study.yaml", YAML_GROUPS)
    sheet = _write(tmp_path, "samples.csv", SHEET)
    with caplog.at_level(logging.WARNING):
        design = load_design(yaml_path, sheet)
    assert "notes" in caplog.text  # unknown columns are ignored with a warning
    assert design.mode == "groups" and design.comparison == Comparison(group_a="LPS", group_b="PBS")
    assert design.samples["A1"] == SampleDesign(sample="A1", group="LPS", biological_unit="mouse1")
    assert design.samples["STD1"].group is None
    assert design.targets["Il6"] == TargetDesign(target="Il6", symbol="IL6")
    settings = StudySettings.from_design(design)
    assert settings.groups_mode and settings.candidates == ("Hprt", "Tbp")
    assert settings.experiment_id == "plate_set" and settings.studio_facts


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("mode: groups\ncolour: red\n", "unknown field"),
        ("mode: marker_split\nmarker_split: {marker: M, cut: 0.15, wrong: 1}\n", "unknown field"),
        ("mode: marker_split\nmarker_split: {marker: M, cut: 0.3}\n", "is not one of cuts"),
        ("mode: marker_split\nmarker_split: {marker: M}\namp_calls: [cq_le_33]\n", "unknown"),
        ("mode: groups\ncomparison: {group_a: A, group_b: B}\n", "comparison groups"),
        ("mode: marker_split\nmode: groups\n", "appears twice"),
        ("a: &x {b: 1}\nc: *x\n", "aliases"),
        ("- just\n- a list\n", "expected a mapping"),
        ("mode: groups\nsamples: {1496: {group: A}}\n", "quotes"),
        ("mode: marker_split\nmarker_split: {marker: M}\nexcluded_wells: [A1]\n", "well keys"),
        ("mode: [unclosed\n", "not valid YAML"),
    ],
)
def test_bad_design_files_are_refused_clearly(tmp_path, text, message):
    with pytest.raises(DesignError, match=message):
        load_design(_write(tmp_path, "bad.yaml", text))


def test_files_over_the_size_cap_are_refused(tmp_path):
    big = _write(tmp_path, "big.yaml", "# " + "x" * MAX_FILE_BYTES + "\nmode: groups\n")
    with pytest.raises(DesignError, match="limit"):
        load_design(big)
    with pytest.raises(DesignError, match="No such file|not"):
        load_design(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("sample,group\nA1,LPS\nA1,PBS\n", "on lines 2 and 3"),
        ("sample,biological_unit\nA1,m1\n", "missing column"),
        ("sample,group,quantity\nA1,LPS,lots\n", "not a number"),
        ("sample,group,role\nA1,LPS,patient\n", "line 2"),
        ("sample,group\n,LPS\n", "no sample name"),
        ("", "empty"),
    ],
)
def test_bad_sample_sheets_are_refused_clearly(tmp_path, text, message):
    with pytest.raises(DesignError, match=message):
        read_sample_sheet(_write(tmp_path, "sheet.csv", text))


def test_a_sample_in_both_files_is_refused(tmp_path):
    text = YAML_GROUPS + "samples:\n  A1: {group: LPS}\n"
    with pytest.raises(DesignError, match="in both"):
        load_design(_write(tmp_path, "s.yaml", text), _write(tmp_path, "s.csv", SHEET))


# ---------- accepted proposals only ----------


def _proposal(kind, subject, payload, status="accepted", edits=None, pid=""):
    return Proposal(
        id=pid,
        study_id="abc123def456",
        kind=kind,
        subject=subject,
        payload=payload,
        made_by=MadeBy(kind="rule"),
        status=status,
        edits=edits,
    )


def _groups_base() -> StudyDesign:
    return StudyDesign(
        mode="groups",
        comparison=Comparison(group_a="LPS", group_b="PBS"),
        samples={
            "A1": SampleDesign(sample="A1", group="LPS"),
            "B1": SampleDesign(sample="B1", group="PBS"),
        },
        reference_candidates=("Hprt",),
    )


def test_only_accepted_or_edited_proposals_change_the_design():
    base = vermeulen_design()
    pending = [
        _proposal("curve.call_rule", "amp_call", {"rule": "cq_le_35"}, status=status)
        for status in ("proposed", "rejected", "superseded")
    ]
    pending.append(_proposal("design.group", "1496", {"group": "x"}, status="proposed"))
    pending.append(_proposal("design.preset", "design", {"preset": "nope"}, status="rejected"))
    assert design_from_proposals(base, pending) == base
    accepted = _proposal("curve.call_rule", "amp_call", {"rule": "cq_le_38"})
    changed = design_from_proposals(base, [*pending, accepted])
    assert changed.amp_calls == ("cq_le_38", "linregpcr", "cq_le_40", "cq_le_35")
    edited = _proposal(
        "curve.call_rule",
        "amp_call",
        {"rule": "cq_le_38"},
        status="edited",
        edits={"rule": "cq_le_40"},
    )
    assert design_from_proposals(base, [edited]).amp_calls[0] == "cq_le_40"


def test_later_proposals_win_and_every_design_kind_applies():
    base = _groups_base()
    proposals = [
        _proposal("design.group", "A2", {"group": "LPS"}),
        _proposal("design.group", "A2", {"group": "PBS"}),  # later wins
        _proposal("design.bio_unit", "A1", {"biological_unit": "mouse1"}),
        _proposal("design.well_role", "NTC1", {"role": "ntc"}),
        _proposal("design.well_role", "run1/H12", {"role": "nrt"}),
        _proposal("design.target_role", "Tbp", {"role": "ref"}),
        _proposal("design.target_role", "Actb", {"role": "ref"}),
        _proposal("design.target_role", "Hprt", {"role": "toi"}),
        _proposal("design.gene_symbol", "Il6", {"symbol": "IL6"}),
        _proposal(
            "design.dilution_series",
            "comp_00",
            {"experiment_id": "tech", "samples": {"S1": 16, "S2": 4}},
        ),
        _proposal("curve.well_call", "run1/A1", {"amplified": False}),
        _proposal("prism.project", "prism", {"template_id": "x"}),  # no design effect
    ]
    design = design_from_proposals(base, proposals)
    assert design.samples["A2"].group == "PBS"
    assert design.samples["A1"].unit() == "mouse1"
    assert design.samples["NTC1"].role == "ntc" and design.well_roles == {"run1/H12": "nrt"}
    assert design.reference_candidates == ("Actb", "Tbp")  # Hprt dropped, new refs sorted
    reordered = [proposals[6], proposals[7], proposals[5], *proposals[:5], *proposals[8:]]
    assert design_from_proposals(base, reordered).reference_candidates == ("Actb", "Tbp")
    confirm = _proposal("design.target_role", "UBC(2)", {"role": "ref"})
    assert design_from_proposals(vermeulen_design(), [confirm]).reference_candidates == (
        REFERENCE_TARGETS
    )  # confirming a candidate does not move it
    assert design.targets["Il6"].symbol == "IL6"
    assert design.samples["S1"].role == "std" and design.samples["S1"].quantity == 16.0
    assert design.well_calls == {"run1/A1": False}


def test_comparison_switches_to_groups_and_preset_resets():
    base = vermeulen_design()
    proposals = [
        _proposal("design.group", "s1", {"group": "high"}),
        _proposal("design.group", "s2", {"group": "low"}),
        _proposal("design.comparison", "comparison", {"group_a": "high", "group_b": "low"}),
    ]
    design = design_from_proposals(base, proposals)
    assert design.mode == "groups" and design.marker_split is None
    assert design.comparison.group_a == "high"
    reset = _proposal("design.preset", "design", {"preset": "vermeulen_expression_defined"})
    assert design_from_proposals(design, [reset]) == vermeulen_design()


def test_exclusions_map_gene_and_sample_to_wells():
    curves = pd.DataFrame(
        {
            "run_id": ["p1", "p1", "p2"],
            "well": ["A1", "A2", "A1"],
            "sample": ["1496", "1497", "1496"],
            "target": ["ODC1", "ODC1", "HMBS"],
        }
    )
    exclude = _proposal(
        "prism.exclusion_reason",
        "ODC1/1496",
        {"gene": "ODC1", "sample": "1496", "action": "exclude"},
    )
    design = design_from_proposals(vermeulen_design(), [exclude], curves)
    assert design.excluded_wells == ("p1/A1",)
    restore = exclude.model_copy(update={"payload": {**exclude.payload, "action": "restore"}})
    assert design_from_proposals(design, [restore], curves).excluded_wells == ()
    with pytest.raises(DesignError, match="per-well table"):
        design_from_proposals(vermeulen_design(), [exclude])


def test_unusable_proposals_are_refused_by_name():
    base = vermeulen_design()
    with pytest.raises(DesignError, match="p_9.*unknown preset"):
        bad = _proposal("design.preset", "design", {"preset": "nope"}, pid="p_9")
        design_from_proposals(base, [bad])
    with pytest.raises(DesignError, match="p_8: payload not usable.*preset"):
        design_from_proposals(base, [_proposal("design.preset", "design", {"x": 1}, pid="p_8")])
    with pytest.raises(DesignError, match="unknown amplification-call rule"):
        design_from_proposals(base, [_proposal("curve.call_rule", "amp_call", {"rule": "x"})])
    with pytest.raises(DesignError, match="true or false"):
        call = _proposal("curve.well_call", "r/A1", {"amplified": "no"})
        design_from_proposals(base, [call])


# ---------- the per-well table as the design says ----------


def _table():
    return pd.DataFrame(
        {
            "run_id": ["p1"] * 4,
            "well": ["A1", "A2", "A3", "A4"],
            "sample": ["s1", "s2", "std", "ntc"],
            "sample_type": ["unkn", "unkn", "std", "ntc"],
            "n0": [1.0, 2.0, 3.0, float("nan")],
        }
    )


def test_design_curves_retypes_and_excludes():
    design = _groups_base().model_copy(
        update={
            "samples": {
                **_groups_base().samples,
                "s2": SampleDesign(sample="s2", role="std"),
                "std": SampleDesign(sample="std", group="LPS"),  # role "unkn" keeps the file's
            },
            "excluded_wells": ("p1/A1",),
        }
    )
    out = design_curves(_table(), design)
    assert list(out["sample_type"]) == ["unkn", "std", "std", "ntc"]
    assert list(out[EXCLUDED]) == [True, False, False, False]
    assert list(_table()["sample_type"]) == ["unkn", "unkn", "std", "ntc"]  # a copy


def test_design_curves_refuses_demoting_a_control_and_unknown_wells():
    base = _groups_base()
    with pytest.raises(DesignError, match="declared control"):
        design_curves(_table(), base.model_copy(update={"well_roles": {"p1/A4": "unkn"}}))
    with pytest.raises(DesignError, match="not in the data"):
        design_curves(_table(), base.model_copy(update={"well_calls": {"p9/A1": False}}))


@pytest.mark.demo_data
def test_demo_exclusion_through_an_accepted_proposal(demo_curves):
    """Plan step 6.2 oracle: excluding ODC1's highest sample (1496) gives 3.59x -> 3.32x."""
    from qpilot.io.datasets import VERMEULEN_SHA256
    from qpilot.qpcr.study import study_from_curves

    legacy = study_from_curves(demo_curves, VERMEULEN_SHA256)[0]
    exclude = _proposal(
        "prism.exclusion_reason",
        "ODC1/1496",
        {"gene": "ODC1", "sample": "1496", "action": "exclude"},
    )
    design = design_from_proposals(vermeulen_design(), [exclude], demo_curves)
    assert len(design.excluded_wells) == 1
    settings = StudySettings.from_design(design)
    result = study_from_curves(demo_curves, VERMEULEN_SHA256, settings)[0]
    before, after = legacy.contrasts["ODC1"], result.contrasts["ODC1"]
    assert (round(before.fc, 3), round(after.fc, 3)) == (3.590, 3.319)
    assert (f"{before.p:.2g}", f"{after.p:.2g}") == ("2.3e-08", "2.1e-08")
    assert after.conclusion == "up" and (after.n_hi, after.n_lo) == (52, 294)
    assert (result.design.n_hi, result.design.n_lo, result.n_samples) == (53, 294, 366)
    contrasts = legacy.contrasts.items()
    assert [g for g, c in contrasts if c.conclusion != result.contrasts[g].conclusion] == []
