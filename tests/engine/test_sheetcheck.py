"""Spreadsheet Check: a lab's own ΔΔCq sheet, recomputed; the first column that differs, named.

Every sheet is generated in ``tmp_path`` (none is committed). The synthetic sheets run in CI;
the ``demo_data`` sheets are built from the Vermeulen demo's real Cq values with the engine's
own MYCN-high versus rest groups. The textbook values the sheets carry are computed here, with
plain numpy, independently of the module under test.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from qpilot.core.validator import validate
from qpilot.explain import sheetcheck_text as text
from qpilot.explain.templates import TemplateError
from qpilot.qpcr import sheetcheck as sc
from qpilot.qpcr.sheetcheck import (
    MAPPING_CONFIRMED,
    MAPPING_GUESSED,
    PATHS,
    Anchors,
    Chain,
    ColumnMapping,
    SheetCheckError,
    check_sheet,
    guess_mapping,
    livak_per_unit,
    row_shift,
    wells_as_n,
)
from qpilot.schemas import ContrastResult

BANNED = ("diagnos", "root cause", "error found", "validated", "valid run", "detects inhibition")


# ---------------------------------------------------------------------------------------------
# A small study and its textbook values (independent of the module)
# ---------------------------------------------------------------------------------------------


@dataclass
class Study:
    units: list[str]
    groups: list[str]
    cq: dict[str, np.ndarray]
    refs: tuple[str, ...]
    control: str
    targets: tuple[str, ...]


def synthetic(seed=7, n=4, shift=2.0, refs=("GAPDH", "ACTB"), targets=("MYC",)) -> Study:
    rng = np.random.default_rng(seed)
    units = [f"mouse-c{i}" for i in range(1, n + 1)] + [f"mouse-t{i}" for i in range(1, n + 1)]
    groups = ["vehicle"] * n + ["drug"] * n
    cq = {}
    for k, ref in enumerate(refs):
        cq[ref] = np.round(18 + k + rng.normal(0, 0.3, 2 * n), 2)
    for k, gene in enumerate(targets):
        values = 26 + k + rng.normal(0, 0.5, 2 * n)
        values[n:] -= shift
        cq[gene] = np.round(values, 2)
    return Study(units, groups, cq, tuple(refs), "vehicle", tuple(targets))


def textbook(study: Study, gene: str, refs=None):
    """ΔCq, ΔΔCq and fold change per unit, plus the control mask."""
    refs = refs or study.refs
    nf = np.mean([study.cq[r] for r in refs], axis=0)
    dcq = study.cq[gene] - nf
    ctrl = np.array([g == study.control for g in study.groups])
    ddcq = dcq - np.nanmean(dcq[ctrl])
    return dcq, ddcq, 2.0**-ddcq, ctrl


def geo(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(2 ** np.mean(np.log2(values)))


def fmt(value, decimals=4) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return ""
    if isinstance(value, str):
        return value
    return f"{value:.{decimals}f}"


def wide_table(study: Study, columns: dict, summaries: dict | None = None, *, cq_header="{} Cq"):
    """Header and rows of a wide sheet: one row per unit, then each group's summary rows."""
    header = ["Sample", "Group", *[cq_header.format(g) for g in study.refs + study.targets]]
    header += list(columns)
    rows = []
    for group in dict.fromkeys(study.groups):
        for i, (unit, g) in enumerate(zip(study.units, study.groups, strict=True)):
            if g != group:
                continue
            row = [unit, g] + [fmt(study.cq[x][i], 2) for x in study.refs + study.targets]
            row += [fmt(values[i]) for values in columns.values()]
            rows.append(row)
        for label, cells in (summaries or {}).get(group, []):
            row = [label] + [""] * (len(header) - 1)
            for name, value in cells.items():
                row[header.index(name)] = fmt(value, 6)
            rows.append(row)
    return header, rows


def write_csv(path: Path, header, rows) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def write_xlsx(path: Path, header, rows) -> Path:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(header)
    for row in rows:
        sheet.append([_typed(v) for v in row])
    book.save(path)
    return path


def _typed(value):
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            return value
    return value if value != "" else None


def clean_columns(study: Study, gene="MYC"):
    dcq, ddcq, fc, _ = textbook(study, gene)
    return {f"ΔCq {gene}": dcq, f"ΔΔCq {gene}": ddcq, f"Fold change {gene}": fc}


def summary_rows(study: Study, fc_by_group: dict, p: float, column="Fold change MYC"):
    out = {g: [("Mean", {column: fc_by_group[g]})] for g in fc_by_group}
    out["drug"].append(("p-value", {column: p}))
    return out


def textbook_summaries(study: Study, gene="MYC"):
    dcq, ddcq, fc, ctrl = textbook(study, gene)
    means = {"vehicle": geo(fc[ctrl]), "drug": geo(fc[~ctrl])}
    p = stats.ttest_ind(dcq[~ctrl], dcq[ctrl], equal_var=True).pvalue
    return summary_rows(study, means, p, f"Fold change {gene}")


def clean_sheet(tmp_path: Path, study: Study | None = None, name="clean.csv") -> Path:
    study = study or synthetic()
    header, rows = wide_table(study, clean_columns(study), textbook_summaries(study))
    return write_csv(tmp_path / name, header, rows)


def first(result):
    assert result.localisation, "expected a difference"
    return next(f for f in result.findings if f.id == result.localisation[0].finding)


# ---------------------------------------------------------------------------------------------
# (a) synthetic sheets
# ---------------------------------------------------------------------------------------------


def test_clean_livak_sheet_has_no_findings(tmp_path):
    result = check_sheet(clean_sheet(tmp_path))
    assert result.findings == [] and result.localisation == []
    s = result.summary
    assert (s.n_fold_changes, s.n_reproduced, s.n_differ) == (10, 10, 0)  # 8 units + 2 means
    assert s.n_columns_checked == s.n_columns_reproduced == 6  # ΔCq ΔΔCq FC, 2 means, p
    assert {c.status for c in result.columns} == {"reproduced"}
    assert next(c for c in result.columns if c.step == "p").variant == "student"
    assert result.mapping_status == MAPPING_GUESSED == s.mapping
    assert [g.control for g in result.groups] == [True, False]


def test_the_guess_maps_every_column(tmp_path):
    mapping = guess_mapping(clean_sheet(tmp_path))
    roles = {c.column: (c.role, c.gene) for c in mapping.columns}
    assert roles == {
        "A": ("sample", None),
        "B": ("group", None),
        "C": ("cq", "GAPDH"),
        "D": ("cq", "ACTB"),
        "E": ("cq", "MYC"),
        "F": ("dcq", "MYC"),
        "G": ("ddcq", "MYC"),
        "H": ("fc", "MYC"),
    }
    assert mapping.layout == "wide" and mapping.references == ["GAPDH", "ACTB"]
    assert not mapping.confirmed and mapping.control_text_id is not None
    assert all(0 < c.confidence <= 1 for c in mapping.columns)


