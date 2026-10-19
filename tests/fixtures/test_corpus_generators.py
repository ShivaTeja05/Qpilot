"""The synthetic corpus files are exactly what the generator writes, and their truth holds."""

from __future__ import annotations

import csv
import importlib.util
import io
import math
import sys
from pathlib import Path

CORPUS = Path(__file__).parent / "corpus"
GENERATOR = CORPUS / "_generators" / "qpcr_synth.py"
CFX = CORPUS / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"
QS = CORPUS / "synthetic" / "quantstudio-design-analysis-rn-drn"


def _generator():
    spec = importlib.util.spec_from_file_location("qpcr_synth", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up while the class is built
    spec.loader.exec_module(module)
    return module


def _wide(path: Path) -> dict[str, list[float]]:
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    wells = rows[0][2:]
    return {w: [float(r[i + 2]) for r in rows[1:]] for i, w in enumerate(wells)}


def _truth(folder: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO((folder / "truth.csv").read_text(encoding="utf-8"))))


def test_generator_reproduces_committed_files_byte_for_byte(tmp_path):
    written = _generator().generate(tmp_path)
    assert len(written) == 8
    for path in written:
        committed = CORPUS / "synthetic" / path.relative_to(tmp_path)
        assert committed.read_bytes() == path.read_bytes(), committed.name


def test_cfx_raw_and_baselined_are_the_same_curves():
    raw = _wide(CFX / "qpilot-synthetic-raw -  Quantification Amplification Results_SYBR.csv")
    bs = _wide(CFX / "qpilot-synthetic-baselined -  Quantification Amplification Results_SYBR.csv")
    assert raw.keys() == bs.keys()
    assert len(raw) == 80 and "H1" not in raw and "E6" not in raw
    for well, ys in raw.items():
        diff = [a - b for a, b in zip(ys, bs[well], strict=True)]
        steps = {round(diff[i + 1] - diff[i], 6) for i in range(len(diff) - 1)}
        assert len(steps) == 1, well  # raw - baselined is a straight line
        assert min(ys) > 900  # raw: ground phase is the background, far from zero
    ground = [v for ys in bs.values() for v in ys[2:15]]
    assert abs(sum(ground) / len(ground)) < 5  # baselined: ground phase centred on zero


def test_truth_matches_the_design():
    truth = _truth(CFX)
    assert truth == _truth(QS)
    by_content = {}
    for row in truth:
        by_content.setdefault(row["content"], []).append(row)
    assert {k: len(v) for k, v in by_content.items()} == {"Unkn": 48, "Std": 20, "NTC": 6, "NRT": 6}
    late_ntc = [r["well"] for r in by_content["NTC"] if r["cq_cfx_threshold_250"]]
    gdna_nrt = [r["well"] for r in by_content["NRT"] if r["cq_cfx_threshold_250"]]
    assert late_ntc == ["G9"] and gdna_nrt == ["G4"]
    assert float(next(r for r in truth if r["well"] == "G9")["cq_cfx_threshold_250"]) > 35


def test_fold_change_and_efficiency_are_recoverable():
    truth = [r for r in _truth(CFX) if r["content"] == "Unkn"]

    def mean_log(target, group):
        values = [
            math.log2(float(r["n0"]))
            for r in truth
            if r["target"] == target and r["group"] == group
        ]
        return sum(values) / len(values)

    log_fc = (mean_log("GOI", "B") - mean_log("REF", "B")) - (
        mean_log("GOI", "A") - mean_log("REF", "A")
    )
    assert abs(2**log_fc - 3.69) < 0.01  # design 4.0; 5 % per-well pipetting noise
    for target, expected in (("REF", 1.92), ("GOI", 1.86)):
        effs = [float(r["efficiency"]) for r in _truth(CFX) if r["target"] == target]
        assert abs(sum(effs) / len(effs) - expected) < 0.01


def test_quantstudio_rn_is_reporter_over_rox():
    raw = _wide(CFX / "qpilot-synthetic-raw -  Quantification Amplification Results_SYBR.csv")
    rox = {r["well"]: float(r["rox_rfu"]) for r in _truth(QS)}
    text = (QS / "qpilot-synthetic_Amplification Data.csv").read_text(encoding="utf-8")
    body = [line for line in text.splitlines() if not line.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(body))))
    assert len(rows) == 80 * 40
    for row in rows[::97]:
        well, cycle = row["Well Position"], int(row["Cycle Number"])
        assert math.isclose(float(row["Rn"]), raw[well][cycle - 1] / rox[well], rel_tol=1e-12)
    assert text.startswith("# File Name: qpilot-synthetic.eds")
    assert "SYNTHETIC" in text.splitlines()[1]
