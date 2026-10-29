"""A gene never detected in one group: "detected only in X", never a fold change made of a cap.

Before, a gene undetermined in every unit of one group was withheld with "fewer than two
biological units with a value", and in any cell of the grid where a cap filled those values in,
the comparison was made of the cap (a fold change of "the lowest value seen" against real
values). Now the withheld reason says which group it was detected in, the facts carry that
group's ΔCq, and no cell of the grid compares a group whose values are all capped: the
robustness grid, the Decision Cards and Trace's what-if all agree.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.study import StudySettings, build_model, study_from_curves
from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign
from tests.engine.test_groups_study import INPUT, SAMPLES, toy_design, toy_wells

NAN = float("nan")


def _absent_in(group: str, target: str = "T1"):
    """Every well of ``target`` in ``group``'s samples undetermined (no Cq, no quantity)."""
    out = {}
    for sample, (_, g) in SAMPLES.items():
        if g == group:
            for rep in range(3):
                out[(sample, target, rep)] = {"n0": NAN, "cq": NAN}
    return out


def test_detected_only_in_one_group_is_withheld_with_its_words_and_dcq():
    curves = toy_wells(overrides=_absent_in("control"))
    settings = StudySettings.from_design(toy_design())
    result, cards, grid = study_from_curves(curves, INPUT, settings)
    assert "T1" not in result.contrasts and "T1" not in set(grid["item"])
    reason = result.facts["f_withheld_t1"].value
    assert reason.startswith("detected only in treated (3 of 3 biological units)")
    assert "not detected in any of the 3 units of control" in reason
    facts = result.facts
    assert facts["f_detected_only_t1"].value == "treated"
    assert (facts["f_n_detected_only_t1"].value, facts["f_n_absent_only_t1"].value) == (3, 3)
    # ΔCq of the treated units: Cq(T1) - Cq(REF) = -(rel) since cq = 40 - log2 value
    expected = -np.mean([3.0, 3.5, 2.5])
    assert facts["f_dcq_only_t1"].value == pytest.approx(expected, abs=1e-6)
    assert facts["f_dcq_sd_only_t1"].value == pytest.approx(0.5, abs=1e-6)
    assert "T2" in result.contrasts  # the other gene is compared as before
    # science review J8: the detection counts' own test, orientation only (3 of 3 vs 0 of 3)
    assert facts["f_fisher_p_only_t1"].value == pytest.approx(0.1, abs=1e-12)
    assert not any(c.kind == "detected_only" for c in cards)


def test_fishers_test_on_the_detection_counts_is_orientation_only():
    """6 of 6 against 0 of 6 is p = 0.002 (Fisher's exact test, two-sided): a presence/absence
    difference is not 'nothing found', and still no fold change or call is made of it."""
    from qpilot.qpcr.space import DetectedOnly
    from qpilot.qpcr.study import detected_only_dcq

    class _Space:
        detected_only = {"G": DetectedOnly("KO", "WT", 6, 6, 6)}
        primary = {"refs": ()}

    class _Model:
        space = _Space()
        settings = StudySettings()
        labels = ("KO", "WT")
        high, rest = frozenset(), frozenset()

        class inputs:  # noqa: N801
            table = pd.DataFrame(
                columns=["run_id", "well", "sample", "sample_type", "target", "cq", "n0"]
            )
            units = None

    out = detected_only_dcq(_Model())  # type: ignore[arg-type]
    assert out["G"]["fisher_p"] == pytest.approx(0.0021645, abs=1e-7)


def test_not_detected_in_either_group():
    overrides = {**_absent_in("control"), **_absent_in("treated")}
    result, _, _ = study_from_curves(
        toy_wells(overrides=overrides), INPUT, StudySettings.from_design(toy_design())
    )
    reason = result.facts["f_withheld_t1"].value
    assert reason.startswith("not detected in any of the 6 biological units of treated or")
    assert result.facts["f_detected_only_t1"].value == "neither group"
    assert "f_dcq_only_t1" not in result.facts


def test_one_unit_short_is_still_the_old_reason():
    # two of three control units undetermined: one detected, so not "detected only"
    overrides = {k: v for k, v in _absent_in("control").items() if k[0] in ("sB1", "sB2")}
    result, _, _ = study_from_curves(
        toy_wells(overrides=overrides), INPUT, StudySettings.from_design(toy_design())
    )
    assert result.facts["f_withheld_t1"].value == (
        "fewer than two biological units with a value in control"
    )
    assert "f_detected_only_t1" not in result.facts


