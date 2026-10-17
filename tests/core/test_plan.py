import pytest

from qpilot.qpcr.plan import mde_fold, n_needed, plan


@pytest.mark.parametrize(("sd", "expected"), [(0.5, 2.2), (1.0, 4.9), (1.95, 22.0)])
def test_mde_three_per_group(sd, expected):
    assert plan(2, sd, 3).mde_fold == pytest.approx(expected, rel=0.03)


def test_n_needed_matches_the_formula():
    # 2 (z.975 + z.80)^2 sigma^2 / delta^2 + 1, rounded up; the planning table's rows.
    assert [n_needed(2, s) for s in (0.3, 0.5, 1.0, 2.0)] == [3, 5, 17, 64]
    # Vermeulen-like sigma 1.95 needs 61 per group (64 is the sigma = 2.0 row).
    assert n_needed(2, 1.95) == 61


def test_down_regulation_is_symmetric():
    assert n_needed(0.5, 1.0) == n_needed(2.0, 1.0)


def test_unknown_sigma_gives_a_message_not_a_number():
    out = plan(2, None, 3)
    assert out.n_needed is None and out.mde_fold is None
    assert "Sigma unknown" in out.message


def test_cannot_detect_list():
    out = plan(2, 1.95, 3)
    assert out.n_needed == 61
    assert len(out.cannot_detect) == 1 and "2-fold" in out.cannot_detect[0]
    assert plan(2, 0.3, 12).cannot_detect == []


def test_rules_in_words():
    out = plan(
        2,
        1.0,
        n_plates=4,
        calibrator_on_every_plate=False,
        n_candidate_refs=2,
        one_sample_per_subject=True,
    )
    joined = " ".join(out.rules)
    assert "confounded" in joined and "geNorm" in joined and "subjects" in joined
    assert plan(2, 1.0, n_plates=4, calibrator_on_every_plate=True).rules == []


@pytest.mark.parametrize(
    "kwargs",
    [{"fc": 1}, {"fc": -2}, {"sd_log2": 0}, {"n_per_group": 1}, {"alpha": 1.5}],
)
def test_bad_inputs(kwargs):
    with pytest.raises(ValueError):
        plan(**{"fc": 2, "sd_log2": 1.0, **kwargs})


def test_mde_shrinks_with_n():
    assert mde_fold(12, 1.0) < mde_fold(3, 1.0)


def test_plan_simulates_qpilots_own_rule():
    from qpilot.qpcr.plan import simulate_calls

    sig, called = simulate_calls(2, 1.0, 17)
    assert sig == pytest.approx(0.8, abs=0.03) and called == pytest.approx(0.5, abs=0.03)
    assert simulate_calls(1.5, 1.0, 47)[1] < 0.05
    # small groups: the simulation, not the normal approximation, is what the message reports
    assert simulate_calls(4, 1.0, 3)[1] == pytest.approx(0.37, abs=0.03)
    assert simulate_calls(2, 1.0, 17) == simulate_calls(2, 1.0, 17)  # seeded
    msg = plan(4, 1.0, 3).message
    assert "At the planned 3 per group: significant 37%, called 37%." in msg
    assert "called only when noise makes it look 2-fold" in plan(1.5, 1.0).message


def test_a_fold_change_near_one_needs_no_big_memory():
    import tracemalloc

    tracemalloc.start()
    out = plan(1.01, 1.0)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert out.n_needed > 10_000 and peak < 50_000_000  # was tens of GB


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fc": 2, "sd_log2": float("inf")},
        {"fc": 2, "sd_log2": 1e200},
        {"fc": float("inf"), "sd_log2": 1.0},
        {"fc": float("nan"), "sd_log2": 1.0},
        {"fc": 1e6, "sd_log2": 1.0},
        {"fc": 2, "sd_log2": 1.0, "n_per_group": 1},
    ],
)
def test_impossible_inputs_are_refused_clearly(kwargs):
    with pytest.raises(ValueError):
        plan(**kwargs)
    from qpilot.mcp_server import QpilotTools

    assert "error" in QpilotTools().qpcr_plan(**kwargs)  # never a traceback over MCP


def test_a_change_the_rule_rarely_calls_is_listed_as_undetectable():
    out = plan(1.5, 0.5, 20)
    assert any("qPilot's rule calls it" in item for item in out.cannot_detect)
    assert "just under 2-fold" in plan(1.9999999, 1.0).message
