import json
import math
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from qpilot.cli import main
from qpilot.qpcr.plan import (
    MAX_REPLICATES,
    cheapest_design,
    design_cost,
    effective_sd,
    group_mean_se,
    mde_fold,
    n_needed,
    plan,
    simulate_calls,
)


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


# --- N4 replicate budget: biological, RT and technical replicates in one formula -------------

LEGACY = [(2, 0.5, 3), (2, 1.0, 3), (2, 1.95, 3), (4, 1.0, 3), (1.5, 0.5, 20), (2, 0.3, 12)]


@pytest.mark.parametrize(("fc", "sd", "n"), LEGACY)
@pytest.mark.parametrize(
    "extra",
    [
        {"sd_rt": 0, "sd_well": 0},
        {"sd_rt": 0.0, "sd_well": None},
        {"sd_rt": None, "sd_well": 0.0, "n_rt": 3, "n_tech": 4},
        {"n_tech": 3},
        {"cost_subject": 100, "cost_rt": 5, "cost_well": 2},
    ],
)
def test_zero_rt_and_well_sd_reproduces_the_single_sd_planner_exactly(fc, sd, n, extra):
    before = plan(fc, sd, n)
    after = plan(fc, sd, n, **extra)
    assert before.budget is None and after.budget is not None
    assert after.mde_fold == before.mde_fold and after.n_needed == before.n_needed  # exact
    assert after.message == before.message and after.cannot_detect == before.cannot_detect
    assert after.budget["sd_effective"] == sd and after.budget["n_bio_needed"] == before.n_needed


def test_effective_sd_short_circuits_and_matches_the_se_formula():
    assert effective_sd(1.95) == 1.95 and effective_sd(0.7, None, None, 3, 3) == 0.7
    assert effective_sd(0.7, 0, 0.0, 10, 10) == 0.7
    for sb, sr, sw, nb, nr, nt in [
        (0.5, 0.4, 0.3, 6, 1, 1),
        (0.5, 0.4, 0.3, 6, 2, 3),
        (1.2, 0.0, 0.9, 4, 1, 5),
        (0.1, 2.0, 0.0, 30, 3, 1),
    ]:
        literal = math.sqrt(sb**2 / nb + sr**2 / (nb * nr) + sw**2 / (nb * nr * nt))
        assert group_mean_se(nb, sb, sr, sw, nr, nt) == pytest.approx(literal, rel=1e-12)
        assert effective_sd(sb, sr, sw, nr, nt) == pytest.approx(literal * math.sqrt(nb))


def test_the_mapped_scratch_numbers_and_the_comparison_sentence():
    # qcplan map §2 item 5: sigma_bio 0.5, sigma_RT 0.4, sigma_well 0.3, six subjects.
    out = plan(2, 0.5, 6, sd_rt=0.4, sd_well=0.3)
    compare = out.budget["compare"]
    assert out.mde_fold == pytest.approx(2.21, abs=0.005) == compare["planned"]
    assert compare["one_more_well"] == pytest.approx(2.13, abs=0.005)
    assert compare["one_more_rt"] == pytest.approx(1.99, abs=0.005)
    assert compare["more_subjects"] == pytest.approx(1.99, abs=0.005)
    assert plan(2, 0.5, 6, sd_rt=0.4, sd_well=0.3, n_tech=2).mde_fold == pytest.approx(
        2.13, abs=0.005
    )
    assert plan(2, 0.5, 6, sd_rt=0.4, sd_well=0.3, n_tech=3).mde_fold == pytest.approx(
        2.10, abs=0.005
    )
    assert plan(2, 0.5, 8, sd_rt=0.4, sd_well=0.3).mde_fold == pytest.approx(1.99, abs=0.005)
    assert (
        "At 6 subjects per group (1 RT reaction each, 1 well per RT, 80% power): a second technical"
        " replicate moves the detectable fold from 2.21 to 2.13; a second RT replicate moves it to"
        " 1.99; two more subjects per group move it to 1.99." in out.budget["sentences"]
    )
    # Replicates cannot buy what subjects buy: the limits with unlimited wells, RT reactions.
    assert compare["wells_limit"] == pytest.approx(mde_fold(6, math.sqrt(0.25 + 0.16)))
    assert compare["replicates_limit"] == pytest.approx(mde_fold(6, 0.5))
    assert out.budget["planned"]["reaches_target"] is False and out.n_needed == 9
    third = plan(2, 0.5, 6, sd_rt=0.4, sd_well=0.3, n_tech=2).budget["sentences"][1]
    assert "a third technical replicate moves the detectable fold from 2.13 to 2.1;" in third


