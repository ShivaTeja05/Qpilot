"""The Evidence Ledger's efficiency line never shows LinRegPCR's "no mean efficiency" sentinel.

LinRegPCR writes ``-1`` as a gene's mean efficiency on a plate when it cannot compute one (no well
in its window of linearity; the LightCycler 96 file of the corpus has one such channel). The line
"gene medians run from … to …" once printed ``-1.00`` as if it were an efficiency. The sentinel
is now left out of the gene medians: the line names the real lowest and highest gene medians.
"""

from __future__ import annotations

from pathlib import Path

from qpilot.explain.evidence_text import render_evidence
from tests.engine.evidence_toys import TARGETS, toy_table
from tests.engine.test_evidence import fact, ledger

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus" / "rdml"


def _efficiency_line(led) -> str:
    (line,) = (x for x in render_evidence(led).plain.split("\n") if "fficiency" in x)
    return line


def test_a_gene_without_a_mean_efficiency_is_left_out_of_the_gene_medians():
    table = toy_table()
    table.loc[table["target"] == "T2", "eff_target"] = -1.0  # LinRegPCR: no mean on that plate
    table.loc[table["target"] == "T1", "eff_target"] = 1.80
    led = ledger(table)
    assert fact(led, "efficiency", "min") == 1.80
    assert fact(led, "efficiency", "max") == 1.95
    line = _efficiency_line(led)
    assert "-1" not in line and "gene medians run from 1.80 to 1.95" in line


def test_the_sentinel_alone_changes_nothing_else():
    clean = ledger(toy_table())
    table = toy_table()
    table.loc[table["target"] == TARGETS[-1], "eff_target"] = -1.0
    led = ledger(table)
    for name in ("n_wells", "n_wells_with_eff", "n_plates", "n_plates_with_series"):
        assert fact(led, "efficiency", name) == fact(clean, "efficiency", name)
    assert led.item("efficiency").status == "present"


def test_the_lightcycler_96_file_shows_its_real_efficiencies():
    """A real export with a channel LinRegPCR gave no mean efficiency (320 wells at -1)."""
    from qpilot.qpcr.curves import CurveSettings, analyse_study
    from qpilot.qpcr.evidence import _efficiency, _study_wells

    table = analyse_study(CORPUS / "lightcycler96-rdml-1.1" / "lc96_bACTXY.rdml", None, (),
                          CurveSettings())  # fmt: skip
    assert (table["eff_target"] == -1.0).any()  # the sentinel is in the file's analysis
    draft = _efficiency(table, _study_wells(table))
    low, high = draft.values["min"][0], draft.values["max"][0]
    assert 1.0 < low <= high < 2.5
