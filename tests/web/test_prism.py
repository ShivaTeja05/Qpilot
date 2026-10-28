"""Prism over HTTP on the real demo session: blind gate, routes, preview, draft, send, round trip.

The module walks the cached demo (Vermeulen 2009 / Ruijter 2013, 64 plates) through Studio as
``qpilot studio demo --check`` does, with the rules alone proposing and the test as the person,
up to the confirmed analysis choices; the tests then use only the page's Prism routes (and
Studio's accept, as the person, for the drafted project). Prism itself is never started.
"""

from __future__ import annotations

import csv
import io
import shutil
import statistics
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.ai.client import ModelClient, NoneBackend
from qpilot.core.store import StudyStore
from qpilot.prism import verify_provenance
from qpilot.qpcr.contrast import ConclusionRule
from qpilot.studio_service import Studio
from qpilot.web.context import make_context
from qpilot.web.folders import exports_root
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN

pytestmark = pytest.mark.demo_data
REASON = "checked the evidence"
ROUTES = ("linear_welch", "linear_student", "ddcq")


def wait(client: TestClient, response, timeout: float = 900.0) -> dict:
    """Follow the job a 202 answer started until it is done or failed."""
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    deadline = time.monotonic() + timeout
    while True:
        view = client.get(f"/api/jobs/{job['id']}").json()
        if view["status"] in ("done", "failed"):
            return view
        assert time.monotonic() < deadline, view
        time.sleep(0.1)


def prism_calls(client: TestClient, sid: str) -> list:
    """Every Prism route once (the round trip with a bundle id that does not exist)."""
    base = f"/api/sessions/{sid}/prism"
    return [
        client.get(base),
        client.get(f"{base}/preview"),
        client.get(f"{base}/routes"),
        client.get(f"{base}/bundles"),
        client.post(f"{base}/draft"),
        client.post(f"{base}/send"),
        client.post(f"{base}/roundtrip", json={"bundle": "abcdefgh", "folder": "/tmp"}),
    ]


@pytest.fixture(scope="module")
def walk(tmp_path_factory):
    """The demo, walked to confirmed choices; yields ``(client, ctx, studio, sid, log)``."""
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    root = tmp_path_factory.mktemp("prism")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_STUDIES_DIR", str(root / "studies"))
        mp.setattr("qpilot.studio_service._mac_prism_installed", lambda: False)
        mp.setattr("qpilot.studio_service._mac_prism_app", lambda: None)
        mp.setattr("qpilot.studio_service._windows_prism_exe", lambda: None)
        store = StudyStore(root / "studies")
        studio = Studio(store, client=ModelClient(backend=NoneBackend()))
        ctx = make_context(store, studio, token=TOKEN, watch=False)
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})
            sid = studio.open(DEMO_RDML)
            log: dict = {"root": root, "blind": prism_calls(client, sid)}
            studio.propose_design(sid)
            preset = next(
                p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.preset"
            )
            studio.accept(sid, preset.id, "human")
            studio.accept_all_consistent(
                sid, "design", "human", studio.consistent_ids(sid, "design")
            )
            left = [p.id for p in studio.inbox(sid, "design", "proposed")]
            studio.reject_many(sid, left, "human", "contradicted by the engine check")
            studio.accept(sid, studio.propose_confirm(sid, "design").proposal.id, "human")
            log["blind_curves"] = prism_calls(client, sid)
            studio.propose_curves(sid)
            inbox = studio.inbox(sid, "curves", "proposed")
            calls = [p.id for p in inbox if p.kind == "curve.well_call"]
            studio.reject_many(sid, calls, "human", "LinRegPCR fitted a complete early curve")
            rule = next(p for p in inbox if p.kind == "curve.call_rule")
            studio.accept(sid, rule.id, "human")
            studio.accept(sid, studio.propose_confirm(sid, "curves").proposal.id, "human")
            study = studio.study(sid)
            log["before_choices"] = {
                "status": client.get(f"/api/sessions/{sid}/prism").json(),
                "draft": client.post(f"/api/sessions/{sid}/prism/draft"),
            }
            for card in store.cards(study):
                if card.status != "auto_decided":
                    head = store.chain_head(study)
                    studio.decide(sid, card.id, card.recommended, REASON, "human", head)
            studio.accept(sid, studio.propose_confirm(sid, "choices").proposal.id, "human")
            log["study"] = study
            yield client, ctx, studio, sid, log