def test_the_sentence_says_only_what_the_inputs_support():
    only_well = plan(2, 0.5, 6, sd_well=0.3).budget
    assert only_well["compare"]["one_more_rt"] is None
    assert "RT replicate" not in only_well["sentences"][1]
    assert any("No RT SD given" in note for note in only_well["notes"])
    zero_well = plan(2, 0.5, 6, sd_rt=0.4, sd_well=0.0).budget["sentences"][1]
    assert "a second technical replicate leaves the detectable fold at" in zero_well
    neither = plan(2, 0.5, 6, n_tech=3).budget
    assert neither["sentences"][1].endswith(
        "two more subjects per group move the detectable fold from 1.75 to 1.62."
    )
    assert any("given no effect" in note for note in neither["notes"])
    assert plan(2, None, 6, sd_well=0.3).budget["sd_effective"] is None


# A test-only simulator of the nested design: every subject has a biological effect, every RT
# reaction an RT effect and every well a well effect; a subject's value is the plain mean of log2
# over all its wells, which is what qpilot.qpcr.quant does for a biological unit.


def _nested_values(rng, reps, n_bio, sd_bio, sd_rt, sd_well, n_rt, n_tech, shift=0.0):
    bio = rng.normal(0.0, sd_bio, (reps, n_bio, 1, 1))
    rt = rng.normal(0.0, sd_rt, (reps, n_bio, n_rt, 1))
    well = rng.normal(0.0, sd_well, (reps, n_bio, n_rt, n_tech))
    wells = shift + bio + rt + well
    return wells, wells.reshape(reps, n_bio, n_rt * n_tech).mean(axis=2)


def test_the_simulator_aggregates_a_unit_the_way_quant_does():
    from qpilot.qpcr.quant import log2_matrix

    rng = np.random.default_rng(5)
    wells, values = _nested_values(rng, 1, 5, 0.5, 0.4, 0.3, n_rt=2, n_tech=3)
    rows, units = [], {}
    for (_, i, j, _), log2 in np.ndenumerate(wells):
        sample = f"s{i:02d}_rt{j}"
        units[sample] = f"s{i:02d}"
        rows.append(("p1", f"A{len(rows) + 1}", sample, "unkn", "G", 2.0**log2))
    curves = pd.DataFrame(rows, columns=["run_id", "well", "sample", "sample_type", "target", "n0"])
    matrix = log2_matrix(curves, units)
    assert list(matrix.index) == [f"s{i:02d}" for i in range(5)]
    assert matrix["G"].to_numpy() == pytest.approx(values[0], abs=1e-12)


DESIGNS = [  # sigma_bio, sigma_RT, sigma_well, n_bio, n_RT, n_tech
    (0.5, 0.4, 0.3, 6, 1, 1),
    (0.5, 0.4, 0.3, 6, 2, 3),
    (0.3, 0.0, 0.6, 4, 1, 3),
    (1.0, 0.5, 0.25, 10, 2, 2),
    (0.2, 0.5, 0.5, 3, 3, 2),
]


@pytest.mark.parametrize("target_power", [0.5, 0.8])
@pytest.mark.parametrize("k", range(len(DESIGNS)))
def test_a_nested_monte_carlo_agrees_with_the_formula(k, target_power):
    from scipy import stats

    sb, sr, sw, nb, nr, nt = DESIGNS[k]
    sd = effective_sd(sb, sr, sw, nr, nt)
    fc = mde_fold(nb, sd, power=target_power)  # the formula's power at this fc is target_power
    delta, reps = math.log2(fc), 40_000
    rng = np.random.default_rng(1000 + k)
    hi = _nested_values(rng, reps, nb, sb, sr, sw, nr, nt, shift=delta)[1]
    lo = _nested_values(rng, reps, nb, sb, sr, sw, nr, nt)[1]
    # the variance of one subject's value is effective_sd squared
    spread = np.concatenate([hi - delta, lo]).var(ddof=1)
    assert spread == pytest.approx(sd**2, rel=0.02)
    # 1. the formula's own test (a z-test on the group means) within 1 percentage point
    nd = NormalDist()
    se_diff = math.sqrt(2) * group_mean_se(nb, sb, sr, sw, nr, nt)
    z = nd.inv_cdf(0.975)
    formula = nd.cdf(delta / se_diff - z) + nd.cdf(-delta / se_diff - z)
    diff = hi.mean(axis=1) - lo.mean(axis=1)
    assert float((np.abs(diff) / se_diff > z).mean()) == pytest.approx(formula, abs=0.01)
    # 2. qPilot's Welch test on subject values matches simulate_calls run on effective_sd
    v_hi, v_lo = hi.var(axis=1, ddof=1) / nb, lo.var(axis=1, ddof=1) / nb
    df = (v_hi + v_lo) ** 2 / ((v_hi**2 + v_lo**2) / (nb - 1))
    p = 2 * stats.t.sf(np.abs(diff / np.sqrt(v_hi + v_lo)), df)
    welch = float((p < 0.05).mean())
    assert welch == pytest.approx(simulate_calls(fc, sd, nb, reps=200_000)[0], abs=0.01)


