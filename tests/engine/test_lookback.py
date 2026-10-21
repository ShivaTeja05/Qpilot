"""Lookback: which conclusions used the runs in a window, and what leaving them out does.

Synthetic tests run in CI; the ``demo_data`` tests check the plan's 3b.3 acceptance on the
Vermeulen demo (one gene per plate) against an independent recomputation.
"""

import dataclasses
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from qpilot.core.instruments import Logbook
from qpilot.core.store import StudyStore
from qpilot.explain.lookback_text import lookback_text, lookback_tokens
from qpilot.qpcr.lookback import (
    REASONS,
    LookbackError,
    dated_runs,
    lookback,
    lookback_study,
    run_name_date,
    write_lookback,
)
from qpilot.qpcr.study import StudySettings, build_model

BANNED = (
    "diagnosis",
    "diagnose",
    "root cause",
    "invalid run",
    "valid run",
    "faulty instrument",
    "error found",
    "compliant",
)

# ---- a small synthetic study: three control genes, a marker, four genes, one plate each ----------

REFS = ("R1", "R2", "R3")
SETTINGS = StudySettings(
    experiment_id=None, candidates=REFS, marker="MK", group_var="MK_high", headline=()
)
PLATES = {
    "R1": "R1_20260105",
    "R2": "R2_20260106",
    "R3": "R3_20260106",
    "MK": "MK_20260107",
    "UPG": "UPG_20260108",
    "DOWNG": "DOWNG_20260108",
    "FLAT": "FLAT_20260109",
    "EDGE": "EDGE_20260109",
}


def synthetic_curves(n: int = 48, seed: int = 11) -> pd.DataFrame:
    """One plate per gene; R1 carries a group effect, so leaving R1 out moves EDGE past 2-fold."""
    rng = np.random.default_rng(seed)
    marker = rng.normal(0, 1, n)
    high = marker >= np.sort(marker)[int(0.85 * n)]
    nf = rng.normal(0, 0.3, n)
    effect = {"UPG": 2.5, "DOWNG": -2.5, "FLAT": 0.0, "EDGE": 1.2}
    rows = []
    for target, run in PLATES.items():
        for i in range(n):
            if target == "R1":
                value = 10 + nf[i] + (0.75 if high[i] else 0) + rng.normal(0, 0.35)
            elif target in REFS:
                value = 10 + nf[i] + rng.normal(0, 0.35)
            elif target == "MK":
                value = 8 + nf[i] + 2 * marker[i]
            else:
                value = 6 + nf[i] + (effect[target] if high[i] else 0) + rng.normal(0, 0.2)
            rows.append(
                {
                    "run_id": run,
                    "well": f"A{i + 1}",
                    "sample": f"s{i:02d}",
                    "sample_type": "unkn",
                    "target": target,
                    "n0": 2.0**value,
                }
            )
    return pd.DataFrame(rows)


def recompute(curves: pd.DataFrame, settings: StudySettings, runs_out: set[str]) -> dict:
    """Independent recomputation: drop the rows, rebuild, evaluate the primary cell (no grid)."""
    before = build_model(curves, settings)
    calls_before = before.space.evaluate(before.space.primary)
    rest = curves[~curves["run_id"].isin(runs_out)]
    left = set(rest["target"])
    reduced = dataclasses.replace(
        settings, candidates=tuple(c for c in settings.candidates if c in left)
    )
    after = build_model(rest, reduced)
    calls_after = after.space.evaluate(after.space.primary)
    changed = sorted(
        g
        for g in calls_before
        if g in calls_after and calls_before[g].conclusion != calls_after[g].conclusion
    )
    return {
        "k": len(changed),
        "changed": changed,
        "gone": sorted(set(calls_before) - set(calls_after)),
        "n": len(calls_before),
    }


@pytest.fixture(scope="module")
def curves():
    return synthetic_curves()


def test_synthetic_baseline_has_the_calls_the_cases_need(curves):
    model = build_model(curves, SETTINGS)
    calls = {g: r.conclusion for g, r in model.space.evaluate(model.space.primary).items()}
    assert calls == {"DOWNG": "down", "EDGE": "none", "FLAT": "none", "UPG": "up"}


def test_a_target_plate_is_no_longer_concluded_not_a_change(curves):
    out = lookback_study(curves, SETTINGS, {"UPG_20260108"}, study_id="syn")
    assert out.status == "evaluated"
    assert out.no_longer_concluded == ["UPG"]
    assert out.n_changed == 0 and out.n_conclusions == 4
    assert out.candidates_in_window == [] and out.groups["changed"] is False
    assert out.runs_in_window == ["UPG_20260108"] and out.n_wells_in_window == 48
    assert recompute(curves, SETTINGS, {"UPG_20260108"}) == {
        "k": 0,
        "changed": [],
        "gone": ["UPG"],
        "n": 4,
    }


