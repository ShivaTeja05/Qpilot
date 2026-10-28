"""Melt-curve analysis (qpilot.qpcr.melt): −dF/dT, peaks and Tm, the assay's product, the calls.

Synthetic curves have products at known temperatures (``tests/qpcr/melt_curves.py``); real files
are the corpus's: CFX Manager's own Tm for 96 wells of a SYBR plate (``Melt Curve Peak
Results``, the vendor's peak list), rdmlpython's melt test file (a declared product Tm), a CFX
RDML with ten assays on one plate and a LightCycler 96 experiment file. Numbers measured on the
real files are written in the tests with what they were measured from.
"""

from __future__ import annotations

import csv
import math
import random
from collections import Counter

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr import melt as M
from qpilot.qpcr.melt import (
    MeltCurve,
    MeltParams,
    MeltSettings,
    analyse_curve,
    judge,
    judge_assay,
    read_melt,
    target_summaries,
)
from tests.gate.wells import table, well
from tests.qpcr.melt_curves import (
    GAPDH,
    HSIEH,
    INHIBITION,
    LC96P,
    MCA,
    RPA,
    curve,
    hsieh_rdml,
    melt_data,
    readings,
)


@pytest.fixture(autouse=True)
def fresh():
    M.clear()
    yield
    M.clear()


@pytest.fixture(scope="module")
def hsieh(tmp_path_factory):
    return hsieh_rdml(str(tmp_path_factory.mktemp("hsieh")))


# ---------- one curve ----------


@pytest.mark.parametrize("step", [0.1, 0.2, 0.3, 0.5, 1.0])
def test_one_product_peaks_at_its_melting_temperature(step):
    w = analyse_curve(curve("A1", ((84.0, 1.0),), step=step))
    assert w.problem == ""
    assert len(w.peaks) == 1
    assert w.peaks[0].tm == pytest.approx(84.0, abs=0.05)
    assert w.step_c == pytest.approx(step)
    # the grid is even and the derivative is on it
    assert len(w.temperature) == len(w.derivative)
    assert np.allclose(np.diff(w.temperature), step)


def test_the_tm_lies_between_readings_and_off_the_grid():
    w = analyse_curve(curve("A1", ((83.3, 1.0),), step=0.5))
    assert w.peaks[0].tm == pytest.approx(83.3, abs=0.05)


def test_noise_moves_the_tm_little_and_the_answer_is_the_same_every_time():
    c = curve("A1", ((84.0, 1.0),), noise=0.002, seed=7)
    first, again = analyse_curve(c), analyse_curve(c)
    assert first == again
    assert first.peaks[0].tm == pytest.approx(84.0, abs=0.2)


def test_a_primer_dimer_is_a_second_lower_peak():
    w = analyse_curve(curve("A1", ((76.0, 0.15), (84.0, 1.0))))
    tms = [p.tm for p in w.peaks]
    assert tms[:2] == [pytest.approx(84.0, abs=0.05), pytest.approx(76.0, abs=0.05)]
    # equal widths: the heights are in proportion to the amounts
    assert w.peaks[1].prominence / w.peaks[0].prominence == pytest.approx(0.15, rel=0.05)


def test_the_width_is_the_peaks_full_width_at_half_height():
    sigma = 0.8
    w = analyse_curve(curve("A1", ((84.0, 1.0),), sigma=sigma, step=0.2))
    fwhm = 2 * math.sqrt(2 * math.log(2)) * sigma
    assert w.peaks[0].width_c == pytest.approx(fwhm, rel=0.1)


def test_the_height_is_minus_df_dt_at_the_peak():
    base, amount, sigma = 10_000.0, 1.0, 0.8
    w = analyse_curve(curve("A1", ((84.0, amount),), sigma=sigma, step=0.1, slope=0.0))
    exact = amount * base / (sigma * math.sqrt(2 * math.pi))
    assert w.peaks[0].height == pytest.approx(exact, rel=0.03)


def test_unsorted_repeated_and_missing_readings_give_the_same_peaks():
    t, f = readings(((84.0, 1.0),))
    clean = analyse_curve(MeltCurve("P", "A1", "T", "S", tuple(t), tuple(f)))
    pairs = list(zip(t, f, strict=True)) + [(t[10], f[10]), (float("nan"), 5.0), (70.0, None)]
    random.Random(3).shuffle(pairs)
    messy = analyse_curve(
        MeltCurve("P", "A1", "T", "S", tuple(p[0] for p in pairs), tuple(p[1] for p in pairs))
    )
    assert [p.tm for p in messy.peaks] == [p.tm for p in clean.peaks]


