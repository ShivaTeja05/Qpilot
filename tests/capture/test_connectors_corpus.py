"""What qPilot reads from each set of the public instrument-export corpus.

Expectations come from each set's ``MANIFEST.yaml`` (controls, wells, cycles, signal) where it
states them; counts the manifest does not give (the vendor's Cq count of a plate, say) come from
reading the files by hand once and are marked so. A weakness that is known and not fixed here is
an ``xfail(strict=True)`` test that says what qPilot does instead, so fixing it fails the test
and the entry must be turned into a plain test.

Corpus: ``tests/fixtures/corpus/README.md``. Connectors: ``qpilot/io/connectors/``.
"""

from __future__ import annotations

from collections import Counter
from functools import cache
from pathlib import Path

import pytest
import yaml

from qpilot.io.connectors import Capture, CaptureError, capture, detect

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
NOT_DATA = {"MANIFEST.yaml", "truth.csv"}


def folder(slug: str) -> Path:
    return CORPUS / slug


def data_files(slug: str) -> list[Path]:
    return sorted(p for p in folder(slug).iterdir() if p.is_file() and p.name not in NOT_DATA)


def manifest(slug: str) -> dict:
    return yaml.safe_load((folder(slug) / "MANIFEST.yaml").read_text(encoding="utf-8"))


def manifest_file(slug: str, name: str) -> dict:
    return next(f for f in manifest(slug)["files"] if f["name"] == name)


@cache
def read(slug: str, *names: str) -> Capture:
    """The capture of a set (or of some of its files), read once per test session."""
    paths = [folder(slug) / n for n in names] if names else [folder(slug)]
    return capture(paths)


def plate(result: Capture, run_id: str):
    return next(p for p in result.meta.plates if p.run_id == run_id)


def reactions(result: Capture, run_id: str):
    return next(p for p in result.plates if p.run_id == run_id).reactions


def verdicts(result: Capture) -> dict[str, str]:
    return result.meta.rawness["plate_verdicts"]


# ---- every set: what detection says, file by file ---------------------------------------------

#: The connector each data file is read by, or None for files no connector reads (they are
#: skipped in a folder and named back by the Open route).
DETECTED = {
    "biorad/covmatic-cfx-maestro-4.0-simulated-4plex": {"*": "cfx"},
    "biorad/hsieh2016-cfx-manager-3.1-sybr": {
        "*": "cfx",
        "2016-09-04 gapdh -  End Point Results_SYBR.csv": None,
        "2016-09-04 gapdh -  Melt Curve Peak Results_0.csv": None,
    },
    "biorad/urtecho-cfx-tsv-baseline-subtracted": {"*": "cfx"},
    "roche/mendeley-diras2-lc480-raw-and-cp": {"*": "lightcycler480"},
    "roche/nomads-lc480-raw-isothermal-not-pcr": {"*": "lightcycler480"},
    "roche/sanger-lc480-cp-table": {"*": "lightcycler480"},
    "synthetic/cfx-manager-raw-vs-baseline-subtracted": {"*": "cfx"},
    "synthetic/quantstudio-design-analysis-rn-drn": {"*": "quantstudio"},
    "thermofisher/allotropy-quantstudio-rtpcr-txt": {"*": "quantstudio"},
    "thermofisher/opentrons-7500-design-analysis-csv": {"*": "quantstudio"},
    "thermofisher/securebio-qs3-design-analysis-2.7": {"*": "quantstudio"},
    "thermofisher/zamanian-stepone-plus-sybr-sections": {
        "*": "quantstudio",
        # per-filter raw counts and the melt-region tables are not read (yet)
        "raw_data.txt": None,
        "melt_region_derivative_data.txt": None,
        "melt_region_normalized_data.txt": None,
        "melt_region_temperature_data.txt": None,
    },
    "rdml/cfx-manager-3.0-rdml-1.1-nonstandard-member": {"*": "rdml"},
    "rdml/cfx-manager-3.0-rdml-1.2-rpa": {"*": "rdml"},
    "rdml/lightcycler96-lc96p-hmuy": {"*": "rdml", "hmuy_cq_values.xlsx": None},
    "rdml/lightcycler96-rdml-1.1": {"*": "rdml"},
    "rdml/linregpcr-rdml-1.3-lc480-kphaffii": {"*": "rdml"},
    "rdml/quantstudio7pro-rdml-1.2-edna": {"*": "rdml"},
    "rdml/rdml-1.2-cq-only-soybean": {"*": "rdml"},
    "rdml/stepone-2.3-rdml-1.0": {"*": "rdml"},
}


