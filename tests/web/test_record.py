"""The Analysis Record over HTTP on the real demo study: export, download, verify, tamper, refuse.

The study is the demo analysed as ``qpilot run`` analyses it (a study outside a Studio session),
with one Decision Card decided by the test as the person, so the record holds a real chain.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.core.decisions import apply_decision
from qpilot.core.store import StudyStore
from qpilot.web.context import make_context
from qpilot.web.folders import exports_root
from qpilot.web.routers import files as files_router
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN

pytestmark = pytest.mark.demo_data


def wait(client: TestClient, response, timeout: float = 600.0) -> dict:
    """Follow the job a 202 answer started until it is done or failed."""
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    deadline = time.monotonic() + timeout
    while True:
        view = client.get(f"/api/jobs/{job['id']}").json()
        if view["status"] in ("done", "failed"):
            return view
        assert time.monotonic() < deadline, view
        time.sleep(0.05)


@pytest.fixture(scope="module")
def study(tmp_path_factory):
    """The demo analysed into a fresh store, one card decided; yields ``(client, ctx, id)``."""
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    root = tmp_path_factory.mktemp("record")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_STUDIES_DIR", str(root / "studies"))
        store = StudyStore(root / "studies")
        study_id = store.ensure_study(DEMO_RDML)
        card = next(c for c in store.cards(study_id) if c.status in ("open", "pending_human"))
        apply_decision(
            store,
            study_id,
            card.id,
            card.recommended,
            "the pre-registered option",
            "human",
            store.chain_head(study_id),
        )
        ctx = make_context(store, token=TOKEN, watch=False)
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})
            yield client, ctx, study_id


@pytest.fixture(scope="module")
def exported(study):
    """The record exported through the page (a job), and the zip it offers."""
    client, ctx, study_id = study
    head = ctx.store.chain_head(study_id)
    job = wait(client, client.post(f"/api/studies/{study_id}/record", json={"expected_head": head}))
    assert job["status"] == "done", job
    body = job["result"]
    r = client.get(body["download"]["url"])
    assert r.status_code == 200
    return body, r


def verify(client: TestClient, data: bytes, name: str = "record.zip"):
    return client.post("/api/records/verify", files={"record": (name, data, "application/zip")})


def rezip(data: bytes, change=None, prefix: str = "", extra: dict | None = None) -> bytes:
    """The zip again, each member passed through ``change(name, bytes)``, under ``prefix``."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w") as zout:
        for member in zin.infolist():
            content = zin.read(member)
            if change is not None:
                content = change(member.filename, content)
            zout.writestr(prefix + member.filename, content)
        for name, content in (extra or {}).items():
            zout.writestr(name, content)
    return out.getvalue()


def test_the_export_is_a_zip_of_the_record(study, exported):
    _, ctx, study_id = study
    body, r = exported
    assert body["study_id"] == study_id
    assert body["chain_head"] == ctx.store.chain_head(study_id)
    assert body["input_included"] is True
    open_flips = [
        c
        for c in ctx.store.cards(study_id)
        if c.impact.get("flips") and c.status in ("open", "pending_human")
    ]
    assert body["open_flips"] == [c.id for c in open_flips]
    assert bool(open_flips) == any("still open" in w for w in body["warnings"])
    assert body["head_moved"] is False
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert body["download"]["name"] == f"qpilot-record-{study_id}.zip"
    assert body["commands"] == {
        "verify": f"qpilot verify qpilot-record-{study_id}.zip",
        "rerun": f"qpilot rerun qpilot-record-{study_id}.zip",
    }
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        checksums = zf.read("CHECKSUMS.sha256")
    assert len(names) == body["n_files"] and "input.rdml" in names
    assert body["record_id"] == hashlib.sha256(checksums).hexdigest()
    # only the zip is kept in the export folder: the unpacked record folder is gone
    leftovers = [
        p
        for p in (exports_root(ctx.store.root) / study_id).rglob("*")
        if p.is_file() and p.suffix not in (".zip", ".json")
    ]
    assert leftovers == []


