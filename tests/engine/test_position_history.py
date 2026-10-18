"""Position history: follows the instrument, moves with the samples, or not enough runs yet.

All synthetic (the plan's six-run Zenodo series is not on disk): a planted offset that stays at
two positions while samples, layouts and people change; an offset that moves at random; and a
six-run series built to the plan's measured numbers (294 residuals, 28.9 % off, 66 positions).
"""

import json
from collections import Counter

import numpy as np
import pandas as pd
import pytest

from qpilot.explain.lookback_text import position_text, position_tokens
from qpilot.qpcr.position_history import (
    RunWells,
    WellReading,
    adjusted_p,
    position_history,
    residuals,
    runs_from_curves,
    runs_needed,
)

BANNED = (
    "diagnosis",
    "diagnose",
    "root cause",
    "invalid run",
    "valid run",
    "faulty instrument",
    "error found",
)
PLATE96 = [f"{r}{c}" for r in "ABCDEFGH" for c in range(1, 13)]


def plate_runs(
    n_runs=8,
    *,
    planted=("B3", "B4"),
    moving=False,
    offset=-1.5,
    seed=7,
    operators=("Ana", "Ben"),
    shuffle=True,
    instrument="qs5-room-2110",
):
    """Triplicates on a 96-well plate; an offset at fixed (or, if moving, random) positions."""
    rng = np.random.default_rng(seed)
    runs = []
    for i in range(n_runs):
        order = rng.permutation(len(PLATE96)) if shuffle else np.arange(len(PLATE96))
        bad = set(rng.choice(PLATE96, size=2, replace=False)) if moving else set(planted)
        wells = []
        for g in range(32):
            sample = f"S{i}_{g}" if shuffle else f"S{g}"
            base = 24 + rng.normal(0, 2)
            for k in range(3):
                position = PLATE96[order[3 * g + k]]
                cq = base + rng.normal(0, 0.15) + (offset if position in bad else 0)
                wells.append(WellReading(well=position, sample=sample, target="GAPDH", cq=cq))
        runs.append(
            RunWells(
                run_id=f"run{i}",
                instrument_id=instrument,
                operator=operators[i % len(operators)],
                wells=wells,
            )
        )
    return runs


def six_run_series():
    """Six runs, 66 positions, 98 triplicates (294 residuals), 85 off: 28.9 %.

    Each triplicate is (median - a, median, median + b) with a, b of 0.8 (off) or 0.2, so the
    off count is exact; each run uses a rotating window of positions, so a position is measured
    in four or five runs (as in a lab whose layouts change), never in all six.
    """
    positions = [f"{r}{c}" for r in "ABCDEF" for c in range(1, 12)]
    runs, outer = [], 0
    for i, n_groups in enumerate((16, 16, 16, 16, 17, 17)):
        start = (i * 11) % 66
        window = [positions[(start + j) % 66] for j in range(3 * n_groups)]
        wells = []
        for g in range(n_groups):
            spreads = []
            for _ in range(2):
                spreads.append(0.8 if (outer * 37) % 196 < 85 else 0.2)
                outer += 1
            median = 25.0 + g * 0.1
            cqs = (median - spreads[0], median, median + spreads[1])
            for position, cq in zip(window[3 * g : 3 * g + 3], cqs, strict=True):
                wells.append(WellReading(well=position, sample=f"s{i}_{g}", target="t", cq=cq))
        runs.append(
            RunWells(run_id=f"r{i}", instrument_id="stepone", operator=f"p{i % 2}", wells=wells)
        )
    return runs


def test_a_planted_offset_at_two_positions_follows_the_instrument():
    """3b.4: -1.5 cycles at B3 and B4 across 8 runs, two people, a new layout every run."""
    report = position_history(plate_runs())
    inst = report.instruments[0]
    assert inst.answer == "follows_instrument" and inst.words == "follows the instrument"
    assert inst.flagged == ["B3", "B4"]
    assert inst.n_runs == 8 and inst.n_people == 2 and inst.n_layouts == 8
    stats = {s.position: s for s in inst.positions}
    for position in ("B3", "B4"):
        assert stats[position].n_off >= 6 and stats[position].p_adjusted < 0.05
        assert stats[position].side == "below" and stats[position].median_residual < -1
    assert sum(s.flagged for s in inst.positions) == 2
    text = position_text(report)
    assert "positions B3, B4 follow the instrument" in text


