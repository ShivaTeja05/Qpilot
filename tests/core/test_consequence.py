"""The consequence classes: changes the call > beyond the CI > changes nothing."""

import math

import pytest

from qpilot.core.consequence import (
    CLASSES,
    NOTHING,
    Baseline,
    Consequence,
    best,
    classify,
    classify_roots,
    sort_key,
)

BASE = {
    "A": Baseline(log2fc=-0.98, call="none", half_ci=0.40),
    "B": Baseline(log2fc=1.50, call="up", half_ci=0.30),
    "C": Baseline(log2fc=0.10, call="none", half_ci=0.20),
}


def _option(**changes):
    out = {k: (v.log2fc, v.call) for k, v in BASE.items()}
    out.update(changes)
    return out


def test_classes_are_ranked_best_first():
    assert CLASSES == ("changes_call", "beyond_ci", "changes_nothing")


def test_nothing_changes():
    cons = classify(BASE, _option())
    assert cons == Consequence("changes_nothing", (), 0, None, 0.0)
    assert NOTHING.cls == "changes_nothing"


def test_a_changed_call_for_the_root_and_elsewhere():
    option = _option(A=(-1.03, "down"), C=(0.15, "none"))
    cons = classify(BASE, option, root="A")
    assert cons.cls == "changes_call"
    assert cons.changed_calls == ("A",)
    assert cons.root == "A"
    assert math.isclose(cons.root_delta, -0.05)
    assert math.isclose(cons.max_abs_delta, 0.05)
    # the root's own class: C moved but did not change its call
    assert classify(BASE, option, root="C").cls == "changes_nothing"
    assert classify(BASE, option, root="C").changed_calls == ("A",)


def test_beyond_the_ci_without_a_changed_call():
    option = _option(B=(1.95, "up"))
    assert classify(BASE, option, root="B").cls == "beyond_ci"
    assert classify(BASE, option).cls == "beyond_ci"
    assert classify(BASE, option, root="A").cls == "changes_nothing"


def test_a_missing_item_can_no_longer_be_concluded():
    option = _option()
    del option["C"]
    cons = classify(BASE, option)
    assert cons.changed_calls == ("C",)
    assert cons.cls == "changes_call"
    assert classify(BASE, option, root="C").root_delta is None


def test_non_finite_deltas_are_ignored_for_size():
    option = _option(C=(float("nan"), "none"))
    cons = classify(BASE, option)
    assert cons.cls == "changes_nothing"
    assert cons.max_abs_delta == 0.0
    base = {**BASE, "D": Baseline(0.0, "none", float("nan"))}
    assert classify(base, {**_option(), "D": (5.0, "none")}, root="D").cls == "changes_nothing"


def test_unknown_root():
    with pytest.raises(KeyError):
        classify(BASE, _option(), root="Z")


def test_changed_calls_are_sorted():
    option = _option(C=(1.2, "up"), A=(-1.2, "down"))
    assert classify(BASE, option).changed_calls == ("A", "C")


def test_classify_roots_equals_classify_for_every_root():
    option = _option(A=(-1.03, "down"), B=(1.95, "up"), C=(float("nan"), "none"))
    every = classify_roots(BASE, option)
    assert every[None] == classify(BASE, option)
    for item in BASE:
        assert every[item] == classify(BASE, option, root=item)


def test_best_and_sort_key():
    call = classify(BASE, _option(A=(-1.03, "down")), root="A")
    big = classify(BASE, _option(A=(-0.40, "none")), root="A")
    small = classify(BASE, _option(A=(-0.97, "none")), root="A")
    assert best([small, big, call]) is call
    assert best([small, big]) is big
    assert sort_key(call) < sort_key(big) < sort_key(small)
    with pytest.raises(ValueError):
        best([])


def test_any_item_ranking_prefers_more_changed_calls():
    two = classify(BASE, _option(A=(-1.03, "down"), C=(1.1, "up")))
    one_bigger = classify(BASE, _option(A=(-1.6, "down")))
    assert best([one_bigger, two]) is two


def test_as_dict_is_plain_data():
    data = classify(BASE, _option(A=(-1.03, "down")), root="A").as_dict()
    assert data["changed_calls"] == ["A"]
    assert set(data) == {"cls", "changed_calls", "n_changed", "root_delta", "max_abs_delta", "root"}
