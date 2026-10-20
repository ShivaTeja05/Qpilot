"""Step 3.1 gate: the demo preset reproduces every locked number byte for byte.

``BEFORE`` holds the sha256 of the four output files of ``run_study(demo)`` with
``StudySettings()``, captured at commit 603d06b before the design work began (Python 3.11, the
project's pinned environment). A mismatch means the default analysis changed: report it, never
update these values to make the test pass. ``results.json`` was re-pinned once, on the
coordinator's decision (#0395), after a JSON diff proved that only the confidence reasons' words
changed (#0286: "of the 186 analyses qPilot checks"); every number and every other file is as
captured.
"""

import hashlib
from pathlib import Path

import pytest

from qpilot.cli import main
from qpilot.qpcr.designs import vermeulen_design
from qpilot.qpcr.study import StudySettings, run_study, write_outputs

REPO = Path(__file__).resolve().parents[2]
DEMO_YAML = REPO / "demo" / "vermeulen.study.yaml"
BEFORE = {
    "cards.json": "c0d8310cce7acccceb55d5d50282a18cedc7f8f7074d69988c5eb8e9b74c0ddc",
    "facts.json": "c09e000bb9764aaef135f6fdf84a9779122ac46d95c04288a31a42a8f56bf31b",
    "grid.csv": "2ef579ff8aa85d4b25da03fdc5491791bcede93be7ff099729731fd2f4e116b1",
    "results.json": "2ba286ac6234db3687ef189054fd7eb76f091ec34135d97e82bfad275c4f3fc5",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preset_settings_are_the_default_settings():
    settings = StudySettings.from_design(vermeulen_design())
    assert settings == StudySettings()
    assert settings.design is None and not settings.studio_facts
    assert settings.amp_calls == ("linregpcr",)


def test_cli_design_options_are_checked(tmp_path, capsys):
    assert main(["run", "--samples", str(tmp_path / "s.csv")]) == 1
    assert "--samples needs --design" in capsys.readouterr().err
    assert main(["run", "--design", str(DEMO_YAML), "--refs", "HMBS"]) == 1
    assert "set --refs in the design file" in capsys.readouterr().err
    assert main(["run", str(tmp_path / "x.rdml"), "--design", str(tmp_path / "none.yaml")]) == 1
    assert "qpilot run" in capsys.readouterr().err


@pytest.mark.demo_data
def test_demo_preset_is_byte_identical_to_before(demo_rdml_path, tmp_path):
    default = write_outputs(*run_study(demo_rdml_path), tmp_path / "default")
    settings = StudySettings.from_design(vermeulen_design())
    preset = write_outputs(*run_study(demo_rdml_path, settings), tmp_path / "preset")
    assert sorted(default) == sorted(BEFORE)
    for name, digest in BEFORE.items():
        assert _sha(default[name]) == digest, f"{name} changed at the default settings"
        assert default[name].read_bytes() == preset[name].read_bytes(), name


@pytest.mark.demo_data
def test_cli_run_with_a_groups_design_and_sample_sheet(
    demo_rdml_path, demo_matrix, tmp_path, capsys
):
    import json

    samples = list(demo_matrix.index[:12])
    rows = ["sample,group,biological_unit"]
    rows += [f"{s},A,unit{i // 2}" for i, s in enumerate(samples[:6])]  # two preps per unit
    rows += [f"{s},B," for s in samples[6:]]
    (tmp_path / "sheet.csv").write_text("\n".join(rows) + "\n")
    (tmp_path / "study.yaml").write_text(
        "design_id: cli_groups\nexperiment_id: biomarker_set\nmode: groups\n"
        "comparison: {group_a: A, group_b: B}\n"
        "reference_candidates: [ALUsq(Eurogentec), HMBS, HPRT1, SDHA(1), UBC(2)]\n"
        "headline: [ODC1]\n"
    )
    out = tmp_path / "out"
    argv = ["run", str(demo_rdml_path), "--design", str(tmp_path / "study.yaml")]
    argv += ["--samples", str(tmp_path / "sheet.csv"), "--out", str(out)]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    assert "A vs B: 3 vs 6 biological units (groups from the confirmed design)" in printed
    results = json.loads((out / "results.json").read_text())
    assert results["design"]["cut"] == 0.0 and results["study_id"] != "bc1d233e3866"
    assert [c["id"] for c in json.loads((out / "cards.json").read_text())] == [
        "card_refset",
        "card_undetermined",
    ]
    facts = json.loads((out / "facts.json").read_text())
    assert facts["f_n_hi"]["value"] == 3 and "f_n_differ_route_ddcq" in facts
    assert "cut" not in (out / "grid.csv").read_text().splitlines()[0].split(",")


@pytest.mark.demo_data
def test_cli_run_with_the_demo_design_file(demo_rdml_path, tmp_path, capsys):
    out = tmp_path / "design"
    assert main(["run", str(demo_rdml_path), "--design", str(DEMO_YAML), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "MYCN-high 53 vs rest 294" in printed and f"(study {'bc1d233e3866'})" in printed
    for name, digest in BEFORE.items():
        assert _sha(out / name) == digest, name
