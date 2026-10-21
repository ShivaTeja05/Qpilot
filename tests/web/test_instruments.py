"""The Instruments section's API (origin/main's instrument registry and logbook, on the page).

What an agent may only propose over MCP, a person does here: confirm or turn down an incident,
note a fix. Every write is a person's; serial numbers and identity strings never come back; a
run file that names no registered instrument asks once, and the answer is remembered; the
logbook stays a verifying hash chain; the lookback reads only and follows the blind rule.
"""

from __future__ import annotations

import json

import pytest

from qpilot.core.instruments import Registry, log_incident
from tests.engine import instrument_files as F
from tests.web.conftest import wait_job

SERIALS = ("278880001", "BLK-1001", "HC-2001")


@pytest.fixture
def reg(web_store):
    registry = Registry(web_store.root / "instruments")
    registry.register("qs-1", "QuantStudio by the window", make_model="QS5", serials=["278880001"])
    return registry


def test_the_registry_lists_state_and_never_a_serial(client, reg):
    body = client.get("/api/instruments").json()
    (inst,) = body["instruments"]
    assert inst["instrument_id"] == "qs-1" and inst["display_name"] == "QuantStudio by the window"
    assert inst["chain_ok"] is True and inst["n_open_incidents"] == 0
    assert {k["id"] for k in body["kinds"]} == {
        "calibration",
        "component_change",
        "service",
        "move",
        "note",
    }
    assert "278880001" not in json.dumps(body)


def test_a_person_registers_logs_and_the_chain_verifies(client, reg):
    r = client.post("/api/instruments", json={"display_name": "CFX in room 2", "location": "R2"})
    assert r.status_code == 200, r.text
    new_id = r.json()["instrument"]["instrument_id"]
    again = client.post("/api/instruments", json={"display_name": "x", "instrument_id": new_id})
    assert again.status_code == 422
    cal = client.post(
        f"/api/instruments/{new_id}/events",
        json={"kind": "calibration", "calibration_type": "background", "at": "2026-10-01"},
    )
    assert cal.status_code == 200, cal.text
    view = cal.json()["instrument"]
    assert view["instrument"]["calibrations"][0]["type"] == "background"
    assert view["instrument"]["calibrations"][0]["performed_on"] == "2026-10-01"
    (event,) = view["events"]
    assert event["actor"] == "human" and event["source"] == "typed"
    note = client.post(
        f"/api/instruments/{new_id}/events", json={"kind": "note", "note": "<b>lamp</b> warm"}
    ).json()
    assert note["instrument"]["events"][-1]["note"] == "<b>lamp</b> warm"  # text, as typed
    assert Registry(reg.root).logbook(new_id).verify() == []
    assert (
        client.post(f"/api/instruments/{new_id}/events", json={"kind": "note"}).status_code == 422
    )
    assert (
        client.post(f"/api/instruments/{new_id}/events", json={"kind": "incident"}).status_code
        == 422
    )


def test_only_a_person_confirms_turns_down_or_fixes_an_agents_incident(client, reg):
    book = reg.logbook("qs-1")
    proposed = log_incident(
        book, actor="agent", wells=["B3"], signature={"metric": "plateau", "direction": "low"}
    )
    second = log_incident(
        book, actor="agent", wells=["C4"], signature={"metric": "plateau", "direction": "low"}
    )
    view = client.get("/api/instruments/qs-1").json()
    waiting = [i for i in view["incidents"] if i["status"] == "proposed"]
    assert [i["seq"] for i in waiting] == [proposed.seq, second.seq]
    assert all(i["can_confirm"] and not i["can_fix"] for i in waiting)
    assert view["instrument"]["n_proposed"] == 2
    ok = client.post(f"/api/instruments/qs-1/incidents/{proposed.seq}/confirm")
    assert ok.status_code == 200, ok.text
    no = client.post(f"/api/instruments/qs-1/incidents/{second.seq}/reject").json()
    statuses = {i["seq"]: i["status"] for i in no["instrument"]["incidents"]}
    assert statuses == {proposed.seq: "confirmed", second.seq: "rejected"}
    twice = client.post(f"/api/instruments/qs-1/incidents/{proposed.seq}/confirm")
    assert twice.status_code == 422 and "already" in twice.json()["error"]["message"]
    fixed = client.post(
        f"/api/instruments/qs-1/incidents/{proposed.seq}/fix", json={"note": "New seal."}
    ).json()
    done = next(i for i in fixed["instrument"]["incidents"] if i["seq"] == proposed.seq)
    assert done["fixes"][0]["note"] == "New seal." and done["can_fix"] is False
    events = reg.logbook("qs-1").events()
    assert {e.actor for e in events if e.seq > second.seq} == {"human"}
    assert reg.logbook("qs-1").verify() == []


def test_a_person_logs_an_incident_confirmed(client, reg):
    r = client.post(
        "/api/instruments/qs-1/incidents",
        json={"wells": ["b3", "B4"], "metric": "cq_residual", "direction": "high", "note": "late"},
    )
    assert r.status_code == 200, r.text
    (incident,) = r.json()["instrument"]["incidents"]
    assert incident["status"] == "confirmed" and incident["actor"] == "human"
    assert incident["wells"] == ["B3", "B4"] and incident["can_fix"]
    bad = client.post(
        "/api/instruments/qs-1/incidents",
        json={"wells": ["B3"], "metric": "Not A Code", "direction": "low"},
    )
    assert bad.status_code == 422