def test_every_corpus_set_is_listed_here():
    sets = {str(p.parent.relative_to(CORPUS)) for p in CORPUS.rglob("MANIFEST.yaml")}
    assert sets == set(DETECTED)


@pytest.mark.parametrize("slug", sorted(DETECTED))
def test_each_file_is_detected_by_its_connector_from_its_content(slug):
    expected = DETECTED[slug]
    for path in data_files(slug):
        want = expected.get(path.name, expected["*"])
        found = detect(path)
        got = found[0].connector_id if found else None
        assert got == want, (path.name, found)


# ---- Bio-Rad CFX -------------------------------------------------------------------------------

COVMATIC = "biorad/covmatic-cfx-maestro-4.0-simulated-4plex"


def test_covmatic_maestro_4plex_is_one_plate_of_four_fluorophores():
    result = read(COVMATIC)
    meta = result.meta
    assert meta.connector.id == "cfx"
    assert set(meta.dialect.split("+")) == {"cfx.amplification", "cfx.cq", "cfx.run_information"}
    assert len(meta.plates) == 1  # "multi-fluor grouping of one run stem into one plate"
    (p,) = meta.plates
    first = manifest_file(COVMATIC, data_files(COVMATIC)[0].name)
    assert (p.n_wells, p.n_cycles) == (first["wells"], first["cycles"]) == (96, 55)
    assert p.n_reactions == 4 * 96  # "4 fluors x 96 wells = 384 rows"
    assert sorted(p.dyes) == ["Cy5", "FAM", "HEX", "ROX"]
    assert len(p.targets) == 4
    # controls: Neg Ctrl and Pos Ctrl, one well per fluor; no NRT, no standards
    assert p.sample_types == {"ntc": 1, "pos": 1, "unkn": 94}
    types = {v.vendor: (v.mapped, v.unmapped) for v in p.vendor_types}
    assert types["negctrl"] == ("ntc", False) and types["posctrl"] == ("pos", False)
    assert not meta.layers.melt and meta.layers.cq and meta.value_kind == "RFU"
    assert {h.key for h in meta.header} >= {"instrument_serial", "software", "run_start"}


def test_covmatic_simulator_signal_is_not_called_raw():
    # manifest: signal "unknown (instrument simulator output)"
    assert verdicts(read(COVMATIC)) == {p.run_id: "unknown" for p in read(COVMATIC).meta.plates}


HSIEH = "biorad/hsieh2016-cfx-manager-3.1-sybr"
GAPDH, KDM6B, INHIBITION = (
    "2016-09-04 gapdh",
    "2016-09-04 kdm6b-ntcs",
    "admin_2016-09-04 16-12-03_CC011664",
)


def test_hsieh_three_cfx_manager_runs_are_three_plates():
    result = read(HSIEH)
    assert sorted(p.run_id for p in result.meta.plates) == sorted([GAPDH, KDM6B, INHIBITION])
    names = {s.name for s in result.meta.sources}
    assert "2016-09-04 gapdh -  End Point Results_SYBR.csv" not in names  # not read
    roles = {s.name: s.role for s in result.meta.sources}
    assert roles["2016-09-04 gapdh -  Melt Curve Derivative Results_SYBR.csv"] == "ignored"


