"""Red team: the robustness audit's routes (downloads, gene views, what-if, attached folders).

Skipped until the audit router is part of the app. A hostile audit folder is planted in the
store beside a study walked to results (the mini file): names listed in its ``AUDIT.sha256``
that point outside it, names with separators, a manifest that is not JSON.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.web.test_redteam_blind import walked

CANARY = "qpilot-redteam-audit-canary-91d2"
FILES = "/api/studies/{study_id}/audit/files/{name}"


@pytest.fixture(scope="module")
def audited(tmp_path_factory) -> Iterator[dict[str, Any]]:
    """A visible study with a hostile audit folder planted beside it."""
    base = tmp_path_factory.mktemp("audit")
    with walked(base, reblind=False) as walk:
        if FILES not in walk["app"].openapi()["paths"]:
            pytest.skip("the audit router is not merged in this checkout")
        secret = base / "outside" / "secret.txt"
        secret.parent.mkdir()
        secret.write_text(CANARY)
        folder = walk["store"].root / "simulator_audits" / walk["study_id"]
        folder.mkdir(parents=True)
        (folder / "audit_manifest.json").write_text("{ not json")
        (folder / "ok.txt").write_text("fine")
        (folder / "evil.txt").symlink_to(secret)
        (folder / "up").symlink_to(base / "outside", target_is_directory=True)
        listed = ["ok.txt", "evil.txt", "up/secret.txt", "../outside/secret.txt", ".."]
        (folder / "AUDIT.sha256").write_text("".join(f"{'0' * 64}  {n}\n" for n in listed))
        yield {**walk, "folder": folder, "secret": secret}


@pytest.mark.parametrize(
    "name",
    [
        "evil.txt",
        "up%2Fsecret.txt",
        "..%2Foutside%2Fsecret.txt",
        "%2e%2e",
        str(Path("/etc/hosts")).replace("/", "%2F"),
    ],
)
def test_audit_downloads_never_leave_the_audit_folder(audited, name):
    c, study_id = audited["client"], audited["study_id"]
    r = c.get(f"/api/studies/{study_id}/audit/files/{name}")
    assert r.status_code in (400, 404, 409, 422), (r.status_code, r.text[:200])
    assert CANARY not in r.text and "localhost" not in r.text


def test_a_listed_file_inside_the_folder_downloads(audited):
    c, study_id = audited["client"], audited["study_id"]
    listing = c.get(f"/api/studies/{study_id}/audit/files")
    assert listing.status_code == 200, listing.text[:200]
    names = {f["name"] for f in listing.json()["files"]}
    assert "ok.txt" in names
    assert not names & {"up/secret.txt", "../outside/secret.txt", ".."}
    r = c.get(f"/api/studies/{study_id}/audit/files/ok.txt")
    assert r.status_code == 200 and r.text == "fine"


@pytest.mark.parametrize(
    "gene", ["..%2F..%2Fresults.json", "%00", "<img src=x onerror=alert(1)>", "A" * 300]
)
@pytest.mark.parametrize("view", ["gene", "analyses", "effects", "lab"])
def test_hostile_genes_in_audit_views_are_refusals_not_errors(audited, view, gene):
    c, study_id = audited["client"], audited["study_id"]
    r = c.get(f"/api/studies/{study_id}/audit/{view}/{gene}")
    assert r.status_code in (400, 404, 409, 422), (r.status_code, r.text[:200])
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    "path,body",
    [
        ("whatif", {"choices": {"../../x": "y"}}),
        ("whatif", {"choices": {"a" * 5000: "b" * 5000}}),
        ("whatif", {"choices": [1, 2, 3]}),
        ("whatif", {}),
        ("samples", {"gene": "../../etc/passwd"}),
        ("samples", {"gene": None, "samples": ["x"] * 100000}),
    ],
)
def test_hostile_audit_bodies_are_refusals_not_errors(audited, path, body):
    c, study_id = audited["client"], audited["study_id"]
    r = c.post(f"/api/studies/{study_id}/audit/{path}", json=body)
    assert r.status_code in (200, 400, 404, 409, 413, 422), (r.status_code, r.text[:200])
    assert "Traceback" not in r.text and CANARY not in r.text


@pytest.mark.parametrize("name", ["%2e%2e", "..%2F..", "x" * 300, "%00"])
def test_attached_audit_names_are_only_keys(audited, name):
    c = audited["client"]
    r = c.get(f"/api/audits/{name}")
    assert r.status_code == 404
    r = c.get(f"/api/audits/{name}/files/secret.txt")
    assert r.status_code == 404


def test_running_the_audit_twice_is_one_job(audited):
    c, study_id = audited["client"], audited["study_id"]
    os.environ.setdefault("QPILOT_REDTEAM", "1")
    first = c.post(f"/api/studies/{study_id}/audit")
    second = c.post(f"/api/studies/{study_id}/audit")
    if first.status_code != 202:  # refused (the mini study, or the planted folder): in words
        assert first.status_code in (400, 409, 422), first.text[:200]
        return
    assert second.status_code == 202
    assert first.json()["job"]["id"] == second.json()["job"]["id"]


@pytest.mark.xfail(
    strict=False,  # fixed on ui/api-audit faa5025 (verified): plain once merged
    reason="RT-UI-021 a NUL in an audit file name (…/audit/files/AUDIT.sha256%00.txt) is a 500: "
    "_download resolves the path before checking the name against the audit's list",
)
def test_a_nul_in_an_audit_file_name_is_not_found(audited):
    from fastapi.testclient import TestClient

    from tests.web.conftest import BASE, TOKEN

    # No ``with``: leaving it would run the shared app's shutdown and close its context.
    c = TestClient(audited["app"], base_url=BASE, raise_server_exceptions=False)
    c.headers["x-qpilot-token"] = TOKEN
    r = c.get(f"/api/studies/{audited['study_id']}/audit/files/AUDIT.sha256%00.txt")
    assert r.status_code == 404, r.status_code


@pytest.mark.xfail(
    strict=False,  # fixed on ui/api-audit faa5025 (verified): plain once merged
    reason="RT-UI-022 a damaged audit_manifest.json (not JSON) makes POST …/audit/verify a 500 "
    "(json.loads unguarded); status already says 'The audit's manifest cannot be read.'",
)
def test_verifying_a_damaged_audit_says_so(audited):
    from fastapi.testclient import TestClient

    from tests.web.conftest import BASE, ORIGIN, TOKEN

    c = TestClient(audited["app"], base_url=BASE, raise_server_exceptions=False)  # no ``with``
    c.headers["x-qpilot-token"] = TOKEN
    r = c.post(f"/api/studies/{audited['study_id']}/audit/verify", json={}, headers=ORIGIN)
    assert r.status_code in (200, 409, 422), r.status_code
    assert "Traceback" not in r.text
