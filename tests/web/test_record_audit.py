"""Verify a record against its robustness audit: the store's audit, an audit in the zip, tampering.

A real audit of the demo study (the Decision Simulator, 99 permutations to keep it short); the
record is exported through the page. The audit sits beside the record, never inside it
(``qpilot verify`` rejects files the record does not list), so a zip may carry ``record/`` and
``audit/`` side by side.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.integration import simulator
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN

pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def audited(tmp_path_factory):
    """The demo study audited into the store: ``(client, ctx, study, record zip, audit)``."""
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    if not simulator.available():
        pytest.skip("the Decision Simulator (qsim) is not installed")
    root = tmp_path_factory.mktemp("record-audit")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_STUDIES_DIR", str(root / "studies"))
        store = StudyStore(root / "studies")
        study = store.ensure_study(DEMO_RDML)
        audit_dir = store.root / "simulator_audits" / study  # where the page finds a study's audit
        simulator.audit(store, study, audit_dir, permutations=99)
        ctx = make_context(store, token=TOKEN, watch=False)
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})
            started = client.post(f"/api/studies/{study}/record")
            assert started.status_code == 202, started.text
            job = started.json()["job"]
            while job["status"] not in ("done", "failed"):
                time.sleep(0.05)
                job = client.get(f"/api/jobs/{job['id']}").json()
            assert job["status"] == "done", job
            zipped = client.get(job["result"]["download"]["url"]).content
            yield client, ctx, study, zipped, audit_dir


def verify(client: TestClient, data: bytes) -> dict:
    r = client.post("/api/records/verify", files={"record": ("r.zip", data, "application/zip")})
    assert r.status_code == 200, r.text
    return r.json()


def beside(record_zip: bytes, audit_dir: Path, change=None) -> bytes:
    """A zip holding ``record/`` and ``audit/`` side by side (``change(name, bytes)`` per file)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(record_zip)) as zin, zipfile.ZipFile(out, "w") as zout:
        for member in zin.infolist():
            zout.writestr("record/" + member.filename, zin.read(member))
        for path in sorted(p for p in audit_dir.rglob("*") if p.is_file()):
            name = path.relative_to(audit_dir).as_posix()
            data = path.read_bytes()
            zout.writestr("audit/" + name, change(name, data) if change else data)
    return out.getvalue()


def test_the_stores_audit_is_bound_to_the_record(audited):
    client, _, study, zipped, _ = audited
    out = verify(client, zipped)
    assert out["ok"] is True and out["known_study"] is True
    assert out["audit"] == {"source": "store", "ok": True, "problems": [], "study_id": study}
    assert "This qPilot's audit" in out["audit_note"]


def test_an_audit_in_the_zip_is_bound_to_the_record(audited):
    client, _, study, zipped, audit_dir = audited
    out = verify(client, beside(zipped, audit_dir))
    assert out["ok"] is True
    assert out["audit"]["source"] == "zip" and out["audit"]["ok"] is True
    assert out["audit"]["study_id"] == study


def test_a_changed_audit_is_not_bound(audited):
    client, _, _, zipped, audit_dir = audited

    def edit(name: str, data: bytes) -> bytes:
        return data + b"\n" if name == "genes.csv" else data

    out = verify(client, beside(zipped, audit_dir, edit))
    assert out["ok"] is True  # the record itself still verifies
    assert out["audit"]["ok"] is False
    assert any("genes.csv" in p for p in out["audit"]["problems"])


def test_an_audit_of_another_chain_is_not_bound(audited):
    client, _, _, zipped, audit_dir = audited
    sums = (audit_dir / "AUDIT.sha256").read_text(encoding="utf-8")
    manifest = json.loads((audit_dir / "audit_manifest.json").read_text(encoding="utf-8"))
    manifest["chain_head"] = "f" * 64  # audited at a head this record's chain never had
    forged = json.dumps(manifest, indent=1).encode()
    old = hashlib.sha256((audit_dir / "audit_manifest.json").read_bytes()).hexdigest()

    def edit(name: str, data: bytes) -> bytes:
        if name == "audit_manifest.json":
            return forged
        if name == "AUDIT.sha256":  # checksums rewritten to match: only the binding catches it
            return sums.replace(old, hashlib.sha256(forged).hexdigest()).encode()
        return data

    out = verify(client, beside(zipped, audit_dir, edit))
    assert out["ok"] is True and out["audit"]["ok"] is False
    assert any("chain head is not in the record's chain" in p for p in out["audit"]["problems"])