def test_hsieh_plates_match_the_manifest():
    result = read(HSIEH)
    gapdh, kdm6b, inhibition = (plate(result, r) for r in (GAPDH, KDM6B, INHIBITION))
    # gapdh: 96 wells all typed Unkn, 40 cycles, melt
    assert (gapdh.n_wells, gapdh.n_cycles, gapdh.sample_types) == (96, 40, {"unkn": 96})
    assert gapdh.n_with_melt == 96
    # kdm6b-ntcs: 96 wells typed Unkn, 38 wells with no Cq, no melt file
    assert (kdm6b.n_wells, kdm6b.sample_types) == (96, {"unkn": 96})
    assert kdm6b.n_with_vendor_cq == 96 - 38 and kdm6b.n_with_melt == 0
    # inhibition_check: 17 wells, 3 typed NTC (Cq 36.3, 35.9, none) + 14 dilution wells
    assert (inhibition.n_wells, inhibition.sample_types) == (17, {"ntc": 3, "unkn": 14})
    ntc_cq = sorted(r.cq or 0 for r in reactions(result, INHIBITION) if r.sample_type == "ntc")
    assert ntc_cq[0] == 0 and [round(c, 1) for c in ntc_cq[1:]] == [35.9, 36.3]
    assert inhibition.n_with_vendor_cq == 16  # by hand: the 14 dilution wells all have a Cq
    melt = [r.melt for r in reactions(result, INHIBITION) if r.melt is not None]
    assert len(melt) == 17 and {len(m.x) for m in melt} == {61}  # 61 temperatures
    # no sample or target names in these exports: targets are named after the fluorophore
    assert {t for p in result.meta.plates for t in p.targets} == {"SYBR"}


def test_hsieh_baseline_subtracted_curves_are_not_called_raw():
    # "amplification is CFX's default baseline-subtracted curve-fit signal ... the raw-ness
    # detector must NOT call it raw"
    result = read(HSIEH)
    assert set(verdicts(result).values()) == {"baseline_subtracted"}
    assert result.meta.rawness["linregpcr_ok"] is False
    assert "CURVES_NOT_RAW" in {w.code for w in result.meta.warnings}


URTECHO = "biorad/urtecho-cfx-tsv-baseline-subtracted"


def test_urtecho_tab_separated_amplification_sheet_alone():
    result = read(URTECHO)
    (p,) = result.meta.plates
    (name,) = (f.name for f in data_files(URTECHO))
    facts = manifest_file(URTECHO, name)
    assert p.n_cycles == facts["cycles"] == 15
    # 96 well columns; F6 is NaN on every cycle, so it is not a reaction
    assert facts["wells"] == 96 and p.n_wells == 95
    assert "F6" not in {r.well for r in reactions(result, p.run_id)}
    assert p.n_with_vendor_cq == 0 and not result.meta.layers.sample_types
    codes = {w.code for w in result.meta.warnings}
    assert {"READER_NOTE", "NO_SAMPLE_TYPES"} <= codes
    assert verdicts(result)[p.run_id] != "raw"


@pytest.mark.xfail(
    strict=True,
    reason="15-cycle library-quantification run: the ground phase is too short for many wells, "
    "so the detector says 'unknown' (mixed) where the manifest says baseline_subtracted",
)
def test_urtecho_is_called_baseline_subtracted():
    assert set(verdicts(read(URTECHO)).values()) == {"baseline_subtracted"}


SYNTH_CFX = "synthetic/cfx-manager-raw-vs-baseline-subtracted"