def test_clean_workbook_with_full_precision_values(tmp_path):
    study = synthetic()
    header, rows = wide_table(study, clean_columns(study), textbook_summaries(study))
    # a workbook keeps the exact numbers its formulas used: write them unrounded
    dcq, ddcq, fc, ctrl = textbook(study, "MYC")
    for row in rows:
        if row[0].startswith("mouse"):
            i = study.units.index(row[0])
            row[5:8] = [repr(float(dcq[i])), repr(float(ddcq[i])), repr(float(fc[i]))]
    result = check_sheet(write_xlsx(tmp_path / "clean.xlsx", header, rows))
    assert result.file_kind == "xlsx"
    assert result.findings == [] and result.summary.n_reproduced == 10


def _slip_sheets(study: Study):
    """Sheet columns and summaries for every wrong path: name -> (columns, summaries, kwargs)."""
    dcq, ddcq, fc, ctrl = textbook(study, "MYC")
    good = clean_columns(study)
    sums = textbook_summaries(study)
    out = {}
    out["sign_inverted"] = ({**good, "Fold change MYC": 2.0**ddcq}, None, {})
    out["exponent_twice"] = ({**good, "Fold change MYC": 2.0**fc}, None, {})
    raw = study.cq["MYC"]
    no_ref = raw - raw[ctrl].mean()
    out["no_reference"] = ({"ΔΔCq MYC": no_ref, "Fold change MYC": 2.0**-no_ref}, None, {})
    d_g = raw - study.cq["GAPDH"]
    dd_g = d_g - d_g[ctrl].mean()
    out["wrong_reference"] = (
        {"ΔCq MYC": d_g, "ΔΔCq MYC": dd_g, "Fold change MYC": 2.0**-dd_g},
        None,
        {},
    )
    arith = {"vehicle": float(np.mean(fc[ctrl])), "drug": float(np.mean(fc[~ctrl]))}
    p_good = stats.ttest_ind(dcq[~ctrl], dcq[ctrl], equal_var=True).pvalue
    out["arith_mean_fc"] = (good, summary_rows(study, arith, p_good), {})
    p_fc = stats.ttest_ind(fc[~ctrl], fc[ctrl], equal_var=True).pvalue
    means = {"vehicle": geo(fc[ctrl]), "drug": geo(fc[~ctrl])}
    out["stats_on_fc"] = (good, summary_rows(study, means, p_fc), {})
    shifted = ddcq.copy()
    shifted[2:] = ddcq[1:-1]  # pasted one row down from the third data row
    out["row_shift"] = ({**good, "ΔΔCq MYC": shifted, "Fold change MYC": 2.0**-shifted}, None, {})
    eff = {"MYC": 1.90, "GAPDH": 1.95, "ACTB": 2.0}
    ratio = eff["MYC"] ** (raw[ctrl].mean() - raw)
    for ref in study.refs:
        q = study.cq[ref]
        ratio = ratio / (eff[ref] ** (q[ctrl].mean() - q)) ** (1 / len(study.refs))
    out["pfaffl"] = ({**good, "Fold change MYC": ratio}, sums, {"efficiencies": eff})
    return out


EXPECTED_FIRST = {  # path -> (step, column)
    "sign_inverted": ("fc", "H"),
    "exponent_twice": ("fc", "H"),
    "no_reference": ("ddcq", "F"),
    "wrong_reference": ("dcq", "F"),
    "arith_mean_fc": ("mean_fc", "H"),
    "stats_on_fc": ("p", "H"),
    "row_shift": ("ddcq", "G"),
    "pfaffl": ("fc", "H"),
}


@pytest.mark.parametrize("path", sorted(EXPECTED_FIRST))
def test_each_wrong_path_is_named_at_its_first_column(tmp_path, path):
    study = synthetic()
    columns, summaries, kwargs = _slip_sheets(study)[path]
    header, rows = wide_table(study, columns, summaries)
    result = check_sheet(write_csv(tmp_path / f"{path}.csv", header, rows), **kwargs)
    found = first(result)
    assert (found.step, found.column) == EXPECTED_FIRST[path]
    assert found.paths == [path] and found.status == "explained"
    assert found.path_kinds[path] == PATHS[path].kind
    if found.step in ("fc", "mean_fc", "dcq", "ddcq"):
        assert result.summary.n_differ > 0  # a p-value slip changes no fold change
    assert result.summary.n_named == result.summary.n_differ  # every difference has a cause


def test_wrong_reference_names_the_column_used(tmp_path):
    study = synthetic()
    columns, _, _ = _slip_sheets(study)["wrong_reference"]
    result = check_sheet(write_csv(tmp_path / "w.csv", *wide_table(study, columns)))
    found = first(result)
    assert found.path_details == {"wrong_reference": ["GAPDH"]}
    assert found.rows == list(range(2, 10)) and found.onwards
    assert sorted(found.followed_by) == ["G:ddcq", "H:fc"]  # later columns follow from it
    statuses = {c.column: c.status for c in result.columns}
    assert statuses == {"F": "differs", "G": "follows", "H": "follows"}


def test_row_shift_starts_where_the_paste_starts(tmp_path):
    study = synthetic()
    columns, _, _ = _slip_sheets(study)["row_shift"]
    result = check_sheet(write_csv(tmp_path / "shift.csv", *wide_table(study, columns)))
    found = first(result)
    assert found.first_row == 4 and found.onwards  # header row 1, third data row is row 4
    assert found.path_details == {"row_shift": ["the previous row"]}


def test_item_64_exponent_twice(tmp_path):
    """ "Cell line A expresses 2^10 more mRNA": a fold change of ten raised to a power again."""
    study = synthetic(shift=math.log2(10))
    dcq, ddcq, fc, ctrl = textbook(study, "MYC")
    mean_drug = geo(fc[~ctrl])
    assert 8 < mean_drug < 12  # the sheet's real answer is about ten-fold
    reported = {"vehicle": 2.0 ** geo(fc[ctrl]), "drug": 2.0**mean_drug}
    p = stats.ttest_ind(dcq[~ctrl], dcq[ctrl], equal_var=True).pvalue
    header, rows = wide_table(study, clean_columns(study), summary_rows(study, reported, p))
    result = check_sheet(write_csv(tmp_path / "item64.csv", header, rows))
    means = [f for f in result.findings if f.step == "mean_fc"]
    assert len(means) == 2 and all(f.paths == ["exponent_twice"] for f in means)
    drug = next(f for f in means if f.group == 2)
    assert drug.user_value > 250 and drug.expected_value == pytest.approx(mean_drug, rel=1e-6)
    assert result.summary.n_fold_changes == 10 and result.summary.n_differ == 2