def test_a_flat_curve_and_a_falling_start_have_no_peak():
    flat = analyse_curve(curve("A1", ()))
    assert flat.problem == "" and flat.peaks == ()
    t = [65 + 0.5 * i for i in range(61)]
    falling = [10_000 * math.exp(-(x - 65) / 3) + 2_000 for x in t]  # steepest at the start
    w = analyse_curve(MeltCurve("P", "A1", "T", "S", tuple(t), tuple(falling)))
    assert w.peaks == ()


def test_too_few_or_too_far_apart_readings_are_said_not_guessed():
    short = analyse_curve(curve("A1", lo=80.0, hi=84.0, step=0.5))
    assert short.problem == "too_few_points" and short.peaks == ()
    coarse = analyse_curve(curve("A1", lo=60.0, hi=95.0, step=2.5))
    assert coarse.problem == "coarse" and coarse.step_c == pytest.approx(2.5)
    empty = analyse_curve(MeltCurve("P", "A1", "T", "S", (), ()))
    assert empty.problem == "too_few_points"
    lenient = analyse_curve(curve("A1", step=2.5, lo=60.0), MeltSettings(max_step_c=3.0))
    assert lenient.problem == ""


# ---------- the calls of one assay ----------


def _assay(rows, curves, declared=None, params=None):
    data = melt_data(curves, declared_tm=declared)
    return judge_assay("P", "T", table(rows), data, params)


def _plate():
    """Six study wells (one off, one with a primer-dimer, one flat), a quiet one, four controls."""
    rows = [
        well("P", "A1", "T", "S1", cq=20.0),
        well("P", "A2", "T", "S1", cq=20.1),
        well("P", "A3", "T", "S2", cq=22.0),
        well("P", "A4", "T", "S2", cq=22.2),
        well("P", "A5", "T", "S3", cq=24.0),
        well("P", "A6", "T", "S3", cq=31.0),
        well("P", "A7", "T", "S4", cq=33.0),
        well("P", "A8", "T", "S5", cq=None),
        well("P", "H1", "T", "NTC", "ntc", cq=None),
        well("P", "H2", "T", "NTC", "ntc", cq=36.0),
        well("P", "H3", "T", "NTC", "ntc", cq=34.0),
        well("P", "H4", "T", "NTC", "ntc", cq=35.0),
    ]
    curves = [
        curve("A1", ((84.0, 1.0),)),
        curve("A2", ((84.2, 1.0),)),
        curve("A3", ((83.9, 1.0),)),
        curve("A4", ((84.1, 1.0),)),
        curve("A5", ((85.6, 1.0),)),  # 1.55 °C above the median: another product
        curve("A6", ((76.0, 0.2), (84.0, 1.0))),  # a primer-dimer beside the product
        curve("A7", ()),  # amplified, nothing melted
        curve("A8", ()),  # did not amplify
        curve("H1", ()),  # clean
        curve("H2", ((76.0, 0.3),)),  # a primer-dimer
        curve("H3", ((84.0, 0.2),)),  # the product: a contamination candidate
        curve("H4", ((90.0, 0.2),)),  # another product
    ]
    return rows, curves


def test_each_wells_call_on_a_plate_of_one_assay():
    a = _assay(*_plate())
    calls = {w.well: w.status for w in a.wells}
    assert calls == {
        "A1": "one_product",
        "A2": "one_product",
        "A3": "one_product",
        "A4": "one_product",
        "A5": "tm_off",
        "A6": "extra_peak",
        "A7": "no_peak",
        "A8": "not_amplified",
        "H1": "no_product",
        "H2": "dimer",
        "H3": "product",
        "H4": "other_product",
    }
    # the median of the six amplified unknowns with a peak (A7 has none)
    assert a.expected_source == "median"
    assert a.expected_tm == pytest.approx(np.median([84.0, 84.2, 83.9, 84.1, 85.6, 84.0]), abs=0.05)
    assert a.reference == ("P/A1", "P/A2", "P/A3", "P/A4", "P/A5", "P/A6")
    assert a.spread_c == pytest.approx(1.7, abs=0.05)
    (a6,) = (w for w in a.wells if w.well == "A6")
    assert [p.tm for p in a6.extra] == [pytest.approx(76.0, abs=0.05)]
    assert a6.shares[1] == pytest.approx(0.2 / 1.2, rel=0.05)
    (a5,) = (w for w in a.wells if w.well == "A5")
    assert a5.offset == pytest.approx(85.6 - a.expected_tm, abs=0.05) and a5.flagged
    assert {w.well for w in a.wells if w.flagged} == {"A5", "A6", "A7", "H3", "H4"}


