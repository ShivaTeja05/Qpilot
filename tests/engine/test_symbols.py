"""The HGNC gene-symbol gate: approved, previous/alias, Excel-mangled, non-gene and unknown."""

import datetime as dt
from importlib import resources

import pytest

from qpilot.io.symbols import (
    check_symbol,
    check_symbols,
    excel_date_parts,
    load_table,
    normalise_assay_name,
)


def test_the_shipped_table_is_small_complete_and_licensed():
    folder = resources.files("qpilot").joinpath("data/hgnc")
    data = folder.joinpath("hgnc_symbols.tsv")
    assert len(data.read_bytes()) < 1_000_000
    table = load_table()
    assert len(table.approved) > 40_000
    readme = folder.joinpath("README.md").read_text(encoding="utf-8")
    assert "CC0" in readme and "genenames.org/about/license" in readme
    assert "CC0" in folder.joinpath("LICENCE").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "query", "symbol"),
    [
        ("MYCN(4)", "MYCN", "MYCN"),
        ("PRKACB_bis", "PRKACB", "PRKACB"),
        ("PRKACB_20080311_bis", "PRKACB", "PRKACB"),
        ("UBC(2)", "UBC", "UBC"),
        ("SDHA(1)", "SDHA", "SDHA"),
        ("WSB1_20080310", "WSB1", "WSB1"),
        ("HMBS", "HMBS", "HMBS"),
        ("NKX2-1", "NKX2-1", "NKX2-1"),  # a hyphen is part of the symbol
        ("GTF2H2C_2", "GTF2H2C_2", "GTF2H2C_2"),  # an underscore symbol is found before stripping
    ],
)
def test_assay_suffixes_are_removed_before_lookup(name, query, symbol):
    finding = check_symbol(name)
    assert finding.status == "approved"
    assert finding.query == query
    assert finding.candidates == (symbol,)
    assert finding.resolved == symbol


def test_alu_is_a_repeat_assay_not_a_gene():
    finding = check_symbol("ALUsq(Eurogentec)")
    assert finding.status == "non_gene"
    assert finding.candidates == ()
    assert finding.resolved is None
    assert normalise_assay_name("ALUsq(Eurogentec)") == "ALUsq"


def test_previous_and_alias_symbols_map_to_the_approved_symbol():
    nmyc = check_symbol("NMYC")
    assert (nmyc.status, nmyc.candidates) == ("previous", ("MYCN",))
    p53 = check_symbol("p53")
    assert (p53.status, p53.candidates) == ("alias", ("TP53",))
    march1 = check_symbol("MARCH1")
    assert (march1.status, march1.candidates) == ("previous", ("MARCHF1",))
    assert "Excel" in march1.note
    sept2 = check_symbol("SEPT2")
    assert sept2.status == "previous" and "SEPTIN2" in sept2.candidates


@pytest.mark.parametrize("value", ["1-Mar", "Mar-01", "01-MAR", "1 Mar", dt.datetime(2024, 3, 1)])
def test_date_mangled_march_lists_every_candidate(value):
    finding = check_symbol(value)
    assert finding.status == "date_mangled"
    assert {"MARCHF1", "MTARC1"} <= set(finding.candidates)  # MARCH1 and MARC1 both became 1-Mar
    assert {"MARCH1", "MARC1"} <= set(finding.matched)
    assert finding.ambiguous and finding.resolved is None


def test_date_mangled_september_and_others():
    sep = check_symbol("2-Sep")
    assert sep.status == "date_mangled" and "SEPTIN2" in sep.candidates
    assert check_symbol("15-Sep").candidates == ("SELENOF",)  # SEP15
    assert "DELEC1" in check_symbol("1-Dec").candidates  # DEC1
    assert check_symbol("4-Oct").candidates == ("POU5F1",)  # Oct4
    assert check_symbol("2.31E+19").status == "number_mangled"


def test_excel_date_parts():
    assert excel_date_parts("1-Mar") == [(3, 1)]
    assert excel_date_parts("Sep-02") == [(9, 2)]
    assert excel_date_parts("3/1/2024") == [(3, 1), (1, 3)]
    assert excel_date_parts("2024-03-01") == [(3, 1), (3, 24)]
    assert excel_date_parts("MYCN") == []


def test_unknown_and_case_blind():
    assert check_symbol("comp_primer").status == "unknown"
    assert check_symbol("TNFRSF").status == "unknown"
    actb = check_symbol("Actb")  # a mouse-style symbol
    assert actb.status == "approved" and actb.case_changed and actb.candidates == ("ACTB",)


def test_check_symbols_keeps_order():
    findings = check_symbols(["MYCN", "1-Mar", "ALUsq(Eurogentec)", "nonsense_xyz"])
    assert [f.status for f in findings] == ["approved", "date_mangled", "non_gene", "unknown"]
