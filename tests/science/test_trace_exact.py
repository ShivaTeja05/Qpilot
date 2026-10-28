"""Trace's what-ifs on a paired or Holm-corrected study are the space's own evaluation.

Trace scores every sample by "what if it were set aside" and every reference well by "what if
it read as the sample's other references expect" in closed form: a one-comparison Welch update.
A paired comparison tests within-pair differences (setting a unit aside takes its pair with it),
and with Holm's correction a call uses the corrected p of every comparison, so the closed form
gave other fold changes (up to 1.06 log2 on the K. phaffii file) and other calls than the
engine's. The science review (``docs/science-review-2026-10.md``) found it; these tests pin that
every what-if equals :meth:`QpcrSpace.evaluate_arrays` with the change made.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from qpilot.qpcr.contrast import ConclusionRule
from qpilot.qpcr.curves import analyse_study
from qpilot.qpcr.study import StudySettings, build_model
from qpilot.qpcr.trace import _closed_form, build_context
from tests.fixtures.studio.compare_mini import design as mini_design
from tests.fixtures.studio.compare_mini import write_compare_mini


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    root = tmp_path_factory.mktemp("trace-exact")
    return write_compare_mini(root / "compare_mini.rdml"), root / "cache"


def _context(mini, design, rule=None):
    path, cache = mini
    settings = StudySettings.from_design(design)
    if rule is not None:
        settings = dataclasses.replace(settings, rule=rule)
    curves = analyse_study(path, settings.experiment_id, settings.candidates, cache_dir=cache)
    model = build_model(curves, settings)
    return build_context(curves, model)


CASES = [
    pytest.param({"paired": True, "correction": "none"}, id="paired-no-correction"),
    pytest.param({"paired": True, "correction": "holm"}, id="paired-holm"),
    pytest.param({"paired": False, "correction": "holm"}, id="unpaired-holm"),
    pytest.param({"paired": False, "correction": "holm", "pattern": "all_pairs"}, id="all-pairs"),
]


@pytest.mark.parametrize("kw", CASES)
def test_a_unit_set_aside_is_the_spaces_own_evaluation(mini, kw):
    ctx = _context(mini, mini_design(**kw))
    space = ctx.space
    values, refs = space.cell_arrays()
    checked = 0
    for i in np.flatnonzero(ctx.in_hi | ctx.in_lo):
        hi, lo = ctx.in_hi.copy(), ctx.in_lo.copy()
        hi[i] = lo[i] = False
        exact = space.evaluate_arrays(values, refs, hi, lo)
        keep = np.isfinite(ctx.loo_log2fc[i])
        np.testing.assert_allclose(ctx.loo_log2fc[i][keep], exact.log2fc[keep], atol=1e-12)
        assert list(ctx.loo_call[i][keep]) == list(exact.conclusion[keep])
        checked += int(keep.sum())
    assert checked > 0


@pytest.mark.parametrize("kw", CASES)
def test_a_reference_read_as_expected_is_the_spaces_own_evaluation(mini, kw):
    ctx = _context(mini, mini_design(**kw))
    space = ctx.space
    values, refs = space.cell_arrays()
    checked = 0
    for i, r in zip(*np.nonzero(np.isfinite(ctx.s1_expected)), strict=True):
        moved = refs.copy()
        moved[i, r] = ctx.s1_expected[i, r]
        exact = space.evaluate_arrays(values, moved, ctx.in_hi, ctx.in_lo)
        keep = np.isfinite(ctx.shift_log2fc[i, r])
        np.testing.assert_allclose(ctx.shift_log2fc[i, r][keep], exact.log2fc[keep], atol=1e-12)
        assert list(ctx.shift_call[i, r][keep]) == list(exact.conclusion[keep])
        checked += int(keep.sum())
    assert checked > 0


def test_with_holm_a_unit_set_aside_keeps_the_corrected_call(mini):
    """IL6, Drug A against Control, under a rule at p < 0.0045: called "up" (raw p 0.0011,
    Holm-corrected 0.0022). Setting Control_D3 aside gives raw p 0.0026 but corrected 0.0051:
    the engine's call becomes "no call", which the closed form (raw p) missed."""
    rule = ConclusionRule(alpha=0.0045)
    ctx = _context(mini, mini_design(paired=False, correction="holm"), rule)
    space = ctx.space
    j = ctx.items.index("IL6")
    assert ctx.base.conclusion[j] == "up"
    values, refs = space.cell_arrays()
    for i in np.flatnonzero(ctx.in_hi | ctx.in_lo):
        hi, lo = ctx.in_hi.copy(), ctx.in_lo.copy()
        hi[i] = lo[i] = False
        exact = space.evaluate_arrays(values, refs, hi, lo)
        assert ctx.loo_call[i, j] == exact.conclusion[j], space.units[i]
    d3 = list(space.units).index("Control_D3")
    assert ctx.loo_call[d3, j] == "none"


def test_a_study_with_one_comparison_keeps_its_closed_form(mini):
    """Nothing changes for the unpaired designs Trace always handled (and its speed)."""
    ctx = _context(mini, mini_design(paired=False, correction="none"))
    assert _closed_form(ctx.space)