def test_a_declared_melting_temperature_comes_before_the_median():
    rows, curves = _plate()
    a = _assay(rows, curves, declared={"T": 85.6})
    assert (a.expected_tm, a.expected_source) == (85.6, "file")
    calls = {w.well: w.status for w in a.wells}
    assert calls["A5"] == "one_product" and calls["A1"] == "tm_off"
    assert calls["H3"] == "dimer"  # 84.0 is now 1.6 °C below the product


def test_the_tolerance_and_the_extra_peak_share_are_the_packs():
    rows, curves = _plate()
    wide = _assay(rows, curves, params=MeltParams(tm_tolerance_c=2.0, extra_peak_share=0.25))
    calls = {w.well: w.status for w in wide.wells}
    assert calls["A5"] == "one_product" and calls["A6"] == "one_product"
    with pytest.raises(ValueError, match="tm_tolerance_c"):
        MeltParams.from_rule({"tm_tolerance_c": 0})
    with pytest.raises(ValueError, match="must be a number"):
        MeltParams.from_rule({"noise_share": "high"})
    assert MeltParams.from_rule({"min_wells": 4.0}).min_wells == 4


def test_a_peak_under_the_noise_floor_is_not_counted():
    rows = [well("P", f"A{i}", "T", f"S{i}", cq=20.0) for i in range(1, 5)]
    rows.append(well("P", "H1", "T", "NTC", "ntc", cq=None))
    curves = [curve(f"A{i}", ((84.0, 1.0),)) for i in range(1, 5)]
    curves.append(curve("H1", ((84.0, 0.02),)))  # 2 % of a product peak: noise at 5 %
    a = _assay(rows, curves)
    assert {w.well: w.status for w in a.wells}["H1"] == "no_product"
    assert a.noise_floor == pytest.approx(0.05 * a.reference_height)
    loud = _assay(rows, curves, params=MeltParams(noise_share=0.01))
    assert {w.well: w.status for w in loud.wells}["H1"] == "product"


def test_too_few_study_wells_leave_the_product_temperature_unknown():
    rows = [
        well("P", "A1", "T", "S1", cq=20.0),
        well("P", "A2", "T", "S2", cq=20.0),
        well("P", "H1", "T", "NTC", "ntc", cq=35.0),
    ]
    curves = [
        curve("A1", ((84.0, 1.0),)),
        curve("A2", ((76.0, 0.2), (86.0, 1.0))),
        curve("H1", ((76.0, 0.3),)),
    ]
    a = _assay(rows, curves)
    assert a.expected_tm is None and a.median_tm is None
    calls = {w.well: w.status for w in a.wells}
    # no tm_off without a product temperature; extra peaks are still seen
    assert calls == {"A1": "one_product", "A2": "extra_peak", "H1": "unclassified"}
    assert _assay(rows, curves, params=MeltParams(min_wells=2)).expected_tm == pytest.approx(85.0)


def test_standards_and_positives_set_the_temperature_when_unknowns_are_too_few():
    rows = [well("P", f"A{i}", "T", f"STD{i}", "std", cq=15.0 + i) for i in range(1, 4)]
    rows.append(well("P", "A9", "T", "S1", cq=25.0))
    curves = [curve(f"A{i}", ((80.0, 1.0),)) for i in range(1, 4)] + [curve("A9", ((80.4, 1.0),))]
    a = _assay(rows, curves)
    assert a.expected_tm == pytest.approx(80.0, abs=0.1) and len(a.reference) == 4


def test_unreadable_and_missing_melt_curves_are_kept_apart():
    rows = [well("P", f"A{i}", "T", "S", cq=20.0) for i in range(1, 5)]
    curves = [curve("A1"), curve("A2"), curve("A3", lo=60, hi=95, step=2.5)]
    a = _assay(rows, curves)
    calls = {w.well: w.status for w in a.wells}
    assert calls == {"A1": "one_product", "A2": "one_product", "A3": "unreadable", "A4": "no_melt"}
    coarse = _assay(rows[:1], [curve("A1", lo=60, hi=95, step=2.5)])
    assert coarse.coarse and coarse.step_c == pytest.approx(2.5)


