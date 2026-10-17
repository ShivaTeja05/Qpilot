"""Task 12 gate: the engine reproduces the RDML consortium's published benchmark."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qpilot.cli import main
from qpilot.io.datasets import cached_benchmark_tables
from qpilot.qpcr.validation import (
    compare_bias,
    compare_cq,
    compare_n0,
    dilution_bias,
    read_methods_cq,
    read_methods_results,
    read_rdml_tools_n0,
    validate,
)

REPO = Path(__file__).resolve().parents[2]

# ---------- small synthetic tables in the published formats (run in CI) ----------

N0_TSV = (
    "\t\tG1\tG2\tPUBONLY\n"
    "\t10\t9.000e+00\t1.000e+01\t1.0e+00\n"
    "\t10\t1.100e+01\t1.300e+01\t1.0e+00\n"
    "\t100\t9.500e+01\t1.010e+02\t1.0e+00\n"
    "\t100\t1.050e+02\t1.200e+02\t1.0e+00\n"
    "\t\t\n"
    "\tmean(max)\tmean(max)\n"
    "\t0.0001\t0.000097\t0.000097\n"  # a later block of scaled values: must not be read
)

CQ_TSV = (
    ";;Tissue;G1;G2\n"
    "method;Standard-Cq;;G1;G2\n"
    ";;STD_10;99.00;99.00\n"
    "method;LinRegPCR;;G1;G2\n"
    ";;STD_10;29.00;30.00\n"
    ";;STD_10;29.50;30.50\n"
    ";;STD_100;26.00;27.00\n"
    ";;STD_100;26.50;-\n"
    ";;tumour_1;20.00;21.00\n"
    "method;5PSM;;G1;G2\n"
    ";;STD_10;1.00;1.00\n"
)

RESULTS_TSV = (
    "Bias as ratio mean\tG1\tG3\n"
    "LinRegPCR (old)\t5\t6\n"
    "\n"
    "slope = bias\tG1\tG3\tPUBONLY\n"
    "Other method\t0.5\t0.5\t0.5\n"
    "LinRegPCR (old)\t1.0\t0.9\t1.0\n"
    "correlation = R\tG1\tG3\n"
    "LinRegPCR (old)\t0.99\t0.98\n"
)


def _wells(target, label, n0s, cqs):
    return [
        {"target": target, "sample": label, "sample_type": "std", "n0": n0, "cq": cq}
        for n0, cq in zip(n0s, cqs, strict=True)
    ]


@pytest.fixture
def curves():
    rows = [
        *_wells("G1", "STD_10", [9.0, 11.0], [30.0, 30.5]),
        *_wells("G1", "STD_100", [95.0, 105.0], [27.0, 27.5]),
        *_wells("G2", "STD_10", [10.0, 12.0], [31.0, 31.5]),
        *_wells("G2", "STD_100", [100.0, 120.0], [28.0, float("nan")]),
        *_wells("G3", "STD_10", [10.0, 10.0], [30.0, 30.0]),
        *_wells("G3", "STD_100", [100.0, 100.0], [26.0, 26.0]),
        {"target": "G1", "sample": "tumour_1", "sample_type": "unkn", "n0": 1.0, "cq": 20.0},
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def tables(tmp_path):
    paths = {
        "n0": tmp_path / "n0.tsv",
        "cq": tmp_path / "cq.tsv",
        "results": tmp_path / "results.tsv",
    }
    paths["n0"].write_text(N0_TSV)
    paths["cq"].write_text(CQ_TSV)
    paths["results"].write_text(RESULTS_TSV)
    return paths


def test_read_rdml_tools_n0_stops_at_the_first_block(tables):
    n0 = read_rdml_tools_n0(tables["n0"])
    assert n0[("G1", "STD_10")] == [9.0, 11.0]
    assert n0[("G2", "STD_100")] == [101.0, 120.0]
    assert ("G1", "STD_0.0001") not in n0
    assert len(n0) == 6  # three genes x two concentrations


def test_read_methods_cq_reads_only_the_named_method(tables):
    cq = read_methods_cq(tables["cq"])
    assert cq[("G1", "STD_10")] == [29.0, 29.5]
    assert cq[("G2", "STD_100")] == [27.0]  # "-" is skipped
    assert not any(label == "tumour_1" for _, label in cq)
    assert read_methods_cq(tables["cq"], "5PSM")[("G1", "STD_10")] == [1.0]


def test_read_methods_results_takes_the_method_row_of_the_named_block(tables):
    assert read_methods_results(tables["results"]) == {"G1": 1.0, "G3": 0.9, "PUBONLY": 1.0}
    assert read_methods_results(tables["results"], "correlation = R") == {"G1": 0.99, "G3": 0.98}
    with pytest.raises(ValueError, match="no 'LinRegPCR \\(old\\)' row"):
        read_methods_results(tables["results"], "missing block")


def test_compare_n0_counts_identical_and_within(curves, tables):
    line = compare_n0(curves, read_rdml_tools_n0(tables["n0"]))
    # G1 and G2 on both sides (8 wells); G3 only ours; PUBONLY only published.
    assert (line.wells, line.genes) == (8, 2)
    # Different: G2 12 vs 13 (7.7 %, outside 5 %) and G2 100 vs 101 (1 %, inside 5 %).
    assert line.identical_4sf == 6
    assert line.within_5pct == 7
    assert line.max_rel_diff == pytest.approx(1 / 13)
    assert line.share_identical == pytest.approx(6 / 8)
    assert line.published_only == ("PUBONLY",)
    assert line.ours_only == ("G3",)


def test_missing_wells_on_our_side_count_against_us(curves, tables):
    curves.loc[(curves.target == "G1") & (curves.n0 == 9.0), "n0"] = np.nan
    line = compare_n0(curves, read_rdml_tools_n0(tables["n0"]))
    assert line.wells == 8  # still every published well
    # G1 at 10 copies: published 9 and 11, ours only 11. Sorted pairing gives (9, 11), 22 % off,
    # and the published 11 has no partner, so both wells drop out of "identical" and "within".
    assert (line.identical_4sf, line.within_5pct) == (4, 5)


def test_dilution_bias_is_the_log_log_slope(curves):
    bias = dilution_bias(curves)
    assert bias["G3"] == pytest.approx(1.0)  # perfect dilution series
    x = np.log10([10, 10, 100, 100])
    expected = np.polyfit(x, np.log10([9.0, 11.0, 95.0, 105.0]), 1)[0]
    assert bias["G1"] == pytest.approx(expected)


def test_compare_bias(curves, tables):
    line = compare_bias(curves, read_methods_results(tables["results"]))
    ours = dilution_bias(curves)
    assert line.genes == 2
    assert line.median_abs_diff == pytest.approx(
        np.median([abs(ours["G1"] - 1.0), abs(ours["G3"] - 0.9)])
    )
    assert line.published_mean == pytest.approx(0.95)
    assert line.published_only == ("PUBONLY",)


def test_compare_cq_reports_the_signed_offset(curves, tables):
    line = compare_cq(curves, read_methods_cq(tables["cq"]))
    assert (line.wells, line.genes) == (7, 2)  # G2 STD_100 has one published well
    assert line.mean_offset == pytest.approx(1.0)
    assert line.sd_offset == pytest.approx(0.0, abs=1e-12)
    assert line.min_offset == pytest.approx(1.0)


def test_report_is_deterministic_and_says_what_was_not_compared(curves, tables):
    report = validate(curves, tables)
    assert report.to_json() == validate(curves, tables).to_json()
    data = json.loads(report.to_json())
    assert data["n0"]["wells"] == 8 and data["cq"]["wells"] == 7
    assert "fce7a44e8b47b90759c646b557de568f7af77e75" == data["benchmark"]["commit"]
    markdown = report.to_markdown()
    assert "do not edit by hand" in markdown
    assert "`PUBONLY`" in markdown and "`G3`" in markdown
    assert "in all 7 wells" in markdown  # every well is later, so the text may say so
    assert len(report.lines()) == 3


def test_cq_wording_does_not_claim_every_well_when_one_is_earlier(curves, tables):
    curves.loc[(curves.target == "G1") & (curves.cq == 30.0), "cq"] = 28.0
    report = validate(curves, tables)
    assert report.cq.min_offset < 0
    assert "in all" not in report.to_markdown()


# ---------- the demo study against the real published tables ----------


@pytest.fixture(scope="module")
def demo_tables():
    tables = cached_benchmark_tables()
    if tables is None:
        pytest.skip("published tables not cached; run `qpilot fetch-demo`")
    return tables


@pytest.fixture(scope="module")
def demo_report(demo_curves, demo_tables):
    return validate(demo_curves, demo_tables)


@pytest.mark.demo_data
def test_demo_n0_reproduces_rdml_tools(demo_report):
    n0 = demo_report.n0
    assert (n0.wells, n0.genes) == (930, 62)
    assert n0.identical_4sf == 926  # the other 4 differ only in the last published digit
    assert n0.share_identical == pytest.approx(0.996, abs=0.02)
    assert n0.share_within == pytest.approx(1.0, abs=0.02)
    assert n0.max_rel_diff < 0.001
    assert n0.published_only == ("PRKACB",)


@pytest.mark.demo_data
def test_demo_bias_matches_published_linregpcr(demo_report):
    bias = demo_report.bias
    assert bias.genes == 62
    assert bias.median_abs_diff == pytest.approx(0.021, abs=0.01)
    assert bias.ours_mean == pytest.approx(0.961, abs=0.005)
    assert bias.published_mean == pytest.approx(0.947, abs=0.001)


@pytest.mark.demo_data
def test_demo_cq_offset_is_disclosed(demo_report):
    cq = demo_report.cq
    assert (cq.wells, cq.genes) == (945, 63)
    assert cq.mean_offset == pytest.approx(0.97, abs=0.05)
    assert cq.sd_offset == pytest.approx(0.175, abs=0.05)
    assert cq.min_offset > 0 and not math.isnan(cq.max_offset)


@pytest.mark.demo_data
def test_committed_table_is_what_the_script_generates(demo_report):
    """The table in the repo is generated, never typed: it must equal a fresh run."""
    assert (REPO / "validation" / "validation_table.md").read_text() == demo_report.to_markdown()
    assert (REPO / "validation" / "validation.json").read_text() == demo_report.to_json()


@pytest.mark.demo_data
def test_cli_validate_writes_both_files(demo_tables, tmp_path, capsys):
    assert main(["validate", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "930 standard wells" in out and "99.6 %" in out and "+0.97" in out
    assert json.loads((tmp_path / "validation.json").read_text())["n0"]["wells"] == 930
    assert "| Starting quantity N0" in (tmp_path / "validation_table.md").read_text()