@pytest.fixture(scope="module")
def sent(walk):
    """Draft the project (job), accept it as the person, then Send to Prism (job)."""
    client, _, studio, sid, log = walk
    log["send_without_project"] = client.post(f"/api/sessions/{sid}/prism/send")
    drafted = wait(client, client.post(f"/api/sessions/{sid}/prism/draft"))
    assert drafted["status"] == "done", drafted
    log["drafted"] = drafted["result"]
    log["status_waiting"] = client.get(f"/api/sessions/{sid}/prism").json()
    studio.accept(sid, drafted["result"]["proposal_id"], "human")
    log["status_accepted"] = client.get(f"/api/sessions/{sid}/prism").json()
    job = wait(client, client.post(f"/api/sessions/{sid}/prism/send"))
    assert job["status"] == "done", job
    return job["result"]


def test_prism_stays_blind_until_the_design_and_curves_are_confirmed(walk):
    *_, log = walk
    for responses in (log["blind"], log["blind_curves"]):
        for r in responses:
            assert r.status_code == 403, r.text
            assert r.json()["error"]["code"] == "blind"
            assert "Results stay hidden" in r.json()["error"]["message"]


def test_drafting_waits_for_the_confirmed_choices(walk):
    *_, log = walk
    before = log["before_choices"]
    assert before["status"]["choices_confirmed"] is False
    assert before["status"]["can_draft"] is False and before["status"]["can_send"] is False
    assert before["status"]["project"]["status"] == "none"
    assert before["draft"].status_code == 409
    assert before["draft"].json()["error"]["code"] == "studio"


def test_unknown_sessions_are_not_found(walk):
    client, *_ = walk
    for path in ("/api/sessions/000000000000/prism", "/api/sessions/../etc/prism/routes"):
        assert client.get(path).status_code == 404


def test_the_routes_are_the_studys_own_facts(walk):
    client, ctx, _, sid, log = walk
    body = client.get(f"/api/sessions/{sid}/prism/routes").json()
    facts = ctx.store.get(log["study"]).facts
    assert body["study_id"] == log["study"]
    assert body["n_genes"] == facts["f_n_genes"].value
    assert [r["route"] for r in body["routes"]] == list(ROUTES)
    for route in body["routes"]:
        assert route["n_differ"] == facts[route["fact"]].value
        assert len(route["genes"]) == route["n_differ"]
        assert (", ".join(route["genes"]) or "none") == facts[route["genes_fact"]].value
        assert route["label"] and route["method"] and route["n_genes"] == body["n_genes"]
    assert "methods/routes.md" in body["note"]
    result = ctx.store.get(log["study"])
    assert body["rule"] == ConclusionRule(**result.conclusion_rule).describe()
    changed = {g for r in body["routes"] for g in r["genes"]}
    assert body["engine"] == {g: result.contrasts[g].conclusion for g in changed}