def test_judge_covers_every_plate_and_target_with_melt_and_the_targets_summary():
    rows, curves = _plate()
    rows2 = [{**r, "run_id": "Q"} for r in rows]
    curves2 = [
        MeltCurve("Q", c.well, c.target, c.sample, c.temperature, c.fluorescence) for c in curves
    ]
    other = [well("R", "A1", "U", "S1", cq=20.0)]  # a plate without melt curves
    data = melt_data([*curves, *curves2])
    assays = judge(table([*rows, *rows2, *other]), data)
    assert [(a.run_id, a.target) for a in assays] == [("P", "T"), ("Q", "T")]
    (summary,) = target_summaries(assays)
    assert (summary.target, summary.n_plates, summary.n_wells) == ("T", 2, 12)
    assert summary.median_tm == pytest.approx(84.05, abs=0.05)
    assert judge(table(rows), M.EMPTY) == []


# ---------- real files ----------


def _cfx_peaks() -> dict[str, list[float]]:
    """CFX Manager's Melt Curve Peak Results: well -> the Tm of each peak it lists."""
    out: dict[str, list[float]] = {}
    with (HSIEH / "2016-09-04 gapdh -  Melt Curve Peak Results_0.csv").open(newline="") as fh:
        for row in csv.DictReader(fh):
            name = row["Well"]
            out.setdefault(f"{name[0]}{int(name[1:])}", []).append(float(row["Melt Temperature"]))
    return out


def test_cfx_managers_own_tm_for_96_sybr_wells(hsieh):
    """Our Tm is within one reading (0.5 °C) of CFX Manager's for every well of the gapdh plate.

    CFX reports the reading at the top of its −dF/dT (a 0.5 °C grid); qPilot the top of a
    parabola through the three highest readings, so it sits up to half a step either side.
    CFX lists one peak per well; so does qPilot once the noise floor applies.
    """
    data = read_melt(hsieh)
    cfx = _cfx_peaks()
    assert len(cfx) == 96 and all(len(v) == 1 for v in cfx.values())
    gaps = []
    for name, (tm,) in cfx.items():
        w = data.wells[(GAPDH, name, "SYBR")]
        assert w.step_c == pytest.approx(0.5)
        gaps.append(w.peaks[0].tm - tm)
    gaps = np.array(gaps)
    assert np.all(np.abs(gaps) <= 0.5)
    assert abs(float(np.mean(gaps))) < 0.25  # measured: -0.18 (CFX reads 83.5, the top is ~83.3)
    rows = [well(GAPDH, name, "SYBR", name, cq=20.0) for name in cfx]
    (a,) = judge(table(rows), data)
    assert Counter(w.status for w in a.wells) == {"one_product": 96}
    assert all(len(w.peaks) == 1 for w in a.wells)


def test_the_inhibition_plates_no_template_controls(hsieh):
    """Two of its three typed NTCs amplified late (Cq 36.3 and 35.9 in CFX): both melt at the
    product's temperature; the third shows no peak."""
    from qpilot.qpcr.curves import analyse_study

    data = read_melt(hsieh)
    curves = analyse_study(hsieh, "qpilot_import", (), use_cache=False)
    assays = {a.run_id: a for a in judge(curves, data)}
    assert set(assays) == {GAPDH, INHIBITION}  # kdm6b-ntcs has no melt file
    a = assays[INHIBITION]
    calls = {w.well: w.status for w in a.wells}
    assert {k: calls[k] for k in ("A1", "A2", "A3")} == {
        "A1": "product",
        "A2": "product",
        "A3": "no_product",
    }
    assert Counter(v for k, v in calls.items() if k[0] != "A") == {"one_product": 14}
    assert a.expected_tm == pytest.approx(83.4, abs=0.1) and len(a.reference) == 14


def test_rdmlpythons_melt_test_file_declares_its_products_tm():
    """rdmlpython's own melt test file: target CRE declared at 85.34 °C, 50 wells, 0.21 °C steps.

    Rows H to J mix a second product melting near 79.5 °C into the CRE product, in rising
    shares (in row J it is the larger peak); row K has the second product only, so its ten wells
    have no product at the declared temperature. Counts measured on the file.
    """
    data = read_melt(MCA)
    assert data.declared_tm == {"CRE": 85.34} and len(data.wells) == 50
    assert all(w.step_c == pytest.approx(0.21, abs=0.01) for w in data.wells.values())
    rows = [well(k[0], k[1], k[2], w.curve.sample, cq=20.0) for k, w in data.wells.items()]
    a = judge_assay("Run 1", "CRE", table(rows), data)
    assert (a.expected_tm, a.expected_source) == (85.34, "file")
    calls = Counter(w.status for w in a.wells)
    assert calls == {"one_product": 13, "extra_peak": 27, "tm_off": 10}
    off = sorted(w.well for w in a.wells if w.status == "tm_off")
    assert off == [f"K{c}" for c in range(12, 22)]
    assert all(w.main.tm == pytest.approx(80.0, abs=0.4) for w in a.wells if w.status == "tm_off")
    mixed = [w for w in a.wells if w.well[0] == "J" and w.status == "extra_peak"]
    assert mixed and all(w.extra[0].tm == pytest.approx(79.7, abs=0.4) for w in mixed)
    # the second product is larger than CRE's in row J: the product still comes first
    assert any(w.shares[1] > w.shares[0] for w in mixed)