def test_this_launchs_records_are_listed(study, exported):
    client, _, study_id = study
    body, _ = exported
    listed = client.get(f"/api/studies/{study_id}/records").json()
    assert listed["study_id"] == study_id
    assert body["record_id"] in [r["record_id"] for r in listed["records"]]
    mine = next(r for r in listed["records"] if r["record_id"] == body["record_id"])
    assert mine["download"]["id"] == body["download"]["id"]


def test_the_exported_record_verifies(study, exported):
    client, ctx, study_id = study
    body, r = exported
    v = verify(client, r.content, "qpilot-record.zip")
    assert v.status_code == 200, v.text
    out = v.json()
    assert out["ok"] is True and out["summary"][0].startswith("OK; decision chain:")
    assert out["report"]["n_entries"] >= 1 and out["report"]["chain_broken_at"] is None
    assert out["record"]["study_id"] == study_id
    assert out["record"]["chain_head"] == body["chain_head"]
    assert out["record"]["record_id"] == body["record_id"]
    assert out["record"]["input_included"] is True
    assert out["known_study"] is True and out["file_name"] == "qpilot-record.zip"
    assert out["note"].startswith("Tamper-evident, not tamper-proof")
    if out["audit"] is None:
        assert "no robustness audit" in out["audit_note"]
    assert list((ctx.private / "verify").iterdir()) == []  # the upload and its unpacking are gone


def test_a_record_of_a_zipped_folder_verifies(study, exported):
    client, *_ = study
    _, r = exported
    v = verify(client, rezip(r.content, prefix="qpilot-record/"))
    assert v.status_code == 200 and v.json()["ok"] is True


def test_a_record_without_its_input_still_verifies(study):
    client, _, study_id = study
    job = wait(
        client, client.post(f"/api/studies/{study_id}/record", json={"include_input": False})
    )
    body = job["result"]
    assert body["input_included"] is False
    zipped = client.get(body["download"]["url"]).content
    assert "input.rdml" not in zipfile.ZipFile(io.BytesIO(zipped)).namelist()
    assert verify(client, zipped).json()["ok"] is True


def test_a_moved_head_is_said(study):
    client, _, study_id = study
    job = wait(
        client, client.post(f"/api/studies/{study_id}/record", json={"expected_head": "0" * 64})
    )
    assert "Something was decided after this page last refreshed." in job["result"]["warnings"]
    assert job["result"]["head_moved"] is True


def test_a_changed_file_fails_verification(study, exported):
    client, *_ = study
    _, r = exported

    def edit(name: str, content: bytes) -> bytes:
        return content.replace(b'"up"', b'"down"', 1) if name == "results.json" else content

    out = verify(client, rezip(r.content, edit)).json()
    assert out["ok"] is False and "results.json" in out["report"]["changed"]
    assert any(line.startswith("changed: results.json") for line in out["summary"])


def test_an_edited_chain_fails_even_with_fresh_checksums(study, exported):
    client, *_ = study
    _, r = exported
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        log = zf.read("decisions.jsonl")
    forged = log.replace(b"the pre-registered option", b"the option a reviewer liked", 1)
    assert forged != log

    def edit(name: str, content: bytes) -> bytes:
        if name == "decisions.jsonl":
            return forged
        if name == "CHECKSUMS.sha256":  # the forger rewrites the checksums too
            old = hashlib.sha256(log).hexdigest().encode()
            return content.replace(old, hashlib.sha256(forged).hexdigest().encode())
        return content

    out = verify(client, rezip(r.content, edit)).json()
    assert out["ok"] is False and out["report"]["changed"] == []
    assert out["report"]["chain_broken_at"] is not None


