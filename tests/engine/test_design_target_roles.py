"""Which targets are reference genes: a sheet's target-role column, placeholders, all-ref files.

The rules proposed reference genes only when the file declared a target ``ref``; a lab's sheet
says it in a "Gene Type" / "Target role" / "Reference" / "Housekeeping" column instead, often on
a well-level table or in a target list beside the samples. Generic names (``REF``, ``GOI``,
``target1``, a dye) are never renamed to a gene.
"""

import pytest

from qpilot.io.sheets import header_field, sheet_table, target_role_word, target_roles
from qpilot.qpcr.design_rules import is_placeholder_name, propose_from_names
from tests.engine.test_design_rules import by, make


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Gene Type", "target_role"),
        ("Target role", "target_role"),
        ("Target type", "target_role"),
        ("Reference", "target_role"),
        ("Reference gene (yes/no)", "target_role"),
        ("Housekeeping", "target_role"),
        ("Endogenous control", "target_role"),
        ("Reference genes", "target_role"),
        ("Role", "type"),  # a sample's role in most sheets
        ("Sample type", "type"),
        ("Reference sample", None),  # ambiguous: left alone
        ("Plate wells", None),
    ],
)
def test_target_role_headers(header, field):
    assert header_field(header) == field


@pytest.mark.parametrize(
    ("text", "header", "role"),
    [
        ("Reference", "", "ref"),
        ("housekeeping", "", "ref"),
        ("Endogenous control", "", "ref"),
        ("REF", "", "ref"),
        ("Target", "", "toi"),
        ("GOI", "", "toi"),
        ("gene of interest", "", "toi"),
        ("Ignore", "", "ignore"),
        ("yes", "Reference", "ref"),
        ("no", "Is reference?", "toi"),
        ("yes", "Gene type", None),  # yes/no only answer a yes/no question
        ("Mitochondrial", "", None),
    ],
)
def test_target_role_words(text, header, role):
    assert target_role_word(text, header) == role


def test_a_target_list_beside_the_samples_is_read_rows_without_a_sample_included(tmp_path):
    path = tmp_path / "sheet.csv"
    path.write_text(
        "Sample,Group,,Target,Target role\nS1,A,,GAPDH,Reference\nS2,B,,ODC1,Target\n,,,ACTB,ref\n"
    )
    table = sheet_table(path)
    assert table is not None and [r["sample"] for r in table.rows] == ["S1", "S2"]
    found = [(c.target, c.role) for c in target_roles(path)]
    assert found == [("GAPDH", "ref"), ("ODC1", "toi"), ("ACTB", "ref")]


def test_a_targets_only_sheet_and_a_named_reference_column(tmp_path):
    only = tmp_path / "targets.csv"
    only.write_text("Gene,Housekeeping\nGAPDH,yes\nODC1,no\n")
    assert sheet_table(only) is None  # no sample column: not a sample table
    assert [(c.target, c.role) for c in target_roles(only)] == [("GAPDH", "ref"), ("ODC1", "toi")]
    named = tmp_path / "named.csv"
    named.write_text("Sample,Group,Reference genes\nS1,A,GAPDH\nS2,A,HPRT1\n")
    cells = target_roles(named)
    assert [(c.target, c.named) for c in cells] == [("GAPDH", True), ("HPRT1", True)]


def test_a_well_level_sheet_with_a_type_column_only_counts_unambiguous_words(tmp_path):
    path = tmp_path / "wells.csv"
    path.write_text(
        "Well,Sample,Target,Type\nA1,S1,GAPDH,Reference\nA2,S1,ODC1,Unknown\nA3,NTC,ODC1,Control\n"
    )
    assert [(c.target, c.role) for c in target_roles(path)] == [("GAPDH", "ref")]


