"""G-INSTR reads the run file a Studio session's own instrument export holds.

The public corpus's synthetic CFX export of plate ``qpilot-synthetic-raw`` (amplification and Cq
results) is dropped on the page with the run's Run Information sheet
(:func:`tests.engine.instrument_files.cfx_run_information`), as a person exports "All Data
Sheets", and walked through Studio as a person would. The Controls route then reads that sheet as
the plate's run file, labelled as the export's own (not linked by a person); a run file a person
links still comes first, and unlinking it reads the export's again. No serial number and no
operator name ever comes back.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from qpilot.web.routers import gate as gate_router
from tests.engine import instrument_files as F
from tests.web.test_gate_routes import check_texts, ready, same_as_report
from tests.web.test_gate_runs import by_rule, link
from tests.web.test_workspaces_capture import SYNTH_CFX, opened

PLATE = "qpilot-synthetic-raw"
RUN_INFO = f"{PLATE} -  Run Information.csv"
SAMPLES = "Sample,Group\nS1,A\nS2,A\nS3,A\nS4,A\nS5,B\nS6,B\nS7,B\nS8,B\n"
SECRETS = ("CC000123", "785BR0001", F.OPERATOR, "AlexandraQuill")


@pytest.fixture(autouse=True)
def fresh_gate_cache():
    gate_router.clear()
    yield
    gate_router.clear()


def walk(studio, sid: str) -> str:
    """Accept what the rules propose and REF as the reference; confirm design and curves."""
    from qpilot.mcp_server import QpilotTools

    studio.propose_design(sid)
    QpilotTools(studio.store).qpcr_propose(sid, "design.target_role", "REF", {"role": "ref"})
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "checked")
    comparison = studio.propose_comparison(sid)
    studio.accept(sid, comparison.proposal.id, "human", "A is the reference")
    for stage in ("design", "curves"):
        if stage == "curves":
            studio.propose_curves(sid)
            for p in studio.inbox(sid, "curves", "proposed"):
                studio.accept(sid, p.id, "human", "checked")
        confirm = studio.propose_confirm(sid, stage)
        studio.accept(sid, confirm.proposal.id, "human")
    return studio.study(sid)


def export_files(folder: Path) -> list[Path]:
    """The CFX export of the plate with its Run Information, and a sample sheet, in ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    for path in SYNTH_CFX.glob(f"{PLATE} *"):
        shutil.copyfile(path, folder / path.name)
    F.cfx_run_information(folder / RUN_INFO)
    sheet = folder / "samples.csv"
    sheet.write_text(SAMPLES, encoding="utf-8")
    return [*sorted(folder.glob(f"{PLATE} *")), sheet]


def open_and_walk(client, studio, folder: Path) -> tuple[str, str]:
    """Drop the export on the page (``POST /api/workspaces``) and walk it: session, study."""
    sid, job = opened(client, export_files(folder))
    assert job["result"]["unused"] == []
    return sid, walk(studio, sid)


@pytest.fixture
def exported(sclient, studio_ctx, tmp_path):
    """The CFX export with its Run Information, opened over HTTP and walked to a study."""
    sid, study = open_and_walk(sclient, studio_ctx.studio, tmp_path / "export")
    return {"client": sclient, "store": studio_ctx.store, "sid": sid, "study": study,
            "tmp": tmp_path}  # fmt: skip


def test_the_exports_run_information_is_the_plates_run_file(exported):
    c, study, store = exported["client"], exported["study"], exported["store"]
    capture = c.get(f"/api/sessions/{exported['sid']}").json()["capture"]
    assert RUN_INFO in [s["name"] for s in capture["sources"]]
    body = ready(c, study).json()
    check_texts(body)
    same_as_report(body, gate_router.compute(store, study, None))
    assert [(r["plate"], r["source"], r["kind"], r["name"], r["linked_at"]) for r in body["runs"]] \
        == [(PLATE, "export", "cfx_run_information", RUN_INFO, None)]  # fmt: skip
    assert "reads each plate's run file in the export" in body["run_note"]
    (row,) = by_rule(body, "G-INSTR")
    assert (row["verdict"], row["code"]) == ("not_applicable", "nothing_to_check")
    assert row["reason"]["plain"] == (
        "This plate's run file in the instrument export names the instrument but records no run "
        "state, calibration or event to check."
    )
    assert body["runs"][0]["evaluation"] == row["id"]
    text = json.dumps(body)
    assert not any(secret in text for secret in SECRETS)


def test_a_persons_link_comes_first_and_unlinking_reads_the_exports_again(exported):
    c, study = exported["client"], exported["study"]
    eds = F.qs_v1_expired(exported["tmp"] / "run.eds", pause_at=23)
    r = link(c, study, PLATE, eds)
    assert r.status_code == 200, r.text
    body = ready(c, study).json()
    check_texts(body)
    (run,) = body["runs"]
    assert (run["source"], run["kind"], run["verdict"]) == ("linked", "eds", "warn")
    (row,) = by_rule(body, "G-INSTR")
    plain = row["reason"]["plain"]
    assert plain.startswith("From the run file a person linked to this plate:")
    # the date it is checked against is the export's own run date (the RDML has none)
    assert "The linked file's run date (2019-05-10) is not this plate's date in the study's " \
        "file (2020-02-27)" in plain  # fmt: skip
    r = c.post(f"/api/studies/{study}/gate/run-files/unlink", json={"plate": PLATE})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == (
        "Unlinked: G-INSTR reads this plate's run file in the instrument export again."
    )
    body = ready(c, study).json()
    assert [(x["source"], x["name"]) for x in body["runs"]] == [("export", RUN_INFO)]
    assert not any(secret in json.dumps(body) for secret in SECRETS)