def test_the_preview_writes_nothing_and_shows_every_unit(walk):
    client, ctx, studio, sid, _ = walk
    exports = exports_root(ctx.store.root)
    before = sorted(p.relative_to(exports).as_posix() for p in exports.rglob("*"))
    r = client.get(f"/api/sessions/{sid}/prism/preview", params={"rows": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(p.relative_to(exports).as_posix() for p in exports.rglob("*")) == before
    assert body["writes_nothing"] is True and body["project_file"] in body["would_write"]
    assert body["needs_template"] is False and body["project_file"].endswith(".pzfx")
    assert [t["kind"] for t in body["project_tables"]][-1] == "grouped"
    assert "run.pzc" not in body["would_write"]
    assert body["genes"] and [t["gene"] for t in body["tables"]] == body["genes"]
    engine = studio.preview_prism(sid, rows=100_000)
    for table in body["tables"]:
        assert len(table["rows"]) == 2
        assert table["n_rows"] == engine["tables"][table["gene"]]["n_rows"]
        assert table["columns"] == engine["tables"][table["gene"]]["columns"]
    assert sorted(body["figures"]) == sorted(body["genes"])
    for gene, figure in body["figures"].items():
        full = list(csv.reader(io.StringIO("\n".join(engine["tables"][gene]["head"]))))
        cells = sum(1 for row in full[1:] for cell in row[1:] if cell)
        assert figure["gene"] == gene and sum(g["n"] for g in figure["groups"]) == cells
        assert [g["name"] for g in figure["groups"]] == full[0][1:]
        for group in figure["groups"]:
            values = [p["value"] for p in group["points"]]
            assert group["n"] == len(values)
            assert group["mean"] == pytest.approx(statistics.fmean(values))
            assert group["ci_lo"] < group["mean"] < group["ci_hi"]
    assert body["caption"] and "{{" not in body["caption"]
    cards = {c.id: c for c in ctx.store.cards(body["study_id"])}
    for choice in body["choices"]:
        card = cards[choice["card_id"]]
        assert choice["option_label"] == next(
            o.label for o in card.options if o.id == choice["option"]
        )
        assert choice["title"] and choice["decided_by"]
    assert body["choices_confirmed"] is True
    assert body["project"]["status"] in ("none", "waiting", "accepted")
    assert client.get(f"/api/sessions/{sid}/prism/preview", params={"rows": 0}).status_code == 422


def test_send_needs_an_accepted_project(walk, sent):
    *_, log = walk
    refused = log["send_without_project"]
    assert (
        refused.status_code == 409
        and "Accept the Prism project" in refused.json()["error"]["message"]
    )
    assert log["drafted"]["status"] == "proposed" and log["drafted"]["proposal_id"]
    assert log["status_waiting"]["project"]["status"] == "waiting"
    assert log["status_waiting"]["can_send"] is False
    accepted = log["status_accepted"]
    assert accepted["project"]["status"] == "accepted" and accepted["can_send"] is True
    assert accepted["project"]["genes"]


def test_send_writes_the_bundle_into_exports_and_offers_its_zip(walk, sent, tmp_path):
    client, ctx, _, sid, log = walk
    bundle = sent["bundle"]
    folder = Path(bundle["folder"])
    assert bundle["id"] and bundle["round_trip"] and bundle["current"] and bundle["exists"]
    assert folder.parent == exports_root(ctx.store.root).resolve() / sid
    assert folder.name == f"prism-{bundle['id']}"
    assert Path(sent["download"]["path"]).parent == folder.parent  # the zip beside its folder
    assert bundle["study_id"] == log["study"]
    assert sent["launched"] is False and "not installed" in sent["launch_note"]
    assert sent["command_line"] == "" and sent["project"] == f"qpilot_{log['study']}.pzfx"
    assert sent["open_steps"] and sent["analyse_steps"] and sent["round_trip_steps"]
    r = client.get(sent["download"]["url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert sent["download"]["name"] in r.headers["content-disposition"]
    assert (
        r.headers["cache-control"] == "no-store"
        and r.headers["x-content-type-options"] == "nosniff"
    )
    assert len(r.content) == sent["download"]["bytes"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = sorted(n for n in zf.namelist() if not n.endswith("/"))
        zf.extractall(tmp_path / "unzipped")
    on_disk = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert names == on_disk == sent["files"] and len(on_disk) >= sent["n_files"]
    assert verify_provenance(tmp_path / "unzipped") == []
    listed = client.get(f"/api/sessions/{sid}/prism/bundles").json()["bundles"]
    mine = next(b for b in listed if b["id"] == bundle["id"])
    assert mine["download"]["id"] == sent["download"]["id"]
    status = client.get(f"/api/sessions/{sid}/prism").json()
    assert status["bundles"] >= 1


def test_the_round_trip_turns_an_edit_in_prism_into_a_question(walk, sent):
    client, _, studio, sid, _ = walk
    folder = Path(sent["bundle"]["folder"])
    back = folder / "sent_back"
    back.mkdir(exist_ok=True)
    tables = sorted(folder.glob("*.csv"))
    for table in tables:
        shutil.copy(table, back / table.name)
    edited = back / tables[0].name
    lines = edited.read_text().split("\n")
    unit = lines[1].split(",")[0]
    lines[1] = ",".join([unit] + [""] * (len(lines[1].split(",")) - 1))  # blanked in Prism
    edited.write_text("\n".join(lines))
    job = wait(
        client,
        client.post(
            f"/api/sessions/{sid}/prism/roundtrip",
            json={"bundle": sent["bundle"]["id"], "folder": str(back)},
        ),
    )
    assert job["status"] == "done", job
    result = job["result"]
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["row"] == unit and item["returned"] is None and item["exported"] is not None
    assert len(result["proposed"]) == 1 and "1 question added" in result["message"]
    waiting = {p.id for p in studio.inbox(sid, "roundtrip", "proposed")}
    assert set(result["proposed"]) <= waiting
    assert result["combined"]["n_genes"] > 0
    bundles = client.get(f"/api/sessions/{sid}/prism/bundles").json()["bundles"]
    mine = next(b for b in bundles if b["id"] == sent["bundle"]["id"])
    assert Path(mine["sent_back_folder"]) == back.resolve()


def test_the_round_trip_refuses_folders_and_bundles_it_may_not_read(walk, sent):
    client, ctx, _, sid, _ = walk
    folder = Path(sent["bundle"]["folder"])
    url = f"/api/sessions/{sid}/prism/roundtrip"
    for bad in ("", "sent_back", f"{folder}/sent_back/../sent_back", str(ctx.store.root)):
        r = client.post(url, json={"bundle": sent["bundle"]["id"], "folder": bad})
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_folder", (bad, r.text)
    for bundle in ("zzzzzzzz", "../prism-x", "a"):
        r = client.post(url, json={"bundle": bundle, "folder": str(folder / "sent_back")})
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_a_bundle_sent_from_elsewhere_is_listed_but_not_round_tripped(walk, sent, tmp_path):
    client, _, studio, sid, _ = walk
    elsewhere = tmp_path / "cli-bundle"
    studio.send_to_prism(sid, elsewhere, "human")  # as `qpilot prism export` or an old page would
    listed = client.get(f"/api/sessions/{sid}/prism/bundles").json()["bundles"]
    other = next(b for b in listed if Path(b["folder"]) == elsewhere.resolve())
    assert other["id"] is None and other["round_trip"] is False and other["download"] is None
    assert listed[0]["folder"] == other["folder"]  # newest first


def test_bundles_outlive_the_server(walk, sent):
    """A new server over the same store lists the bundle, serves its zip and can round-trip it."""
    _, ctx, studio, sid, _ = walk
    later = make_context(ctx.store, studio, token=TOKEN, watch=False)
    with TestClient(create_app(later), base_url=BASE) as client:
        client.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})
        assert client.get(sent["download"]["url"]).status_code == 404  # ids are per server
        listed = client.get(f"/api/sessions/{sid}/prism/bundles").json()["bundles"]
        mine = next(b for b in listed if b["id"] == sent["bundle"]["id"])
        assert mine["round_trip"] and mine["download"]["path"] == sent["download"]["path"]
        r = client.get(mine["download"]["url"])
        assert r.status_code == 200 and len(r.content) == sent["download"]["bytes"]
        assert client.get(f"/api/sessions/{sid}/prism").json()["bundles"] >= 1


def test_the_round_trip_reads_the_demo_project_prism_saved(walk, sent, tmp_path):
    """The docs' oracle through the project route: leaving out ODC1's highest tumour."""
    from lxml import etree

    from qpilot.prism import pzfx

    client, _, studio, sid, _ = walk
    folder = Path(sent["bundle"]["folder"])
    saved = tmp_path / "ODC1 checked.pzfx"
    root = etree.fromstring((folder / sent["project"]).read_bytes())
    ns = {"p": pzfx.NAMESPACE}
    table = next(
        t for t in root.findall("p:Table", ns) if t.find("p:Title", ns).text.startswith("ODC1 ")
    )
    units = [d.text for d in table.findall("p:RowTitlesColumn/p:Subcolumn/p:d", ns)]
    high = table.findall("p:YColumn", ns)[0].findall("p:Subcolumn/p:d", ns)
    values = {units[i]: float(d.text) for i, d in enumerate(high) if d.text}
    top = max(values, key=values.get)
    high[units.index(top)].set("Excluded", "1")
    saved.write_bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))
    with saved.open("rb") as fh:
        r = client.post(
            f"/api/sessions/{sid}/prism/roundtrip/upload",
            data={"bundle": sent["bundle"]["id"]},
            files={"project": (saved.name, fh, "application/xml")},
        )
    job = wait(client, r)
    assert job["status"] == "done", job
    result = job["result"]
    assert result["source"] == "project"
    assert [(i["kind"], i["row"]) for i in result["items"]] == [("excluded", top)]
    (pid,) = result["proposed"]
    proposal = next(p for p in studio.inbox(sid, "roundtrip", "proposed") if p.id == pid)
    consequence = proposal.consequence
    assert proposal.payload["question"] == f"You excluded sample {top} for ODC1 in Prism. Reason?"
    assert consequence["conclusion_before"] == consequence["conclusion_after"] == "up"
    assert (
        round(consequence["fc_before"], 3) == 3.590 and round(consequence["fc_after"], 3) == 3.319
    )
    assert consequence["n_conclusions_changed"] == 0