def test_synthetic_cfx_raw_and_baselined_stems_stay_two_plates_with_known_verdicts():
    result = read(SYNTH_CFX)
    assert verdicts(result) == {
        "qpilot-synthetic-raw": "raw",
        "qpilot-synthetic-baselined": "baseline_subtracted",
    }
    assert result.meta.rawness["plate_linregpcr_ok"] == {
        "qpilot-synthetic-raw": True,
        "qpilot-synthetic-baselined": False,
    }
    for p in result.meta.plates:
        # 2 targets x 8 samples x 3 reps + 5 standards x 2 + 3 NTC + 3 NRT per target
        assert (p.n_wells, p.n_cycles) == (80, 40)
        assert p.sample_types == {"unkn": 48, "std": 20, "ntc": 6, "nrt": 6}
        assert p.targets == ["REF", "GOI"] and p.dyes == ["SYBR"]


# ---- Thermo Fisher QuantStudio family ----------------------------------------------------------

SYNTH_QS = "synthetic/quantstudio-design-analysis-rn-drn"


def test_synthetic_quantstudio_rn_is_normalized():
    result = read(SYNTH_QS)
    (p,) = result.meta.plates
    assert result.meta.value_kind == "Rn" and verdicts(result) == {p.run_id: "normalized"}
    assert result.meta.rawness["linregpcr_ok"] is True
    # NRT wells use Task NTC (QuantStudio has no NRT task): 3 NTC + 3 NRT per target
    assert p.sample_types == {"unkn": 48, "std": 20, "ntc": 12}
    assert (p.n_wells, p.n_cycles) == (80, 40)
    keys = {h.key for h in result.meta.header}
    assert {"block_type", "instrument_type", "passive_reference", "software"} <= keys


def test_synthetic_quantstudio_drn_only_is_baseline_subtracted(tmp_path):
    """The same export without its Rn column: Delta Rn is baseline-subtracted."""
    source = folder(SYNTH_QS) / "qpilot-synthetic_Amplification Data.csv"
    lines = source.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line.startswith("#"):
            out.append(line)
            continue
        cells = line.split(",")
        out.append(",".join(c for i, c in enumerate(cells) if i != 4))  # drop "Rn"
    assert '"Rn"' in lines[[i for i, x in enumerate(lines) if not x.startswith("#")][0]]
    target = tmp_path / source.name
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    (tmp_path / "qpilot-synthetic_Results.csv").write_bytes(
        (folder(SYNTH_QS) / "qpilot-synthetic_Results.csv").read_bytes()
    )
    result = capture(tmp_path)
    assert result.meta.value_kind == "dRn"
    assert set(verdicts(result).values()) == {"baseline_subtracted"}
    assert any("Delta Rn" in w.message for w in result.meta.warnings)


SECUREBIO = "thermofisher/securebio-qs3-design-analysis-2.7"


def test_securebio_design_analysis_two_exports_are_two_plates():
    result = read(SECUREBIO)
    assert sorted(p.run_id for p in result.meta.plates) == [
        "2023-11-14_Cov2_Copy",
        "2023-11-14_PMMoV_VIC",
    ]
    for p in result.meta.plates:
        # 93 wells, 40 cycles; 2 NTCs (UNDETERMINED); 5-point standard curve in triplicate
        assert (p.n_wells, p.n_cycles, p.rows, p.columns) == (93, 40, 8, 12)
        assert p.sample_types == {"ntc": 2, "std": 15, "unkn": 76}
        ntc_cq = [r.cq for r in reactions(result, p.run_id) if r.sample_type == "ntc"]
        assert ntc_cq == [None, None]
    assert plate(result, "2023-11-14_Cov2_Copy").targets == ["Cov2"]
    assert plate(result, "2023-11-14_PMMoV_VIC").dyes == ["VIC"]
    assert not result.meta.layers.quantities  # "quantities not in the Results file"
    assert set(verdicts(result).values()) == {"normalized"}  # Rn (normalised to ROX)
    keys = {h.key for h in result.meta.header}
    assert {"passive_reference", "block_type", "instrument_serial", "software", "run_end"} <= keys


OPENTRONS = "thermofisher/opentrons-7500-design-analysis-csv"


