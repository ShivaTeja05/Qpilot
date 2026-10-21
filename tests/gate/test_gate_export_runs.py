"""G-INSTR reads the run file a plate's own instrument export holds (``qpcr/export_runs.py``).

A session opened from a vendor export is analysed from the RDML qPilot built from it, which says
nothing about the run; the export's own files often do (a QuantStudio results export's header
rows, CFX run information). Each plate records the files it was read from (``PlateMeta.sources``;
read from the file names as the connectors group them for a capture recorded before it did); the
plate's run file is read from the folder that keeps the files by content, checked by sha256, and
G-INSTR says it read the export's file. A run file a person links comes first, the study's RDML
last. Synthetic run files (``tests/engine/instrument_files``), the corpus's synthetic CFX export
and one public QuantStudio text export of the corpus; no download.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from qpilot.core.rules import NOT_APPLICABLE
from qpilot.core.store import sha256_file
from qpilot.io.connectors import CaptureMeta, capture
from qpilot.io.connectors.common import plate_sources
from qpilot.qpcr.export_runs import export_runs
from qpilot.qpcr.gate_rules import GateContext, file_runs, with_export, with_linked
from qpilot.qpcr.instrument_context import read_run_context
from tests.engine import instrument_files as F
from tests.gate.test_gate_rt_instr import G_INSTR, core_gate_plain, evals_of, plate_table

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
SYNTH_CFX = CORPUS / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"
ALLOTROPY = CORPUS / "thermofisher" / "allotropy-quantstudio-rtpcr-txt"
RAW, BASELINED = "qpilot-synthetic-raw", "qpilot-synthetic-baselined"
RUN_INFO = f"{RAW} -  Run Information.csv"
CFX_SECRETS = ("CC000123", "785BR0001", F.OPERATOR, "AlexandraQuill")
QS_SECRETS = ("278880001", F.OPERATOR, "AlexandraQuill")
LEAD = "From this plate's run file in the instrument export:"


def keep(folder: Path, paths: list[Path]) -> Path:
    """The files kept by content (``<sha256[:24]><suffix>``), as the page keeps every drop."""
    folder.mkdir(exist_ok=True)
    for path in paths:
        shutil.copyfile(path, folder / f"{sha256_file(path)[:24]}{path.suffix.lower()}")
    return folder


def cfx_export(folder: Path, *stems: str) -> list[Path]:
    """The corpus's synthetic CFX export of each run, with the raw run's Run Information."""
    folder.mkdir()
    for stem in stems:
        for path in SYNTH_CFX.glob(f"{stem} *"):
            shutil.copyfile(path, folder / path.name)
    F.cfx_run_information(folder / RUN_INFO)
    return sorted(folder.iterdir())


def without_plate_files(meta: CaptureMeta) -> CaptureMeta:
    """``meta`` as a capture recorded before plates named their files."""
    plates = [p.model_copy(update={"sources": []}) for p in meta.plates]
    return meta.model_copy(update={"plates": plates})


def instr(runs) -> tuple[GateContext, list]:
    ctx = GateContext(table=plate_table(tuple(runs)), runs=runs)
    return ctx, evals_of(G_INSTR, ctx)


# ---------- which files each plate was read from ----------


def test_each_plate_names_the_files_it_was_read_from(tmp_path):
    files = cfx_export(tmp_path / "x", RAW, BASELINED)
    meta = capture(files).meta
    expected = {
        RAW: sorted(p.name for p in files if p.name.startswith(f"{RAW} ")),
        BASELINED: sorted(p.name for p in files if p.name.startswith(f"{BASELINED} ")),
    }
    assert RUN_INFO in expected[RAW] and len(expected[BASELINED]) == 2
    assert {p.run_id: sorted(p.sources) for p in meta.plates} == expected
    assert {k: sorted(v) for k, v in plate_sources(meta).items()} == expected
    # a capture recorded before: the files are grouped by the plate their stem names
    older = plate_sources(without_plate_files(meta))
    assert {k: sorted(v) for k, v in older.items()} == expected
    # one plate: every file is its own
    qs = F.quantstudio_csv(tmp_path / "QS5 run_Results.csv")
    assert plate_sources(without_plate_files(capture([qs]).meta)) == {"QS5 run": [qs.name]}


# ---------- the export's run file, read for its plate ----------


def test_a_quantstudio_results_exports_header_is_its_plates_run_file(tmp_path):
    qs = F.quantstudio_csv(tmp_path / "QS5 run_Results.csv", expired={"Background": "Yes"})
    meta = capture([qs]).meta
    (plate,) = (p.run_id for p in meta.plates)
    found = export_runs(meta, keep(tmp_path / "kept", [qs]))
    assert set(found) == {plate}
    run = found[plate]
    assert (run.name, run.sha256) == (qs.name, sha256_file(qs))
    assert run.context.source_kind == "quantstudio_export"
    runs = with_export({}, {plate: run.context})
    assert runs[plate].source == "export" and not runs[plate].linked
    ctx, (ev,) = instr(runs)
    assert (ev.verdict, ev.outcome) == ("warn", "calibration_expired")
    shown = core_gate_plain(ev, ctx)
    assert shown.startswith(LEAD) and "Background calibration" in shown
    assert ev.evidence["source"] == "export run file"
    assert ev.evidence["source_kind"] == "quantstudio_export"
    assert ev.flagged == [f"{plate}/A1", f"{plate}/A2"]  # the plate's study wells
    assert ev.options == {"exclude_run": ev.flagged}
    values = " ".join(str(f.value) for f in ctx.facts.as_dict().values())
    for secret in QS_SECRETS:
        assert secret not in shown + repr(ev.evidence) + values


def test_cfx_run_information_is_its_runs_file_and_the_data_sheets_are_not(tmp_path):
    files = cfx_export(tmp_path / "x", RAW, BASELINED)
    meta = capture(files).meta
    found = export_runs(meta, keep(tmp_path / "kept", files))
    assert set(found) == {RAW}  # the baselined run's export has no Run Information
    assert found[RAW].name == RUN_INFO
    assert found[RAW].context.source_kind == "cfx_run_information"
    ctx, (ev,) = instr(with_export({}, {RAW: found[RAW].context}))
    assert (ev.verdict, ev.code) == (NOT_APPLICABLE, "nothing_to_check")
    assert core_gate_plain(ev, ctx) == (
        "This plate's run file in the instrument export names the instrument but records no run "
        "state, calibration or event to check."
    )  # and no RDML hint: the export's file is not RDML
    for secret in CFX_SECRETS:
        assert secret not in ev.reason + repr(ev.evidence)


def test_a_real_quantstudio_text_export_is_its_own_plates_run_file(tmp_path):
    path = ALLOTROPY / "appbio_quantstudio_example02.txt"
    meta = capture([path]).meta
    found = export_runs(meta, keep(tmp_path / "kept", [path]))
    ((plate, run),) = found.items()
    assert plate == "appbio_quantstudio_example02" and run.name == path.name
    assert run.context.source_kind == "quantstudio_export" and "calibrations" in run.context.checked
    ctx, (ev,) = instr(with_export({}, {plate: run.context}))
    assert (ev.verdict, ev.outcome) == ("pass", "calibrations_in_date")
    assert core_gate_plain(ev, ctx).startswith(LEAD)


def test_a_kept_file_that_is_gone_or_changed_is_not_read(tmp_path):
    files = cfx_export(tmp_path / "x", RAW)
    meta = capture(files).meta
    assert export_runs(meta, tmp_path / "nowhere") == {}  # an export opened outside the page
    kept = keep(tmp_path / "kept", files)
    path = kept / f"{sha256_file(tmp_path / 'x' / RUN_INFO)[:24]}.csv"
    assert set(export_runs(meta, kept)) == {RAW}
    path.write_bytes(path.read_bytes() + b"Notes,changed\n")
    assert export_runs(meta, kept) == {}
    path.unlink()
    assert export_runs(meta, kept) == {}


# ---------- a person's link first, then the export's file, then the study's own ----------


def test_a_linked_file_comes_first_then_the_exports_then_the_studys_own(tmp_path):
    rdml = F.write_rdml(tmp_path / "runs.rdml", [{"id": "P1"}, {"id": "P2"}, {"id": "P3"}])
    own = file_runs(rdml)
    exported = read_run_context(F.quantstudio_csv(tmp_path / "qs.csv"))  # ended 2019-09-11
    eds = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds"))  # ran 2019-05-10
    runs = with_linked(with_export(own, {"P1": exported, "P2": exported}), {"P1": eds})
    assert {p: r.source for p, r in runs.items()} == {
        "P1": "linked",
        "P2": "export",
        "P3": "study_file",
    }
    assert runs["P1"].context is eds and runs["P1"].study_date == "2019-09-11"
    ctx, (p1, p2, p3) = instr(runs)
    assert p1.evidence["source"] == "linked run file"
    assert "The linked file's run date (2019-05-10) is not this plate's date in the study's " \
        "file (2019-09-11)" in core_gate_plain(p1, ctx)  # fmt: skip
    assert p2.evidence["source"] == "export run file" and p2.reason.startswith(LEAD)
    assert p3.evidence["source"] == "study file" and "RDML has no field" in p3.reason
