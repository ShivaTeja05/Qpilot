"""The Prism section over HTTP on the walked mini study (no demo download, no model, no Prism):

* Send writes a Prism project that opens as it is, with plain steps for Windows and macOS (no
  command line, no repo path);
* the round trip reads the project Prism saved, from the bundle folder or as an upload;
* a project accepted for an earlier analysis whose tables hold the same numbers stays current
  (no needless re-draft), checked in the background so no reading route waits for it;
* the Prism routes answer ``503 warming`` while the session's file is cold, and the usual-routes
  panel is cached per study.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path

import pytest
from lxml import etree

from qpilot.prism import pzfx
from tests.timing import work_time
from tests.web.conftest import wait_job

NS = {"p": pzfx.NAMESPACE}


def _decide_and_confirm(client, store, studio, sid: str) -> str:
    study = studio.study(sid)
    for card in store.cards(study):
        if card.status in ("open", "pending_human"):
            head = store.chain_head(study)
            studio.decide(sid, card.id, card.recommended, "the planned option", "human", head)
    studio.accept(sid, studio.propose_confirm(sid, "choices").proposal.id, "human")
    return study


@pytest.fixture
def ready(walked):
    """The walked mini session with confirmed choices and an accepted Prism project."""
    client, store, studio, sid = (walked[k] for k in ("client", "store", "studio", "sid"))
    study = _decide_and_confirm(client, store, studio, sid)
    drafted = wait_job(client, client.post(f"/api/sessions/{sid}/prism/draft").json()["job"])
    assert drafted["status"] == "done", drafted
    pid = drafted["result"]["proposal_id"]
    proposal = store.proposals(sid).get(pid)
    assert proposal.effective_payload().get("tables_sha256"), "the draft keeps its tables digest"
    studio.accept(sid, pid, "human")
    return {**walked, "study": study, "project_id": pid}


def _send(client, sid) -> dict:
    job = wait_job(client, client.post(f"/api/sessions/{sid}/prism/send").json()["job"], 600)
    assert job["status"] == "done", job
    return job["result"]


def test_send_writes_a_project_with_plain_steps_and_no_command(ready, monkeypatch):
    service = importlib.import_module("qpilot.studio_service")
    monkeypatch.setattr(service, "_mac_prism_app", lambda: None)
    monkeypatch.setattr(service, "_windows_prism_exe", lambda: None)
    client, sid = ready["client"], ready["sid"]
    sent = _send(client, sid)
    folder = Path(sent["bundle"]["folder"])
    assert sent["project"] == f"qpilot_{ready['study']}.pzfx"
    assert (folder / sent["project"]).is_file() and sent["project"] in sent["files"]
    assert not any(f.endswith(".pzc") for f in sent["files"])
    assert sent["command_line"] == "" and sent["send_back_command"] == ""
    assert sent["launched"] is False and "double-click the project file" in sent["launch_note"]
    assert [o["platform"] for o in sent["open_steps"]][0] == sent["this_platform"]
    assert {o["label"] for o in sent["open_steps"]} == {"Windows", "macOS"}
    words = " ".join(step for o in sent["open_steps"] for step in o["steps"])
    words += " ".join(sent["analyse_steps"] + sent["round_trip_steps"])
    assert "Double-click" in words and "Analyze" in words and "File > Save" in words
    for gone in ("osascript", "qpilot/prism/templates", "run.pzc", "prism.exe"):
        assert gone not in words and gone not in " ".join(sent["notes"])
    assert sent["bundle"]["project"] == str(folder / sent["project"])
    assert Path(sent["bundle"]["sent_back_folder"]) == folder  # Prism saves it back there
    project = pzfx.read_project((folder / sent["project"]).read_bytes())
    assert project.infos[0].title == "qPilot provenance"
    assert dict(project.infos[0].constants)["qPilot study"] == ready["study"]
    assert [t.kind for t in project.tables][0] == "column"


def _exclude_first(path: Path) -> tuple[str, str]:
    root = etree.fromstring(path.read_bytes())
    table = root.find("p:Table", NS)
    unit = table.find("p:RowTitlesColumn/p:Subcolumn/p:d", NS).text
    for column in table.findall("p:YColumn", NS):
        cell = column.find("p:Subcolumn/p:d", NS)
        if cell.text:
            cell.set("Excluded", "1")
            break
    path.write_bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))
    return table.find("p:Title", NS).text, unit


def test_the_round_trip_reads_the_saved_project_from_the_bundle_folder(ready):
    client, studio, sid = ready["client"], ready["studio"], ready["sid"]
    sent = _send(client, sid)
    folder = Path(sent["bundle"]["folder"])
    _, unit = _exclude_first(folder / sent["project"])
    job = wait_job(
        client,
        client.post(
            f"/api/sessions/{sid}/prism/roundtrip",
            json={"bundle": sent["bundle"]["id"], "folder": str(folder)},
        ).json()["job"],
        600,
    )
    assert job["status"] == "done", job
    result = job["result"]
    assert result["source"] == "project"
    (item,) = result["items"]
    assert item["kind"] == "excluded" and item["row"] == unit
    (pid,) = result["proposed"]
    proposal = next(p for p in studio.inbox(sid, "roundtrip", "proposed") if p.id == pid)
    assert proposal.payload["question"].startswith("You excluded sample")
    # the saved project's own path is accepted too
    r = client.post(
        f"/api/sessions/{sid}/prism/roundtrip",
        json={"bundle": sent["bundle"]["id"], "folder": str(folder / sent["project"])},
    )
    assert r.status_code == 202, r.text
    wait_job(client, r.json()["job"], 600)


def test_the_round_trip_takes_an_uploaded_project(ready, tmp_path):
    client, sid = ready["client"], ready["sid"]
    sent = _send(client, sid)
    folder = Path(sent["bundle"]["folder"])
    saved = tmp_path / "saved on the Prism PC.pzfx"
    saved.write_bytes((folder / sent["project"]).read_bytes())
    _, unit = _exclude_first(saved)
    url = f"/api/sessions/{sid}/prism/roundtrip/upload"
    with saved.open("rb") as fh:
        r = client.post(
            url,
            data={"bundle": sent["bundle"]["id"]},
            files={"project": (saved.name, fh, "application/xml")},
        )
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"], 600)
    assert job["status"] == "done", job
    assert [(i["kind"], i["row"]) for i in job["result"]["items"]] == [("excluded", unit)]
    kept = list((folder / "returned").glob("*.pzfx"))
    assert len(kept) == 1 and kept[0].read_bytes() == saved.read_bytes()
    refused = client.post(
        url,
        data={"bundle": sent["bundle"]["id"]},
        files={"project": ("notes.txt", b"hello", "text/plain")},
    )
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "not_pzfx"
    unknown = client.post(
        url,
        data={"bundle": "zzzzzzzz"},
        files={"project": ("x.pzfx", b"<x/>", "application/xml")},
    )
    assert unknown.status_code == 404


def test_a_file_outside_the_allowed_folders_is_refused(ready, tmp_path):
    client, ctx, sid = ready["client"], ready["ctx"], ready["sid"]
    sent = _send(client, sid)
    store_file = ctx.store.root / "x.pzfx"
    store_file.write_bytes(b"<x/>")
    for bad in (str(store_file), "relative.pzfx", str(tmp_path / "missing.pzfx")):
        r = client.post(
            f"/api/sessions/{sid}/prism/roundtrip",
            json={"bundle": sent["bundle"]["id"], "folder": bad},
        )
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_folder", (bad, r.text)


def test_a_project_for_an_earlier_analysis_with_the_same_tables_stays_current(ready, monkeypatch):
    """The UX walk's needless re-draft: a new analysis id, the same numbers in every table."""
    client, store, studio, sid = (ready[k] for k in ("client", "store", "studio", "sid"))
    proposal = store.proposals(sid).get(ready["project_id"])
    digest = proposal.effective_payload()["tables_sha256"]
    status = client.get(f"/api/sessions/{sid}/prism").json()
    assert status["project"]["status"] == "accepted" and not status["project"]["still_current"]
    # Another analysis of the session (as a decision that changed no number makes one): its
    # tables digest is computed from its own tables, here the same numbers as the earlier one.
    monkeypatch.setattr(type(studio), "study", lambda self, s: "0a0a0a0a0a0a")
    monkeypatch.setattr(
        importlib.import_module("qpilot.prism"),
        "project_digest",
        lambda store_, study_id, genes=None: digest,
    )
    monkeypatch.setattr(store, "chain_head", lambda study_id: "ab" * 32)
    first = client.get(f"/api/sessions/{sid}/prism").json()
    assert first["project"]["checking"] or first["project"]["still_current"]
    deadline = time.monotonic() + 60
    while True:
        status = client.get(f"/api/sessions/{sid}/prism").json()
        if status["project"]["status"] == "accepted" or time.monotonic() > deadline:
            break
        time.sleep(0.05)
    project = status["project"]
    assert project["status"] == "accepted" and project["still_current"] is True
    assert (
        project["drafted_for"] == ready["study"] and project["proposal_id"] == ready["project_id"]
    )
    assert "still current" in status["next"] and status["can_send"] is True
    # when a number changed, the earlier project does not hold
    monkeypatch.setattr(
        importlib.import_module("qpilot.prism"),
        "project_digest",
        lambda store_, study_id, genes=None: "0" * 64,
    )
    monkeypatch.setattr(store, "chain_head", lambda study_id: "cd" * 32)
    deadline = time.monotonic() + 60
    while True:
        status = client.get(f"/api/sessions/{sid}/prism").json()
        if not status["project"]["checking"] or time.monotonic() > deadline:
            break
        time.sleep(0.05)
    assert status["project"]["status"] == "none" and not status["project"]["still_current"]