def test_wells_counted_as_n_in_a_long_per_well_sheet(tmp_path):
    study = synthetic()
    rng = np.random.default_rng(3)
    header = ["Sample", "Group", "Gene", "Cq", "ΔCq", "ΔΔCq", "RQ"]
    wells = {g: study.cq[g][:, None] + np.round(rng.normal(0, 0.1, (8, 3)), 2) for g in study.cq}
    nf = np.mean([wells[r].mean(axis=1) for r in study.refs], axis=0)
    ctrl = np.array([g == study.control for g in study.groups])
    d_well = wells["MYC"] - nf[:, None]
    k = d_well.mean(axis=1)[ctrl].mean()
    rows = []
    for group in ("vehicle", "drug"):
        for i in np.flatnonzero(np.array(study.groups) == group):
            for gene in ("GAPDH", "ACTB", "MYC"):
                for j in range(3):
                    cells = [study.units[i], group, gene, fmt(wells[gene][i, j], 2)]
                    if gene == "MYC":
                        d = d_well[i, j]
                        cells += [fmt(d), fmt(d - k), fmt(2.0 ** -(d - k))]
                    else:
                        cells += ["", "", ""]
                    rows.append(cells)
        sel = np.array(study.groups) == group
        rows.append(["Mean", "", "", "", "", "", fmt(geo(2.0 ** -(d_well[sel] - k)), 6)])
    p_wells = stats.ttest_ind(d_well[~ctrl].ravel(), d_well[ctrl].ravel(), equal_var=True).pvalue
    rows.append(["p-value", "", "", "", "", "", fmt(p_wells, 6)])
    result = check_sheet(write_csv(tmp_path / "wells.csv", header, rows))
    assert result.layout == "long"
    found = first(result)
    assert (found.step, found.paths) == ("p", ["wells_as_n"])
    assert [c.status for c in result.columns if c.step in ("dcq", "ddcq", "fc")] == [
        "reproduced"
    ] * 3


def test_a_typo_is_unexplained_with_its_gap(tmp_path):
    study = synthetic()
    columns = clean_columns(study)
    typo = columns["ΔΔCq MYC"].copy()
    typo[4] += 0.5
    columns = {**columns, "ΔΔCq MYC": typo, "Fold change MYC": 2.0**-typo}
    result = check_sheet(write_csv(tmp_path / "typo.csv", *wide_table(study, columns)))
    found = first(result)
    assert (found.step, found.status, found.rows) == ("ddcq", "unexplained", [6])
    assert found.gap == pytest.approx(0.5, abs=1e-3) and not found.onwards
    assert result.summary.n_unexplained == 1 and result.summary.n_named == 0


def test_two_paths_that_fit_are_ambiguous(tmp_path):
    """A reference column that never varies cannot be told apart from no reference at all."""
    study = synthetic()
    study.cq["ACTB"] = np.full(8, 20.0)
    raw = study.cq["MYC"]
    ctrl = np.array([g == study.control for g in study.groups])
    dd = raw - raw[ctrl].mean()
    columns = {"ΔΔCq MYC": dd, "Fold change MYC": 2.0**-dd}
    result = check_sheet(write_csv(tmp_path / "amb.csv", *wide_table(study, columns)))
    found = first(result)
    assert found.status == "ambiguous"
    assert found.paths == ["no_reference", "wrong_reference"]
    assert found.path_details == {"wrong_reference": ["ACTB"]}
    assert result.summary.n_ambiguous == result.summary.n_differ > 0


def test_reference_minus_target_is_a_convention(tmp_path):
    study = synthetic()
    dcq, _, fc, ctrl = textbook(study, "MYC")
    flipped = -dcq
    dd = flipped - flipped[ctrl].mean()  # = -textbook ΔΔCq
    columns = {"ΔCq MYC": flipped, "ΔΔCq MYC": dd, "Fold change MYC": 2.0**dd}
    result = check_sheet(write_csv(tmp_path / "conv.csv", *wide_table(study, columns)))
    assert result.findings == []
    assert {c.status for c in result.columns} == {"reproduced"}
    assert result.summary.n_reproduced == result.summary.n_fold_changes == 8
    conventions = {c.column: c.convention for c in result.columns}
    assert conventions["F"] == sc.CONVENTIONS["dcq"]
    assert conventions["G"] == sc.CONVENTIONS["ddcq"] and conventions["H"] is None


def test_method_only_difference_is_a_hand_over(tmp_path):
    study = synthetic()
    dcq, _, fc, ctrl = textbook(study, "MYC")
    log2fc = float(np.mean(-dcq[~ctrl]) - np.mean(-dcq[ctrl]))
    engine = ContrastResult(
        target="MYC",
        log2fc=log2fc + 0.4,  # per-well efficiency moves the engine's answer
        fc=2 ** (log2fc + 0.4),
        ci=(1.0, 9.0),
        p=0.001,
        t=5.0,
        n_hi=4,
        n_lo=4,
        conclusion="up",
    )
    result = check_sheet(clean_sheet(tmp_path), study={"MYC": engine})
    assert result.findings == []
    assert len(result.hand_overs) == 1
    hand = result.hand_overs[0]
    assert hand.gene == hand.engine_gene == "MYC" and hand.causes == ["efficiency"]
    assert hand.sheet_fc == pytest.approx(2**log2fc, rel=1e-9)
    assert hand.ratio == pytest.approx(2**0.4, rel=1e-9)
    assert hand.see == ["robustness_grid"] and result.summary.n_hand_overs == 1
    same = check_sheet(
        clean_sheet(tmp_path, name="b.csv"),
        study={"MYC": engine.model_copy(update={"log2fc": log2fc})},
    )
    assert same.hand_overs == []  # the same answer: nothing to hand over
    other = check_sheet(clean_sheet(tmp_path, name="c.csv"), study={"BCL2": engine})
    assert other.hand_overs == [] and any("no counterpart" in n for n in other.notes)


def test_output_is_byte_deterministic(tmp_path):
    study = synthetic()
    columns, _, _ = _slip_sheets(study)["wrong_reference"]
    a = write_csv(tmp_path / "a.csv", *wide_table(study, columns))
    (tmp_path / "copy").mkdir()
    b = write_csv(tmp_path / "copy" / "a.csv", *wide_table(study, columns))  # same name, same bytes
    first_run = check_sheet(a).to_json()
    assert first_run == check_sheet(a).to_json() == check_sheet(b).to_json()
    data = json.loads(first_run)
    assert data["file_sha256"] == sc._read(a)[0].sha256
    assert first_run.endswith("\n") and "NaN" not in first_run


def test_sheet_labels_are_never_copied_into_the_result(tmp_path):
    result = check_sheet(clean_sheet(tmp_path))
    dumped = result.to_json()
    for label in ("mouse-c1", "mouse-t4", "vehicle", "drug", "Fold change MYC", "ΔΔCq MYC"):
        assert label not in dumped
    assert result.mapping.control_group is None


