"""The normaliser and between-plate axes as design choices: the field, the proposal, D-AXIS, CLI.

Absent by default (no design hash or study id moves); a ``choice.axis`` a person accepted
switches them on; D-AXIS refutes what the file cannot support. No demo data needed here
(``test_norm_studio_demo.py`` has the demo).
"""

from __future__ import annotations

import pandas as pd
import pytest

from qpilot.qpcr.design_checks import axis_check
from qpilot.qpcr.designs import (
    DESIGN_AXES,
    DesignError,
    axis_options,
    design_from_proposals,
    study_key,
    vermeulen_design,
)
from qpilot.qpcr.study import StudySettings
from qpilot.schemas_studio import MadeBy, Proposal

NORM = ("planned", "normfinder_pair", "global_mean")
IRC = ("none", "calibrator", "factor")


def _proposal(kind, subject, payload, status="accepted") -> Proposal:
    return Proposal(
        id="p_" + "b" * 16,
        study_id="s",
        kind=kind,
        subject=subject,
        payload=payload,
        made_by=MadeBy(kind="rule"),
        status=status,
    )


def test_both_axes_can_be_asked_for_and_are_absent_by_default():
    assert DESIGN_AXES == ("efficiency", "normaliser", "interrun")
    base = vermeulen_design()
    assert StudySettings.from_design(base) == StudySettings()  # the legacy demo, as before
    assert StudySettings().normaliser == ("planned",) and StudySettings().interrun == ("none",)
    tested = base.model_copy(update={"axes": {"normaliser": NORM, "interrun": IRC}})
    assert study_key("0" * 64, tested) != study_key("0" * 64, base)
    settings = StudySettings.from_design(tested)
    assert settings.normaliser == NORM and settings.interrun == IRC


@pytest.mark.parametrize(
    ("name", "options", "match"),
    [
        ("normaliser", ["global_mean", "planned"], "must start with 'planned'"),
        ("normaliser", ["planned", "median"], "unknown option 'median'"),
        ("interrun", ["calibrator", "none"], "must start with 'none'"),
        ("interrun", ["none", "none"], "more than once"),
    ],
)
def test_axis_options_are_refused_in_words(name, options, match):
    with pytest.raises(DesignError, match=match):
        axis_options(name, options)


def test_an_accepted_choice_switches_the_normaliser_on_and_off_again():
    base = vermeulen_design()
    on = design_from_proposals(base, [_proposal("choice.axis", "normaliser", {"options": NORM})])
    assert on.axes == {"normaliser": NORM}
    off = design_from_proposals(
        on, [_proposal("choice.axis", "normaliser", {"options": ["planned"]})]
    )
    assert off.axes is None and off.design_hash() == base.design_hash()


def _wells(rows) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["run_id", "sample", "sample_type", "target", "n0"])
    frame["well"] = [f"W{i}" for i in range(len(frame))]
    return frame


def test_d_axis_refutes_a_global_mean_of_few_genes_and_pairs_without_three_refs():
    rows = [("P1", f"s{i}", "unkn", t, 2.0**i) for i in range(4) for t in ("A", "B", "C")]
    wells = _wells(rows)
    refs = [_proposal("design.target_role", t, {"role": "ref"}) for t in ("A", "B")]
    check = axis_check("normaliser", {"options": list(NORM)}, wells, refs)
    assert check.status == "contradicted" and check.rule_ids == ["D-AXIS"]
    assert check.details["not_in_the_file"] == ["normfinder_pair", "global_mean"]
    assert "three reference genes" in check.note and "too few genes" in check.note
    three = [*refs, _proposal("design.target_role", "C", {"role": "ref"})]
    pair = axis_check("normaliser", {"options": ["planned", "normfinder_pair"]}, wells, three)
    assert pair.status == "consistent"
    preset = [_proposal("design.preset", "vermeulen", {})]  # the preset decides the references
    assert axis_check(
        "normaliser", {"options": ["planned", "genorm_pair"]}, wells, preset
    ).status == ("consistent")


def test_d_axis_refutes_a_correction_the_plates_cannot_support():
    one_each = _wells([("P1", "s1", "unkn", "A", 1.0), ("P2", "s1", "unkn", "B", 1.0)])
    check = axis_check("interrun", {"options": list(IRC)}, one_each, [])
    assert check.status == "contradicted"
    assert "cancels in every fold change" in check.note
    split = _wells(
        [
            *[(run, f"s{i}{run}", "unkn", "A", 2.0) for run in ("P1", "P2") for i in range(3)],
            *[(run, "IRC", "pos", "A", 4.0) for run in ("P1", "P2")],
        ]
    )
    ok = axis_check("interrun", {"options": ["none", "calibrator"]}, split, [])
    assert ok.status == "consistent" and ok.details["genes_split_over_plates"] == 1
    no_share = axis_check("interrun", {"options": ["none", "factor"]}, split, [])
    assert no_share.status == "consistent"  # IRC (A) is on both plates: a shared measurement
    lone = split[split["sample"] != "IRC"]
    refuted = axis_check("interrun", {"options": list(IRC)}, lone, [])
    assert refuted.details["not_in_the_file"] == ["calibrator", "factor"]


def test_the_cli_parses_the_options():
    from qpilot.cli.engine_cmds import _axis_options

    assert _axis_options("normaliser", "all") == (
        "planned",
        "normfinder_pair",
        "genorm_pair",
        "global_mean",
    )
    assert _axis_options("interrun", "factor") == ("none", "factor")
    with pytest.raises(ValueError, match="unknown --normaliser option"):
        _axis_options("normaliser", "median")
    with pytest.raises(ValueError, match="no option besides"):
        _axis_options("interrun", "none")


def test_studio_words_for_the_proposal():
    from qpilot.studio_state import describe

    on = _proposal("choice.axis", "normaliser", {"options": list(NORM)}, "proposed")
    assert describe(on) == (
        "Also test what to normalise each gene to: NormFinder's best pair of reference genes; "
        "the mean of every gene measured (global mean) (besides the reference genes chosen for "
        "this study, the analysis in use)"
    )
    off = _proposal("choice.axis", "interrun", {"options": ["none"]}, "proposed")
    assert describe(off) == (
        "Stop testing how to correct differences between plates; keep no correction between "
        "plates only"
    )