def test_prism_routes_answer_warming_while_the_file_is_cold(ready):
    from qpilot.qpcr import inspect as qinspect

    client, ctx, sid = ready["client"], ready["ctx"], ready["sid"]
    qinspect.clear_cache()  # as after a restart
    ctx.facts_wait = 0.0
    try:
        r = client.get(f"/api/sessions/{sid}/prism/routes")
        if r.status_code == 503:  # the file is read in the background meanwhile
            assert r.json()["error"]["code"] == "warming"
            wait_job(client, r.json()["error"]["details"]["job"])
    finally:
        ctx.facts_wait = None
    assert client.get(f"/api/sessions/{sid}/prism/routes").status_code == 200


def test_the_routes_panel_is_cached_per_study(ready, monkeypatch):
    client, sid = ready["client"], ready["sid"]
    first = client.get(f"/api/sessions/{sid}/prism/routes")
    assert first.status_code == 200
    calls = []
    from qpilot.web.routers import files

    real = files._routes_view
    monkeypatch.setattr(files, "_routes_view", lambda *a: calls.append(a) or real(*a))
    again = client.get(f"/api/sessions/{sid}/prism/routes")
    assert again.json() == first.json() and calls == []
    with work_time() as spent:
        client.get(f"/api/sessions/{sid}/prism/routes")
    assert spent.seconds < 2.0, spent