def test_a_reference_plate_reruns_with_the_other_candidates(curves):
    out = lookback_study(curves, SETTINGS, {"R1_20260105"})
    assert out.status == "evaluated"
    assert out.candidates_in_window == ["R1"] and out.candidates_after == ["R2", "R3"]
    assert out.changed_genes == ["EDGE"]
    edge = out.changed[0]
    assert (edge.before, edge.after) == ("none", "up")
    assert edge.log2fc_before < 1 <= edge.log2fc_after
    expected = recompute(curves, SETTINGS, {"R1_20260105"})
    assert (out.n_changed, out.changed_genes, out.no_longer_concluded) == (
        expected["k"],
        expected["changed"],
        expected["gone"],
    )
    assert out.grid_cells["after"] < out.grid_cells["before"]  # fewer reference subsets


def test_the_marker_plate_cannot_be_evaluated(curves):
    out = lookback_study(curves, SETTINGS, {"MK_20260107", "FLAT_20260109"})
    assert out.status == "cannot_evaluate" and out.reason == "marker_in_window"
    assert REASONS["marker_in_window"].endswith("the grouping marker was measured in the window")
    assert out.n_changed == 0 and out.changed == []


def test_no_control_gene_left_and_every_run_out(curves):
    every_ref = {PLATES[r] for r in REFS}
    assert lookback_study(curves, SETTINGS, every_ref).reason == "no_control_gene_left"
    assert lookback_study(curves, SETTINGS, set(PLATES.values())).reason == "all_runs_in_window"


def test_lookback_study_is_deterministic(curves):
    a = lookback_study(curves, SETTINGS, {"R1_20260105", "FLAT_20260109"})
    b = lookback_study(curves, SETTINGS, {"FLAT_20260109", "R1_20260105"})
    assert json.dumps(a.model_dump(mode="json"), sort_keys=True) == json.dumps(
        b.model_dump(mode="json"), sort_keys=True
    )


# ---- dates --------------------------------------------------------------------------------------


def test_run_name_dates():
    assert run_name_date("HMBS_20080318") == date(2008, 3, 18)
    assert run_name_date("PRKACB_20080311_bis") == date(2008, 3, 11)
    assert run_name_date("UBC(2)_20080220") == date(2008, 2, 20)
    assert run_name_date("380_replicates_set") is None
    assert run_name_date("X_20081399") is None  # not a calendar date
    assert run_name_date("X_200803181") is None


def test_dates_come_from_given_then_context_then_run_name():
    contexts = {"B_20080301": (date(2008, 4, 1), "run context")}
    out = dated_runs(
        ["A_20080301", "B_20080301", "C_20080301", "plain"],
        given={"C_20080301": "2008-05-02T23:30:00-02:00"},
        contexts=contexts,
    )
    assert out == {
        "A_20080301": (date(2008, 3, 1), "run name"),
        "B_20080301": (date(2008, 4, 1), "run context"),
        "C_20080301": (date(2008, 5, 3), "given"),  # a date-time counts by its UTC date
        "plain": None,
    }


def test_window_and_mapping_are_checked(tmp_studies_dir):
    store = StudyStore(tmp_studies_dir)
    with pytest.raises(LookbackError, match="starts after"):
        lookback(store, {}, "qs", "2008-03-18", "2008-03-01")
    with pytest.raises(LookbackError, match="ISO date"):
        lookback(store, {}, "qs", "18/03/2008", "2008-03-20")
    with pytest.raises(LookbackError):
        lookback(store, ["HMBS_20080318"], "qs", "2008-03-18", "2008-03-18")
    empty = lookback(store, {}, "qs", "2008-03-01", "2008-03-18")
    assert empty.studies == [] and empty.n_runs_in_window == 0
    missing = lookback(store, {}, "qs", "2008-03-01", "2008-03-18", studies=["abcdef123456"])
    assert [(s.status, s.reason) for s in missing.studies] == [("cannot_evaluate", "unknown_study")]
    assert lookback_text(missing).endswith(REASONS["unknown_study"] + ".")


def test_text_without_a_result_is_digit_free():
    assert lookback_tokens(None) == "No lookback has been run for this instrument."


# ---- the Vermeulen demo (3b.3 acceptance) -------------------------------------------------------

DEMO = "qs-demo"


