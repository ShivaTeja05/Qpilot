"""The planner's additions to ``qpilot.qpcr.plan`` keep the module's API and numbers.

``simulate_calls`` without ``n_other`` gives exactly the numbers it always gave; equal groups give
``mde_fold`` exactly; ``pooled_sd`` is the textbook pooled SD; ``n_for_call`` is the first size
whose simulated call rate reaches the power; ``plan(min_log2fc=1)`` is ``plan()``.
"""

from __future__ import annotations

import math
import statistics

import pytest

from qpilot.qpcr import plan as qplan


@pytest.mark.parametrize(("fc", "sd", "n"), [(2, 1.95, 3), (3, 1.27, 12), (0.5, 0.9, 40)])
def test_equal_groups_are_the_balanced_numbers(fc, sd, n):
    assert qplan.simulate_calls(fc, sd, n, n_other=n) == qplan.simulate_calls(fc, sd, n)
    assert qplan.mde_fold_groups(n, n, sd) == pytest.approx(qplan.mde_fold(n, sd), rel=1e-12)
    assert qplan.balanced_equivalent(n, n) == pytest.approx(n)


def test_the_readmes_numbers_still_hold():
    assert qplan.n_needed(2, 1.95) == 61
    assert qplan.plan(2, 1.95, 3).mde_fold == pytest.approx(22.0, rel=0.03)
    assert qplan.plan(2, 1.95, 3, min_log2fc=1.0) == qplan.plan(2, 1.95, 3)


def test_unbalanced_groups_sit_between_their_sizes():
    sd = 1.27
    mde = qplan.mde_fold_groups(53, 294, sd)
    assert qplan.mde_fold(294, sd) < mde < qplan.mde_fold(53, sd)
    assert mde == pytest.approx(qplan.mde_fold(qplan.balanced_equivalent(53, 294), sd))
    sig, called = qplan.simulate_calls(3, sd, 53, n_other=294)
    assert 0 <= called <= sig <= 1


def test_pooled_sd_is_the_textbook_one():
    a, b = [1.0, 2.0, 4.0], [3.0, 7.0]
    expected = math.sqrt(
        (2 * statistics.variance(a) + 1 * statistics.variance(b)) / (len(a) + len(b) - 2)
    )
    sd, df = qplan.pooled_sd([a, b, [9.0]])  # a group of one adds nothing
    assert sd == pytest.approx(expected) and df == 3
    with pytest.raises(ValueError):
        qplan.pooled_sd([[1.0], [2.0]])


def test_sigma_interval_brackets_sigma_and_narrows_with_df():
    lo, hi = qplan.sigma_interval(1.0, 4)
    lo2, hi2 = qplan.sigma_interval(1.0, 400)
    assert lo < lo2 < 1.0 < hi2 < hi


@pytest.mark.parametrize(("fc", "sd", "power"), [(3, 1.27, 0.8), (4, 0.8, 0.8), (0.33, 1.4, 0.9)])
def test_n_for_call_is_the_first_size_that_reaches_the_power(fc, sd, power):
    n = qplan.n_for_call(fc, sd, power)
    assert n is not None and n >= 2
    assert qplan.simulate_calls(fc, sd, n)[1] >= power
    if n > 2:
        assert qplan.simulate_calls(fc, sd, n - 1)[1] < power


def test_no_size_calls_a_change_at_or_below_the_threshold():
    assert qplan.n_for_call(2.0, 1.0) is None
    assert qplan.n_for_call(1.5, 0.3) is None
    assert qplan.n_for_call(2.5, 4.4, n_max=50) is None  # beyond the largest size allowed
