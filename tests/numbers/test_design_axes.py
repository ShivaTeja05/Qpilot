"""The efficiency models as a design choice: the design field, the proposal, its check, the CLI.

``StudyDesign.axes`` is opt-in: ``None`` (the default) leaves the canonical design, its hash and
so every existing study id exactly as they were. A ``choice.axis`` proposal a person accepted
switches an axis on (or off again); ``StudySettings.from_design`` turns it into the engine's
``efficiency`` options. No demo data needed here (``test_efficiency_studio_demo.py`` has the demo).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qpilot.qpcr import inspect as qinspect
from qpilot.qpcr.design_checks import axis_check
from qpilot.qpcr.designs import (
    DesignError,
    axis_options,
    check_design,
    design_from_proposals,
    study_key,
    vermeulen_design,
)
from qpilot.qpcr.study import StudySettings
from qpilot.schemas_studio import MadeBy, Proposal, StudyDesign

ON = ("linregpcr", "per_well", "assumed_2")


def _axis(options, status="accepted") -> Proposal:
    return Proposal(
        id="p_" + "a" * 16,
        study_id="s",
        kind="choice.axis",
        subject="efficiency",
        payload={"options": list(options)},
        made_by=MadeBy(kind="rule"),
        status=status,
    )


# ---- the design field ---------------------------------------------------------------------


def test_no_axes_keeps_every_design_hash_and_study_id():
    base = vermeulen_design()
    assert base.axes is None
    assert "axes" not in base.canonical()
    explicit = StudyDesign.model_validate({**base.model_dump(), "axes": None})
    assert explicit.design_hash() == base.design_hash()
    assert study_key("0" * 64, base) == "0" * 64  # the legacy workspace name, unchanged


def test_axes_change_the_design_and_so_the_study():
    base = vermeulen_design()
    tested = base.model_copy(update={"axes": {"efficiency": ON}})
    assert tested.design_hash() != base.design_hash()
    assert study_key("0" * 64, tested) != study_key("0" * 64, base)
    assert '"axes":{"efficiency":["linregpcr","per_well","assumed_2"]}' in tested.canonical()


@pytest.mark.parametrize("axes", [{}, {"efficiency": ("linregpcr",)}, {"efficiency": ()}])
def test_one_spelling_per_analysis(axes):
    with pytest.raises(ValidationError):
        StudyDesign.model_validate({**vermeulen_design().model_dump(), "axes": axes})


@pytest.mark.parametrize(
    ("name", "options", "match"),
    [
        ("efficiency", ["per_well", "linregpcr"], "must start with 'linregpcr'"),
        ("efficiency", ["linregpcr", "guess"], "unknown option 'guess'"),
        ("efficiency", ["linregpcr", "per_well", "per_well"], "more than once"),
        ("efficiency", "linregpcr,per_well", "list of option ids"),
        ("efficiency", [], "non-empty list"),
        ("refs", ["x", "y"], "cannot ask to test 'refs'"),
        ("undetermined", ["drop", "floor"], "cannot ask to test 'undetermined'"),
    ],
)
def test_axis_options_are_refused_in_words(name, options, match):
    with pytest.raises(DesignError, match=match):
        axis_options(name, options)


def test_check_design_checks_the_axes():
    bad = vermeulen_design().model_copy(update={"axes": {"efficiency": ("linregpcr", "guess")}})
    with pytest.raises(DesignError, match="unknown option 'guess'"):
        check_design(bad)
    good = vermeulen_design().model_copy(update={"axes": {"efficiency": ON}})
    assert check_design(good) is good


# ---- a person's decision ------------------------------------------------------------------


def test_an_accepted_choice_switches_the_axis_on_and_off_again():
    base = vermeulen_design()
    on = design_from_proposals(base, [_axis(ON)])
    assert on.axes == {"efficiency": ON}
    off = design_from_proposals(on, [_axis(["linregpcr"])])
    assert off.axes is None
    assert off.design_hash() == base.design_hash()  # back to the study it was
    later = design_from_proposals(base, [_axis(ON), _axis(["linregpcr"])])
    assert later.axes is None  # a later decision on the same choice wins


@pytest.mark.parametrize("status", ["proposed", "rejected", "superseded"])
def test_a_choice_nobody_accepted_changes_nothing(status):
    base = vermeulen_design()
    assert design_from_proposals(base, [_axis(ON, status)]).design_hash() == base.design_hash()


def test_an_unusable_choice_is_refused_with_the_proposal_named():
    with pytest.raises(DesignError, match="proposal p_a+: the options of 'efficiency'"):
        design_from_proposals(vermeulen_design(), [_axis(["per_well"])])


def test_the_design_gives_the_engine_its_efficiency_options():
    assert StudySettings.from_design(vermeulen_design()).efficiency == ("linregpcr",)
    assert StudySettings.from_design(vermeulen_design()) == StudySettings()  # legacy, as before
    tested = vermeulen_design().model_copy(update={"axes": {"efficiency": ON}})
    settings = StudySettings.from_design(tested)
    assert settings.efficiency == ON
    assert settings.design == tested  # a designed study, with its own id


# ---- the engine's check (D-AXIS) ----------------------------------------------------------


@pytest.fixture
def mini_facts(tmp_path):
    from tests.fixtures.studio.studio_mini import write_studio_mini

    qinspect.clear_cache()
    facts = qinspect.file_facts(write_studio_mini(tmp_path / "mini.rdml"))
    yield facts
    qinspect.clear_cache()


def _series() -> Proposal:
    samples = {"STD_100": 100.0, "STD_1000": 1000.0, "STD_10000": 10000.0}
    return Proposal(
        id="p_" + "b" * 16,
        study_id="s",
        kind="design.dilution_series",
        subject="std",
        payload={"samples": samples},
        made_by=MadeBy(kind="rule"),
        status="accepted",
    )


def test_d_axis_finds_nothing_against_what_the_file_can_give(mini_facts):
    check = axis_check("efficiency", {"options": ["linregpcr", "per_well", "assumed_2"]},
                       mini_facts.wells, [])  # fmt: skip
    assert check.status == "consistent" and check.rule_ids == ["D-AXIS"]
    assert check.details["own_efficiency_in_valid_range"] > 0
    assert check.details["options"] == ["linregpcr", "per_well", "assumed_2"]


def test_d_axis_refutes_a_dilution_series_the_file_does_not_have(mini_facts):
    payload = {"options": ["linregpcr", "standard_curve"]}
    check = axis_check("efficiency", payload, mini_facts.wells, [])
    assert check.status == "contradicted"
    assert check.details["not_in_the_file"] == ["standard_curve"]
    assert "dilution series" in check.note
    # once a person accepted the standards as a dilution series, the file has one
    check = axis_check("efficiency", payload, mini_facts.wells, [_series()])
    assert check.status == "consistent"
    assert check.details["dilution_series_with_three_levels"] >= 1


@pytest.mark.parametrize(
    ("subject", "payload"),
    [
        ("efficiency", {"options": ["per_well"]}),
        ("efficiency", {"options": ["linregpcr", "guess"]}),
        ("efficiency", {}),
        ("refs", {"options": ["a", "b"]}),
    ],
)
def test_d_axis_refutes_options_that_are_not_the_choices_own(mini_facts, subject, payload):
    check = axis_check(subject, payload, mini_facts.wells, [])
    assert check.status == "contradicted" and check.details["problem"]
    assert not any(ch.isdigit() for ch in check.note)  # numbers live in the details


def test_d_axis_notes_never_carry_digits(mini_facts):
    for payload in ({"options": list(ON)}, {"options": ["linregpcr", "amplicon_mean"]}):
        check = axis_check("efficiency", payload, mini_facts.wells, [])
        assert not any(ch.isdigit() for ch in check.note), check.note


# ---- the CLI ------------------------------------------------------------------------------


def test_qpilot_run_names_the_models_it_can_test(capsys):
    from qpilot.cli import main

    assert main(["run", "--efficiency", "guess"]) == 1
    err = capsys.readouterr().err
    assert "unknown efficiency model(s) ['guess']" in err and "per_well" in err
    assert main(["run", "--efficiency", "all", "--contrast", "ODC1"]) == 1
    assert "cannot be combined with --contrast" in capsys.readouterr().err


def test_the_cli_reads_the_models_primary_first():
    from qpilot.cli.engine_cmds import _efficiency_models

    assert _efficiency_models("all") == (
        "linregpcr",
        "per_well",
        "amplicon_mean",
        "assumed_2",
        "standard_curve",
    )
    assert _efficiency_models("assumed_2, per_well,assumed_2") == (
        "linregpcr",
        "assumed_2",
        "per_well",
    )
    assert _efficiency_models("linregpcr") == ("linregpcr",)
