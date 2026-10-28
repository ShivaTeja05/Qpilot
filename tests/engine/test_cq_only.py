"""A file of Cq values only: analysed from its Cq, with no curve fit (``qpilot/qpcr/cq_only.py``).

The mini file (``tests/fixtures/studio/studio_mini.py``) written with ``curves=False`` holds the
same wells, samples and dilution series as the curve file, with each well's Cq and no curve, so
every number below is checked against the Cq values the fixture writes.
"""

from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qpilot.io.rdml_io import load, runs
from qpilot.qpcr import cq_only
from qpilot.qpcr import curves as C
from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
from qpilot.qpcr.designs import design_curves
from qpilot.qpcr.study import StudySettings, build_model, study_from_curves
from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign, TargetDesign
from tests.fixtures.studio.studio_mini import PLATES, write_studio_mini

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
SOYBEAN = CORPUS / "rdml" / "rdml-1.2-cq-only-soybean" / "VPZ_raw_data.rdml"
HMUY_TABLE = CORPUS / "rdml" / "lightcycler96-lc96p-hmuy" / "hmuy_cq_values.xlsx"
SERIES = {"STD_100": 100.0, "STD_1000": 1000.0, "STD_10000": 10000.0}
GROUPS = {"WT_1": "WT", "WT_2": "WT", "KO_1": "KO", "KO_2": "KO"}


@pytest.fixture(autouse=True)
def private_cache(tmp_path, monkeypatch):
    """Never read or write the shared curve cache (a Cq table must not depend on one)."""
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def mini_cq(tmp_path) -> Path:
    return write_studio_mini(tmp_path / "mini_cq.rdml", curves=False)


def design(series: dict[str, float] | None = SERIES, axes=None) -> StudyDesign:
    samples = {s: SampleDesign(sample=s, group=g) for s, g in GROUPS.items()}
    for s, q in (series or {}).items():
        samples[s] = SampleDesign(sample=s, role="std", quantity=q)
    return StudyDesign(
        design_id="cq_only_test",
        mode="groups",
        experiment_id="mini_set",
        samples=samples,
        targets={
            "GAPDH": TargetDesign(target="GAPDH", role="ref"),
            "1-Mar": TargetDesign(target="1-Mar", role="toi"),
        },
        comparison=Comparison(group_a="KO", group_b="WT"),
        reference_candidates=["GAPDH"],
        amp_calls=STUDIO_AMP_CALLS,
        axes=axes,
    )


def table_of(path: Path, refs=("GAPDH",)) -> pd.DataFrame:
    return C.analyse_study(path, "mini_set", refs)


# ---- the per-well table of a file without curves -----------------------------------------


def test_a_file_of_cq_values_is_read_from_its_cq_without_linregpcr(mini_cq, monkeypatch):
    def never(*_a, **_k):
        raise AssertionError("LinRegPCR must not run on a file without curves")

    monkeypatch.setattr(C, "analyse_run", never)
    table = table_of(mini_cq)
    assert C.without_curves(table)
    assert list(table.columns) == list(C.COLUMN_ORDER)
    wt1 = table[(table["sample"] == "WT_1") & (table["target"] == "GAPDH")]
    assert wt1["cq"].tolist() == PLATES["GAPDH"]["WT_1"]
    assert np.allclose(wt1["n0"], np.exp2(-wt1["cq"]), rtol=0, atol=0)
    assert (table["eff_target"] == 2.0).all()
    assert table[list(C.FITTED_COLUMNS)].isna().all().all() and (table["note"] == "").all()
    flat = table[table["sample"] == "water"]
    assert flat["cq"].isna().all() and flat["n0"].isna().all() and not flat["amplification"].any()
    assert set(table["sample_type"]) == {"unkn", "ntc"}
    assert set(table.loc[table["target"] == "GAPDH", "target_type"]) == {"ref"}


def test_the_rows_are_linregpcrs_own_names_types_and_wells(tmp_path):
    """The same reactions read both ways give the same well, sample, type, target and key."""
    doc = load(write_studio_mini(tmp_path / "mini.rdml", instrument_cq=True))
    for run in runs(doc, "mini_set"):
        fitted, read = C.analyse_run(run), C.cq_only_run(run)
        cols = ["run_id", "well", "sample", "sample_type", "target_raw"]
        assert fitted[cols].equals(read[cols])
        # LinRegPCR adds its own warnings to a well's exclusion; a Cq alone has none to add
        own = fitted["excluded"].str.contains("negative control")
        assert fitted.loc[~own, "excluded"].equals(read.loc[~own, "excluded"])


