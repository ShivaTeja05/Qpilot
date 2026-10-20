"""Workspace routes over a real (throwaway) store."""


def test_system_says_what_this_install_is(client):
    body = client.get("/api/system").json()
    assert body["method"].startswith("LinRegPCR")
    assert body["never"][0].startswith("For research use only")
    assert "outbound" in body["model"]["outbound"]


def test_an_empty_store_lists_no_workspaces(client):
    assert client.get("/api/workspaces").json() == {"workspaces": []}


def test_bad_workspace_ids_are_not_found(client):
    for key in ("../etc", "ABCDEF123456", "abc", "0" * 13):
        assert client.get(f"/api/sessions/{key}").status_code == 404
        assert client.get(f"/api/studies/{key}").status_code == 404


def test_opening_a_file_starts_a_session(client, smoke_rdml):
    with smoke_rdml.open("rb") as fh:
        r = client.post(
            "/api/workspaces",
            files={"rdml": (smoke_rdml.name, fh, "application/xml")},
            headers={"origin": "http://127.0.0.1:7860"},
        )
    assert r.status_code == 202, r.text
    job_id = r.json()["job"]["id"]
    import time

    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    key = job["result"]["key"]
    frame = client.get(f"/api/sessions/{key}").json()
    assert frame["kind"] == "session" and not frame["results_visible"]
    assert frame["next_step"]["section"] == "design"
    assert [w["key"] for w in client.get("/api/workspaces").json()["workspaces"]] == [key]


def test_a_file_of_the_wrong_kind_is_refused(client):
    r = client.post(
        "/api/workspaces",
        files={"rdml": ("notes.txt", b"hello", "text/plain")},
        headers={"origin": "http://127.0.0.1:7860"},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_file"