def test_opentrons_7500_multiplex_wells_and_tasks():
    result = read(OPENTRONS)
    (p,) = result.meta.plates
    # 51 wells with data, 77 well-target rows, 50 cycles
    assert (p.n_wells, p.n_reactions, p.n_cycles) == (51, 77, 50)
    assert sorted(p.targets) == ["Endo", "IEC", "nCoV"]
    tasks = Counter(r.vendor_type for r in reactions(result, p.run_id))
    assert tasks["NTC"] == 3 and tasks["IPC"] == 1  # Task NTC (3 rows), IPC (1 row)
    ipc = next(v for v in p.vendor_types if v.vendor == "ipc")
    assert (ipc.mapped, ipc.unmapped) == ("unkn", True)  # IPC -> unkn + flag


def test_opentrons_rn_without_a_passive_reference_is_not_called_normalized():
    # "NEGATIVE Rn values (no passive reference ...). A raw-ness trap: do not call this Rn
    # 'normalized'."
    result = read(OPENTRONS)
    assert result.meta.value_kind == "fluorescence"
    assert set(verdicts(result).values()) != {"normalized"}
    assert any("no passive reference" in w.message for w in result.meta.warnings)


ZAMANIAN = "thermofisher/zamanian-stepone-plus-sybr-sections"


def test_zamanian_stepone_section_files_are_one_plate():
    result = read(ZAMANIAN)
    assert result.meta.connector.id == "quantstudio"
    (p,) = result.meta.plates
    # "3 targets x 18 unknown wells + 1 NTC per target" = 57 wells (the manifest's "58 wells
    # used" does not add up to its own composition); "2 NTC wells Undetermined"
    assert sorted(p.targets) == ["GAPDH", "OSM-9", "TAX-4"]
    assert (p.n_wells, p.n_reactions, p.n_cycles) == (57, 57, 40)
    assert p.sample_types == {"ntc": 3, "unkn": 54}
    assert p.n_with_vendor_cq == 57 - 2
    assert {s.role for s in result.meta.sources} == {"plate"}
    assert verdicts(result) == {p.run_id: "normalized"}  # Rn = normalized


ALLOTROPY = "thermofisher/allotropy-quantstudio-rtpcr-txt"


def test_allotropy_quantstudio_text_headers_and_sections():
    """Truncated parser fixtures: headers and sections only, never numbers."""
    ex01 = read(ALLOTROPY, "appbio_quantstudio_example01.txt").meta
    keys = {h.key for h in ex01.header}
    assert {"calibration_background_is_expired", "instrument_serial", "block_type"} <= keys
    assert (ex01.plates[0].rows, ex01.plates[0].columns) == (16, 24)  # ViiA 7, 384-well
    ex02 = read(ALLOTROPY, "appbio_quantstudio_example02.txt").meta.plates[0]
    assert any(v.vendor == "ipc" and v.unmapped for v in ex02.vendor_types)
    assert any(v.vendor == "ntc" and v.mapped == "ntc" for v in ex02.vendor_types)  # Task NTC
    ex04 = read(ALLOTROPY, "appbio_quantstudio_example04.txt")
    p04 = ex04.meta.plates[0]
    assert p04.sample_types["std"] > 0 and ex04.meta.layers.quantities
    assert all(
        r.quantity is not None for r in reactions(ex04, p04.run_id) if r.sample_type == "std"
    )
    only = read(ALLOTROPY, "example_quantsudio_results_only.txt")
    assert only.meta.plates[0].n_wells == 24  # "24 wells; Cq-only table"
    assert set(verdicts(only).values()) == {"cq_only"}
    assert "CQ_ONLY" in {w.code for w in only.meta.warnings}


# ---- Roche LightCycler 480 ---------------------------------------------------------------------

MENDELEY = "roche/mendeley-diras2-lc480-raw-and-cp"


