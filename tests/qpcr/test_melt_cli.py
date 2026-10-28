"""``qpilot melt``: what each well's melt curve says, from a file, without a study (reads only)."""

from __future__ import annotations

import json

from qpilot.cli import main
from tests.qpcr.melt_curves import HSIEH, RPA


def test_the_ten_assay_cfx_rdml_as_json(capsys):
    assert main(["melt", str(RPA), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["has_melt"] and out["pack"] == "research-default 1.2.0" and out["note"] == ""
    assert len(out["assays"]) == 10
    flagged = {(a["target"], f["well"], f["call"]) for a in out["assays"] for f in a["flagged"]}
    assert flagged == {
        ("HoxB1P1", "A4", "extra_peak"),
        ("HoxB9P4", "F4", "tm_off"),
        ("HoxB9P4", "F6", "tm_off"),
        ("LMNAP1", "H5", "tm_off"),
        ("LMNAP1", "H6", "tm_off"),
    }


def test_a_cfx_export_in_words(capsys):
    files = [str(p) for p in sorted(HSIEH.glob("*.csv"))]
    assert main(["melt", *files]) == 0
    text = capsys.readouterr().out
    assert "control: a peak at the product's Tm (contamination candidate)" in text
    assert text.count("G-MELT points at") == 2
    assert "does not guarantee that it is the intended amplicon (MIQE 2.0)" in text


def test_no_melt_curves_and_missing_files(capsys, fixtures_dir):
    assert main(["melt", str(fixtures_dir / "vermeulen_std_150000.rdml")]) == 0
    assert capsys.readouterr().out.strip() == "These files hold no melt curves."
    assert main(["melt", "no/such/file.rdml"]) == 2
    assert "no such file" in capsys.readouterr().err