def test_ten_assays_on_one_cfx_plate():
    """CFX Manager 3.0 RDML: ten SYBR assays x nine wells; measured once, kept as a regression."""
    from qpilot.qpcr.curves import analyse_study

    data = read_melt(RPA)
    curves = analyse_study(RPA, "All Wells", (), use_cache=False)
    assays = {a.target: a for a in judge(curves, data)}
    assert len(assays) == 10
    tm = {t: round(a.expected_tm, 1) for t, a in assays.items()}
    assert tm == {
        "HoxB1P1": 84.5,
        "GusBP1": 83.3,
        "HoxB2P2": 75.8,
        "HoxB3P2": 80.3,
        "HoxB5P1": 80.6,
        "ActBP1": 78.8,
        "HoxB8P2": 79.9,
        "HoxB9P4": 80.9,
        "Hry1P2": 77.1,
        "LMNAP1": 81.7,
    }
    flagged = {
        (a.target, w.well, w.status, round(w.main.tm, 1))
        for a in assays.values()
        for w in a.wells
        if w.flagged
    }
    assert flagged == {
        ("HoxB1P1", "A4", "extra_peak", 83.9),
        ("HoxB9P4", "F4", "tm_off", 86.0),
        ("HoxB9P4", "F6", "tm_off", 88.4),
        ("LMNAP1", "H5", "tm_off", 76.4),
        ("LMNAP1", "H6", "tm_off", 87.0),
    }
    quiet = [w.well for w in assays["GusBP1"].wells if w.status == "not_amplified"]
    assert quiet == ["B10", "B11", "B12"]


def test_a_lightcycler_96_file_with_two_assays():
    """LightCycler 96 (0.2 °C steps): hmuY and 16S rRNA melt as one product each; its 60 wells
    without a target are typed no-template with no product temperature to compare."""
    from qpilot.io.connectors import materialise
    from qpilot.qpcr.curves import analyse_study

    path = materialise(LC96P).rdml_path
    data = read_melt(path)
    experiment = "0311a87d-a929-434b-a01f-c9f5af1d20af"
    assays = judge(analyse_study(path, experiment, (), use_cache=False), data)
    by = {a.target: Counter(w.status for w in a.wells) for a in assays}
    assert by["sybr_green_i_hmuype"] == {"one_product": 18}
    assert by["sybr_green_i_16s_rrna"] == {"one_product": 18}
    tm = {a.target: round(a.expected_tm, 1) for a in assays if a.expected_tm is not None}
    assert tm == {"sybr_green_i_hmuype": 82.0, "sybr_green_i_16s_rrna": 87.1}


def test_a_file_without_melt_readings_is_not_parsed(monkeypatch, fixtures_dir):
    import qpilot.io.rdml_io as rdml_io

    def refuse(*a, **k):
        raise AssertionError("parsed a file without melt readings")

    monkeypatch.setattr(rdml_io, "load", refuse)
    data = read_melt(fixtures_dir / "vermeulen_std_150000.rdml")
    assert not data.has_melt and data.wells == {}


def test_the_file_is_kept_in_memory_and_a_bad_file_is_refused(tmp_path):
    first = read_melt(MCA)
    assert read_melt(MCA) is first
    bad = tmp_path / "bad.rdml"
    bad.write_text("<rdml><mdp>", encoding="utf-8")
    with pytest.raises(M.MeltError):
        read_melt(bad)
    with pytest.raises(M.MeltError):
        read_melt(tmp_path / "missing.rdml")


def test_probe_chemistry_is_known_per_target():
    data = melt_data([curve("A1")], chemistry={"T": "hydrolysis probe", "U": M.DYE_CHEMISTRIES[0]})
    assert data.probe("T") and not data.probe("U") and not data.probe("V")


def test_study_melt_reads_the_curve_table_through_the_design(hsieh):
    from qpilot.qpcr.study import StudySettings

    settings = StudySettings(experiment_id="qpilot_import", candidates=())
    data, assays = M.study_melt(hsieh, settings)
    assert data.has_melt and {a.run_id for a in assays} == {GAPDH, INHIBITION}
    frame = pd.DataFrame({"run_id": [], "target": []})
    assert judge(frame, data) == []