def test_a_randomly_moving_offset_is_not_flagged():
    report = position_history(plate_runs(moving=True))
    inst = report.instruments[0]
    assert inst.flagged == [] and inst.beats_chance == []
    assert inst.answer == "moves_with_samples" and inst.reason == "none_beats_chance"
    assert inst.n_positions_testable == inst.n_positions_tested == 96
    assert "nothing follows the instrument" in position_text(report)


def test_one_person_one_layout_cannot_tell_the_instrument_from_the_samples():
    """Same samples in the same wells every run, one person: beats chance, but not flagged."""
    report = position_history(plate_runs(shuffle=False, operators=("Ana",)))
    inst = report.instruments[0]
    assert inst.beats_chance == ["B3", "B4"] and inst.flagged == []
    assert inst.answer == "not_enough_runs" and inst.reason == "one_person_one_layout"
    assert inst.n_people == 1 and inst.n_layouts == 1
    # A second person on the same layout is enough: "two people or two plate layouts".
    two = position_history(plate_runs(shuffle=False, operators=("Ana", "Ben")))
    assert two.instruments[0].flagged == ["B3", "B4"]
    strict = position_history(plate_runs(), min_people_or_layouts=9)
    assert strict.instruments[0].flagged == []


def test_the_six_run_series_reports_not_enough_runs_need_six():
    """3b.4 on the plan's numbers: 28.9 % base rate, 66 positions, nothing flagged, need 6."""
    runs = six_run_series()
    coverage = Counter(w.well for r in runs for w in r.wells)
    assert len(coverage) == 66 and max(coverage.values()) == 5
    report = position_history(runs)
    assert (report.n_residuals, report.n_off) == (294, 85)
    assert report.base_rate == pytest.approx(0.289, abs=5e-4)
    inst = report.instruments[0]
    assert inst.n_positions_tested == 66 and inst.runs_needed == 6
    assert inst.flagged == [] and inst.beats_chance == []
    assert inst.answer == "not_enough_runs" and inst.reason == "too_few_runs"
    assert inst.n_positions_testable == 0
    assert all(s.p_adjusted == 1.0 for s in inst.positions)
    text = position_text(report)
    assert "Base rate: 28.9% of wells" in text
    assert "not enough runs yet (need ≈ 6 runs at this lab's noise; it has 6)" in text


def test_the_runs_needed_arithmetic():
    """The plan: at 28.9 % over 66 positions, 6 of 6 beats 5 % family-wise and 5 of 5 does not."""
    assert runs_needed(0.289, 66) == 6
    assert 66 * 0.289**6 == pytest.approx(0.0385, abs=1e-4)
    assert adjusted_p(6, 6, 0.289, 66) == pytest.approx(66 * 0.289**6)
    assert adjusted_p(6, 6, 0.289, 66) < 0.05 < adjusted_p(5, 5, 0.289, 66)
    assert adjusted_p(5, 5, 0.289, 66) == pytest.approx(66 * 0.289**5)
    assert adjusted_p(3, 3, 0.289, 66) == 1.0  # the plan's most extreme position: chance
    assert adjusted_p(0, 6, 0.289, 66) == 1.0
    assert runs_needed(0.0, 66) == 1 and runs_needed(1.0, 66) is None
    assert runs_needed(0.289, 0) is None


def test_residuals_use_the_replicate_median_and_skip_singletons():
    run = RunWells(
        run_id="r",
        instrument_id="x",
        wells=[
            WellReading(well="A1", sample="s", target="t", cq=20.0),
            WellReading(well="A2", sample="s", target="t", cq=21.0),
            WellReading(well="A3", sample="s", target="t", cq=23.0),
            WellReading(well="B1", sample="alone", target="t", cq=30.0),
            WellReading(well="B2", sample="s", target="u", cq=None),
            WellReading(well="B3", sample="s", target="u", cq=25.0),
        ],
    )
    table = residuals([run])
    assert table["position"].tolist() == ["A1", "A2", "A3"]
    assert table["residual"].tolist() == [-1.0, 0.0, 2.0]
    with pytest.raises(ValueError):
        position_history([run], min_replicates=1)


