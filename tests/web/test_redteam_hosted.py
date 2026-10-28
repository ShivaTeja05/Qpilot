"""Red team (excellence round): the public sandbox (``QPILOT_HOSTED=1``) and the folder rule.

On a hosted server every visitor may do what a person may do (there is no launch key; the
banner says it is shared), so what a visitor's request can reach is the server's, not theirs:

* RT-EX-004: the Prism round trip read a folder anywhere in the *server's* home folder (on a
  Hugging Face Space, the app's own code); hosted, only qPilot's export folder (a visitor
  uploads the project Prism saved);
* RT-EX-005: a folder outside the allowed roots was looked up on disk before the roots were
  checked, so "There is no folder /x" against "must be inside your home folder" told whether
  any path on the server exists; now a path outside gets one answer either way;
* RT-EX-006: a 10 MB zipped RDML may hold 1 GiB of XML, about 20 GB of memory to load (the
  demo's 60 MB of XML takes 1.35 GB): ``QPILOT_MAX_UNPACKED_MB`` lowers the cap (the Space sets
  it), for RDML archives and plain XML and for workbooks;
* RT-EX-007: uploads and exports are kept until the server restarts; a hosted server turns
  read-only (507, in words) while its store's disk has less than ``QPILOT_MIN_FREE_MB`` free.
"""

from __future__ import annotations

import io
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qpilot.web import folders
from qpilot.web.security import Guard, Hosting
from tests.web.conftest import BASE, wait_job

# ---- RT-EX-005: the folder rule never says what exists outside the roots ------------------


@pytest.fixture
def roots(tmp_path):
    exports = tmp_path / "exports"
    home = tmp_path / "home"
    store = home / ".cache" / "qpilot" / "studies"
    elsewhere = tmp_path / "elsewhere"
    for folder in (exports, store, elsewhere / "real"):
        folder.mkdir(parents=True)
    (elsewhere / "real" / "project.pzfx").write_text("<x/>", encoding="utf-8", newline="\n")
    return {"exports": exports, "home": home, "store": store, "elsewhere": elsewhere}


def _refusal(roots, text: str, **kw) -> str:
    rule = folders.allowed_returned if text.endswith(".pzfx") else folders.allowed_folder
    with pytest.raises(folders.FolderRefused) as err:
        rule(text, roots=(roots["exports"], roots["home"]), store_root=roots["store"], **kw)
    return str(err.value)


@pytest.mark.parametrize("name", ["real", "real/project.pzfx"])
def test_a_path_outside_the_roots_gets_one_answer_whether_it_exists_or_not(roots, name):
    there = _refusal(roots, str(roots["elsewhere"] / name))
    missing = _refusal(roots, str(roots["elsewhere"] / name.replace("real", "nothing-here")))
    assert there == missing == folders.OUTSIDE


def test_a_missing_folder_inside_a_root_is_still_named(roots):
    assert "There is no folder" in _refusal(roots, str(roots["home"] / "not-yet"))


def test_the_server_root_and_system_folders_are_outside(roots):
    for text in ("/", "/etc", "/proc/self", "/dev/zero", "/nonexistent/x"):
        assert _refusal(roots, text) == folders.OUTSIDE


# ---- RT-EX-004: a hosted round trip reads the export folder only ---------------------------


def test_the_round_trip_roots_follow_the_hosting(monkeypatch, tmp_path):
    exports = tmp_path / "exports"
    monkeypatch.delenv("QPILOT_HOSTED", raising=False)
    roots, outside = folders.returned_rule(exports)
    assert roots == (exports, Path.home()) and outside == folders.OUTSIDE
    monkeypatch.setenv("QPILOT_HOSTED", "1")
    roots, outside = folders.returned_rule(exports)
    assert roots == (exports,) and "public sandbox" in outside