def test_mendeley_raw_data_and_cp_table_join_into_one_plate():
    result = read(MENDELEY)
    (p,) = result.meta.plates
    raw = manifest_file(MENDELEY, "CP1.txt")
    assert (p.n_wells, p.n_cycles) == (raw["wells"], raw["cycles"]) == (384, 45)
    assert (p.rows, p.columns) == (16, 24)
    assert p.n_with_vendor_cq == 384 - 6  # "6 wells without Cp"
    assert p.n_with_amplification == 384
    assert p.targets == ["465-510"]
    names = {q.value for q in result.meta.quarantine if q.origin.endswith(":sample")}
    assert names == {"AAV2_1", "AAV4_1", "Scr_1", "Unb_1"}  # 4 samples x 96 assays
    assert verdicts(result) == {p.run_id: "raw"}  # "LC480 raw export is not baseline-corrected"
    cp = [r.cq for r in reactions(result, p.run_id) if r.well == "A1"]
    assert cp == [33.59]  # decimal comma "33,59"


SANGER = "roche/sanger-lc480-cp-table"


def test_sanger_cp_table_standards_and_excluded_wells():
    result = read(SANGER)
    (p,) = result.meta.plates
    assert result.meta.connector.id == "lightcycler480"
    assert p.n_wells == 384 and p.n_cycles == 0
    # 21 standard wells (Standard column > 0), 5 excluded wells (Include FALSE, no Cp)
    assert p.sample_types["std"] == 21
    assert len(p.vendor_omitted) == 5
    rows = reactions(result, p.run_id)
    assert all(r.cq is None for r in rows if r.omitted)
    quantities = {r.quantity for r in rows if r.sample_type == "std"}
    assert min(quantities) == 0.0002 and max(quantities) == 200  # 0.0002-200 pM
    assert all(r.quantity is None for r in rows if r.sample_type != "std")
    assert "QUANTITY_CONFLICT" not in {w.code for w in result.meta.warnings}
    assert set(verdicts(result).values()) == {"cq_only"}


NOMADS = "roche/nomads-lc480-raw-isothermal-not-pcr"


def test_nomads_isothermal_plate_read_is_refused_in_words():
    # not_pcr: "a reader must not treat it as an amplification run"
    assert manifest(NOMADS)["not_pcr"] is True
    with pytest.raises(CaptureError) as err:
        read(NOMADS)
    message = str(err.value)
    assert "not a PCR run" in message and "37 °C" in message


# ---- RDML files (used as they are) -------------------------------------------------------------

RPA = "rdml/cfx-manager-3.0-rdml-1.2-rpa"


def test_rpa_rdml_from_cfx_manager():
    result = read(RPA)
    assert result.xml is None and result.meta.connector.id == "rdml"  # used as it is
    (p,) = result.meta.plates
    # "1 run, 90 reactions, 61 cycles, melt 61 points, 88 Cq", 10 targets
    assert (p.n_reactions, p.n_cycles, p.n_with_vendor_cq, len(p.targets)) == (90, 61, 88, 10)
    assert p.n_with_melt == 90
    assert {len(r.melt.x) for r in reactions(result, p.run_id)} == {61}
    assert verdicts(result) == {p.run_id: "baseline_subtracted"}  # first cycles ~0-15 RFU


def test_lightcycler96_rdml_four_dyes_and_standards():
    result = read("rdml/lightcycler96-rdml-1.1")
    (p,) = result.meta.plates
    # 96 reacts x 4 data (384 curves), 50 cycles; sample types std, unkn, ntp
    assert (p.n_wells, p.n_reactions, p.n_cycles) == (96, 384, 50)
    assert sorted(p.dyes) == ["Cy5", "FAM", "Hex", "Texas Red"]
    assert set(p.sample_types) == {"std", "unkn", "ntp"}