def test_a_table_with_curves_or_the_trust_cards_cq_only_is_not_a_cq_table(tmp_path):
    curves = write_studio_mini(tmp_path / "mini.rdml", instrument_cq=True)
    assert not C.without_curves(table_of(curves))
    trust_cq = C.analyse_study(
        curves, "mini_set", ("GAPDH",), C.CurveSettings(quantities=C.INSTRUMENT_CQ)
    )
    assert not C.without_curves(trust_cq)  # its notes say the curve is not used
    toy = pd.DataFrame({"cq": [20.0], "n0": [1.0]})
    assert not C.without_curves(toy) and not C.without_curves(toy.iloc[:0])


def test_a_file_with_neither_curves_nor_cq_and_a_mixed_file_are_refused_in_words(tmp_path):
    mini = write_studio_mini(tmp_path / "mini.rdml")  # curves, no instrument Cq
    with zipfile.ZipFile(mini) as z:
        xml = z.read("rdml_data.xml").decode()
    bare = re.sub(r"<adp>.*?</adp>", "", xml)
    with zipfile.ZipFile(tmp_path / "bare.rdml", "w") as z:
        z.writestr("rdml_data.xml", bare)
    with pytest.raises(C.CurveAnalysisError, match="neither amplification curves nor Cq"):
        table_of(tmp_path / "bare.rdml")
    cq = write_studio_mini(tmp_path / "cq.rdml", instrument_cq=True)
    with zipfile.ZipFile(cq) as z:
        xml = z.read("rdml_data.xml").decode()
    first, second = xml.split('<run id="1-Mar_plate">')
    mixed = first + '<run id="1-Mar_plate">' + re.sub(r"<adp>.*?</adp>", "", second)
    with zipfile.ZipFile(tmp_path / "mixed.rdml", "w") as z:
        z.writestr("rdml_data.xml", mixed)
    with pytest.raises(C.CurveAnalysisError, match="Cq values only .* other runs"):
        table_of(tmp_path / "mixed.rdml")
    # the Import Trust card's Cq only reads every well's Cq, curves or not
    either = C.CurveSettings(quantities=C.INSTRUMENT_CQ)
    table = C.analyse_study(tmp_path / "mixed.rdml", "mini_set", ("GAPDH",), either)
    assert (
        table["cq"].notna().sum()
        == table_of(write_studio_mini(tmp_path / "x.rdml", curves=False))["cq"].notna().sum()
    )


# ---- each assay's efficiency -------------------------------------------------------------


def test_each_assays_efficiency_is_its_dilution_series_and_n0_follows(mini_cq):
    table = design_curves(table_of(mini_cq), design())
    plan = cq_only.efficiency_plan(table, design())
    for target in ("GAPDH", "1-Mar"):
        std = table[(table["sample_type"] == "std") & (table["target"] == target)]
        x = np.log10(std["sample"].map(SERIES).to_numpy())
        slope = np.polyfit(x, std["cq"].to_numpy(), 1)[0]
        expected = 10 ** (-1 / slope)
        assay = plan.assays[target]
        assert assay.source == "dilution_series" and assay.levels == 3
        assert math.isclose(assay.efficiency, expected, rel_tol=1e-12)
        rows = table[table["target"] == target]
        assert np.allclose(rows["eff_target"], expected, rtol=1e-12)
        has = rows["cq"].notna()
        assert np.allclose(rows.loc[has, "n0"], expected ** -rows.loc[has, "cq"], rtol=1e-12)
    assert "from its dilution series" in cq_only.efficiency_words(plan.assays["GAPDH"])
    assert cq_only.cap_for(plan).level == "Moderate"


def test_without_a_series_the_efficiency_is_assumed_and_the_quantities_untouched(mini_cq):
    raw = table_of(mini_cq)
    table = design_curves(raw, design(series=None))
    # without the series in the design its wells are study samples: no assay has a series
    plan = cq_only.efficiency_plan(table, design(series=None))
    assert plan.assumed == ("1-Mar", "GAPDH") and not plan.measured
    assert table["n0"].equals(raw["n0"])  # bit for bit: 2^-Cq as read
    cap = cq_only.cap_for(plan)
    assert cap.level == "Low" and not any(ch.isdigit() for ch in cap.note)
    words = cq_only.efficiency_words(plan.assays["GAPDH"])
    assert "assumed to be 2.0" in words


