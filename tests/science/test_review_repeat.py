"""Science review J3: "no amplification where one was expected" counts within the sample's group.

A gene that is truly off in a small group (two knock-outs among twenty samples, a sex-specific
gene) passed the old rule (18 of 19 other samples amplified it) and put every sample of that
group on the repeat plate as a technical failure. Now the share is counted within the sample's
own group, with at least three other samples there, and the reason names the group.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr import repeat


def _ctx(groups: dict[str, list[str]], silent: set[tuple[str, str]]):
    """A stand-in for Trace's context: one well of gene G per unit; ``silent`` did not amplify."""
    labels = tuple(groups)
    units = tuple(u for g in labels for u in groups[g])
    rows = []
    for unit in units:
        for target in ("G", "H"):
            n0 = np.nan if (unit, target) in silent else 1.0
            rows.append(
                {"key": f"p1/{unit}_{target}", "run_id": "p1", "well": f"{unit}_{target}",
                 "sample": unit, "unit": unit, "sample_type": "unkn", "target": target,
                 "n0": n0, "person_excluded": False}
            )  # fmt: skip
    wells = pd.DataFrame(rows).set_index("key")
    return SimpleNamespace(
        wells=wells,
        units=units,
        used=np.ones(len(units), dtype=bool),
        items=("G", "H"),
        cell={},
        unit_row={u: i for i, u in enumerate(units)},
        in_hi=np.array([u in groups[labels[0]] for u in units]),
        in_lo=np.array([u in groups[labels[1]] for u in units]),
        labels=labels,
    )


def _flagged(ctx, share=repeat.EXPECTED_SHARE):
    plan = repeat._Plan(ctx)
    repeat._no_amplification(plan, share)
    return {key: item.reasons[0].words for key, item in plan.items.items()}


def test_a_gene_off_in_a_small_group_is_not_a_technical_failure():
    wt = [f"WT_{i}" for i in range(18)]
    ko = ["KO_1", "KO_2"]
    ctx = _ctx({"WT": wt, "KO": ko}, {("KO_1", "G"), ("KO_2", "G")})
    assert _flagged(ctx) == {}  # was: both knock-outs flagged (18 of 19 others amplified G)


def test_a_dropout_inside_its_group_is_flagged_and_the_reason_names_the_group():
    wt = [f"WT_{i}" for i in range(10)]
    ko = [f"KO_{i}" for i in range(5)]
    ctx = _ctx({"WT": wt, "KO": ko}, {("WT_3", "H")} | {(k, "G") for k in ko})
    found = _flagged(ctx)
    assert set(found) == {("WT_3", "H")}  # the knock-outs' silent G is their group's biology
    words = found[("WT_3", "H")]
    assert "amplified in 9 of the 9 other compared samples of its group (WT)" in words


def test_too_few_samples_in_the_group_flag_nothing_and_the_share_is_lab_editable():
    ctx = _ctx({"A": ["a1", "a2", "a3"], "B": [f"b{i}" for i in range(6)]}, {("a1", "G")})
    assert _flagged(ctx) == {}  # two other samples in A: too few to expect a value
    ctx = _ctx({"A": [f"a{i}" for i in range(6)], "B": [f"b{i}" for i in range(6)]},
               {("a0", "G"), ("a1", "G")})  # fmt: skip
    assert _flagged(ctx) == {}  # 4 of 5 others (80 %) is below the 90 % default
    assert set(_flagged(ctx, share=0.8)) == {("a0", "G"), ("a1", "G")}  # a lab's own line


def test_the_share_is_checked():
    for bad in (0, 1.5, -0.1, True):
        with pytest.raises(repeat.RepeatError, match="expected share"):
            repeat.build_plan("s", SimpleNamespace(), expected_share=bad)
    assert repeat.EXPECTED_SHARE == 0.9 and repeat.MIN_GROUP_OTHERS == 3
