"""Red team (excellence round): the ETag/304 layer (``qpilot/web/cache.py``) never answers for
another state, key or study.

The layer tags the bytes a route has just produced and answers 304 only when the request names
that very tag, so the route (and its blind gate) runs on every read. These tests keep it so:
an old tag of a study's results is not a way past the blind rule once a person's design change
reopens the confirmation; a tag is no oracle without the launch key; a tag of one view is not
honoured by another; ``Prefer: respond-async`` softens only the two waits it names.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from qpilot.mcp_server import QpilotTools
from tests.web.conftest import BASE


def _reblind(c: TestClient, store, sid: str) -> None:
    """An agent proposes moving one sample; a person accepts it: the session is blind again."""
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    listed = c.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    change = next(
        p for p in listed["proposals"] if p["status"] == "proposed" and p["kind"] == "design.group"
    )
    r = c.post(
        f"/api/sessions/{sid}/proposals/{change['id']}/accept",
        json={"reason": "the lab book says KO", "expected_head": listed["head"]},
    )
    assert r.status_code == 200 and not r.json()["results_visible"], r.text


def test_an_old_tag_is_no_way_past_the_blind_rule(walked):
    c, store, sid, study = walked["client"], walked["store"], walked["sid"], walked["study"]
    views = [f"/api/studies/{study}/results", f"/api/studies/{study}/cards"]
    tags = {}
    for url in views:
        r = c.get(url)
        assert r.status_code == 200 and r.headers.get("etag"), (url, r.status_code)
        assert c.get(url, headers={"if-none-match": r.headers["etag"]}).status_code == 304
        tags[url] = r.headers["etag"]
    _reblind(c, store, sid)
    for url, tag in tags.items():
        for offered in (tag, "*"):
            r = c.get(url, headers={"if-none-match": offered, "prefer": "respond-async"})
            assert r.status_code == 403 and r.json()["error"]["code"] == "blind", (url, r.text)


def test_a_tag_is_no_oracle_without_the_key(walked):
    c, study = walked["client"], walked["study"]
    url = f"/api/studies/{study}/results"
    tag = c.get(url).headers["etag"]
    with TestClient(c.app, base_url=BASE) as stranger:
        for offered in (tag, "*"):
            r = stranger.get(url, headers={"if-none-match": offered})
            assert r.status_code == 401 and "etag" not in r.headers, r.status_code


def test_one_views_tag_is_not_honoured_by_another(walked):
    c, sid, study = walked["client"], walked["sid"], walked["study"]
    tag = c.get(f"/api/studies/{study}/results").headers["etag"]
    for url in (f"/api/studies/{study}/cards", f"/api/sessions/{sid}", "/api/workspaces"):
        r = c.get(url, headers={"if-none-match": tag})
        assert r.status_code == 200 and r.headers["etag"] != tag, url


def test_a_304_is_never_stored_by_the_browser(walked):
    c, study = walked["client"], walked["study"]
    url = f"/api/studies/{study}/results"
    r = c.get(url, headers={"if-none-match": c.get(url).headers["etag"]})
    assert r.status_code == 304 and r.content == b""
    assert "no-store" in r.headers.get("cache-control", "")
    assert r.headers["content-security-policy"].startswith("default-src 'self'")


def test_respond_async_softens_only_loading_and_warming(walked):
    c, study = walked["client"], walked["study"]
    soft = {"prefer": "respond-async"}
    assert c.get("/api/studies/nope/results", headers=soft).status_code == 404
    r = c.get(f"/api/studies/{study}/report/figure/info", params={"gene": "x"}, headers=soft)
    assert r.status_code == 404, r.text  # not softened into a 202 the page would wait on
    r = c.get(f"/api/studies/{study}/cards/not_a_card", headers=soft)
    assert r.status_code in (404, 405, 422) and r.status_code != 202