@pytest.fixture(scope="module")
def demo_store(tmp_path_factory, demo_rdml_path_module):
    store = StudyStore(tmp_path_factory.mktemp("studies"))
    sid = store.ensure_study(demo_rdml_path_module)
    return store, sid


@pytest.fixture(scope="module")
def demo_rdml_path_module():
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    path = default_cache_dir() / VERMEULEN_FILENAME
    if not path.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return path


@pytest.fixture(scope="module")
def all_on_one(demo_curves):
    """A synthetic instrument mapping: all 64 demo plates ran on one instrument."""
    return {run: DEMO for run in sorted(set(demo_curves["run_id"]))}


def _in_window(curves, first, last):
    runs = set(curves["run_id"])
    return {r for r in runs if first <= run_name_date(r) <= last}


@pytest.mark.demo_data
@pytest.mark.parametrize(
    ("first", "last"),
    [
        (date(2008, 3, 11), date(2008, 3, 11)),  # 8 target plates
        (date(2008, 2, 25), date(2008, 2, 27)),  # 13 target plates over three dates
    ],
)
def test_demo_window_of_target_plates_only(demo_store, demo_curves, all_on_one, first, last):
    store, sid = demo_store
    result = lookback(store, all_on_one, DEMO, first.isoformat(), last.isoformat())
    window = _in_window(demo_curves, first, last)
    study = result.studies[0]
    expected = recompute(demo_curves, StudySettings(), window)
    assert study.status == "evaluated" and study.study_id == sid
    assert sorted(study.runs_in_window) == sorted(window) == [r.run_id for r in result.runs]
    assert study.n_conclusions == expected["n"] == 58
    assert study.n_changed == expected["k"] == 0
    assert study.no_longer_concluded == expected["gone"]
    assert len(study.no_longer_concluded) == len(window)  # one gene per plate, none dropped
    assert study.candidates_in_window == [] and study.groups["changed"] is False
    assert study.baseline_matches_stored is True
    assert result.n_wells_in_window == 384 * len(window)
    assert all(r.date_source == "run name" for r in result.runs)


@pytest.mark.demo_data
def test_demo_window_with_a_reference_plate(demo_store, demo_curves, all_on_one):
    store, _ = demo_store
    result = lookback(store, all_on_one, DEMO, "2008-03-18", "2008-03-18")
    study = result.studies[0]
    window = {"HMBS_20080318", "NTRK1_20080318"}
    expected = recompute(demo_curves, StudySettings(), window)
    assert set(study.runs_in_window) == window
    assert study.n_changed == expected["k"] == 5
    assert study.changed_genes == expected["changed"]
    assert study.changed_genes == ["DPYSL3", "PAICS", "PDE4DIP", "PLAGL1", "SLC25A5"]
    assert study.no_longer_concluded == ["NTRK1"] == expected["gone"]
    assert study.candidates_in_window == ["HMBS"]
    assert study.candidates_after == ["ALUsq(Eurogentec)", "HPRT1", "SDHA(1)", "UBC(2)"]
    assert study.groups["before"] == {"n_high": 53, "n_rest": 294}
    assert study.groups["after"] == {"n_high": 54, "n_rest": 305}
    assert study.grid_cells == {"before": 186, "after": 90}  # 31 -> 15 reference subsets
    text = lookback_text(result)
    assert "changes 5 of 58 conclusions (DPYSL3, PAICS, PDE4DIP, PLAGL1, SLC25A5)" in text
    assert "No longer concluded" in text and "NTRK1" in text and "HMBS" in text


@pytest.mark.demo_data
def test_demo_grid_after_matches_the_robustness_grid_rerun(demo_curves):
    """k from lookback's grid summary equals the grid run by hand on the reduced data."""
    from qpilot.core import robustness

    window = {"HPRT1_20080303", "INPP1_20080303", "PTPRN2_20080303"}
    out = lookback_study(demo_curves, StudySettings(), window)
    rest = demo_curves[~demo_curves["run_id"].isin(window)]
    settings = dataclasses.replace(
        StudySettings(), candidates=("ALUsq(Eurogentec)", "HMBS", "SDHA(1)", "UBC(2)")
    )
    model = build_model(rest, settings)
    summary = robustness.summary(robustness.run_grid(model.space), model.space)
    before = build_model(demo_curves, StudySettings())
    base = before.space.evaluate(before.space.primary)
    flips = sorted(g for g in base if g in summary and summary[g].conclusion != base[g].conclusion)
    assert out.changed_genes == flips == ["CDKN3", "IGSF4", "NM23A"]
    assert {c.gene: c.holds_after for c in out.changed} == {
        g: round(summary[g].holds, 10) for g in flips
    }


