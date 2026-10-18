"""Ask your data passes the replicate-budget arguments to qpcr_plan (numbers only)."""

import pytest

from qpilot.ai.ask import PLAN_ARGS, _Context, answer_facts, run_tool


def test_plan_budget_arguments_reach_the_planner(store, study):
    ctx = _Context(store, study)
    args = {"fc": 2.0, "sd_log2": 0.5, "n_per_group": 6, "sd_rt": 0.3, "sd_well": 0.4,
            "n_rt": 1, "n_tech": 2, "cost_subject": 100, "cost_rt": 10, "cost_well": 2,
            "ignored": "x"}  # fmt: skip
    out = run_tool(ctx, "qpcr_plan", args)
    assert "error" not in out and out["budget"]["inputs"]["n_tech"] == 2
    assert out["budget"]["cheapest"] is not None
    view, facts = answer_facts(ctx, "qpcr_plan", out)
    assert view["n_per_group_needed"].startswith("{{") and facts
    assert {
        "sd_rt",
        "sd_well",
        "n_rt",
        "n_tech",
        "cost_subject",
        "cost_rt",
        "cost_well",
    } <= PLAN_ARGS


@pytest.mark.parametrize("bad", [{"n_rt": 1.5}, {"n_tech": 2.0}, {"sd_rt": "0.3"}, {"n_rt": True}])
def test_plan_budget_arguments_must_be_numbers_and_counts_whole(store, study, bad):
    with pytest.raises(TypeError):
        run_tool(_Context(store, study), "qpcr_plan", {"fc": 2.0, "sd_log2": 0.5, **bad})
