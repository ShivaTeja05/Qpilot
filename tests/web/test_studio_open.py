"""Opening a file for Studio: upload caps, kinds, the one sentence, and where uploads are kept."""

from __future__ import annotations

from qpilot.web import views
from qpilot.web.routers import workspaces
from tests.web.conftest import wait_job


def _open(client, name, data, **form):
    return client.post(
        "/api/workspaces", files={"rdml": (name, data, "application/xml")}, data=form
    )


def test_uploads_over_the_cap_are_refused_and_not_kept(sclient, web_store, monkeypatch):
    monkeypatch.setattr(workspaces, "MAX_RDML_BYTES", 1024)
    r = _open(sclient, "big.rdml", b"<rdml>" + b" " * 4096 + b"</rdml>")
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"
    assert not any(views.inputs_dir(web_store).iterdir()), "a refused upload leaves nothing"


def test_empty_and_wrong_kind_uploads_are_refused(sclient):
    r = _open(sclient, "empty.rdml", b"")
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_file"
    r = _open(sclient, "../../escape.exe", b"MZ")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_file"
    assert "escape.exe" in r.json()["error"]["message"] and ".." not in r.json()["error"]["message"]


def test_the_sentence_is_capped_and_remembered_for_the_design(sclient, mini_rdml):
    data = mini_rdml.read_bytes()
    r = _open(sclient, "mini.rdml", data, sentence="x" * 501)
    assert r.status_code == 422
    sentence = "Knock-out vs wild type mouse liver, two mice each"
    job = wait_job(sclient, _open(sclient, "mini.rdml", data, sentence=sentence).json()["job"])
    sid = job["result"]["key"]
    r = sclient.post(f"/api/sessions/{sid}/propose/design")
    assert wait_job(sclient, r.json()["job"])["status"] == "done"
    quarantine = sclient.get(f"/api/sessions/{sid}/quarantine").json()["entries"]
    assert [e["value"] for e in quarantine if e["origin"] == "studio:sentence"] == [sentence]


def test_an_upload_is_kept_by_content(sclient, web_store, mini_rdml):
    data = mini_rdml.read_bytes()
    first = wait_job(sclient, _open(sclient, "a.rdml", data).json()["job"])
    second = wait_job(sclient, _open(sclient, "b.rdml", data).json()["job"])
    assert first["result"]["key"] == second["result"]["key"]
    kept = list(views.inputs_dir(web_store).iterdir())
    assert len(kept) == 1 and kept[0].suffix == ".rdml" and len(kept[0].stem) == 24


def test_the_workspace_shows_the_name_the_file_had(sclient, mini_rdml):
    job = wait_job(
        sclient, _open(sclient, "Liver KO vs WT.rdml", mini_rdml.read_bytes()).json()["job"]
    )
    frame = sclient.get(f"/api/sessions/{job['result']['key']}").json()
    assert frame["title"] == "Liver KO vs WT.rdml" == frame["facts"]["file_name"]


def test_an_unreadable_file_says_why_in_plain_words(sclient, fixtures_dir):
    cases = {
        "not xml.rdml": (b"hello, not xml", "not a valid RDML file"),
        "entities.rdml": ((fixtures_dir / "xxe.rdml").read_bytes(), "XML entities"),
    }
    for name, (data, words) in cases.items():
        job = wait_job(sclient, _open(sclient, name, data).json()["job"])
        assert job["status"] == "failed" and name in job["error"]["message"], job
        assert words in job["error"]["message"] and "XML load error" not in job["error"]["message"]