def test_date_mangled_gene_name_is_flagged(tmp_path):
    study = synthetic(targets=("MARCH1",))
    header = ["Sample", "Group", "Gene", "Cq"]
    rows = []
    for i, (unit, group) in enumerate(zip(study.units, study.groups, strict=True)):
        for gene, shown in (("GAPDH", "GAPDH"), ("ACTB", "ACTB"), ("MARCH1", "1-Mar")):
            rows.append([unit, group, shown, fmt(study.cq[gene][i], 2)])
    result = check_sheet(write_csv(tmp_path / "dates.csv", header, rows))
    flagged = [g for g in result.genes if g.flagged]
    assert [(g.key, g.status) for g in flagged] == [("1-Mar", "date_mangled")]
    assert "MARCHF1" in flagged[0].candidates and flagged[0].cell == "C4"
    assert result.summary.n_symbol_flags == 1
    assert result.facts["f_sc_sym_1_status"].value == "date mangled"


def test_date_cell_in_a_workbook_is_flagged(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Sample", "Group", "Gene", "Cq"])
    for unit, group in (("a1", "control"), ("a2", "control"), ("b1", "treated"), ("b2", "treated")):
        sheet.append([unit, group, "GAPDH", 18.0])
        sheet.append([unit, group, dt.datetime(2024, 9, 2), 24.0])  # SEPT2 as Excel shows it
    book.save(tmp_path / "dates.xlsx")
    result = check_sheet(tmp_path / "dates.xlsx")
    flagged = [g for g in result.genes if g.flagged]
    assert len(flagged) == 1 and "SEPTIN2" in flagged[0].candidates


def test_formula_only_workbook_is_refused(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Sample", "Group", "GAPDH Cq", "MYC Cq", "ΔCq MYC"])
    for i, (unit, group) in enumerate((("a", "control"), ("b", "control"), ("c", "treated"))):
        sheet.append([unit, group, 18.0 + i, 25.0 - i, f"=D{i + 2}-C{i + 2}"])
    book.save(tmp_path / "formulas.xlsx")
    with pytest.raises(SheetCheckError, match="formulas without saved values"):
        check_sheet(tmp_path / "formulas.xlsx")
    with pytest.raises(SheetCheckError, match="formulas without saved values"):
        guess_mapping(tmp_path / "formulas.xlsx")


def test_oversize_and_unreadable_sheets_are_refused(tmp_path):
    big = tmp_path / "big.csv"
    big.write_text("Sample,Cq\n" + "x,1\n" * 1_400_000)
    assert big.stat().st_size > 5 * 1024 * 1024
    with pytest.raises(SheetCheckError, match="too large"):
        check_sheet(big)
    (tmp_path / "notes.csv").write_text("just,some\nfree,text\n")
    with pytest.raises(SheetCheckError, match="no table"):
        check_sheet(tmp_path / "notes.csv")
    (tmp_path / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(SheetCheckError, match="unsupported"):
        check_sheet(tmp_path / "old.xls")


def test_a_sheet_without_a_known_reference_needs_one_named(tmp_path):
    study = synthetic(refs=("FOO1",), targets=("MYC",))
    header, rows = wide_table(study, {})
    path = write_csv(tmp_path / "noref.csv", header, rows)
    with pytest.raises(SheetCheckError, match="no reference"):
        check_sheet(path)
    mapping = guess_mapping(path).model_copy(update={"references": ["FOO1"]})
    assert check_sheet(path, mapping).findings == []


def test_mapping_override_and_confirmation(tmp_path):
    study = synthetic()
    columns, _, _ = _slip_sheets(study)["wrong_reference"]
    path = write_csv(tmp_path / "w.csv", *wide_table(study, columns))
    guessed = guess_mapping(path)
    declared_gapdh = guessed.model_copy(update={"references": ["GAPDH"], "confirmed": True})
    result = check_sheet(path, declared_gapdh)
    assert result.findings == []  # GAPDH alone was the declared reference after all
    assert result.mapping_status == MAPPING_CONFIRMED == result.facts["f_sc_mapping_status"].value
    from_json = ColumnMapping.model_validate_json(result.mapping.model_dump_json())
    assert check_sheet(path, from_json).to_json() == result.to_json()  # the round trip holds
    by_label = guessed.model_copy(update={"control_group": "drug", "control_text_id": None})
    flipped = check_sheet(clean_sheet(tmp_path), by_label)
    assert [g.control for g in flipped.groups] == [False, True]
    assert flipped.findings  # ΔΔCq against the other group's mean no longer reproduces
    assert flipped.mapping.control_group is None and flipped.mapping.control_text_id


def test_a_bad_mapping_is_refused(tmp_path):
    path = clean_sheet(tmp_path)
    mapping = guess_mapping(path)
    no_sample = mapping.model_copy(
        update={"columns": [c for c in mapping.columns if c.role != "sample"]}
    )
    with pytest.raises(SheetCheckError, match="sample column"):
        check_sheet(path, no_sample)
    with pytest.raises(SheetCheckError, match="no sheet"):
        check_sheet(path, mapping.model_copy(update={"sheet": 3}))
    with pytest.raises(SheetCheckError, match="amplification factor"):
        check_sheet(path, efficiencies={"MYC": 95})


def test_group_level_columns(tmp_path):
    study = synthetic()
    _, _, fc, ctrl = textbook(study, "MYC")
    geo_col = np.where(ctrl, geo(fc[ctrl]), geo(fc[~ctrl]))
    arith_col = np.where(ctrl, fc[ctrl].mean(), fc[~ctrl].mean())
    varying = fc * 0.1
    columns = {**clean_columns(study), "Mean FC MYC": geo_col}
    ok = check_sheet(write_csv(tmp_path / "geo.csv", *wide_table(study, columns)))
    assert ok.findings == [] and ok.summary.n_fold_changes == 10
    columns = {**clean_columns(study), "Mean FC MYC": arith_col, "SD MYC": varying}
    slip = check_sheet(write_csv(tmp_path / "arith.csv", *wide_table(study, columns)))
    assert {(f.column, f.step, tuple(f.paths)) for f in slip.findings} == {
        ("I", "mean_fc", ("arith_mean_fc",))
    }
    skipped = next(c for c in slip.columns if c.column == "J")
    assert skipped.status == "not_checked" and "vary within a group" in skipped.reason


def test_long_per_sample_sheet(tmp_path):
    study = synthetic()
    dcq, ddcq, fc, _ = textbook(study, "MYC")
    header = ["Sample", "Group", "Target", "Cq", "dCt", "ddCt", "2^-ddCt"]
    rows = []
    for i, (unit, group) in enumerate(zip(study.units, study.groups, strict=True)):
        for gene in ("GAPDH", "ACTB"):
            rows.append([unit, group, gene, fmt(study.cq[gene][i], 2), "", "", ""])
        rows.append(
            [unit, group, "MYC", fmt(study.cq["MYC"][i], 2), fmt(dcq[i]), fmt(ddcq[i]), fmt(fc[i])]
        )
    result = check_sheet(write_csv(tmp_path / "long.csv", header, rows))
    assert result.layout == "long" and result.mapping.references == ["GAPDH", "ACTB"]
    assert result.findings == [] and result.summary.n_reproduced == 8
    slipped = [r[:6] + [fmt(2.0 ** float(r[5]))] if r[2] == "MYC" else r for r in rows]
    found = first(check_sheet(write_csv(tmp_path / "long_slip.csv", header, slipped)))
    assert (found.column, found.step, found.paths) == ("G", "fc", ["sign_inverted"])


def test_sign_inverted_workbook(tmp_path):
    study = synthetic()
    columns, _, _ = _slip_sheets(study)["sign_inverted"]
    result = check_sheet(write_xlsx(tmp_path / "inv.xlsx", *wide_table(study, columns)))
    assert first(result).paths == ["sign_inverted"]


def test_sd_and_sem_summary_rows(tmp_path):
    study = synthetic()
    dcq, _, fc, ctrl = textbook(study, "MYC")
    sums = textbook_summaries(study)
    for group, mask in (("vehicle", ctrl), ("drug", ~ctrl)):
        sums[group].insert(1, ("SD", {"ΔCq MYC": float(np.std(dcq[mask], ddof=1))}))
        sem = float(np.std(fc[mask], ddof=1) / math.sqrt(mask.sum()))
        sums[group].insert(2, ("SEM", {"Fold change MYC": sem}))
    header, rows = wide_table(study, clean_columns(study), sums)
    result = check_sheet(write_csv(tmp_path / "sd.csv", header, rows))
    assert result.findings == []
    variants = {(c.step, c.variant) for c in result.columns if c.step in ("sd", "sem")}
    assert variants == {("sd", "dcq"), ("sem", "fc")}


def test_wide_replicate_columns_and_their_mean(tmp_path):
    study = synthetic()
    rng = np.random.default_rng(11)
    wells = {g: study.cq[g][:, None] + np.round(rng.normal(0, 0.1, (8, 2)), 2) for g in study.cq}
    means = {g: wells[g].mean(axis=1) for g in wells}
    nf = (means["GAPDH"] + means["ACTB"]) / 2
    ctrl = np.array([g == study.control for g in study.groups])
    dcq = means["MYC"] - nf
    ddcq = dcq - dcq[ctrl].mean()
    header = ["Sample", "Group"]
    for g in ("GAPDH", "ACTB", "MYC"):
        header += [f"{g} Ct 1", f"{g} Ct 2"]
    header += ["MYC mean Ct", "dCt MYC", "ddCt MYC", "RQ MYC"]
    rows = []
    for i, (unit, group) in enumerate(zip(study.units, study.groups, strict=True)):
        row = [unit, group]
        for g in ("GAPDH", "ACTB", "MYC"):
            row += [fmt(wells[g][i, 0], 2), fmt(wells[g][i, 1], 2)]
        row += [fmt(means["MYC"][i]), fmt(dcq[i]), fmt(ddcq[i]), fmt(2.0 ** -ddcq[i])]
        rows.append(row)
    mapping = guess_mapping(write_csv(tmp_path / "reps.csv", header, rows))
    assert [c.gene for c in mapping.columns if c.role == "cq"] == ["GAPDH"] * 2 + ["ACTB"] * 2 + [
        "MYC"
    ] * 2
    assert next(c for c in mapping.columns if c.column == "I").role == "mean_cq"
    result = check_sheet(tmp_path / "reps.csv")
    assert result.findings == [] and {c.step for c in result.columns} == {
        "mean_cq",
        "dcq",
        "ddcq",
        "fc",
    }
    p_wells = stats.ttest_ind(
        (wells["MYC"] - nf[:, None])[~ctrl].ravel(),
        (wells["MYC"] - nf[:, None])[ctrl].ravel(),
        equal_var=True,
    ).pvalue
    rows.append(["p-value"] + [""] * 10 + [fmt(p_wells, 6)])
    slip = check_sheet(write_csv(tmp_path / "reps_p.csv", header, rows))
    assert [(f.step, f.paths) for f in slip.findings] == [("p", ["wells_as_n"])]


def test_european_csv_with_comma_decimals_and_undetermined_cells(tmp_path):
    study = synthetic()
    study.cq["MYC"][1] = np.nan  # a Cq the instrument did not call
    header, rows = wide_table(study, clean_columns(study))
    rows[1][4] = "Undetermined"
    text_rows = [";".join(header)] + [";".join(c.replace(".", ",") for c in r) for r in rows]
    path = tmp_path / "eu.csv"
    path.write_text("\n".join(text_rows) + "\n", encoding="utf-8")
    result = check_sheet(path)
    assert result.findings == [] and result.summary.n_fold_changes == 7


def test_no_template_rows_are_left_out(tmp_path):
    study = synthetic()
    dcq, ddcq, fc, _ = textbook(study, "MYC")
    header = ["Sample", "Group", "Task", "Target", "Cq", "Fold change"]
    rows = []
    for i, (unit, group) in enumerate(zip(study.units, study.groups, strict=True)):
        for gene in ("GAPDH", "ACTB"):
            rows.append([unit, group, "Unknown", gene, fmt(study.cq[gene][i], 2), ""])
        rows.append([unit, group, "Unknown", "MYC", fmt(study.cq["MYC"][i], 2), fmt(fc[i])])
    rows.append(["water", "vehicle", "NTC", "MYC", "38.10", "0.0001"])
    result = check_sheet(write_csv(tmp_path / "ntc.csv", header, rows))
    assert result.findings == [] and result.n_rows == 24
    assert any("left out" in note for note in result.notes)


def test_a_p_value_repeated_on_every_row_is_one_value(tmp_path):
    study = synthetic()
    dcq, _, _, ctrl = textbook(study, "MYC")
    p = stats.ttest_ind(dcq[~ctrl], dcq[ctrl], equal_var=False).pvalue
    columns = {**clean_columns(study), "p-value MYC": np.full(8, p)}
    result = check_sheet(write_csv(tmp_path / "p.csv", *wide_table(study, columns)))
    checks = [c for c in result.columns if c.step == "p"]
    assert len(checks) == 1 and checks[0].status == "reproduced" and checks[0].variant == "welch"


def test_a_column_whose_gene_is_not_identified_is_listed(tmp_path):
    study = synthetic(targets=("MYC", "BCL2"))
    columns = {**clean_columns(study), "dCt": clean_columns(study)["ΔCq MYC"]}
    result = check_sheet(write_csv(tmp_path / "two.csv", *wide_table(study, columns)))
    unnamed = [c for c in result.columns if c.gene is None]
    assert len(unnamed) == 1 and unnamed[0].status == "not_checked"
    assert "not identified" in unnamed[0].reason


def test_the_store_entry_reads_the_stored_result(tmp_path):
    study = synthetic()
    dcq, _, _, ctrl = textbook(study, "MYC")
    log2fc = float(np.mean(-dcq[~ctrl]) - np.mean(-dcq[ctrl]))

    class Store:
        def __init__(self):
            self.asked = []

        def get(self, study_id):
            self.asked.append(study_id)
            return {
                "MYC": ContrastResult(
                    target="MYC",
                    log2fc=log2fc + 1,
                    fc=2 ** (log2fc + 1),
                    ci=(1, 2),
                    p=0.01,
                    t=3,
                    n_hi=4,
                    n_lo=4,
                    conclusion="up",
                )
            }

    store = Store()
    result = sc.check_sheet_store(store, "study-1", clean_sheet(tmp_path))
    assert store.asked == ["study-1"] and len(result.hand_overs) == 1


def test_guess_mapping_takes_what_the_reader_returned(tmp_path):
    from qpilot.io.sheets import read_sheet

    path = clean_sheet(tmp_path)
    assert guess_mapping(read_sheet(path)) == guess_mapping(path)


def test_two_row_header_with_genes_above(tmp_path):
    study = synthetic()
    dcq, ddcq, fc, _ = textbook(study, "MYC")
    genes = ["", "", "GAPDH", "ACTB", "MYC", "MYC", "MYC", "MYC"]
    steps = ["Sample", "Group", "Ct", "Ct", "Ct", "ΔCt", "ΔΔCt", "2^-ΔΔCt"]
    rows = [steps]  # the header proper is the second row
    for i, (unit, group) in enumerate(zip(study.units, study.groups, strict=True)):
        cqs = [fmt(study.cq[g][i], 2) for g in ("GAPDH", "ACTB", "MYC")]
        rows.append([unit, group, *cqs, fmt(dcq[i]), fmt(ddcq[i]), fmt(fc[i])])
    path = write_csv(tmp_path / "two_rows.csv", genes, rows)
    mapping = guess_mapping(path)
    assert mapping.header_row == 2 and mapping.references == ["GAPDH", "ACTB"]
    assert [(c.column, c.role, c.gene) for c in mapping.columns if c.gene] == [
        ("C", "cq", "GAPDH"),
        ("D", "cq", "ACTB"),
        ("E", "cq", "MYC"),
        ("F", "dcq", "MYC"),
        ("G", "ddcq", "MYC"),
        ("H", "fc", "MYC"),
    ]
    assert check_sheet(path).findings == []


def test_a_log2_fold_change_column_is_minus_ddcq(tmp_path):
    study = synthetic()
    dcq, ddcq, fc, _ = textbook(study, "MYC")
    columns = {"log2 fold change MYC": -ddcq, "Fold change MYC": fc}
    result = check_sheet(write_csv(tmp_path / "log2.csv", *wide_table(study, columns)))
    assert result.findings == []
    log2 = next(c for c in result.columns if c.column == "F")
    assert (log2.step, log2.status, log2.convention) == (
        "ddcq",
        "reproduced",
        sc.CONVENTIONS["ddcq"],
    )
    assert next(c for c in result.columns if c.column == "G").status == "reproduced"


# ---------------------------------------------------------------------------------------------
# the path library as pure functions
# ---------------------------------------------------------------------------------------------


def _chain(**kw) -> Chain:
    base = dict(
        gene="T",
        rows=(2, 3, 4, 5),
        unit=np.array([0, 1, 2, 3]),
        unit_group=np.array([1, 1, 2, 2]),
        control=1,
        target=np.array([[25.0], [25.5], [23.0], [22.0]]),
        refs=("R",),
        ref_row={"R": np.array([18.0, 18.3, 18.0, 17.5])},
        ref_unit={"R": np.array([18.0, 18.3, 18.0, 17.5])},
        all_refs=("R",),
    )
    base.update(kw)
    return Chain(**base)


def test_livak_per_unit_by_hand():
    values = livak_per_unit(_chain())
    dcq = np.array([7.0, 7.2, 5.0, 4.5])
    ddcq = dcq - 7.1
    assert values.unit["dcq"] == pytest.approx(dcq)
    assert values.unit["ddcq"] == pytest.approx(ddcq)
    assert values.unit["fc"] == pytest.approx(2.0**-ddcq)
    assert values.group[("mean_fc", 1, "")] == pytest.approx(1.0)  # geometric mean
    assert values.group[("mean_fc", 2, "")] == pytest.approx(2**2.35)
    assert values.group[("sd", 2, "dcq")] == pytest.approx(np.std([5.0, 4.5], ddof=1))
    assert values.group[("sem", 2, "fc")] == pytest.approx(
        np.std(2.0 ** -ddcq[2:], ddof=1) / math.sqrt(2)
    )
    for variant, equal in (("welch", False), ("student", True)):
        expected = stats.ttest_ind(dcq[2:], dcq[:2], equal_var=equal).pvalue
        assert values.group[("p", 2, variant)] == pytest.approx(expected)


def test_paths_are_pure_and_wells_equal_units_without_replicates():
    chain = _chain()
    before = chain.target.copy()
    a, b = livak_per_unit(chain), wells_as_n(chain)
    assert np.array_equal(chain.target, before)
    for key, value in a.group.items():
        assert value == pytest.approx(b.group[key], nan_ok=True)
    assert not chain.has_replicates
    replicated = replace(
        chain, target=np.array([[25.0, 25.2], [25.5, 25.1], [23, 23.4], [22, 22.2]])
    )
    assert replicated.has_replicates
    unit = livak_per_unit(replicated).group[("p", 2, "student")]
    wells = wells_as_n(replicated).group[("p", 2, "student")]
    assert wells < unit  # counting wells as n makes the p-value smaller


def test_sign_convention_anchor():
    chain = _chain()
    flipped = Anchors(sign=-1)
    ddcq = np.array([7.0, 7.2, 5.0, 4.5]) - 7.1
    assert livak_per_unit(chain, flipped).unit["fc"] == pytest.approx(2.0**ddcq)


def test_row_shift_function():
    values = {2: 1.0, 3: 2.0, 4: 3.0}
    assert list(row_shift(values, [2, 3, 4], 1)[:2]) == [2.0, 3.0]
    assert math.isnan(row_shift(values, [2, 3, 4], 1)[2])
    assert list(row_shift(values, [3, 4], -1)) == [1.0, 2.0]


def test_method_card_matches_the_methods_page():
    card = sc.METHOD_CARD
    assert {"id", "version", "inputs", "outputs", "acceptance_tests", "licence"} <= set(card)
    page = Path(__file__).resolve().parents[2] / card["card"]
    assert page.exists()
    names = {t.split("::")[1] for t in card["acceptance_tests"]}
    assert names <= set(globals())


# ---------------------------------------------------------------------------------------------
# the text
# ---------------------------------------------------------------------------------------------


def test_text_renders_from_facts_and_passes_the_validator(tmp_path):
    study = synthetic()
    columns, _, _ = _slip_sheets(study)["wrong_reference"]
    result = check_sheet(write_csv(tmp_path / "w.csv", *wide_table(study, columns)))
    rendered = text.render(result)
    assert validate(rendered.tokens, result.facts).ok
    assert "{{" not in rendered.plain and 'data-fact="f_sc_n_fc"' in rendered.html
    assert "look is column F (ΔCq for MYC), from row 2 onwards (8 rows)." in rendered.plain
    assert "a reference other than the one declared (GAPDH)" in rendered.plain
    findings = text.render(result, text.FINDINGS_KEY, gene="MYC")
    assert findings.plain.startswith("Column F (ΔCq for MYC) differs from row 2 onwards")
    for piece in (rendered.plain, findings.plain):
        assert not any(word in piece.lower() for word in BANNED)


def test_text_for_a_clean_sheet_and_a_hand_over(tmp_path):
    study = synthetic()
    dcq, _, _, ctrl = textbook(study, "MYC")
    log2fc = float(np.mean(-dcq[~ctrl]) - np.mean(-dcq[ctrl]))
    engine = ContrastResult(
        target="MYC",
        log2fc=log2fc + 1.2,
        fc=2 ** (log2fc + 1.2),
        ci=(1.0, 9.0),
        p=0.001,
        t=5.0,
        n_hi=4,
        n_lo=4,
        conclusion="up",
    )
    result = check_sheet(clean_sheet(tmp_path), study={"MYC": engine})
    plain = text.render(result).plain
    assert sc.MAPPING_GUESSED in plain and "Every column" in plain
    assert "difference of method" in plain
    hand = text.render(result, text.HANDOVER_KEY, gene="MYC").plain
    assert hand.startswith("MYC: the sheet's arithmetic reproduces")
    assert "each well's own amplification efficiency" in hand


@pytest.mark.parametrize("key", sorted(text.TEMPLATES))
def test_text_degrades_without_facts(key):
    for facts in ({}, {"f_other": sc.Fact(id="f_other", value=1)}):
        rendered = text.render(facts, key)
        assert not any(ch.isdigit() for ch in rendered.plain)
    assert text.render({}, key, gene="MYC").plain


def test_text_refuses_an_unknown_key():
    with pytest.raises(KeyError):
        text.render({}, "nope")
    assert issubclass(TemplateError, ValueError)


# ---------------------------------------------------------------------------------------------
# (b) demo data: sheets built from the Vermeulen fixture's real Cq values
# ---------------------------------------------------------------------------------------------

DEMO_REFS = ("HPRT1", "SDHA(1)", "UBC(2)")
DEMO_GENES = ("ODC1", "BIRC5", "NTRK1", "CAMTA2")


@pytest.fixture(scope="module")
def demo_study(request):
    curves = request.getfixturevalue("demo_curves")
    from qpilot.qpcr.study import build_model

    model = build_model(curves)
    unknown = curves[curves["sample_type"] == "unkn"]
    cq = unknown.pivot(index="sample", columns="target", values="cq")
    high = sorted(model.high)
    rest = sorted(model.rest)
    units = rest + high
    groups = ["rest"] * len(rest) + ["MYCN high"] * len(high)
    values = {g: cq.loc[units, g].to_numpy(dtype=float) for g in DEMO_REFS + DEMO_GENES}
    eff = unknown.groupby("target")["eff_target"].first()
    study = Study(units, groups, values, DEMO_REFS, "rest", DEMO_GENES)
    return study, {g: float(eff[g]) for g in DEMO_REFS + DEMO_GENES}, curves


def demo_table(study: Study, gene_columns: dict, summaries: dict | None = None):
    """A wide demo sheet (Cq with four decimals as the engine reports them)."""
    header = ["Sample", "Group", *[f"{g} Cq" for g in study.refs + study.targets]]
    names = [h for cols in gene_columns.values() for h in cols]
    header += names
    rows = []
    for group in dict.fromkeys(study.groups):
        for i, (unit, g) in enumerate(zip(study.units, study.groups, strict=True)):
            if g != group:
                continue
            row = [unit, g] + [fmt(study.cq[x][i], 4) for x in study.refs + study.targets]
            for cols in gene_columns.values():
                row += [fmt(v[i], 6) for v in cols.values()]
            rows.append(row)
        for label, cells in (summaries or {}).get(group, []):
            row = [label] + [""] * (len(header) - 1)
            for name, value in cells.items():
                row[header.index(name)] = f"{value:.6g}"
            rows.append(row)
    return header, rows


def demo_columns(study: Study, gene: str, refs=None):
    dcq, ddcq, fc, _ = textbook(study, gene, refs)
    return {f"ΔCq {gene}": dcq, f"ΔΔCq {gene}": ddcq, f"Fold change {gene}": fc}


def demo_mapping(path: Path, refs=DEMO_REFS) -> ColumnMapping:
    guessed = guess_mapping(path)
    return guessed.model_copy(update={"references": list(refs), "control_group": "rest"})


def demo_clean(study: Study):
    return {g: demo_columns(study, g) for g in study.targets}


def demo_summaries(study: Study, gene: str, *, arithmetic=False, p_on_fc=False):
    dcq, _, fc, ctrl = textbook(study, gene)
    ok = np.isfinite(dcq)
    mean = (lambda v: float(np.nanmean(v))) if arithmetic else geo
    on = fc if p_on_fc else dcq
    p = stats.ttest_ind(on[~ctrl & ok], on[ctrl & ok], equal_var=True).pvalue
    column = f"Fold change {gene}"
    return {
        "rest": [("Mean", {column: mean(fc[ctrl & ok])})],
        "MYCN high": [("Mean", {column: mean(fc[~ctrl & ok])}), ("p-value", {column: p})],
    }


@pytest.mark.demo_data
def test_demo_clean_sheet_has_no_findings(tmp_path, demo_study):
    study, _, _ = demo_study
    header, rows = demo_table(study, demo_clean(study), demo_summaries(study, "ODC1"))
    path = write_csv(tmp_path / "demo.csv", header, rows)
    guessed = guess_mapping(path)
    assert guessed.references == ["HPRT1", "SDHA(1)", "UBC(2)"]
    result = check_sheet(path, demo_mapping(path))
    assert result.findings == []
    assert result.n_rows == 347 and [g.n_units for g in result.groups] == [294, 53]
    # 347 units x 4 genes, minus 5 NTRK1 wells without a Cq, plus the 2 group means of ODC1
    assert result.summary.n_fold_changes == result.summary.n_reproduced == 347 * 4 - 5 + 2


def _demo_slip(study: Study, path: str, eff: dict):
    """(gene columns, summaries, kwargs, gene) of one wrong path on the demo's Cq values."""
    cols = demo_clean(study)
    sums = None
    kwargs: dict = {}
    if path == "sign_inverted":
        gene = "ODC1"
        cols[gene] = {**cols[gene], f"Fold change {gene}": 2.0 ** cols[gene][f"ΔΔCq {gene}"]}
    elif path == "exponent_twice":
        gene = "CAMTA2"
        cols[gene] = {**cols[gene], f"Fold change {gene}": 2.0 ** cols[gene][f"Fold change {gene}"]}
    elif path == "no_reference":
        gene = "CAMTA2"
        raw = study.cq[gene]
        ctrl = np.array([g == "rest" for g in study.groups])
        dd = raw - np.nanmean(raw[ctrl])
        cols[gene] = {f"ΔΔCq {gene}": dd, f"Fold change {gene}": 2.0**-dd}
    elif path == "wrong_reference":
        gene = "NTRK1"
        cols[gene] = demo_columns(study, gene, refs=("HPRT1",))
    elif path == "arith_mean_fc":
        gene = "ODC1"
        sums = demo_summaries(study, gene, arithmetic=True)
    elif path == "stats_on_fc":
        gene = "ODC1"
        sums = demo_summaries(study, gene, p_on_fc=True)
    elif path == "row_shift":
        gene = "BIRC5"
        dd = cols[gene][f"ΔΔCq {gene}"].copy()
        dd[100:] = cols[gene][f"ΔΔCq {gene}"][99:-1]
        cols[gene] = {**cols[gene], f"ΔΔCq {gene}": dd, f"Fold change {gene}": 2.0**-dd}
    elif path == "pfaffl":
        gene = "ODC1"
        ctrl = np.array([g == "rest" for g in study.groups])
        raw = study.cq[gene]
        ratio = eff[gene] ** (np.nanmean(raw[ctrl]) - raw)
        for ref in study.refs:
            q = study.cq[ref]
            ratio = ratio / (eff[ref] ** (np.nanmean(q[ctrl]) - q)) ** (1 / len(study.refs))
        cols[gene] = {**cols[gene], f"Fold change {gene}": ratio}
        kwargs = {"efficiencies": eff}
    else:  # pragma: no cover
        raise AssertionError(path)
    return cols, sums, kwargs, gene


DEMO_FIRST = {  # path -> step of the first divergent column
    "sign_inverted": "fc",
    "exponent_twice": "fc",
    "no_reference": "ddcq",
    "wrong_reference": "dcq",
    "arith_mean_fc": "mean_fc",
    "stats_on_fc": "p",
    "row_shift": "ddcq",
    "pfaffl": "fc",
}


@pytest.mark.demo_data
@pytest.mark.parametrize("path", sorted(DEMO_FIRST))
def test_demo_each_wrong_path_is_detected(tmp_path, demo_study, path):
    study, eff, _ = demo_study
    cols, sums, kwargs, gene = _demo_slip(study, path, eff)
    header, rows = demo_table(study, cols, sums)
    sheet = write_csv(tmp_path / f"{path}.csv", header, rows)
    result = check_sheet(sheet, demo_mapping(sheet), **kwargs)
    found = first(result)
    assert found.gene == gene and found.step == DEMO_FIRST[path]
    assert found.paths == [path]
    assert header[sc._letter_index(found.column) - 1].endswith(gene)
    assert {f.gene for f in result.findings} == {gene}  # the other genes still reproduce
    if path == "row_shift":
        assert found.first_row == 102 and found.onwards  # header row 1; 101st data row


@pytest.mark.demo_data
def test_demo_hand_over_to_the_engine(tmp_path, demo_study):
    study, _, curves = demo_study
    from qpilot.qpcr.study import study_from_curves

    engine, _, _ = study_from_curves(curves, "demo")
    header, rows = demo_table(study, demo_clean(study))
    sheet = write_csv(tmp_path / "demo.csv", header, rows)
    result = check_sheet(sheet, demo_mapping(sheet), study=engine)
    assert result.findings == []
    hands = {h.gene: h for h in result.hand_overs}
    assert sorted(hands) == sorted(DEMO_GENES)
    for gene, hand in hands.items():
        assert {"efficiency", "normaliser"} <= set(hand.causes)  # three references, not five
        assert hand.engine_fc == pytest.approx(engine.contrasts[gene].fc)
        assert hand.engine_conclusion == engine.contrasts[gene].conclusion
    assert hands["ODC1"].sheet_fc == pytest.approx(4.4373, rel=1e-4)
    assert hands["NTRK1"].sheet_fc == pytest.approx(0.036304, rel=1e-4)
    assert [h.conclusion_differs for h in result.hand_overs] == [False] * 4
    assert "card_refset" in hands["ODC1"].see
    plain = text.render(result, text.HANDOVER_KEY, gene="ODC1").plain
    assert plain.startswith("ODC1: the sheet's arithmetic reproduces and gives 4.44×")


@pytest.mark.demo_data
def test_demo_hand_over_with_the_engine_normaliser(tmp_path, demo_study):
    """All five references, as the engine uses: what is left is the efficiency model."""
    study, _, curves = demo_study
    from qpilot.qpcr.study import build_model, study_from_curves

    engine, _, _ = study_from_curves(curves, "demo")
    refs = tuple(engine.design.refs_primary)
    model = build_model(curves)
    unknown = curves[curves["sample_type"] == "unkn"]
    cq = unknown.pivot(index="sample", columns="target", values="cq")
    keep = [u for u in study.units if cq.loc[u, list(refs)].notna().all()]
    groups = ["MYCN high" if u in model.high else "rest" for u in keep]
    values = {g: cq.loc[keep, g].to_numpy(dtype=float) for g in refs + DEMO_GENES}
    five = Study(keep, groups, values, refs, "rest", DEMO_GENES)
    header, rows = demo_table(five, demo_clean(five))
    sheet = write_csv(tmp_path / "five.csv", header, rows)
    result = check_sheet(sheet, demo_mapping(sheet, refs), study=engine)
    assert result.findings == [] and len(keep) == 347
    hands = {h.gene: h for h in result.hand_overs}
    assert sorted(hands) == sorted(DEMO_GENES)
    assert all(h.causes == ["efficiency"] for h in result.hand_overs)
    # efficiency 2.0 alone moves CAMTA2 across the call line, as the ddcq route says
    # (methods/routes.md: CAMTA2, IGSF4, PAICS and PRKACB_bis differ under that route)
    camta2 = hands["CAMTA2"]
    assert (camta2.sheet_conclusion, camta2.engine_conclusion) == ("down", "none")
    assert camta2.sheet_fc == pytest.approx(0.46443, rel=1e-4) and camta2.conclusion_differs
    assert [g for g, h in hands.items() if h.conclusion_differs] == ["CAMTA2"]