def test_the_sheet_proposes_reference_genes_and_outranks_the_file():
    sheet = [
        ["Sample", "Group", "", "Target", "Gene Type"],
        ["S1", "A", "", "GAPDH", "Reference"],
        ["S2", "B", "", "odc1", "Target"],  # matched to ODC1 case-insensitively
        ["", "", "", "HPRT1", "Target"],
    ]
    summary, q = make(
        {"S1": "unkn", "S2": "unkn"},
        targets={"GAPDH": "toi", "ODC1": "toi", "HPRT1": "ref"},
        sheet=sheet,
    )
    roles = {f.subject: f for f in by(propose_from_names(summary, q), "design.target_role")}
    assert roles["GAPDH"].value == {"role": "ref"} and roles["GAPDH"].level == "Moderate"
    assert roles["ODC1"].value == {"role": "toi"} and roles["ODC1"].level == "High"
    # the file said ref, the sheet says target: the sheet's, with the file's as the alternative
    assert roles["HPRT1"].value == {"role": "toi"}
    assert {"role": "ref"} in roles["HPRT1"].alternatives
    cited = set(roles["GAPDH"].cites)
    assert {"Sheet1!D2", "Sheet1!E2"} <= cited  # the cells it rests on


def test_every_target_declared_ref_is_only_a_low_proposal():
    summary, q = make({"S1": "unkn"}, targets={"T1": "ref", "T2": "ref", "T3": "ref"})
    roles = by(propose_from_names(summary, q), "design.target_role")
    assert len(roles) == 3 and {f.level for f in roles} == {"Low"}
    assert all(f.alternatives == [{"role": "toi"}] for f in roles)
    one, q1 = make({"S1": "unkn"}, targets={"GAPDH": "ref", "ODC1": "toi"})
    (only,) = by(propose_from_names(one, q1), "design.target_role")
    assert only.level == "High"  # one declared reference among others still says something


@pytest.mark.parametrize(
    ("name", "placeholder"),
    [
        ("REF", True),
        ("GOI", True),
        ("target1", True),
        ("Target 1", True),
        ("Gene-A", True),
        ("NTC", True),
        ("STD", True),
        ("CTRL", True),
        ("IPC", True),
        ("FAM", True),
        ("SYBR", True),
        ("GAPDH", False),
        ("HK2", False),  # hexokinase 2, a gene
        ("FAM83A", False),
        ("HEXB", False),
        ("NEGR1", False),
        ("ALUsq", False),
    ],
)
def test_placeholder_names(name, placeholder):
    assert is_placeholder_name(name) is placeholder


def test_no_gene_symbol_is_proposed_for_a_placeholder_and_its_check_is_never_consistent():
    summary, q = make({"S1": "unkn"}, targets={"REF": "toi", "GOI": "toi", "GAPDH": "toi"})
    symbols = {f.subject for f in by(propose_from_names(summary, q), "design.gene_symbol")}
    assert "REF" not in symbols and "GOI" not in symbols and "GAPDH" in symbols


def test_the_lightcycler96_depositors_table_names_its_reference_gene(tmp_path):
    """The hmuY deposit's own table (tests/fixtures/corpus/rdml/lightcycler96-lc96p-hmuy,
    hmuy_cq_values.xlsx), its sample columns as intake keeps them (no Cq beside a group):
    'Gene Type' says Target / Reference, padded with spaces as the depositors typed it."""
    path = tmp_path / "hmuy_cq_values (sample columns).csv"
    rows = ["Replicate,Sample Name,Gene Name,Condition Name,Gene Type"]
    for sample, condition in (("Hm_1", "Hm"), ("DIP_1", "DIP")):
        rows.append(f"1,{sample}       ,hmuYPe   ,{condition},Target   ")
        rows.append(f"1,{sample}       ,16S rRNA ,{condition},Reference")
    path.write_text("\n".join(rows) + "\n")
    table = sheet_table(path)
    assert table is not None
    assert {"sample", "target", "group", "target_role"} <= set(table.columns)
    roles = {(c.target, c.role) for c in target_roles(path)}
    assert roles == {("hmuYPe", "toi"), ("16S rRNA", "ref")}
