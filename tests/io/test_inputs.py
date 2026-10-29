"""The files a person opened, by their own names, from the path qPilot kept them under."""

from __future__ import annotations

import shutil
from pathlib import Path

from qpilot.io import inputs
from qpilot.io.connectors import materialise

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
SYNTH_CFX = CORPUS / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"


def test_a_converted_export_is_named_by_every_file_it_was_read_from(tmp_path):
    files = sorted(SYNTH_CFX.glob("qpilot-synthetic-raw *"))
    built = materialise(files, cache_dir=tmp_path)
    assert built.rdml_path.parent.name == "capture" and inputs.is_converted(built.rdml_path)
    named = inputs.input_files(built.rdml_path)
    assert [f.name for f in named] == [p.name for p in files]
    assert {f.role for f in named} == {"amplification", "cq"}
    assert all(len(f.sha256) == 64 and f.bytes for f in named)
    assert inputs.input_label(built.rdml_path) == ", ".join(p.name for p in files)


def test_a_kept_upload_is_named_as_it_was_on_the_persons_computer(tmp_path):
    kept = tmp_path / "studio-inputs" / "62e1627642b28bb029cf916a.rdml"
    kept.parent.mkdir()
    shutil.copyfile(CORPUS / "rdml" / "stepone-2.3-rdml-1.0" / "stepone_std.rdml", kept)
    names = tmp_path / "studio-input-names"
    names.mkdir()
    (names / kept.name).write_text("Liver KO vs WT.rdml", encoding="utf-8")
    assert inputs.input_label(kept) == "Liver KO vs WT.rdml"
    (only,) = inputs.input_files(kept)
    assert only.name == "Liver KO vs WT.rdml" and len(only.sha256) == 64
    assert not inputs.is_converted(kept)


def test_any_other_file_keeps_its_own_name_and_many_files_are_counted(tmp_path):
    plain = tmp_path / "data_vermeulen_raw.rdml"
    plain.write_bytes(b"x")
    assert inputs.input_label(plain) == "data_vermeulen_raw.rdml"
    assert inputs.input_label(None) is None
    capture = tmp_path / "imports" / "capture"
    capture.mkdir(parents=True)
    rdml = capture / "4f8d9806a92cf1a21a9b.rdml"
    rdml.write_bytes(b"x")
    sources = [{"name": f"plate{i}.csv", "sha256": "ab" * 32, "bytes": 1} for i in range(5)]
    (capture / "4f8d9806a92cf1a21a9b.capture.json").write_text(
        __import__("json").dumps({"sources": sources}), encoding="utf-8"
    )
    assert inputs.input_label(rdml) == "plate0.csv, plate1.csv and 3 more files"
