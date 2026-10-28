"""Correction between plates: inter-run calibration and factor correction (Ruijter et al. 2015)."""

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr import interrun as irc
from qpilot.qpcr.quant import log2_matrix


def _wells(rows) -> pd.DataFrame:
    """A per-well table from (run, sample, type, target, log2 n0) rows."""
    frame = pd.DataFrame(rows, columns=["run_id", "sample", "sample_type", "target", "log2"])
    frame["well"] = [f"W{i}" for i in range(len(frame))]
    frame["n0"] = np.exp2(frame.pop("log2"))
    frame["cq"] = 20.0
    return frame


OFFSET = {"P1": 0.0, "P2": 1.0, "P3": -0.5}  # each plate's own offset (log2)


def _split_gene(calibrator: bool = True) -> tuple[pd.DataFrame, dict[str, float]]:
    """Gene T's six samples split over three plates, with an IRC on every plate."""
    rng = np.random.default_rng(1)
    truth = {f"s{i}": float(rng.normal(10, 1)) for i in range(6)}
    rows = []
    for i, (sample, value) in enumerate(truth.items()):
        run = ("P1", "P2", "P3")[i % 3]
        rows.append((run, sample, "unkn", "T", value + OFFSET[run]))
        rows.append((run, sample, "unkn", "R", 12.0 + OFFSET[run]))
    for run in OFFSET:
        if calibrator:
            for _ in range(2):  # two replicate wells of the calibrator
                rows.append((run, "IRC", "pos", "T", 9.0 + OFFSET[run]))
                rows.append((run, "IRC", "pos", "R", 11.0 + OFFSET[run]))
        rows.append((run, "water", "ntc", "T", 30.0))  # a negative control is never used
    return _wells(rows), truth


def test_calibrator_removes_a_known_plate_offset():
    table, truth = _split_gene()
    assert irc.split_targets(table) == {"R": ("P1", "P2", "P3"), "T": ("P1", "P2", "P3")}
    assert irc.calibrators(table) == {"R": ("IRC",), "T": ("IRC",)}
    done = irc.calibrate(table)
    mean = np.mean(list(OFFSET.values()))
    assert done.factors[("P2", "T")] == pytest.approx(OFFSET["P2"] - mean)
    assert done.uncorrected == ()
    study = done.table[done.table["sample_type"] == "unkn"]
    got = np.log2(study[study["target"] == "T"].set_index("sample")["n0"])
    diff = got - pd.Series(truth)
    assert diff.max() - diff.min() == pytest.approx(0.0, abs=1e-12)  # one common constant
    # the relative quantity T / R is now the truth up to that constant
    matrix = log2_matrix(done.table)
    relative = matrix["T"] - matrix["R"]
    assert (relative - pd.Series(truth)).std() == pytest.approx(0.0, abs=1e-12)


def test_calibrator_needs_the_same_sample_on_every_plate():
    table, _ = _split_gene()
    table = table[~((table["sample"] == "IRC") & (table["run_id"] == "P3"))]
    assert irc.calibrators(table) == {"R": (), "T": ()}
    done = irc.calibrate(table)
    assert done.uncorrected == ("R", "T") and done.factors == {}
    assert np.allclose(done.table["n0"], table["n0"])
    assert "no gene split over plates" in irc.unavailable(table)["calibrator"]


def _shared_plates(link_1_3: bool = True) -> pd.DataFrame:
    """Two genes on three plates; the same samples on several plates (Ruijter's overlap)."""
    rng = np.random.default_rng(4)
    truth = {(t, f"s{i}"): float(rng.normal(10, 1)) for t in ("A", "B") for i in range(8)}
    layout = {
        "P1": ["s0", "s1", "s2", "s3", "s4"],
        "P2": ["s2", "s3", "s4", "s5", "s6"],
        "P3": ["s5", "s6", "s7"] + (["s0"] if link_1_3 else []),
    }
    rows = []
    for run, samples in layout.items():
        for sample in samples:
            for target in ("A", "B"):
                value = truth[(target, sample)] + OFFSET[run] + float(rng.normal(0, 0.01))
                rows.append((run, sample, "unkn", target, value))
    return _wells(rows)


def test_factor_recovers_known_plate_factors():
    table = _shared_plates()
    factors, unlinked = irc.plate_factors(table)
    assert unlinked == ()
    mean = np.mean(list(OFFSET.values()))
    for run, offset in OFFSET.items():
        assert factors[run] == pytest.approx(offset - mean, abs=0.02)
    done = irc.factor_correct(table)
    runs, after = irc.ratio_matrix(done.table)
    off = ~np.eye(len(runs), dtype=bool)
    assert np.nanmax(np.abs(after[off])) < 0.02  # no plate differs from another any more


def test_factor_fills_a_gap_through_a_third_plate():
    table = _shared_plates(link_1_3=False)
    runs, matrix = irc.ratio_matrix(table)
    assert runs == ["P1", "P2", "P3"] and np.isnan(matrix[0, 2]) and np.isnan(matrix[2, 0])
    factors, unlinked = irc.plate_factors(table)  # P1-P3 estimated through P2 (Eq. 3)
    assert unlinked == ()
    mean = np.mean(list(OFFSET.values()))
    assert factors["P3"] == pytest.approx(OFFSET["P3"] - mean, abs=0.02)


def test_a_plate_sharing_nothing_is_left_as_it_is():
    table = _shared_plates()
    lone = _wells([("P4", "x", "unkn", "A", 5.0), ("P4", "y", "unkn", "A", 6.0)])
    both = pd.concat([table, lone], ignore_index=True)
    factors, unlinked = irc.plate_factors(both)
    assert unlinked == ("P4",) and "P4" not in factors
    done = irc.factor_correct(both)
    kept = done.table[done.table["run_id"] == "P4"]["n0"].to_numpy()
    assert np.allclose(kept, lone["n0"].to_numpy())


def test_one_plate_per_gene_cannot_change_a_fold_change():
    rows = [("P1", f"s{i}", "unkn", "T", 10.0 + i) for i in range(4)]
    rows += [("P2", f"s{i}", "unkn", "R", 12.0) for i in range(4)]
    table = _wells(rows)
    assert irc.split_targets(table) == {}
    why = irc.unavailable(table)
    assert set(why) == {"calibrator", "factor"} and "cancels in every fold change" in why["factor"]


def test_no_shared_measurement_means_no_factor():
    table, _ = _split_gene(calibrator=False)
    assert "no two plates share a measurement" in irc.unavailable(table)["factor"]


def test_none_returns_the_table_itself_and_unknown_option_is_refused():
    table, _ = _split_gene()
    assert irc.correct(table, "none").table is table
    with pytest.raises(ValueError, match="unknown inter-run option"):
        irc.correct(table, "guess")
