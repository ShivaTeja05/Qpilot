"""G-RT and G-INSTR on the Controls route, and a run file a person links to a plate.

* G-RT over HTTP: a synthetic two-plate file whose design marks reverse-transcription
  replicates (three units per group, each reverse-transcribed twice; unit ``KO2``'s second RT
  amplifies later on ``1-Mar``) gives one verdict per unit x target, the unit in the view, and
  the consequence test of leaving the unit's wells out.
* G-INSTR reads each plate's run file: the study's own RDML (nothing to check), or a run file a
  person links here (``POST /studies/{id}/gate/run-files``). A paused run warns, leaving its
  study wells out is priced, no serial number ever comes back, and the link is kept per input
  file, so it holds for the new analysis a person's decision makes in a Studio session.
* Refusals: an RDML file, a plate the study does not have, no file, a linked file that changed.

The blind rule for the two new routes is in ``test_redteam_blind.py`` (the sweep of every study
route).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.qpcr import run_links
from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign
from qpilot.web.context import make_context
from qpilot.web.routers import gate as gate_router
from qpilot.web.server import create_app
from tests.engine import instrument_files as F
from tests.web.conftest import BASE, TOKEN, settled, wait_job
from tests.web.test_gate_routes import check_texts, ready, same_as_report

SECRETS = ("278880001", "BLK-1001", "HC-2001", F.OPERATOR)
PLATE = "1-Mar_plate"


@pytest.fixture(autouse=True)
def fresh_gate_cache():
    gate_router.clear()
    yield
    gate_router.clear()


def rt_file(path: Path, monkeypatch) -> tuple[Path, StudyDesign]:
    """The mini file's two plates with RT replicates a/b of six units; ``KO2``'s b is late."""
    from tests.fixtures.studio import studio_mini

    samples: dict[str, str] = {}
    plates: dict[str, dict[str, list[float | None]]] = {"GAPDH": {}, "1-Mar": {}}
    design: dict[str, SampleDesign] = {}
    for group, level in (("WT", 25.0), ("KO", 27.0)):
        for u in (1, 2, 3):
            unit = f"{group}{u}"
            for rt in ("a", "b"):
                name = f"{unit}{rt}"
                shift = 1.5 if (unit, rt) == ("KO2", "b") else 0.1 * u
                samples[name] = "unkn"
                plates["GAPDH"][name] = [22.0 + 0.1 * u + d for d in (0.0, 0.05, 0.1)]
                plates["1-Mar"][name] = [level + shift + d for d in (0.0, 0.05, 0.1)]
                design[name] = SampleDesign(
                    sample=name, group=group, biological_unit=unit, rt_replicate=rt
                )
    samples["NTC"] = "ntc"
    for plate in plates.values():
        plate["NTC"] = [None, None, None]
    monkeypatch.setattr(studio_mini, "SAMPLES", samples)
    monkeypatch.setattr(studio_mini, "PLATES", plates)
    rdml = studio_mini.write_studio_mini(path)
    return rdml, StudyDesign(
        design_id="rt_mini",
        mode="groups",
        comparison=Comparison(group_a="KO", group_b="WT"),
        samples=design,
        reference_candidates=("GAPDH",),
    )


@pytest.fixture
def rt(tmp_path, monkeypatch):
    """A study of the RT file analysed outside Studio, its store and a keyed client."""
    data = tmp_path / "data"
    data.mkdir()
    rdml, design = rt_file(data / "rt.rdml", monkeypatch)
    store = StudyStore(tmp_path / "studies")
    study = store.ensure_study(rdml, design)
    ctx = make_context(store, None, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield {"client": c, "store": store, "study": study, "tmp": tmp_path}
    ctx.close()


def link(c: TestClient, study: str, plate: str, path: Path, name: str | None = None, follow=True):
    """Link ``path`` to ``plate``. A link reads the study's plates from the gate, so the first
    one waits out the ``gate.run`` job like any read of the gate (409 loading meanwhile);
    ``follow=False`` returns the first answer as it is."""

    def send():
        with path.open("rb") as handle:
            return c.post(
                f"/api/studies/{study}/gate/run-files",
                data={"plate": plate},
                files={"run": (name or path.name, handle, "application/octet-stream")},
            )

    return settled(c, send) if follow else send()


def by_rule(body: dict, rule_id: str) -> list[dict]:
    return [e for e in body["evaluations"] if e["rule_id"] == rule_id]


# ---- G-RT ------------------------------------------------------------------------------------


def test_rt_replicates_are_checked_per_unit_and_target(rt):
    c, study, store = rt["client"], rt["study"], rt["store"]
    body = ready(c, study).json()
    check_texts(body)
    same_as_report(body, gate_router.compute(store, study, None))
    rows = by_rule(body, "G-RT")
    assert len(rows) == 12  # six units x two targets
    assert all(r["level"] == "unit" and r["plate"] is None for r in rows)
    (warn,) = (r for r in rows if r["verdict"] != "pass")
    assert (warn["unit"], warn["target"], warn["verdict"]) == ("KO2", "1-Mar", "warn")
    assert len(warn["flagged"]) == 6 and all(w.startswith(PLATE) for w in warn["flagged"])
    (conseq,) = (x for x in body["consequences"] if x["rule_id"] == "G-RT")
    assert conseq["unit"] == "KO2" and conseq["target"] == "1-Mar"
    (option,) = conseq["options"]
    assert option["id"] == "exclude_unit_target"
    assert option["label"] == "Leave out this unit's wells for this target"
    assert sorted(option["excluded"]) == sorted(warn["flagged"])
    rule = next(r for r in body["pack"]["rules"] if r["rule_id"] == "G-RT")
    assert rule["sources"][0]["key"] == "bustin_2015" and not rule["informational"]
    assert body["pack"]["version"] == "1.2.0"


# ---- G-INSTR and linked run files ------------------------------------------------------------


def test_the_studys_own_file_names_little_and_says_how_to_check_more(rt):
    body = ready(rt["client"], rt["study"]).json()
    assert [(r["plate"], r["source"], r["kind"], r["verdict"]) for r in body["runs"]] == [
        ("GAPDH_plate", "study_file", "rdml", "not_applicable"),
        (PLATE, "study_file", "rdml", "not_applicable"),
    ]
    assert "Link the run file the instrument wrote" in body["run_note"]
    rows = by_rule(body, "G-INSTR")
    assert {r["code"] for r in rows} == {"nothing_in_file"}
    assert all("RDML has no field" in r["reason"]["plain"] for r in rows)
    ids = {r["id"] for r in rows}
    assert {r["evaluation"] for r in body["runs"]} == ids


def test_a_linked_run_file_is_read_for_its_plate_and_priced(rt):
    c, study, store = rt["client"], rt["study"], rt["store"]
    eds = F.qs_v1_expired(rt["tmp"] / "run.eds", pause_at=23)
    r = link(c, study, PLATE, eds, name="QS5_278880001_mar.eds")
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["linked"] and done["plate"] == PLATE and done["kind"] == "eds"
    assert done["name"] == "QS5_…_mar.eds"  # the serial in the name is blanked out
    body = ready(c, study).json()
    check_texts(body)
    same_as_report(body, gate_router.compute(store, study, None))
    text = json.dumps(body)
    assert not any(secret in text for secret in SECRETS)
    run = next(x for x in body["runs"] if x["plate"] == PLATE)
    assert (run["source"], run["kind"], run["name"]) == ("linked", "eds", "QS5_…_mar.eds")
    assert run["linked_at"] and run["verdict"] == "warn" and run["problem"] == ""
    row = next(e for e in by_rule(body, "G-INSTR") if e["plate"] == PLATE)
    assert row["verdict"] == "warn" and row["outcome"] == "interrupted"
    assert row["reason"]["plain"].startswith("From the run file a person linked to this plate:")
    assert "paused during cycles 23–24" in row["reason"]["plain"]
    (conseq,) = (x for x in body["consequences"] if x["rule_id"] == "G-INSTR")
    (option,) = conseq["options"]
    assert option["id"] == "exclude_run" and option["label"] == "Leave out this run's study wells"
    assert sorted(option["excluded"]) == sorted(row["flagged"])
    assert option["consequence"] == "flip" and "1-Mar" in option["flipped"]
    card = next(x for x in body["cards"] if x["card"]["id"] == conseq["card_id"])
    assert card["card"]["status"] == "open" and not body["can_decide"]  # outside Studio
    # kept per input file, by a person, with the file it names
    sha = store.get(study).input_sha256
    (kept,) = run_links.load(store.root, sha).values()
    assert kept.by == "human" and kept.plate == PLATE and kept.kind == "eds"
    assert (rt["tmp"] / "studio-inputs" / kept.file).is_file()
    # the other plate still reads the study's own file
    other = next(x for x in body["runs"] if x["plate"] == "GAPDH_plate")
    assert other["source"] == "study_file"


def test_an_agent_reads_the_same_checks_over_mcp_without_a_serial(rt):
    from qpilot.agents.outputs import GateOut
    from qpilot.mcp_server import QpilotTools

    c, study, store = rt["client"], rt["study"], rt["store"]
    eds = F.qs_v1_expired(rt["tmp"] / "run.eds", pause_at=23)
    assert link(c, study, PLATE, eds).status_code == 200
    out = QpilotTools(store).qpcr_gate(study)
    GateOut.model_validate(out)
    checks = {x["rule_id"]: x for x in out["checks"]}
    assert checks["G-RT"]["scope"] == {"unit": "KO2", "target": "1-Mar"}
    assert checks["G-INSTR"]["scope"] == {"plate": PLATE}
    assert [o["id"] for o in checks["G-INSTR"]["options"]] == ["exclude_run"]
    assert "1-Mar" in checks["G-INSTR"]["options"][0]["calls_changed"]
    assert not any(secret in json.dumps(out) for secret in SECRETS)


def test_unlinking_reads_the_studys_own_file_again(rt):
    c, study = rt["client"], rt["study"]
    assert link(c, study, PLATE, F.aborted(rt["tmp"] / "a.eds")).status_code == 200
    body = ready(c, study).json()
    row = next(e for e in by_rule(body, "G-INSTR") if e["plate"] == PLATE)
    assert row["outcome"] == "run_not_complete"
    r = c.post(f"/api/studies/{study}/gate/run-files/unlink", json={"plate": PLATE})
    assert r.status_code == 200 and r.json()["linked"] is False, r.text
    body = ready(c, study).json()
    assert {x["source"] for x in body["runs"]} == {"study_file"}
    again = c.post(f"/api/studies/{study}/gate/run-files/unlink", json={"plate": PLATE})
    assert again.status_code == 404 and again.json()["error"]["code"] == "not_found"


def test_a_second_link_does_not_wait_for_the_gate_to_be_read_again(rt, monkeypatch):
    c, study = rt["client"], rt["study"]
    ready(c, study)
    monkeypatch.setattr(gate_router, "WAIT_S", 0.0)  # a re-read gate would answer 409 loading
    first = link(c, study, PLATE, F.aborted(rt["tmp"] / "a.eds"), follow=False)
    assert first.status_code == 200, first.text
    r = link(c, study, "GAPDH_plate", F.eds2_json(rt["tmp"] / "b.eds"), follow=False)
    assert r.status_code == 200, r.text
    monkeypatch.setattr(gate_router, "WAIT_S", 1.5)
    body = ready(c, study).json()
    assert {x["plate"]: x["source"] for x in body["runs"]} == {
        "GAPDH_plate": "linked",
        PLATE: "linked",
    }
    assert {x["plate"]: x["verdict"] for x in body["runs"]} == {
        "GAPDH_plate": "pass",
        PLATE: "warn",
    }


def test_what_cannot_be_linked_is_refused_in_words(rt):
    c, study = rt["client"], rt["study"]
    ready(c, study)
    rdml = F.write_rdml(rt["tmp"] / "other.rdml", [{"id": "r1", "runDate": "2019-05-10"}])
    r = link(c, study, PLATE, rdml)
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_file"
    assert "RDML" in r.json()["error"]["message"]
    r = link(c, study, "no such plate", F.aborted(rt["tmp"] / "a.eds"))
    assert r.status_code == 404 and r.json()["error"]["message"] == gate_router.NOT_A_PLATE
    r = c.post(f"/api/studies/{study}/gate/run-files", data={"plate": PLATE})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    bad = rt["tmp"] / "notes.txt"
    bad.write_text("not a run file\n")
    r = link(c, study, PLATE, bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_file"
    assert run_links.load(rt["store"].root, rt["store"].get(study).input_sha256) == {}


def test_a_linked_file_that_changed_is_said_not_read(rt):
    c, study, store = rt["client"], rt["study"], rt["store"]
    assert link(c, study, PLATE, F.aborted(rt["tmp"] / "a.eds")).status_code == 200
    (kept,) = run_links.load(store.root, store.get(study).input_sha256).values()
    path = rt["tmp"] / "studio-inputs" / kept.file
    path.write_bytes(path.read_bytes() + b"\0")
    gate_router.clear()
    body = ready(c, study).json()
    run = next(x for x in body["runs"] if x["plate"] == PLATE)
    assert (run["source"], run["problem"]) == ("linked", "changed")
    assert run["verdict"] == "not_applicable"
    row = next(e for e in by_rule(body, "G-INSTR") if e["plate"] == PLATE)
    assert row["code"] == "linked_file_unreadable" and "has changed" in row["reason"]["plain"]


def test_a_link_holds_for_the_new_analysis_a_persons_decision_makes(walked, tmp_path):
    """In a Studio session: leave a paused run's wells out; the new analysis reads the link."""
    c, study, sid = walked["client"], walked["study"], walked["sid"]
    eds = F.qs_v1_expired(tmp_path / "run.eds", pause_at=23)
    assert link(c, study, PLATE, eds).status_code == 200
    body = ready(c, study).json()
    (conseq,) = (x for x in body["consequences"] if x["rule_id"] == "G-INSTR")
    assert conseq["can_decide"] and conseq["card_id"]
    r = c.post(
        f"/api/studies/{study}/gate/cards/{conseq['decision_id']}/decide",
        json={
            "option": "exclude_run",
            "reason": "the run was paused during cycles 23-24",
            "expected_head": body["head"],
            "expected_inbox": body["inbox_head"],
        },
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "left_out"
    assert sorted(done["left_out"]) == sorted(conseq["options"][0]["excluded"])
    job = wait_job(c, done["job"])
    assert job["status"] == "done", job
    new = c.get(f"/api/sessions/{sid}").json()["study_id"]
    assert new and new != study
    after = ready(c, new).json()
    run = next(x for x in after["runs"] if x["plate"] == PLATE)
    assert run["source"] == "linked" and run["verdict"] == "warn"
    (again,) = (x for x in after["consequences"] if x["rule_id"] == "G-INSTR")
    (option,) = again["options"]
    assert option["code"] == "already_left_out" and option["left_out"] == option["excluded"]
    assert again["decision"]["action"] == "left_out" and again["can_decide"]