def test_bustin_2025_six_technical_replicates_closest_reading():
    from scipy import stats

    # 1.5-fold at SD 0.5 Cq and 80 % power; one cycle = one log2 unit at perfect doubling.
    delta, sd = math.log2(1.5), 0.5
    zsum = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.80)
    # Closest reading: one mean of n replicate values against a fixed value, normal approximation.
    one_sample = zsum**2 * sd**2 / delta**2
    assert one_sample == pytest.approx(5.73, abs=0.01) and math.ceil(one_sample) == 6
    assert 2 ** (zsum * sd / math.sqrt(6)) == pytest.approx(1.49, abs=0.005)

    # The exact one-sample t-test needs eight; two groups (the planner's design) need thirteen.
    def one_sample_t_power(n):
        nc, crit = delta / (sd / math.sqrt(n)), stats.t.ppf(0.975, n - 1)
        return stats.nct.sf(crit, n - 1, nc) + stats.nct.cdf(-crit, n - 1, nc)

    assert one_sample_t_power(7) < 0.80 < one_sample_t_power(8)
    assert n_needed(1.5, 0.5) == 13
    assert mde_fold(6, 0.5) == pytest.approx(1.75, abs=0.005)
    # The same two-group reading through the nested formula: one sample per arm, six wells each.
    assert mde_fold(1, effective_sd(0.0, 0.0, 0.5, 1, 6)) == pytest.approx(mde_fold(6, 0.5))


def test_the_cost_optimiser_picks_the_hand_checked_cheapest_design():
    # sigma_bio = sigma_well = 0.5, no RT SD (one RT per subject), 100 per subject, 10 per well.
    # Subjects needed are ceil(2 * 2.8016^2 * sd^2 + 1) for a 2-fold change:
    #   wells 1: sd^2 0.5    -> 9 subjects, 9 * 110 = 990
    #   wells 2: sd^2 0.375  -> 7 subjects, 7 * 120 = 840
    #   wells 3: sd^2 0.333  -> 7 subjects, 7 * 130 = 910
    #   wells 4: sd^2 0.3125 -> 6 subjects, 6 * 140 = 840  (ties with wells 2; detects 1.87-fold)
    #   wells 5: sd^2 0.3    -> 6 subjects, 6 * 150 = 900, and more wells only cost more.
    best = cheapest_design(2, 0.5, sd_well=0.5, cost_subject=100, cost_rt=0, cost_well=10)
    assert (best["n_bio"], best["n_rt"], best["n_tech"]) == (6, 1, 4)
    assert best["cost_per_group"] == 840 and best["cost_both_groups"] == 1680
    assert best["wells_per_group"] == 24 and best["n_designs"] == MAX_REPLICATES
    tied = mde_fold(7, effective_sd(0.5, None, 0.5, 1, 2))
    assert best["mde_fold"] == pytest.approx(1.87, abs=0.005)
    assert best["mde_fold"] < tied  # the tie goes to the smaller detectable fold
    # Three levels (100 per subject, 5 per RT, 2 per well): six subjects is the fewest possible;
    # among six-subject designs that reach the target, 3 RT x 2 wells (762) beats 4 x 1 (768).
    three = cheapest_design(
        2, 0.5, sd_rt=0.4, sd_well=0.3, cost_subject=100, cost_rt=5, cost_well=2
    )
    assert (three["n_bio"], three["n_rt"], three["n_tech"], three["cost_per_group"]) == (
        6,
        3,
        2,
        762,
    )
    assert three["n_designs"] == MAX_REPLICATES**2
    assert design_cost(6, 4, 1, 100, 5, 2) == 768


