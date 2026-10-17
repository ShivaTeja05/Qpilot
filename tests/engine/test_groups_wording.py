"""Every module that tells a confirmed-design study from the demo uses the same marker."""

from qpilot import app_state
from qpilot.core import record
from qpilot.explain.templates import render_template
from qpilot.qpcr import confidence_checks, study
from qpilot.schemas import DesignSummary, Fact, StudyResult


def test_groups_note_is_one_string_everywhere():
    notes = {
        study.GROUPS_NOTE,
        confidence_checks.GROUPS_NOTE,
        app_state.GROUPS_NOTE,
        record.GROUPS_NOTE,
    }
    assert notes == {"groups from the confirmed design"}


def test_design_line_never_prints_a_cut_for_a_confirmed_design(fixture_result: StudyResult):
    design = DesignSummary(
        group_var="LPS vs PBS",
        cut=0.0,
        n_hi=4,
        n_lo=5,
        note=study.GROUPS_NOTE,
        refs_primary=("Hprt",),
    )
    line = app_state.design_line(fixture_result.model_copy(update={"design": design}))
    assert "top" not in line and "%" not in line and "LPS vs PBS" in line
    assert "Expression-defined" in app_state.design_line(fixture_result)


def test_summary_names_the_confirmed_groups(fixture_facts):
    facts = {
        **fixture_facts,
        "f_group_a": Fact(id="f_group_a", value="LPS"),
        "f_group_b": Fact(id="f_group_b", value="PBS"),
    }
    text = render_template("summary_v1", facts)
    assert "LPS" in text.plain and "PBS" in text.plain and "High group" not in text.plain
    assert "High group" in render_template("summary_v1", fixture_facts).plain