def test_unsafe_or_wrong_uploads_are_refused(study, exported, tmp_path):
    client, ctx, _ = study
    _, r = exported

    def code(data: bytes, name: str = "x.zip") -> tuple[int, str]:
        resp = verify(client, data, name)
        return resp.status_code, resp.json()["error"]["code"]

    for member in ("../evil.txt", "/abs/evil.txt", "a/../../evil.txt", "a\\..\\evil.txt"):
        assert code(rezip(r.content, extra={member: "x"})) == (400, "bad_record"), member
    link = io.BytesIO()
    with zipfile.ZipFile(link, "w") as zf:
        info = zipfile.ZipInfo("CHECKSUMS.sha256")
        info.external_attr = 0o120777 << 16  # a symbolic link
        zf.writestr(info, "/etc/passwd")
    assert code(link.getvalue()) == (400, "bad_record")
    assert code(b"PK not really a zip") == (400, "not_zip")
    assert code(b"") == (400, "empty_file")
    plain = io.BytesIO()
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("notes.txt", "hello")
    assert code(plain.getvalue()) == (400, "not_record")
    assert code(_two_records(r.content)) == (400, "not_record")
    assert (
        not (ctx.private / "evil.txt").exists() and not (ctx.private.parent / "evil.txt").exists()
    )
    assert list((ctx.private / "verify").iterdir()) == []


def _two_records(data: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w") as zout:
        for member in zin.infolist():
            for prefix in ("one/", "two/"):
                zout.writestr(prefix + member.filename, zin.read(member))
    return out.getvalue()


def test_an_oversized_upload_is_refused(study, monkeypatch):
    client, *_ = study
    monkeypatch.setattr(files_router, "MAX_RECORD_BYTES", 1024)
    resp = verify(client, b"0" * 4096)
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "too_large"


def test_downloads_serve_only_registered_files_inside_exports(study, exported, tmp_path):
    client, ctx, _ = study
    body, _ = exported
    assert client.get("/api/downloads/AAAAAAAAAAAAAAAA").status_code == 404
    assert client.get("/api/downloads/short").status_code == 404
    secret = tmp_path / "secret.txt"
    secret.write_text("not for the page")
    upload = ctx.uploads / "kept.rdml"
    upload.write_text("an upload, not an export")
    link = exports_root(ctx.store.root) / "link.zip"
    os.symlink(secret, link)
    ctx.downloads.update({"outsideAAAAA": secret, "uploadsAAAAA": upload, "linkedAAAAAA": link})
    for token in ("outsideAAAAA", "uploadsAAAAA", "linkedAAAAAA"):
        resp = client.get(f"/api/downloads/{token}")
        assert resp.status_code == 404 and resp.json()["error"]["code"] == "not_found"
    assert client.get(body["download"]["url"]).status_code == 200


def test_unknown_studies_are_not_found(study):
    client, *_ = study
    for key in ("000000000000", "ABCDEF123456", "abc"):
        assert client.post(f"/api/studies/{key}/record").status_code == 404
        assert client.get(f"/api/studies/{key}/records").status_code == 404


def test_writes_from_another_site_are_refused(study):
    client, _, study_id = study
    r = client.post(f"/api/studies/{study_id}/record", headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "cross_origin"
    r = client.post(
        "/api/records/verify",
        files={"record": ("r.zip", b"x", "application/zip")},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_a_study_id_in_an_uploaded_record_never_names_a_path(study, exported):
    client, *_ = study
    _, r = exported

    def edit(name: str, content: bytes) -> bytes:
        if name != "record.json":
            return content
        meta = json.loads(content)
        meta["study_id"] = "../simulator_audits/../../.."
        return json.dumps(meta).encode()

    out = verify(client, rezip(r.content, edit)).json()
    assert out["ok"] is False and "record.json" in out["report"]["changed"]
    assert out["known_study"] is False and out["audit"] is None


def test_records_outlive_the_server(study, exported):
    """A new server over the same store lists the record and serves its zip again."""
    _, ctx, study_id = study
    body, r = exported
    assert Path(body["download"]["path"]).parent.parent == (
        exports_root(ctx.store.root).resolve() / study_id
    )
    later = make_context(ctx.store, token=TOKEN, watch=False)
    with TestClient(create_app(later), base_url=BASE) as client:
        client.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})
        listed = client.get(f"/api/studies/{study_id}/records").json()["records"]
        mine = next(x for x in listed if x["record_id"] == body["record_id"])
        again = client.get(mine["download"]["url"])
        assert again.status_code == 200 and again.content == r.content