def test_the_optimiser_is_the_minimum_of_an_independent_enumeration():
    for sb, sr, sw, costs in [
        (0.5, 0.4, 0.3, (100, 5, 2)),
        (0.3, 0.6, 0.2, (40, 25, 1)),
        (1.0, 0.2, 0.8, (500, 2, 0.5)),
    ]:
        best = cheapest_design(
            2, sb, sd_rt=sr, sd_well=sw, cost_subject=costs[0], cost_rt=costs[1], cost_well=costs[2]
        )
        every = [
            design_cost(n_needed(2, effective_sd(sb, sr, sw, r, t)), r, t, *costs)
            for r in range(1, MAX_REPLICATES + 1)
            for t in range(1, MAX_REPLICATES + 1)
        ]
        assert best["cost_per_group"] == min(every)


def test_equal_costs_tie_as_written_and_break_by_rule():
    # 0.3 per subject, 0.7 per RT, 0.1 per well: n (1.0 + 0.1 wells). Six subjects with four
    # wells and seven with two both cost 8.4; binary floats would see two different costs.
    assert design_cost(6, 1, 4, 0.3, 0.7, 0.1) == design_cost(7, 1, 2, 0.3, 0.7, 0.1) == 8.4
    assert design_cost(1, 3, 1, 0, 0.1, 0) == design_cost(1, 1, 1, 0.3, 0, 0)
    best = cheapest_design(2, 0.5, sd_well=0.5, cost_subject=0.3, cost_rt=0.7, cost_well=0.1)
    assert (best["n_bio"], best["n_tech"]) == (6, 4)  # the smaller detectable fold wins the tie
    runs = {
        json.dumps(
            cheapest_design(
                2, 0.5, sd_rt=0.4, sd_well=0.3, cost_subject=100, cost_rt=5, cost_well=2
            )
        )
        for _ in range(3)
    }
    assert len(runs) == 1


def test_a_level_is_searched_only_when_its_sd_is_given():
    out = plan(2, 0.5, 6, sd_well=0.5, n_rt=2, cost_subject=100, cost_rt=5, cost_well=10).budget
    assert out["searched"] == {"n_rt": [2, 2], "n_tech": [1, MAX_REPLICATES]}
    assert out["cheapest"]["n_rt"] == 2
    unmodelled = plan(2, 0.5, 6, n_tech=2, cost_subject=100, cost_rt=5, cost_well=10).budget
    assert unmodelled["cheapest"]["n_tech"] == 2 and unmodelled["cheapest"]["n_designs"] == 1


def test_the_budget_states_costs_and_the_planned_design():
    out = plan(2, 0.5, 6, sd_rt=0.4, sd_well=0.3, cost_subject=100, cost_rt=5, cost_well=2)
    budget = out.budget
    assert budget["planned"]["cost_per_group"] == 6 * (100 + 1 * (5 + 1 * 2))
    assert (
        budget["cheapest"]["simulated_significant"]
        == simulate_calls(2, budget["cheapest"]["sd_effective"], 6)[0]
    )
    text = " ".join(budget["sentences"])
    assert "Cheapest design (of 100 compared)" in text and "costing 762 per group" in text
    assert "The planned design costs 642 per group and does not reach the target." in text
    json.dumps(out.model_dump(mode="json"), allow_nan=False)


@pytest.mark.parametrize(
    ("costs", "says"),
    [
        ({"cost_subject": 100}, "give the cost per RT reaction and per well as well"),
        ({"cost_well": 2, "cost_rt": 1}, "give the cost per subject as well"),
        ({"cost_subject": 0, "cost_rt": 0, "cost_well": 0}, "every cost is zero"),
    ],
)
def test_the_cheapest_design_needs_every_cost(costs, says):
    budget = plan(2, 0.5, 6, sd_rt=0.4, sd_well=0.3, **costs).budget
    assert budget["cheapest"] is None and any(says in note for note in budget["notes"])