@pytest.fixture
def sent_mini(walked, monkeypatch, tmp_path):
    """The walked mini study with confirmed choices, sent to Prism (a project in exports)."""
    import importlib

    service = importlib.import_module("qpilot.studio_service")
    monkeypatch.setattr(service, "_mac_prism_app", lambda: None)
    monkeypatch.setattr(service, "_windows_prism_exe", lambda: None)
    c, store, studio, sid = (walked[k] for k in ("client", "store", "studio", "sid"))
    study = studio.study(sid)
    for card in store.cards(study):
        if card.status in ("open", "pending_human"):
            studio.decide(
                sid, card.id, card.recommended, "planned", "human", store.chain_head(study)
            )
    studio.accept(sid, studio.propose_confirm(sid, "choices").proposal.id, "human")
    drafted = wait_job(c, c.post(f"/api/sessions/{sid}/prism/draft").json()["job"])
    assert drafted["status"] == "done", drafted
    studio.accept(sid, drafted["result"]["proposal_id"], "human")
    job = wait_job(c, c.post(f"/api/sessions/{sid}/prism/send").json()["job"], 600)
    assert job["status"] == "done", job
    return {**walked, "sent": job["result"]}


def test_a_hosted_round_trip_never_reads_the_servers_home_folder(sent_mini, monkeypatch, tmp_path):
    c, sid, sent = sent_mini["client"], sent_mini["sid"], sent_mini["sent"]
    home = tmp_path / "server-home"
    (home / "app").mkdir(parents=True)
    project = Path(sent["bundle"]["folder"]) / sent["project"]
    shutil.copy(project, home / "app" / project.name)
    monkeypatch.setenv("HOME", str(home))
    url = f"/api/sessions/{sid}/prism/roundtrip"
    body = {"bundle": sent["bundle"]["id"], "folder": str(home / "app" / project.name)}
    monkeypatch.delenv("QPILOT_HOSTED", raising=False)
    r = c.post(url, json=body)
    assert r.status_code == 202, r.text  # on a person's own computer: their home folder
    wait_job(c, r.json()["job"])
    monkeypatch.setenv("QPILOT_HOSTED", "1")
    r = c.post(url, json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_folder", r.text
    assert "public sandbox" in r.json()["error"]["message"]
    r = c.post(url, json={**body, "folder": str(project)})  # the bundle's own folder: still read
    assert r.status_code == 202, r.text
    wait_job(c, r.json()["job"])


# ---- RT-EX-006: the unpacked-size cap a hosted server sets ----------------------------------


def _zipped_rdml(path: Path, xml: bytes) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("rdml_data.xml", xml)
    return path


def _padded_xml(n_bytes: int) -> bytes:
    """An RDML-looking document of about ``n_bytes`` that packs at well under 100:1."""
    pad = os.urandom(n_bytes // 2).hex().encode()
    return b'<rdml xmlns="http://www.rdml.org" version="1.4"><!--' + pad + b"--></rdml>"


def test_the_unpacked_cap_follows_the_environment(monkeypatch):
    from qpilot.io.rdml_io import MAX_XML_BYTES, unpacked_cap

    monkeypatch.delenv("QPILOT_MAX_UNPACKED_MB", raising=False)
    assert unpacked_cap(MAX_XML_BYTES) == MAX_XML_BYTES
    monkeypatch.setenv("QPILOT_MAX_UNPACKED_MB", "128")
    assert unpacked_cap(MAX_XML_BYTES) == 128 * 1024 * 1024
    monkeypatch.setenv("QPILOT_MAX_UNPACKED_MB", "999999")  # never raises a cap
    assert unpacked_cap(MAX_XML_BYTES) == MAX_XML_BYTES
    for junk in ("", "0", "-5", "lots"):
        monkeypatch.setenv("QPILOT_MAX_UNPACKED_MB", junk)
        assert unpacked_cap(MAX_XML_BYTES) == MAX_XML_BYTES


@pytest.mark.parametrize("zipped", [True, False])
def test_a_hosted_server_refuses_xml_over_its_cap_before_parsing(monkeypatch, tmp_path, zipped):
    from qpilot.io import rdml_io

    xml = _padded_xml(3 * 1024 * 1024)
    if zipped:
        path = _zipped_rdml(tmp_path / "big.rdml", xml)
    else:
        path = tmp_path / "big.xml"
        path.write_bytes(xml)
    parsed: list[str] = []
    monkeypatch.setattr(rdml_io.rdml.Rdml, "loadXMLString", lambda *a: parsed.append("x"))
    monkeypatch.setenv("QPILOT_MAX_UNPACKED_MB", "2")
    with pytest.raises(rdml_io.RdmlLoadError) as err:
        rdml_io.load(path)
    assert err.value.kind == "too_large" and not parsed
    monkeypatch.delenv("QPILOT_MAX_UNPACKED_MB")
    with pytest.raises(Exception) as other:  # read and handed to the parser (then it fails)
        rdml_io.load(path)
    assert getattr(other.value, "kind", "") != "too_large" and parsed


def test_a_hosted_server_refuses_a_workbook_over_its_cap(monkeypatch, tmp_path):
    from qpilot.io.connectors.base import CaptureError
    from qpilot.io.connectors.tables import check_workbook

    book = tmp_path / "cq.xlsx"
    with zipfile.ZipFile(book, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", _padded_xml(3 * 1024 * 1024))
    check_workbook(book)  # under the default caps
    monkeypatch.setenv("QPILOT_MAX_UNPACKED_MB", "2")
    with pytest.raises(CaptureError, match="too large"):
        check_workbook(book)


def test_the_space_sets_the_hosted_caps():
    app = (Path(__file__).parents[2] / "deploy" / "hf-space" / "app.py").read_text("utf-8")
    assert '"QPILOT_MAX_UNPACKED_MB"' in app and '"QPILOT_MIN_FREE_MB"' in app


# ---- RT-EX-007: a hosted server turns read-only when its disk is nearly full ---------------


def _guarded(hosting: Hosting) -> TestClient:
    app = FastAPI()

    @app.post("/api/x")
    def write() -> dict:
        return {"ok": True}

    @app.get("/api/x")
    def read() -> dict:
        return {"ok": True}

    return TestClient(Guard(app, token="t", hosting=hosting), base_url=BASE)


@pytest.mark.parametrize("free_mb, status", [(10, 507), (5000, 200)])
def test_hosted_writes_wait_for_disk_space(monkeypatch, tmp_path, free_mb, status):
    usage = shutil.disk_usage(tmp_path)._replace(free=free_mb * 1024 * 1024)
    monkeypatch.setattr("qpilot.web.security.shutil.disk_usage", lambda _p: usage)
    env = {"QPILOT_HOSTED": "1", "QPILOT_STUDIES_DIR": str(tmp_path / "studies")}
    with _guarded(Hosting.from_env(env)) as c:
        r = c.post("/api/x", json={}, headers={"origin": BASE})
        assert r.status_code == status, r.text
        if status == 507:
            assert r.json()["error"]["code"] == "sandbox_full"
            assert "install qPilot" in r.json()["error"]["message"]
        assert c.get("/api/x").status_code == 200  # reading never waits


def test_a_local_server_never_checks_the_disk(monkeypatch, tmp_path):
    def boom(_path):
        raise AssertionError("a local server asked for the disk usage")

    monkeypatch.setattr("qpilot.web.security.shutil.disk_usage", boom)
    with _guarded(Hosting()) as c:
        r = c.post("/api/x", json={}, headers={"origin": BASE, "x-qpilot-token": "t"})
        assert r.status_code == 200, r.text


def test_the_floor_can_be_set_or_switched_off():
    env = {"QPILOT_HOSTED": "1", "QPILOT_MIN_FREE_MB": "0"}
    assert not Hosting.from_env(env).disk_full()
    assert Hosting.from_env({"QPILOT_HOSTED": "1"}).min_free_mb == 1024
    assert Hosting.from_env({"QPILOT_HOSTED": "1", "QPILOT_MIN_FREE_MB": "x"}).min_free_mb == 1024


def test_an_upload_to_a_full_sandbox_is_refused_before_it_is_read(monkeypatch, tmp_path):
    usage = shutil.disk_usage(tmp_path)._replace(free=0)
    monkeypatch.setattr("qpilot.web.security.shutil.disk_usage", lambda _p: usage)
    seen: list[int] = []
    app = FastAPI()

    @app.post("/api/workspaces")
    async def upload(request: __import__("fastapi").Request) -> dict:
        seen.append(len(await request.body()))
        return {}

    env = {"QPILOT_HOSTED": "1", "QPILOT_STUDIES_DIR": str(tmp_path)}
    with TestClient(Guard(app, token="t", hosting=Hosting.from_env(env)), base_url=BASE) as c:
        files = {"rdml": ("x.rdml", io.BytesIO(b"x" * 1000))}
        r = c.post("/api/workspaces", files=files, headers={"origin": BASE})
    assert r.status_code == 507 and not seen