def test_a_capped_only_group_is_never_compared_in_any_cell():
    """A gene compared at the primary cell, but all-undetermined in a group under a Cq rule."""
    # T1 in the control units is late (Cq > 35): the cq_le_35 rule calls every control well
    # undetermined; LinRegPCR's own call (the primary) keeps them.
    late = {}
    for sample, (_, g) in SAMPLES.items():
        if g == "control":
            for rep in range(3):
                late[(sample, "T1", rep)] = {"cq": 36.0 + rep}
    curves = toy_wells(overrides=late)
    design = toy_design(amp_calls=("linregpcr", "cq_le_35"))
    settings = StudySettings.from_design(design)
    model = build_model(curves, settings)
    space = model.space
    assert "T1" in space.items and not space.detected_only
    cell = {**space.primary, "amp_call": "cq_le_35", "undetermined": "cap"}
    capped = space.evaluate(cell)["T1"]
    assert math.isnan(capped.p) and capped.conclusion == "none"
    assert all(math.isnan(v) for v in capped.ci)
    dropped = space.evaluate({**cell, "undetermined": "drop"})["T1"]
    assert math.isnan(dropped.p) and dropped.conclusion == "none"
    # Trace's what-if with no change returns exactly what evaluate returns
    same = space.evaluate_with(cell)["T1"]
    assert math.isnan(same.p) and same.conclusion == capped.conclusion
    # the other genes are still capped and compared in that cell
    assert np.isfinite(space.evaluate(cell)["T2"].p)
    result, _, grid = study_from_curves(curves, INPUT, settings)
    rows = grid[(grid["item"] == "T1") & (grid["undetermined"] == "cap")]
    if "amp_call" in grid.columns:
        rows = rows[rows["amp_call"] == "cq_le_35"]
        assert not rows.empty and rows["p"].isna().all()


def test_several_comparisons_agree():
    samples = {
        **SAMPLES,
        "sC1": ("mC1", "third"),
        "sC2": ("mC2", "third"),
    }
    design = StudyDesign(
        design_id="toy_three",
        mode="groups",
        comparison=Comparison(group_a="treated", group_b="control"),
        samples={
            s: SampleDesign(sample=s, group=g, biological_unit=u) for s, (u, g) in samples.items()
        },  # fmt: skip
        reference_candidates=("REF",),
        headline=("T1", "T2"),
        comparisons={
            "comparisons": [
                {"group_a": "treated", "group_b": "control"},
                {"group_a": "third", "group_b": "control"},
            ],
            "correction": "holm",
        },
    )
    curves = toy_wells(overrides=_absent_in("control"))
    extra = curves[curves["sample"] == "sA1"]
    added = [extra.assign(sample=n, well=extra["well"] + n) for n in ("sC1", "sC2")]
    curves = pd.concat([curves, *added], ignore_index=True)
    model = build_model(curves, StudySettings.from_design(design))
    assert "T1" in model.space.detected_only
    assert model.space.detected_only["T1"].group == "treated"


@pytest.mark.demo_data
def test_constructed_design_from_the_demo_curves(demo_rdml_path):
    """Real curves: NHLH2 is undetermined in 92 tumours; a design puts six of them together."""
    from qpilot.qpcr.curves import analyse_study

    legacy = StudySettings()
    curves = analyse_study(demo_rdml_path, legacy.experiment_id, legacy.candidates, legacy.curves)
    unknown = curves[curves["sample_type"] == "unkn"]
    nhlh2 = unknown[unknown["target"] == "NHLH2"]
    absent = sorted(nhlh2.loc[nhlh2["n0"].isna(), "sample"])[:6]
    present = sorted(nhlh2.loc[nhlh2["n0"].notna(), "sample"])[:6]
    design = StudyDesign(
        design_id="nhlh2_constructed",
        experiment_id=legacy.experiment_id,
        mode="groups",
        comparison=Comparison(group_a="present", group_b="absent"),
        samples={
            **{s: SampleDesign(sample=s, group="absent") for s in absent},
            **{s: SampleDesign(sample=s, group="present") for s in present},
        },
        reference_candidates=("HMBS", "SDHA(1)", "UBC(2)"),
        headline=("NHLH2",),
    )
    settings = StudySettings.from_design(design)
    result, cards, grid = study_from_curves(curves, "ab" * 32, settings)
    assert "NHLH2" not in result.contrasts and "NHLH2" not in set(grid["item"])
    assert result.facts["f_detected_only_nhlh2"].value == "present"
    assert result.facts["f_withheld_nhlh2"].value.startswith(
        "detected only in present (6 of 6 biological units)"
    )
    dcq = result.facts["f_dcq_only_nhlh2"].value
    assert math.isfinite(dcq) and abs(dcq) < 20
    for card in cards:  # no card counts NHLH2 (withheld genes are not items)
        assert "NHLH2" not in str(card.impact)