def test_an_expected_cq_is_accepted_but_no_floor_is_invented():
    out = plan(1.5, 0.5, 6, expected_cq=31)
    budget = out.budget
    assert budget["claim_floor"] == "not_built" and budget["inputs"]["expected_cq"] == 31
    assert any("not built yet, so no floor is applied" in note for note in budget["notes"])
    assert out.mde_fold == plan(1.5, 0.5, 6).mde_fold
    # Nothing else moves: the same budget as without a Cq, apart from the input and the note.
    plain = plan(1.5, 0.5, 6, n_tech=1, sd_rt=None, cost_subject=None, n_rt=2).budget
    with_cq = plan(1.5, 0.5, 6, n_rt=2, expected_cq=31).budget
    with_cq["inputs"]["expected_cq"], with_cq["claim_floor"] = None, None
    with_cq["notes"] = [n for n in with_cq["notes"] if "claim-floor" not in n]
    assert with_cq == plain


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sd_rt": -0.1},
        {"sd_rt": 10.5},
        {"sd_well": float("nan")},
        {"sd_well": True},
        {"sd_rt": "0.4"},
        {"n_rt": 0},
        {"n_rt": 11},
        {"n_tech": 2.0},
        {"n_tech": True},
        {"n_tech": None},
        {"cost_subject": -1},
        {"cost_well": float("inf")},
        {"cost_rt": 1e10},
        {"expected_cq": 0},
        {"expected_cq": 61},
        {"expected_cq": float("nan")},
    ],
)
def test_impossible_budget_inputs_are_refused(kwargs):
    with pytest.raises(ValueError):
        plan(2, 0.5, 6, **kwargs)


def test_the_new_arguments_are_keyword_only():
    with pytest.raises(TypeError):
        plan(2, 0.5, 6, 0.05, 0.8, None, None, None, None, 0.4)


def test_plan_is_deterministic_with_a_budget():
    kwargs = {"sd_rt": 0.4, "sd_well": 0.3, "cost_subject": 100, "cost_rt": 5, "cost_well": 2}
    assert (
        plan(2, 0.5, 6, **kwargs).model_dump_json() == plan(2, 0.5, 6, **kwargs).model_dump_json()
    )


def test_plan_cli_budget_flags(capsys):
    args = ["plan", "--fc", "2", "--sd", "0.5", "--n", "6", "--sd-rt", "0.4", "--sd-well", "0.3"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Budget: At 6 subjects per group" in out and "Note: The biological SD" in out
    assert (
        main(
            [
                *args,
                "--cost-subject",
                "100",
                "--cost-rt",
                "5",
                "--cost-well",
                "2",
                "--n-rt",
                "1",
                "--n-tech",
                "1",
                "--cq",
                "31",
                "--json",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["budget"]["cheapest"]["cost_per_group"] == 762
    assert data["budget"]["claim_floor"] == "not_built"
    assert main(["plan", "--sd", "1", "--n-tech", "0"]) == 2
    assert "n_tech must be a whole number" in capsys.readouterr().err
    assert main(["plan", "--sd", "1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["budget"] is None


@pytest.mark.demo_data
def test_demo_has_no_replicates_and_quant_averages_planted_ones_as_the_formula_says(
    demo_rdml_path,
):
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.quant import log2_matrix, replicate_sd

    curves = analyse_study(demo_rdml_path)
    unknown = curves[curves["sample_type"] == "unkn"]
    # Measured: 366 samples, one well per sample and gene, so no RT or well SD can come from it.
    assert unknown["sample"].nunique() == 366
    assert not unknown.duplicated(["sample", "target"]).any()
    assert replicate_sd(curves).isna().to_numpy().all()
    # Plant two RT reactions x three wells of every real well, with seeded RT and well noise,
    # and let quant average each unit: what is left over is the formula's RT and well term.
    n_rt, n_tech, sd_rt, sd_well = 2, 3, 0.4, 0.3
    rng = np.random.default_rng(7)
    m = len(unknown)
    rt = np.repeat(rng.normal(0.0, sd_rt, (m, n_rt)), n_tech, axis=1)
    noise = rt + rng.normal(0.0, sd_well, (m, n_rt * n_tech))
    copies = np.repeat(np.arange(m), n_rt * n_tech)
    rt_index = np.tile(np.repeat(np.arange(n_rt), n_tech), m)
    samples = unknown["sample"].to_numpy(dtype=object)[copies]
    planted = pd.DataFrame(
        {
            "sample": [f"{s}|rt{r}" for s, r in zip(samples, rt_index, strict=True)],
            "sample_type": "unkn",
            "target": unknown["target"].to_numpy(dtype=object)[copies],
            "n0": unknown["n0"].to_numpy(dtype=float)[copies] * 2.0 ** noise.ravel(),
        }
    )
    units = dict(zip(planted["sample"], samples, strict=True))
    left = (log2_matrix(planted, units) - log2_matrix(curves)).to_numpy().ravel()
    left = left[~np.isnan(left)]
    assert len(left) > 23_000
    expected = effective_sd(0.0, sd_rt, sd_well, n_rt, n_tech) ** 2
    assert left.var(ddof=1) == pytest.approx(expected, rel=0.03)
    assert left.mean() == pytest.approx(0.0, abs=0.01)
