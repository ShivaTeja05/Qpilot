"""The gene-symbol gate never reads a qPCR label as a gene, and says which evidence names one.

``REF`` is an HGNC alias of ALYREF and ``STD`` a previous symbol of two genes, so the gate used
to offer ``REF -> ALYREF`` and the design check called it consistent: "Accept all consistent"
would have renamed a reference gene to a gene nobody measured.
"""

from __future__ import annotations

import pytest

from qpilot.io.symbols import check_symbol


@pytest.mark.parametrize(
    "name",
    ["REF", "Ref", "ref", "REF1", "Ref_2", "Reference", "NTC", "NRT", "STD", "STD 3", "Standard",
     "CTRL", "Control", "GOI", "GOI2", "Target", "Target 2", "IPC", "HK", "KO", "WT", "X", "Y"],
)  # fmt: skip
def test_a_qpcr_label_is_not_a_gene(name):
    finding = check_symbol(name)
    assert finding.status == "non_gene", (name, finding)
    assert finding.candidates == () and finding.resolved is None and not finding.identifies


@pytest.mark.parametrize("name", ["HK1", "HK2", "WT1", "GAPDH", "MYC", "PC", "UBC(2)"])
def test_real_genes_that_look_like_labels_stay_genes(name):
    finding = check_symbol(name)
    assert finding.status == "approved" and finding.identifies, (name, finding)


def test_only_evidence_that_names_one_gene_identifies_it():
    assert check_symbol("NMYC").identifies  # a previous symbol of one gene: HGNC renamed it
    p53 = check_symbol("p53")
    assert (p53.status, p53.candidates, p53.identifies) == ("alias", ("TP53",), False)
    assert "confirm the gene" in p53.note
    act1 = check_symbol("ACT1")  # yeast actin in the corpus; an HGNC alias of TRAF3IP2
    assert act1.status == "alias" and not act1.identifies
    gapdh = check_symbol("Gapdh")  # the mouse spelling: a human symbol only ignoring case
    assert gapdh.case_changed and not gapdh.identifies
    assert not check_symbol("1-Mar").identifies  # Excel's date of three genes' names
    assert not check_symbol("CTL1").identifies  # an alias: SLC44A1 or "control 1"


def test_the_design_rules_no_longer_propose_renaming_a_reference_label():
    from qpilot.qpcr.design_rules import _symbol_field

    assert _symbol_field("REF", "t1", {}) is None
    assert _symbol_field("GOI", "t2", {}) is None
    gapdh = _symbol_field("GAPDH", "t3", {})
    assert gapdh is not None and gapdh.value == {"symbol": "GAPDH"}
