"""Running the audit from the page: the job, its stages, where it lands, and its refusals.

Most tests swap the simulator's 50-second run for one that writes a real audit's files in the
simulator's order (so the job, its stages and the folder handling are what is tested); one
test runs the real audit end to end and checks it reproduces the existing one exactly.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pandas as pd
import pytest

from qpilot.core.store import StudyStore
from qpilot.integration import simulator as sim
from qpilot.web.routers import audit as audit_router
from tests.web.test_audit import WRITE, _client, _close, _copy, seeded  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.demo_data,  # the audited study's input file is the demo's
    pytest.mark.skipif(not sim.available(), reason="the Decision Simulator is not installed"),
]

ORDER = ("lock.json", "grid.parquet", "genes.csv", "explain.json", "summary.json")


def _wait(client, job_id: str, timeout: float = 1800.0) -> dict:
    steps: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["step"] and (not steps or steps[-1] != job["step"]):
            steps.append(job["step"])
        if job["status"] in ("done", "failed"):
            job["steps"] = steps
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in {timeout} s")


def _replay(source: Path, pause: float = 0.7, grid: int = 0):
    """Stands in for ``simulator.audit``: writes ``source``'s files in the simulator's order.

    With ``grid``, tells ``progress`` the full grid's count after ``lock.json`` (as the real
    audit's engine count does).
    """

    def fake(store, study_id, out_dir, progress=None, **_):
        out = Path(out_dir)
        assert not out.exists() or not any(out.iterdir())
        out.mkdir(parents=True, exist_ok=True)
        names = [n for n in ORDER if (source / n).exists()]
        rest = sorted(p.name for p in source.iterdir() if p.is_file() and p.name not in names)
        for name in names:
            shutil.copyfile(source / name, out / name)
            if name == "lock.json" and grid and progress is not None:
                for done in range(grid // 4, grid + 1, grid // 4):
                    progress(done, grid)
                    time.sleep(0.6)  # the router tells the count at most twice a second
            time.sleep(pause)  # long enough for the stage watcher to see each file
        for name in rest:
            shutil.copyfile(source / name, out / name)
        manifest = json.loads((out / "audit_manifest.json").read_text())
        summary = json.loads((out / "summary.json").read_text())
        return sim.AuditResult(
            out_dir=out,
            study_id=study_id,
            manifest=manifest,
            summary=summary,
            verdicts={},
            your_choices=pd.DataFrame(),
            seconds=1.0,
        )

    return fake


def _leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "simulator_audits").glob(".*partial*"))


def test_the_audit_job_reports_its_stages_and_lands_whole(seeded, tmp_path, monkeypatch):  # noqa: F811
    root = _copy(seeded, tmp_path, audits=False)
    study = seeded[1]
    source = seeded[0] / "simulator_audits" / study
    monkeypatch.setattr(sim, "audit", _replay(source))
    monkeypatch.setattr(audit_router, "_load_job", lambda *a: None)
    ctx, client = _client(StudyStore(root))
    with client:
        r = client.post(f"/api/studies/{study}/audit", json={}, headers=WRITE)
        assert r.status_code == 202, r.text
        started = r.json()["job"]
        assert started["kind"] == "audit" and started["key"] == study and started["typical_s"]
        again = client.post(f"/api/studies/{study}/audit", json={}, headers=WRITE).json()
        assert again["job"]["id"] == started["id"]  # one audit at a time per study
        running = client.get(f"/api/studies/{study}/audit").json()
        assert running["status"] in ("running", "ready")
        job = _wait(client, started["id"])
        assert job["status"] == "done", job
        stages = [step for _, step, _ in audit_router.RUN_STAGES]
        seen = [s for s in job["steps"] if s in stages]
        assert seen == sorted(seen, key=stages.index) and len(seen) >= 3, job["steps"]
        assert (
            job["result"]["verdict_counts"]
            == json.loads((source / "audit_manifest.json").read_text())["verdict_counts"]
        )
        body = client.get(f"/api/studies/{study}/audit").json()
        assert body["status"] == "ready" and body["manifest"]["reproduces_qpilot"]["ok"]
        assert _leftovers(root) == []
        check = client.post(f"/api/studies/{study}/audit/verify", json={}, headers=WRITE).json()
        assert check["ok"], check["problems"]
    _close(ctx)


def test_the_audit_tells_how_far_the_grid_has_come(seeded, tmp_path, monkeypatch):  # noqa: F811
    """perf: the longest stage moves (was one step at 0.17 for most of the run)."""
    root = _copy(seeded, tmp_path, audits=False)
    study = seeded[1]
    source = seeded[0] / "simulator_audits" / study
    monkeypatch.setattr(sim, "audit", _replay(source, pause=0.6, grid=6912))
    monkeypatch.setattr(audit_router, "_load_job", lambda *a: None)
    ctx, client = _client(StudyStore(root))
    fractions: list[float] = []
    with client:
        r = client.post(f"/api/studies/{study}/audit", json={}, headers=WRITE)
        job_id = r.json()["job"]["id"]
        deadline = time.monotonic() + 120
        steps: list[str] = []
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["fraction"] is not None and (not fractions or fractions[-1] != job["fraction"]):
                fractions.append(job["fraction"])
            if job["step"] and (not steps or steps[-1] != job["step"]):
                steps.append(job["step"])
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
    _close(ctx)
    assert job["status"] == "done", job
    counted = [s for s in steps if s.endswith(" analyses")]
    assert counted[0].endswith("1,728 of 6,912 analyses") and counted[-1].endswith(
        "6,912 of 6,912 analyses"
    )
    assert fractions == sorted(fractions), fractions  # never goes back
    assert any(0.17 < f < 0.88 for f in fractions), fractions


def test_running_again_keeps_the_earlier_audit(seeded, tmp_path, monkeypatch):  # noqa: F811
    root = _copy(seeded, tmp_path)
    study = seeded[1]
    source = seeded[0] / "simulator_audits" / study
    monkeypatch.setattr(sim, "audit", _replay(source, pause=0.0))
    monkeypatch.setattr(audit_router, "_load_job", lambda *a: None)
    ctx, client = _client(StudyStore(root))
    with client:
        r = client.post(f"/api/studies/{study}/audit", json={"again": True}, headers=WRITE)
        assert r.status_code == 202, r.text
        assert _wait(client, r.json()["job"]["id"])["status"] == "done"
        earlier = sorted((root / "simulator_audits").glob(f"{study}.earlier-*"))
        assert len(earlier) == 1 and (earlier[0] / "audit_manifest.json").exists()
        assert (root / "simulator_audits" / study / "audit_manifest.json").exists()
        assert client.get(f"/api/studies/{study}/audit").json()["status"] == "ready"
    _close(ctx)


@pytest.mark.parametrize(
    ("error", "status", "words"),
    [
        (
            sim.NotApplicable("the simulator varies the cut-off over (0.1, 0.15, 0.2)"),
            "not_applicable",
            "The audit does not apply here: the simulator varies the cut-off",
        ),
        (
            sim.AuditRefused("the simulator's baseline does not reproduce qPilot's stored result"),
            "refused",
            "The audit stopped before writing anything. The simulator's baseline",
        ),
        (RuntimeError("disk full"), "failed", "disk full"),
    ],
)
def test_a_refusal_is_said_in_words_and_leaves_nothing(
    seeded,  # noqa: F811
    tmp_path,
    monkeypatch,
    error,
    status,
    words,
):
    root = _copy(seeded, tmp_path, audits=False)
    study = seeded[1]

    def refuse(store, study_id, out_dir, **_):
        Path(out_dir).mkdir(parents=True)
        (Path(out_dir) / "lock.json").write_text("{}")  # half-written: must be removed
        raise error

    monkeypatch.setattr(sim, "audit", refuse)
    ctx, client = _client(StudyStore(root))
    with client:
        r = client.post(f"/api/studies/{study}/audit", json={}, headers=WRITE)
        job = _wait(client, r.json()["job"]["id"])
        assert job["status"] == "failed" and words in job["error"]["message"]
        body = client.get(f"/api/studies/{study}/audit").json()
        assert body["status"] == status and words in body["reason"]
        assert body["manifest"] is None and body["job"]["status"] == "failed"
        assert _leftovers(root) == [] and not (root / "simulator_audits" / study).exists()
    _close(ctx)


def test_the_real_audit_through_the_page_reproduces_the_existing_one(seeded, tmp_path):  # noqa: F811
    """End to end: the simulator runs (about a minute) and writes the same verdicts again."""
    root = _copy(seeded, tmp_path, audits=False)
    study = seeded[1]
    existing = json.loads(
        (seeded[0] / "simulator_audits" / study / "audit_manifest.json").read_text()
    )
    ctx, client = _client(StudyStore(root))
    with client:
        r = client.post(f"/api/studies/{study}/audit", json={}, headers=WRITE)
        job = _wait(client, r.json()["job"]["id"])
        assert job["status"] == "done", job
        assert job["result"]["reproduces_qpilot"] is True
        assert job["result"]["verdict_counts"] == existing["verdict_counts"]
        body = client.get(f"/api/studies/{study}/audit").json()
        assert body["status"] == "ready"
        assert body["manifest"]["lock_sha256"] == existing["lock_sha256"]
        assert body["manifest"]["grid_hash"] == existing["grid_hash"]
        check = client.post(f"/api/studies/{study}/audit/verify", json={}, headers=WRITE).json()
        assert check["ok"], check["problems"]
        assert _leftovers(root) == []
    _close(ctx)