def test_a_series_no_pcr_could_give_is_not_used_and_says_why(mini_cq):
    wild = {"STD_100": 100.0, "STD_1000": 1e5, "STD_10000": 1e8}  # slope ~ -1.1: E ~ 7
    table = design_curves(table_of(mini_cq), design(series=wild))
    plan = cq_only.efficiency_plan(table, design(series=wild))
    assay = plan.assays["GAPDH"]
    assert assay.source == "assumed" and assay.rejected
    assert "outside the range a PCR can have" in cq_only.efficiency_words(assay)
    assert (table["eff_target"] == 2.0).all()


# ---- the study ---------------------------------------------------------------------------


def test_the_comparison_is_the_ddcq_of_the_files_cq_at_an_assumed_two(mini_cq):
    """Without a series the engine's log2 fold change is exactly −ΔΔCq of the given Cq."""
    result, cards, _ = study_from_curves(
        table_of(mini_cq), "0" * 64, StudySettings.from_design(design(None))
    )

    def dcq(sample: str) -> float:
        return float(np.mean(PLATES["1-Mar"][sample])) - float(np.mean(PLATES["GAPDH"][sample]))

    ko = np.mean([dcq("KO_1"), dcq("KO_2")])
    wt = np.mean([dcq("WT_1"), dcq("WT_2")])
    assert math.isclose(result.contrasts["1-Mar"].log2fc, -(ko - wt), abs_tol=1e-9)
    facts = result.facts
    assert facts["f_cq_only"].value == "Cq values only"
    assert facts["f_eff_source_gapdh"].value == "assumed"
    assert facts["f_n_eff_assumed"].value == 2 and facts["f_eff_assumed_value"].value == 2.0
    grade = result.confidence["1-Mar"]
    assert any(c.id == cq_only.CAP_ID for c in grade.checks)
    assay = next(c for c in grade.checks if c.id == "assay")
    assert "Cq values only" in assay.note and "LinRegPCR" not in assay.note


def test_with_a_series_the_study_uses_it_and_the_efficiency_axis_offers_only_two(mini_cq):
    axes = {"efficiency": ["linregpcr", "per_well", "amplicon_mean", "assumed_2", "standard_curve"]}
    settings = StudySettings.from_design(design(axes=axes))
    model = build_model(table_of(mini_cq), settings)
    assert model.cq_only is not None and model.cq_only.measured == ("1-Mar", "GAPDH")
    axis = model.space.axes["efficiency"]
    unavailable = dict(axis.unavailable)
    assert unavailable["per_well"].startswith("Not applicable: this file has Cq values only")
    assert unavailable["amplicon_mean"].startswith("Not applicable")
    assert "already takes each assay's efficiency" in unavailable["standard_curve"]
    assert "assumed_2" not in unavailable
    result, _, _ = study_from_curves(table_of(mini_cq), "0" * 64, settings)
    assert result.efficiency == {
        g: pytest.approx(model.cq_only.assays[g].efficiency, rel=1e-12) for g in ("1-Mar", "GAPDH")
    }
    assert result.facts["f_eff_source_1_mar"].value == "dilution series"
    assert result.confidence["1-Mar"].level in ("Low", "Moderate")
    assert result.facts["f_axis_efficiency"].value in ("screened_out", "swept")


# ---- real files --------------------------------------------------------------------------


def test_the_soybean_rdml_of_cq_values_is_read_in_full():
    """RDML 1.2, 3 experiments, 17 runs: 1,428 reactions, 1,291 Cq (the corpus MANIFEST)."""
    doc = load(SOYBEAN)
    total_rows = total_cq = 0
    types: set[str] = set()
    for experiment in doc.experiments():
        table = C.analyse_study(SOYBEAN, experiment["id"], (), use_cache=False)
        assert C.without_curves(table)
        total_rows += len(table)
        total_cq += int(table["cq"].notna().sum())
        types |= set(table["sample_type"])
    assert total_cq == 1291
    assert total_rows == 1428
    assert {"unkn", "nrt", "ntc"} <= types


def test_a_persons_excel_cq_table_is_analysable():
    from qpilot.io.connectors.registry import capture

    found = capture([HMUY_TABLE])
    table = C.analyse_study(found.doc, found.meta.experiment_id or None, ("16S rRNA",))
    assert C.without_curves(table) and len(table) == 36 and table["cq"].notna().all()
    assert set(table["target"]) == {"hmuYPe", "16S rRNA"}


def test_the_demo_fixture_with_curves_is_untouched(fixtures_dir):
    """A file with curves never takes the Cq-only path (the demo's numbers stay as they were)."""
    table = C.analyse_study(fixtures_dir / "vermeulen_std_150000.rdml", "biomarker_set")
    assert not C.without_curves(table)
    assert cq_only.efficiency_plan(table).assays == {}