@pytest.mark.demo_data
def test_demo_window_with_the_marker_plate(demo_store, all_on_one):
    store, _ = demo_store
    result = lookback(store, all_on_one, DEMO, "2008-02-22", "2008-02-22")
    study = result.studies[0]
    assert study.status == "cannot_evaluate" and study.reason == "marker_in_window"
    assert set(study.runs_in_window) == {"MRPL3_20080222", "MYCN(4)_20080222", "NHLH2_20080222"}
    assert study.marker == "MYCN(4)"
    text = lookback_text(result)
    assert "cannot evaluate: the grouping marker was measured in the window (MYCN(4))" in text


@pytest.mark.demo_data
def test_demo_result_is_byte_deterministic_and_writes_nothing(demo_store, all_on_one):
    store, sid = demo_store
    workspace = store.workspace(sid)
    before = {p.name: p.read_bytes() for p in workspace.iterdir() if p.is_file()}
    a = lookback(store, all_on_one, DEMO, "2008-03-04", "2008-03-18")
    b = lookback(store, all_on_one, DEMO, "2008-03-04", "2008-03-18")
    assert a.canonical() == b.canonical() and a.sha256() == b.sha256()
    after = {p.name: p.read_bytes() for p in workspace.iterdir() if p.is_file()}
    assert after == before
    assert not (store.root / "instruments").exists()


@pytest.mark.demo_data
def test_demo_dates_given_or_from_a_run_context(demo_store, all_on_one):
    store, sid = demo_store
    moved = lookback(
        store,
        all_on_one,
        DEMO,
        "2008-03-18",
        "2008-03-18",
        run_dates={"HMBS_20080318": "2008-01-01"},
    )
    assert moved.studies[0].runs_in_window == ["NTRK1_20080318"]
    assert moved.studies[0].candidates_in_window == []
    context = store.workspace(sid) / "run_context.json"
    context.write_text(
        json.dumps([{"run_id": "NTRK1_20080318", "run_start": "2008-04-01T09:00:00Z"}])
    )
    try:
        result = lookback(store, all_on_one, DEMO, "2008-03-18", "2008-03-18")
    finally:
        context.unlink()
    assert result.studies[0].runs_in_window == ["HMBS_20080318"]
    late = lookback(store, all_on_one, DEMO, "2008-04-01", "2008-04-01")
    assert late.studies[0].status == "no_runs_in_window"
    assert lookback_text(late).endswith(
        "Studies with no runs from this instrument in the window: 1."
    )


@pytest.mark.demo_data
def test_demo_other_instruments_and_unmapped_runs_are_not_in_the_window(demo_store):
    store, _ = demo_store
    runs = {"HMBS_20080318": "other", "NTRK1_20080318": DEMO}
    result = lookback(store, runs, DEMO, "2008-03-18", "2008-03-18")
    study = result.studies[0]
    assert study.runs_in_window == ["NTRK1_20080318"]
    assert study.n_changed == 0 and study.no_longer_concluded == ["NTRK1"]


@pytest.mark.demo_data
def test_demo_write_lookback_appends_a_chained_event(demo_store, all_on_one, tmp_path):
    store, sid = demo_store
    result = lookback(store, all_on_one, DEMO, "2008-03-18", "2008-03-18")
    book = Logbook(DEMO, tmp_path / "instruments")
    event = write_lookback(book, result, "agent")
    assert event.kind == "lookback" and event.source == "inferred" and event.actor == "agent"
    assert event.payload["result_sha256"] == result.sha256()
    assert event.payload["window"] == {"start": "2008-03-18", "end": "2008-03-18"}
    study = event.payload["studies"][0]
    assert (study["study_id"], study["n_changed"], study["n_conclusions"]) == (sid, 5, 58)
    assert study["no_longer_concluded"] == ["NTRK1"]
    assert book.verify() == []
    with pytest.raises(LookbackError):
        write_lookback(Logbook("elsewhere", tmp_path / "instruments"), result, "human")


@pytest.mark.demo_data
def test_demo_text_validates_and_keeps_to_the_words(demo_store, all_on_one):
    store, _ = demo_store
    for window in (("2008-03-11", "2008-03-11"), ("2008-02-20", "2008-02-22")):
        result = lookback(store, all_on_one, DEMO, *window)
        tokens = lookback_tokens(result)  # validates, or raises
        text = lookback_text(result).lower()
        assert "{{" in tokens and "{{" not in text
        assert not [w for w in BANNED if w in text]
