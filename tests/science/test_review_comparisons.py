"""Science review J9: Dunnett and Tukey under the "cap" rule, and Welch's ANOVA's words.

A group whose values for a gene are all the cap (none detected) is not tested itself; it must not
lend the pooled variance its ``n - 1`` degrees of freedom with no spread either.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from qpilot.qpcr.contrast import ConclusionRule
from qpilot.qpcr.space import ComparisonSpec, _Family, _Masks

A = [0.1, 0.9, 0.5, 1.3]  # treated 1
B = [-2.0, -2.0, -2.0, -2.0]  # treated 2: every value the cap (none detected)
C = [2.0, 2.8, 2.4, 1.6]  # control


def _family(correction: str):
    units = [f"a{i}" for i in range(4)] + [f"b{i}" for i in range(4)] + [f"c{i}" for i in range(4)]
    group = {u: u[0] for u in units}
    specs = [
        ComparisonSpec("a_c", ("A", "C"), frozenset(u for u in units if u[0] == "a"),
                       frozenset(u for u in units if u[0] == "c")),
        ComparisonSpec("b_c", ("B", "C"), frozenset(u for u in units if u[0] == "b"),
                       frozenset(u for u in units if u[0] == "c")),
    ]  # fmt: skip
    if correction == "tukey":
        specs.append(ComparisonSpec("a_b", ("A", "B"), specs[0].group_a, specs[1].group_a))
    family = _Family.of(specs, correction, "C" if correction == "dunnett" else None)
    names = np.array([group[u] for u in units])
    masks = [_Masks(names == s.labels[0].lower(), names == s.labels[1].lower()) for s in specs]
    values = np.array(A + B + C, dtype=float)[:, None]
    valid = np.ones_like(values, dtype=bool)
    capped = np.zeros_like(values, dtype=bool)
    capped[4:8, 0] = True
    return family, masks, values, valid, capped


@pytest.mark.parametrize("correction", ["dunnett", "tukey"])
def test_a_group_of_capped_values_is_left_out_of_the_pooled_variance(correction):
    family, masks, values, valid, capped = _family(correction)
    rule = ConclusionRule()
    out = family.compare(["G"], values, valid, masks, rule, True, capped=capped)
    a_c, b_c = out[0], out[1]
    assert np.isnan(b_c.p[0]) and b_c.conclusion[0] == "none"  # the capped group: not tested
    # the pooled SD is A's and C's alone: df 6, not 9 (B's identical values add no spread)
    sp2 = (np.var(A, ddof=1) * 3 + np.var(C, ddof=1) * 3) / 6
    se = np.sqrt(sp2 * (1 / 4 + 1 / 4))
    assert a_c.se[0] == pytest.approx(se, rel=1e-12)
    t = (np.mean(A) - np.mean(C)) / se
    assert a_c.t[0] == pytest.approx(t, rel=1e-12)
    assert 2 * stats.t.sf(abs(t), 6) == pytest.approx(2 * stats.t.sf(abs(a_c.t[0]), 6), rel=1e-12)
    # without the cap the same values would have pooled B's zero spread with df 9
    plain = family.compare(["G"], values, valid, masks, rule, True, capped=None)
    assert plain[0].se[0] < a_c.se[0]


def test_welchs_anova_says_when_a_group_was_left_out_for_a_gene():
    """The ANOVA drops a group with fewer than two values for the gene; df1 shows it."""
    from qpilot.qpcr.contrast import welch_anova
    from qpilot.schemas import Omnibus
    from qpilot.web.compare_views import omnibus_coverage

    groups = ["A", "B", "C", "D"]
    stats_ = [
        (np.array([3.0]), np.array([0.5]), np.array([0.2])),
        (np.array([3.0]), np.array([1.5]), np.array([0.3])),
        (np.array([1.0]), np.array([2.0]), np.array([np.nan])),  # one value: left out
        (np.array([4.0]), np.array([0.1]), np.array([0.25])),
    ]
    f, df1, df2, p = welch_anova(stats_)
    assert df1[0] == 2.0  # three groups used
    found = omnibus_coverage(Omnibus(f=f[0], df1=df1[0], df2=df2[0], p=p[0]), groups)
    assert found == {
        "n_groups_used": 3,
        "groups_words": "across 3 of the 4 groups: 1 group with fewer than two values for this "
        "gene left out",
    }
    every = omnibus_coverage(Omnibus(f=1.0, df1=3.0, df2=8.0, p=0.4), groups)
    assert every == {"n_groups_used": 4, "groups_words": ""}
