"""Multiplex wells on real lab files: every dye's curve gets its own LinRegPCR analysis and N0.

LinRegPCR, as vendored, gives each reaction's volume only to the first curve of a well, so on a
multiplex plate every other dye's N0 came out as 0 (``undetermined``): the HEX/VIC reference of a
TaqMan duplex was lost to relative quantification. qPilot analyses each dye of a multiplex plate on
its own (``curves.channels``); these tests pin what that gives on the corpus's multiplex files:
LightCycler 96 (FAM/Hex/Texas Red/Cy5), QuantStudio 7 Pro (BRK2 + IPC), CFX Maestro 4-plex and a
7500 duplex export.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from lxml import etree

from qpilot.io.connectors.registry import materialise
from qpilot.io.rdml_io import NS, load, runs
from qpilot.qpcr import curves
from qpilot.qpcr import multiplex as mx

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
LC96 = CORPUS / "rdml" / "lightcycler96-rdml-1.1" / "lc96_bACTXY.rdml"
QS7 = CORPUS / "rdml" / "quantstudio7pro-rdml-1.2-edna"
QS7_PLATE = QS7 / "SupplementaryMaterials2_qPCR_Plate1.rdml"
QS7_STD = QS7 / "SupplementaryMaterials2_qPCR_ConcentrationStandardCurve.rdml"
CFX = CORPUS / "biorad" / "covmatic-cfx-maestro-4.0-simulated-4plex"
QS7500 = CORPUS / "thermofisher" / "opentrons-7500-design-analysis-csv"
SINGLEPLEX = CORPUS / "rdml" / "cfx-manager-3.0-rdml-1.2-rpa" / "rpa.rdml"

#: Per target: (curves, with a Cq, with an N0). Before the fix only the first dye of each well had
#: an N0 (LC96: bACT 16, IPC/X/Y 0; QS7: BRK2 79, IPC 0; CFX: E_covid 96, the rest 0; 7500: IEC
#: 15, nCoV 0).
EXPECTED = {
    "lc96": {"bACT": (16, 16, 16), "X": (16, 12, 12), "Y": (16, 12, 12), "IPC": (16, 14, 14)},
    "qs7_plate": {"BRK2": (96, 79, 79), "IPC": (96, 95, 95)},
    "qs7_std": {"BRK2": (42, 34, 34), "IPC": (42, 40, 40)},
    "cfx": {
        "E_covid": (96, 96, 96),
        "IEC": (96, 96, 96),
        "N_covid": (96, 96, 96),
        "ORF1ab_covid": (96, 96, 0),  # simulated: no target efficiency, so no N0 (as singleplex)
    },
    "7500": {"Endo": (25, 25, 25), "IEC": (26, 15, 15), "nCoV": (26, 21, 21)},
}


def _rdml(name: str, cache: Path) -> Path:
    if name == "lc96":
        return LC96
    if name == "qs7_plate":
        return QS7_PLATE
    if name == "qs7_std":
        return QS7_STD
    folder = CFX if name == "cfx" else QS7500
    return materialise([folder], cache_dir=cache).rdml_path


def _experiment(path: Path) -> str:
    return str(load(path).experiments()[0]["id"])


@pytest.fixture
def cache(tmp_path) -> Path:
    return tmp_path / "cache"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_dye_of_a_multiplex_well_gets_its_cq_and_n0(name, cache):
    path = _rdml(name, cache)
    table = curves.analyse_study(path, _experiment(path), (), cache_dir=cache)
    table = table[~table["target"].str.startswith("no target")]
    got = {
        target: (len(rows), int(rows["cq"].notna().sum()), int(rows["n0"].notna().sum()))
        for target, rows in table.groupby("target")
    }
    assert got == EXPECTED[name]
    # every curve with a Cq and a target efficiency has a starting quantity, whatever its dye
    usable = table["cq"].notna() & (table["eff_target"] > 0)
    assert table["n0"].notna().equals(usable)
    assert mx.is_multiplex(table)


def test_the_vendored_linregpcr_still_gives_the_other_dyes_no_volume():
    """Why qPilot analyses one dye at a time: called on the whole plate, LinRegPCR gives each
    reaction's volume to the first curve of the well only. If an upstream update fixes this, this
    test fails and the per-dye analysis can be compared with the whole-plate one again."""
    run = runs(load(LC96))[0]
    table = curves._linregpcr(run, "lc96", curves.CurveSettings())
    first = table.groupby("id", sort=False).head(1).index
    vol = pd.to_numeric(table["vol"])
    assert (vol.loc[first] > 0).all()
    assert (vol.drop(index=first) == 0).all()


def test_each_dye_is_analysed_as_on_a_plate_of_that_dye_alone():
    doc = load(LC96)
    experiment = _experiment(LC96)
    table = curves.analyse_study(doc, experiment, ())
    dyes = curves.target_dyes(doc._node)
    for dye in ("FAM", "Hex", "Texas Red", "Cy5"):
        alone = load(LC96)
        for react in alone._node.iter(NS + "react"):
            for data in react.findall(NS + "data"):
                if dyes[data.find(NS + "tar").get("id")] != dye:
                    react.remove(data)
        one = curves.analyse_study(alone, experiment, ())
        assert set(one.groupby(["run_id", "well"])["target"].nunique()) == {1}  # singleplex
        mine = table[table["target"].map(dyes) == dye].reset_index(drop=True)
        pd.testing.assert_frame_equal(mine, one.reset_index(drop=True), check_exact=True)


def test_rows_keep_the_files_order_and_the_callers_document_is_unchanged():
    doc = load(LC96)
    before = etree.tostring(doc._node)
    run = runs(doc)[0]
    table = curves.analyse_run(run)
    assert etree.tostring(doc._node) == before
    order = [
        (str(react.get("id")), data.find(NS + "tar").get("id"))
        for react in run._node.findall(NS + "react")
        for data in react.findall(NS + "data")
    ]
    wells = [curves.react_well_label(i, 12) for i, _ in order]
    assert list(zip(table["well"], table["target_raw"], strict=True)) == [
        (w, t) for w, (_, t) in zip(wells, order, strict=True)
    ]
    assert curves.channels(run) == [
        frozenset({"no target (FAM)", "bACT"}),
        frozenset({"no target (Hex)", "X"}),
        frozenset({"no target (Texas Red)", "Y"}),
        frozenset({"no target (Cy5)", "IPC"}),
    ]


def test_a_singleplex_plate_is_analysed_as_one_plate_as_before():
    doc = load(SINGLEPLEX)
    for run in runs(doc):
        assert curves.channels(run) is None
        direct = curves._linregpcr(run, "r", curves.CurveSettings())
        direct = direct[list(curves.RESULT_COLUMNS)].rename(columns=curves.RESULT_COLUMNS)
        mine = curves.analyse_run(run).drop(columns="run_id")
        pd.testing.assert_frame_equal(mine, direct, check_exact=True)


def test_two_targets_declared_in_one_dye_in_one_well_are_split_by_target():
    doc = load(LC96)
    for target in doc._node.findall(NS + "target"):
        if target.get("id") == "X":
            target.find(NS + "dyeId").set("id", "FAM")  # X now shares bACT's dye
    run = runs(doc)[0]
    groups = curves.channels(run)
    assert frozenset({"bACT"}) in groups and frozenset({"X"}) in groups
    table = curves.analyse_run(run)
    assert table.groupby("target_raw")["n0"].apply(lambda s: (s != "").sum())["X"] > 0


def test_a_multiplex_table_is_cached_under_its_own_key(cache, monkeypatch):
    experiment = _experiment(LC96)
    first = curves.analyse_study(LC96, experiment, (), cache_dir=cache)
    key = (curves.file_sha256(LC96), experiment, (), curves.CurveSettings(), cache)
    names = curves.names_key(LC96)
    multiplex = curves.cache_path(*key, names, multiplex=True)
    plain = curves.cache_path(*key, names)
    assert multiplex.exists() and not plain.exists()
    assert multiplex != plain

    def no_analysis(*args, **kwargs):
        raise AssertionError("the cached table should have been read")

    monkeypatch.setattr(curves, "analyse_run", no_analysis)
    again = curves.analyse_study(LC96, experiment, (), cache_dir=cache)
    pd.testing.assert_frame_equal(again, first, check_exact=True)


def test_a_multiplex_table_cached_before_the_fix_is_analysed_again(cache):
    experiment = _experiment(LC96)
    fresh = curves.analyse_study(LC96, experiment, (), use_cache=False)
    stale = fresh.copy()
    stale.loc[stale["target"] != "bACT", "n0"] = np.nan  # what the whole-plate analysis gave
    key = (curves.file_sha256(LC96), experiment, (), curves.CurveSettings(), cache)
    plain = curves.cache_path(*key, curves.names_key(LC96))
    curves._write_cache(stale, plain)
    table = curves.analyse_study(LC96, experiment, (), cache_dir=cache)
    pd.testing.assert_frame_equal(table, fresh, check_exact=True)


def test_internal_positive_controls_are_named_and_share_wells():
    for name in ("IPC", "ipc2", "Exo IPC", "IAC", "Internal Positive Control", "TaqMan Exo IPC"):
        assert mx.is_internal_control_name(name), name
    for name in ("IEC", "bACT", "RIPC", "IPCx", "no target (Cy5)", "HIPC1"):
        assert not mx.is_internal_control_name(name), name
    plate = curves.analyse_study(QS7_PLATE, "Experiment 1", ())
    assert mx.internal_controls(plate) == ["IPC"]
    assert len(mx.multiplex_keys(plate)) == 96
    # an IPC measured in wells of its own is not an internal control of anything
    alone = plate[plate["target"] == "IPC"]
    assert mx.internal_controls(alone) == []


def test_pairing_with_the_same_wells_reference_differs_only_where_one_dye_has_no_value():
    table = curves.analyse_study(LC96, _experiment(LC96), ())
    # the six unknowns, one well each: X and Y did not amplify in four of them, so those units
    # have no X or Y value at all, paired or not
    assert mx.pairing_gaps(table, ["bACT"]).empty
    # the standards, in duplicate wells, read as study units: every dye has a value in both wells
    duplicates = table[table["sample_type"] == "std"].assign(sample_type="unkn")
    duplicates = duplicates[duplicates["target"].isin(["bACT", "X", "Y"])]
    assert mx.pairing_gaps(duplicates, ["bACT"]).empty
    # X without a value in one well of Sample 39: qPilot's X mean is over D3, bACT's over D3 and
    # D4, while pairing would use D3 alone; leaving the whole well out pairs them again
    gap = duplicates.copy()
    gap.loc[(gap["well"] == "D4") & (gap["target"] == "X"), "n0"] = np.nan
    found = mx.pairing_gaps(gap, ["bACT"])
    assert found.to_dict("records") == [
        {"unit": "Sample 39", "target": "X", "ref": "bACT", "n_wells": 2, "n_unpaired": 1}
    ]
    d4 = set(mx.well_keys(gap[gap["well"] == "D4"]))
    assert mx.pairing_gaps(gap, ["bACT"], excluded=d4).empty
