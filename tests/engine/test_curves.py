"""Task 3 gate: LinRegPCR on every plate, parsed by header, names validated, cached by content."""

import time

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr import curves
from qpilot.qpcr.curves import (
    COLUMN_ORDER,
    REFERENCE_TARGETS,
    CurveAnalysisError,
    analyse_run,
    analyse_study,
    normalise_target,
    safe_name,
    slug,
)


@pytest.fixture
def std_rdml(fixtures_dir):
    return fixtures_dir / "vermeulen_std_150000.rdml"


# ---------- pure helpers ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PRKACB_20080311", "PRKACB"),
        ("PRKACB_20080311_bis", "PRKACB_bis"),
        ("AHCY_20080229", "AHCY"),
        ("SDHA(1)", "SDHA(1)"),
        ("MYCN(4)", "MYCN(4)"),
        ("GENE_2008", "GENE_2008"),
    ],
)
def test_normalise_target(raw, expected):
    assert normalise_target(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ALUsq(Eurogentec)", "alusq_eurogentec"),
        ("SDHA(1)", "sdha_1"),
        ("UBC(2)", "ubc_2"),
        ("NM23A", "nm23a"),
    ],
)
def test_slug(raw, expected):
    assert slug(raw) == expected


def test_safe_names_pass_unchanged():
    for name in ("1495", "STD_150", "SDHA(1)", "ALUsq(Eurogentec)", "AHCY_20080229", "A1"):
        assert safe_name(name, "sample") == name


def test_unsafe_names_are_replaced_with_a_warning(caplog):
    assert safe_name("<script>alert(1)</script>", "sample") == "script_alert_1_script"
    assert "unsafe sample name" in caplog.text
    assert safe_name("x" * 80, "sample") == "x" * 64
    assert safe_name("{{f_fc_odc1}}", "target") == "f_fc_odc1"


# ---------- on the 54 KB standards fixture (runs in CI) ----------


def test_analyse_study_on_fixture_has_documented_shape(std_rdml, tmp_path):
    table = analyse_study(std_rdml, cache_dir=tmp_path)
    assert list(table.columns) == list(COLUMN_ORDER)
    assert len(table) == 192
    assert table["run_id"].nunique() == 64
    assert table["target"].nunique() == 64
    assert set(table.loc[table.target_type == "ref", "target"]) == set(REFERENCE_TARGETS)
    assert (table["sample_type"] == "std").all()
    assert table["n0"].dtype == float and table["amplification"].dtype == bool
    assert not table["target"].str.contains("_2008").any()
    assert table["eff_target"].between(1.5, 2.1).all()


def test_raw_target_name_is_kept_for_traceability(std_rdml, tmp_path):
    table = analyse_study(std_rdml, cache_dir=tmp_path)
    assert table["target_raw"].str.contains("_2008").any()


def test_cache_round_trip_is_exact_and_atomic(std_rdml, tmp_path):
    fresh = analyse_study(std_rdml, cache_dir=tmp_path)
    cache_files = list(tmp_path.glob("*.curves.csv"))
    assert len(cache_files) == 1 and not list(tmp_path.glob("*.tmp"))
    cached = analyse_study(std_rdml, cache_dir=tmp_path)
    pd.testing.assert_frame_equal(fresh, cached, check_exact=True)


def test_cache_key_changes_with_settings_and_references(std_rdml, tmp_path):
    analyse_study(std_rdml, cache_dir=tmp_path)
    analyse_study(std_rdml, cache_dir=tmp_path, reference_targets=("HMBS",))
    analyse_study(
        std_rdml, cache_dir=tmp_path, settings=curves.CurveSettings(pcrEfficiencyExl=0.10)
    )
    assert len(list(tmp_path.glob("*.curves.csv"))) == 3


def test_loaded_document_is_analysed_without_caching(std_rdml, tmp_path):
    from qpilot.io.rdml_io import load

    table = analyse_study(load(std_rdml), cache_dir=tmp_path)
    assert len(table) == 192 and not list(tmp_path.iterdir())


def test_unknown_experiment_is_reported(std_rdml, tmp_path):
    from qpilot.io.rdml_io import RdmlLoadError

    with pytest.raises(RdmlLoadError, match="biomarker_set"):
        analyse_study(std_rdml, "no_such_experiment", cache_dir=tmp_path, use_cache=False)


def test_plate_without_raw_curves_raises(smoke_rdml):
    from qpilot.io.rdml_io import load, runs

    with pytest.raises(CurveAnalysisError, match="raw data"):
        analyse_run(runs(load(smoke_rdml))[0])


# ---------- the gate: all 64 plates of the demo study ----------


@pytest.fixture(scope="module")
def demo_table(tmp_path_factory):
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    path = default_cache_dir() / VERMEULEN_FILENAME
    if not path.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    cache = tmp_path_factory.mktemp("curves_cache")
    start = time.perf_counter()
    table = analyse_study(path, cache_dir=cache)
    cold = time.perf_counter() - start
    start = time.perf_counter()
    again = analyse_study(path, cache_dir=cache)
    warm = time.perf_counter() - start
    return table, again, cold, warm


@pytest.mark.demo_data
def test_demo_every_plate_every_well(demo_table):
    table, *_ = demo_table
    assert table["run_id"].nunique() == 64
    assert len(table) == 24_576


@pytest.mark.demo_data
def test_demo_targets_and_references(demo_table):
    table, *_ = demo_table
    assert table["target"].nunique() == 64
    refs = sorted(table.loc[table.target_type == "ref", "target"].unique())
    assert refs == sorted(REFERENCE_TARGETS)


@pytest.mark.demo_data
def test_demo_per_gene_efficiency_matches_oracle(demo_table):
    table, *_ = demo_table
    per_gene = table.groupby("target")["eff_target"].first()
    assert len(per_gene) == 64
    assert np.median(per_gene) == pytest.approx(1.903, abs=0.002)
    assert per_gene.min() == pytest.approx(1.726, abs=0.002)
    assert per_gene.max() == pytest.approx(1.936, abs=0.002)


@pytest.mark.demo_data
def test_demo_undetermined_unknown_wells_match_oracle(demo_table):
    table, *_ = demo_table
    unknown = table[table.sample_type == "unkn"]
    assert len(unknown) == 23_424
    assert int(unknown["n0"].isna().sum()) == 323


@pytest.mark.demo_data
def test_demo_matches_oracle_wells_exactly(demo_table):
    """Spot-check two wells against the oracle cache (recon/results.tsv)."""
    table, *_ = demo_table
    ahcy = table[(table.run_id == "AHCY_20080229") & (table["sample"] == "1495")].iloc[0]
    assert ahcy["cq"] == pytest.approx(25.9824)
    assert ahcy["n0"] == pytest.approx(5281.3746)
    assert ahcy["eff_target"] == pytest.approx(1.909489)


@pytest.mark.demo_data
def test_demo_timing_and_cache(demo_table):
    table, again, cold, warm = demo_table
    pd.testing.assert_frame_equal(table, again, check_exact=True)
    assert cold < 60, f"cold analysis took {cold:.1f} s"
    assert warm < 2, f"cached analysis took {warm:.1f} s"