def test_lc96p_experiment_file_alone_is_rdml():
    result = read("rdml/lightcycler96-lc96p-hmuy", "hmuy_hm_vs_dip_r123.lc96p")
    (p,) = result.meta.plates
    # 96 wells: 36 positive wells (2 targets x 6 samples x 3), 60 without target (type ntp)
    assert (p.n_wells, p.n_cycles) == (96, 35)
    assert p.sample_types == {"unkn": 36, "ntp": 60}
    assert p.n_with_melt == 96


def test_quantstudio7pro_rdml_plates_one_at_a_time():
    slug = "rdml/quantstudio7pro-rdml-1.2-edna"
    plate1 = read(slug, "SupplementaryMaterials2_qPCR_Plate1.rdml")
    (p,) = plate1.meta.plates
    assert (p.n_wells, p.n_reactions) == (96, 192)  # 96 reacts x 2 dyes
    assert set(p.sample_types) == {"unkn", "ntc", "pos"}
    standards = read(slug, "SupplementaryMaterials2_qPCR_ConcentrationStandardCurve.rdml")
    assert standards.meta.plates[0].sample_types.get("std", 0) > 0
    assert standards.meta.layers.quantities
    # an Rn-like signal (~0.4) in an RDML file carries no column name: judged by its curves
    for result in (plate1, standards):
        assert result.meta.rawness["linregpcr_ok"] is True


# ---- refusals, in plain words ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "words"),
    [
        ("rdml/quantstudio7pro-rdml-1.2-edna", "one RDML file at a time"),
        ("rdml/cfx-manager-3.0-rdml-1.1-nonstandard-member", "no rdml_data.xml"),
        ("rdml/rdml-1.2-cq-only-soybean", "no rdml_data.xml"),
        ("rdml/stepone-2.3-rdml-1.0", "fails the RDML schema"),
        ("rdml/linregpcr-rdml-1.3-lc480-kphaffii", "fails the RDML schema"),
    ],
)
def test_unreadable_or_mixed_input_is_refused_in_words(slug, words):
    with pytest.raises(CaptureError) as err:
        capture(folder(slug))
    message = str(err.value)
    assert words in message
    assert "Traceback" not in message and "\n" not in message


def test_a_mix_of_vendors_is_refused_in_words():
    cfx = data_files(SYNTH_CFX)[0]
    qs = data_files(SYNTH_QS)[0]
    with pytest.raises(CaptureError, match="import one kind of export at a time") as err:
        capture([cfx, qs])
    assert qs.name in str(err.value) and "Bio-Rad" in str(err.value)


def test_lc96p_folder_reads_the_experiment_and_leaves_the_depositors_sheet():
    """The depositors' Cq table names a condition per sample: a sample sheet, not an export."""
    result = capture(folder("rdml/lightcycler96-lc96p-hmuy"))
    assert [s.name for s in result.meta.sources] == ["hmuy_hm_vs_dip_r123.lc96p"]


@pytest.mark.parametrize(
    "slug",
    [
        "rdml/cfx-manager-3.0-rdml-1.1-nonstandard-member",
        "rdml/rdml-1.2-cq-only-soybean",
    ],
)
@pytest.mark.xfail(
    strict=True,
    reason="rdml_io.load reads only an archive member named rdml_data.xml; these archives hold "
    "one XML member under another name (CFX Manager 3.0; a figshare deposit)",
)
def test_rdml_archives_with_another_member_name_are_read(slug):
    assert capture(folder(slug)).meta.plates


@pytest.mark.parametrize(
    "slug", ["rdml/stepone-2.3-rdml-1.0", "rdml/linregpcr-rdml-1.3-lc480-kphaffii"]
)
@pytest.mark.xfail(
    strict=True,
    reason="rdml_io.load validates against the RDML schema: StepOne 2.3's RDML 1.0 and "
    "LinRegPCR's RDML 1.3 put elements out of schema order (dye; Ncopy) and are refused",
)
def test_rdml_files_out_of_schema_order_are_read(slug):
    assert capture(folder(slug)).meta.plates
