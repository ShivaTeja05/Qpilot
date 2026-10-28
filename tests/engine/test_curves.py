"""Task 3 gate: LinRegPCR on every plate, parsed by header, names validated, cached by content."""

import zipfile

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
    react_well_label,
    safe_name,
    slug,
    well_label,
)
from tests.timing import work_time


@pytest.fixture
def std_rdml(fixtures_dir):
    return fixtures_dir / "vermeulen_std_150000.rdml"


def rewrite_run(source, target, run_id, edit):
    """A copy of an RDML file with one run's XML passed through ``edit`` (str -> str)."""
    with zipfile.ZipFile(source) as archive:
        xml = archive.read("rdml_data.xml").decode("utf-8")
    start = xml.index(f'<run id="{run_id}">')
    end = xml.index("</run>", start)
    xml = xml[:start] + edit(xml[start:end]) + xml[end:]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", xml)
    return target


def tall_plate(source, target):
    """The fixture's AHCY run on a 32 x 12 plate, its three wells in rows 27, 28 and 29.

    LinRegPCR names these wells ``[1``, ``\\1`` and ``]1``, which all become ``1`` as safe names.
    """

    def edit(run):
        run = run.replace(
            "<rows>16</rows><columns>24</columns>", "<rows>32</rows><columns>12</columns>"
        )
        for old, new in (("326", "313"), ("328", "325"), ("330", "337")):
            run = run.replace(f'<react id="{old}">', f'<react id="{new}">')
        return run

    return rewrite_run(source, target, "AHCY_20080229", edit)


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


@pytest.mark.parametrize(
    ("row", "column", "expected"),
    [
        (1, 1, "A1"),
        (16, 24, "P24"),  # the demo's last well: LinRegPCR's own name up to row 26
        (26, 3, "Z3"),
        (27, 1, "AA1"),  # LinRegPCR would write "[1"
        (32, 48, "AF48"),  # a 1536-well plate's last well
        (52, 2, "AZ2"),
        (53, 2, "BA2"),
        (702, 1, "ZZ1"),
        (703, 1, "AAA1"),
    ],
)
def test_every_well_position_has_its_own_name(row, column, expected):
    assert well_label(row, column) == expected


def test_reaction_numbers_map_to_well_names_row_by_row():
    assert react_well_label("1", 24) == "A1" and react_well_label("25", 24) == "B1"
    assert react_well_label(384, 24) == "P24"
    assert [react_well_label(i, 12) for i in (313, 325, 337)] == ["AA1", "AB1", "AC1"]
    assert react_well_label(72, 1) == "BT1"  # a 72-position rotor
    names = {react_well_label(i, 48) for i in range(1, 1537)}
    assert len(names) == 1536 and all(name == safe_name(name, "well") for name in names)
    for bad in ((0, 24), (1, 0), (-3, 12)):
        with pytest.raises(CurveAnalysisError):
            react_well_label(*bad)


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


def test_a_plate_with_more_than_26_rows_keeps_one_key_per_well(std_rdml, tmp_path):
    """Rows 27-29 were all named ``1``: one exclusion or well call hit three wells."""
    tall = tall_plate(std_rdml, tmp_path / "tall.rdml")
    table = analyse_study(tall, cache_dir=tmp_path)
    run = table[table["run_id"] == "AHCY_20080229"]
    assert list(run["well"]) == ["AA1", "AB1", "AC1"]
    assert not table.duplicated(["run_id", "well"]).any()
    other = table[table["run_id"] != "AHCY_20080229"]
    assert set(other["well"]) == {"N14", "N16", "N18"}  # 16 x 24 plates: LinRegPCR's names


def test_a_cached_table_from_before_unique_well_names_is_analysed_again(std_rdml, tmp_path):
    tall = tall_plate(std_rdml, tmp_path / "tall.rdml")
    fresh = analyse_study(tall, cache_dir=tmp_path)
    (cache_file,) = tmp_path.glob("*.curves.csv")
    stale = fresh.copy()
    stale.loc[stale["run_id"] == "AHCY_20080229", "well"] = "1"  # what the old code wrote
    stale.to_csv(cache_file, index=False)
    again = analyse_study(tall, cache_dir=tmp_path)
    pd.testing.assert_frame_equal(fresh, again, check_exact=True)
    pd.testing.assert_frame_equal(curves._read_cache(cache_file), fresh, check_exact=True)


def test_curves_that_would_share_a_run_and_well_key_are_refused(std_rdml, tmp_path):
    """Two runs whose ids both become ``ahcy_1``, with wells N14, N16 and N18: refused."""
    first = rewrite_run(
        std_rdml,
        tmp_path / "a.rdml",
        "AHCY_20080229",
        lambda r: r.replace("AHCY_20080229", "AHCY/1", 1),
    )
    both = rewrite_run(
        first,
        tmp_path / "b.rdml",
        "AKR1C1_20080307",
        lambda r: r.replace("AKR1C1_20080307", "AHCY+1", 1),
    )
    with pytest.raises(CurveAnalysisError, match="share run_id/well"):
        analyse_study(both, cache_dir=tmp_path)
    assert not list(tmp_path.glob("*.curves.csv"))  # nothing refused is cached


# ---------- the gate: all 64 plates of the demo study ----------


@pytest.fixture(scope="module")
def demo_table(tmp_path_factory):
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    path = default_cache_dir() / VERMEULEN_FILENAME
    if not path.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    cache = tmp_path_factory.mktemp("curves_cache")
    with work_time() as cold:
        table = analyse_study(path, cache_dir=cache)
    with work_time() as warm:
        again = analyse_study(path, cache_dir=cache)
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
    assert cold.seconds < 60, f"cold analysis took {cold}"
    assert warm.seconds < 2, f"cached analysis took {warm}"