def test_operators_are_counted_never_reported():
    report = position_history(plate_runs(operators=("Ana Example", "Ben Example")))
    dumped = json.dumps(report.model_dump(mode="json")) + position_text(report)
    assert "Example" not in dumped
    assert report.instruments[0].n_people == 2


def test_instruments_are_answered_separately_on_a_pooled_base_rate():
    runs = plate_runs() + plate_runs(moving=True, seed=9, instrument="qs7")
    report = position_history(runs)
    answers = {i.instrument_id: i.answer for i in report.instruments}
    assert answers == {"qs5-room-2110": "follows_instrument", "qs7": "moves_with_samples"}
    assert report.n_residuals == 16 * 96


def test_deterministic_json_and_text():
    a = position_history(plate_runs())
    b = position_history(plate_runs())
    assert json.dumps(a.model_dump(mode="json"), sort_keys=True) == json.dumps(
        b.model_dump(mode="json"), sort_keys=True
    )
    assert position_tokens(a) == position_tokens(b)


def test_text_validates_and_keeps_to_the_words():
    for runs in (plate_runs(), plate_runs(moving=True), six_run_series()):
        report = position_history(runs)
        tokens = position_tokens(report)  # validates, or raises
        assert "{{" in tokens
        text = position_text(report).lower()
        assert not [w for w in BANNED if w in text]
    assert position_tokens(None) == "Position history has not been checked for this instrument."
    empty = position_history([RunWells(run_id="r", instrument_id="x", wells=[])])
    assert empty.instruments[0].answer == "not_enough_runs"
    assert position_tokens(empty) == position_tokens(None)


def test_runs_from_curves_keeps_study_wells_of_mapped_runs():
    curves = pd.DataFrame(
        {
            "run_id": ["p1", "p1", "p1", "p2"],
            "well": ["A1", "A2", "P24", "A1"],
            "sample": ["STD_15", "STD_15", "water", "s1"],
            "sample_type": ["std", "std", "ntc", "unkn"],
            "target": ["HMBS", "HMBS", "HMBS", "UBC"],
            "cq": [34.1, float("nan"), 38.0, 25.0],
        }
    )
    runs = runs_from_curves(curves, {"p1": "qs"}, operators={"p1": "Ana"})
    assert [r.run_id for r in runs] == ["p1"]
    assert [(w.well, w.cq) for w in runs[0].wells] == [("A1", 34.1), ("A2", None)]
    assert runs[0].operator == "Ana" and runs[0].instrument_id == "qs"


@pytest.mark.demo_data
def test_demo_standards_are_not_taken_for_the_instrument(demo_curves):
    """The demo's only replicates are its standards (5 levels x 3 wells, same wells, 64 plates).

    The 15-copy standard's wells (P14, P16, P18) are off their replicates far more often than
    the base rate, but the same standard sits there on every plate and no operator is on
    record, so the answer is "not enough runs yet", never "follows the instrument".
    """
    instruments = {run: "qs-demo" for run in set(demo_curves["run_id"])}
    report = position_history(runs_from_curves(demo_curves, instruments))
    inst = report.instruments[0]
    assert report.n_residuals == 960 and report.base_rate == pytest.approx(0.0479, abs=1e-4)
    assert inst.n_runs == 64 and inst.n_positions_tested == 15
    assert inst.n_layouts == 1 and inst.n_people == 0
    assert inst.beats_chance == ["P14", "P16", "P18"] and inst.flagged == []
    assert inst.answer == "not_enough_runs" and inst.reason == "one_person_one_layout"
    standard = demo_curves[demo_curves["well"].isin(inst.beats_chance)]
    assert set(standard["sample"]) == {"STD_15"}
    assert "cannot yet tell the instrument from the samples" in position_text(report)


@pytest.mark.demo_data
def test_demo_store_level_entry_pools_each_input_once(tmp_path, demo_rdml_path, demo_curves):
    from qpilot.core.store import StudyStore
    from qpilot.qpcr.position_history import position_history_store

    store = StudyStore(tmp_path / "studies")
    store.ensure_study(demo_rdml_path)
    instruments = {run: "qs-demo" for run in set(demo_curves["run_id"])}
    stored = position_history_store(store, instruments)
    direct = position_history(runs_from_curves(demo_curves, instruments))
    assert stored.model_dump(mode="json") == direct.model_dump(mode="json")
    assert position_history_store(store, {}).instruments == []