@pytest.mark.parametrize("instrument_id", ["NOPE", "../x", "x" * 80, "unknown-one"])
def test_unknown_instruments_are_not_found(client, reg, instrument_id):
    assert client.get(f"/api/instruments/{instrument_id}").status_code in (404, 422)


def test_a_run_file_says_what_it_says_and_never_a_serial(client, reg, tmp_path):
    path = F.qs_v1_expired(tmp_path / "run.eds")
    with path.open("rb") as fh:
        r = client.post("/api/instruments/runs", files={"run": ("run.eds", fh, "application/zip")})
    assert r.status_code == 200, r.text
    body = r.json()
    dumped = json.dumps(body)
    for serial in SERIALS:
        assert serial not in dumped
    assert F.OPERATOR not in dumped
    assert body["instrument_id"] == "qs-1" and body["question"] is None
    assert {line["code"] for line in body["gate"]} >= {"interrupted", "calibration_expired"}
    for line in body["gate"]:
        for segment in line["text"]["segments"]:
            if segment["fact"] is None:
                assert not any(ch.isdigit() for ch in segment["text"]), segment


def test_an_unknown_run_file_asks_once_and_the_answer_is_remembered(client, reg, tmp_path):
    path = F.qs_v1_expired(tmp_path / "other.eds", block_serial="BLK-2002")
    reg.register("qs-2", "QuantStudio in the corridor")
    # another instrument serial: rewrite the experiment's serial so it names no one
    other = F.write_eds(
        tmp_path / "unknown.eds",
        {"experiment.xml": F.experiment_xml(start_ms=1, end_ms=2, serial="999999999")},
    )
    del path
    with other.open("rb") as fh:
        body = client.post(
            "/api/instruments/runs", files={"run": ("unknown.eds", fh, "application/zip")}
        ).json()
    assert body["instrument_id"] is None
    assert body["question"]["question"] == "Which instrument is this?"
    assert {c["instrument_id"] for c in body["question"]["choices"]} == {"qs-1", "qs-2"}
    linked = client.post(
        f"/api/instruments/runs/{body['run_id']}/link", json={"instrument_id": "qs-2"}
    )
    assert linked.status_code == 200, linked.text
    with other.open("rb") as fh:
        again = client.post(
            "/api/instruments/runs", files={"run": ("unknown.eds", fh, "application/zip")}
        ).json()
    assert again["instrument_id"] == "qs-2" and again["question"] is None
    assert "999999999" not in json.dumps(client.get("/api/instruments/qs-2").json())


def test_a_run_file_of_another_kind_is_refused(client, reg, tmp_path):
    junk = tmp_path / "notes.pdf"
    junk.write_bytes(b"%PDF")
    with junk.open("rb") as fh:
        r = client.post("/api/instruments/runs", files={"run": ("notes.pdf", fh, "x/y")})
    assert r.status_code == 400
    txt = tmp_path / "junk.txt"
    txt.write_text("hello\n")
    with txt.open("rb") as fh:
        r = client.post("/api/instruments/runs", files={"run": ("junk.txt", fh, "text/plain")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_file"


def test_the_lookback_reads_only_and_says_what_changes(walked):
    c, store, study = walked["client"], walked["store"], walked["study"]
    Registry(store.root / "instruments").register("lc-1", "LightCycler")
    head = store.chain_head(study)
    r = c.post(
        f"/api/studies/{study}/lookback",
        json={"instrument_id": "lc-1", "start": "2000-01-01", "end": "2100-01-01"},
    )
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job"])
    assert job["status"] == "done", job
    out = job["result"]
    assert out["assumed_all_runs"] is True and out["saved"] is False
    assert out["text"]["plain"].startswith("Lookback for instrument")
    assert store.chain_head(study) == head
    assert Registry(store.root / "instruments").logbook("lc-1").events() == []
    bad = c.post(
        f"/api/studies/{study}/lookback",
        json={"instrument_id": "lc-1", "start": "2001-13-01", "end": "2002-01-01"},
    )
    assert bad.status_code == 422
    unknown = c.post(
        f"/api/studies/{study}/lookback",
        json={"instrument_id": "nope", "start": "2001-01-01", "end": "2002-01-01"},
    )
    assert unknown.status_code == 404


def test_a_logbook_whose_chain_breaks_is_shown_broken_not_refused(client, reg):
    from qpilot.core.instruments import log_typed

    book = reg.logbook("qs-1")
    log_typed(book, "note", actor="human", note="first")
    log_typed(book, "note", actor="human", note="second")
    path = next(reg.root.rglob("qs-1.jsonl"))
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0].replace("first", "edited"), *lines[1:]]) + "\n")
    r = client.get("/api/instruments/qs-1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["instrument"]["chain_ok"] is False and body["instrument"]["problems"]
    assert body["events"] == [] and body["incidents"] == []


def test_a_serial_in_a_run_files_name_is_not_echoed(client, reg, tmp_path):
    path = F.qs_v1_expired(tmp_path / "run.eds")
    with path.open("rb") as fh:
        body = client.post(
            "/api/instruments/runs", files={"run": ("QS5_278880001_run.eds", fh, "application/zip")}
        ).json()
    assert "278880001" not in body["name"] and body["name"].startswith("QS5_")
