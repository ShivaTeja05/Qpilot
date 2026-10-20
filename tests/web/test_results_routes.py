"""Results routes over a study walked through Studio (the synthetic mini file).

Results, one gene, the flip matrix, the Decision Cards (decide, undo as a new entry, turn down an
agent's request), the decision chain; the blind rule, the version check and the actor.
"""

from __future__ import annotations

from qpilot.mcp_server import QpilotTools
from tests.web.test_studio_flow import no_html


def test_results_say_what_the_study_found(walked):
    c, study = walked["client"], walked["study"]
    body = c.get(f"/api/studies/{study}/results").json()
    assert body["study_id"] == study and body["session"] == walked["sid"]
    assert [g["gene"] for g in body["genes"]] == ["1-Mar"]
    gene = body["genes"][0]
    assert gene["conclusion"] in ("up", "down", "none") and len(gene["ci"]) == 2
    assert 0.0 <= gene["holds"] <= 1.0 and gene["n_cells"] > 0
    assert body["summary"]["mode"] == "groups"
    assert {g["label"] for g in body["summary"]["groups"]} == {"KO", "WT"}
    assert body["references"]["used"] == ["GAPDH"]
    assert body["rule"]["min_fold"] == 2.0 and "p < 0.05" in body["rule"]["text"]
    assert body["audit"]["status"] == "none"
    assert body["head"] == walked["store"].chain_head(study)
    text = body["summary"]["text"]
    assert text and "".join(s["text"] for s in text["segments"]) == text["plain"]
    assert all(f["id"].startswith("f_") for f in text["facts"])
    no_html(body)


def test_one_gene_and_the_flip_matrix(walked):
    c, study = walked["client"], walked["study"]
    gene = c.get(f"/api/studies/{study}/genes/1-Mar").json()
    assert gene["gene"] == "1-Mar" and gene["prev_gene"] is None and gene["next_gene"] is None
    grid = gene["grid"]
    assert grid and len(grid["cells"]) == gene["row"]["n_cells"] == len(grid["log2fc"])
    assert all(len(cell) == len(grid["dimensions"]) for cell in grid["cells"])
    assert {e["dimension"] for e in gene["effects"]} == set(gene["robustness"]["impact"])
    flips = c.get(f"/api/studies/{study}/flips").json()
    assert flips["genes"] == ["1-Mar"]
    for row in flips["rows"]:
        assert len(row["flips"]) == len(flips["genes"]) == len(row["max_delta_log2fc"])
        assert sum(o["planned"] for o in row["options"]) == 1
        for option in row["options"]:
            assert len(option["conclusion"]) == len(flips["genes"])
    assert c.get(f"/api/studies/{study}/genes/GAPDH").status_code == 404
    assert c.get(f"/api/studies/{study}/genes/{'x' * 200}").status_code == 404
    no_html(gene)
    no_html(flips)


def test_decide_then_undo_writes_new_entries_as_a_person(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    cards = c.get(f"/api/studies/{study}/cards").json()
    card = next(v for v in cards["cards"] if v["card"]["id"] == "card_undetermined")
    assert card["card"]["decision"] == "drop" and card["undo_option"] is None
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/decide",
        json={"option": "cap", "reason": "Undo: our lab caps empty wells", "actor": "agent",
              "expected_head": cards["head"]},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["outcome"]["status"] == "applied" and after["card"]["card"]["decision"] == "cap"
    last = store.entries(study)[-1]
    assert last.actor == "human" and last.reason == "our lab caps empty wells"
    assert after["card"]["undo_option"] == "drop"
    # the page's old head is now stale for this card
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/decide",
        json={"option": "drop", "reason": "back", "expected_head": cards["head"]},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    assert r.json()["error"]["details"]["head"] == store.chain_head(study)
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/undo",
        json={"reason": "the cap was a slip", "expected_head": after["head"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["card"]["card"]["decision"] == "drop"
    entries = store.entries(study)
    assert entries[-1].reason.startswith("Undo:") and entries[-1].actor == "human"
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/undo",
        json={"reason": "again", "expected_head": store.chain_head(study)},
    )
    assert r.status_code == 409 and "Nothing to undo" in r.json()["error"]["message"]
    chain = c.get(f"/api/studies/{study}/decisions").json()
    assert chain["head"] == store.chain_head(study)
    assert [e["undo"] for e in chain["entries"]][-1] is True
    assert chain["entries"][-1]["option_label"]


def test_decide_refuses_bad_requests(walked):
    c, study = walked["client"], walked["study"]
    head = walked["store"].chain_head(study)
    url = f"/api/studies/{study}/cards"
    r = c.post(f"{url}/card_undetermined/decide", json={"option": "cap", "reason": " "})
    assert r.status_code == 422 and "reason" in r.json()["error"]["message"]
    r = c.post(f"{url}/card_undetermined/decide", json={"option": "nope", "reason": "x"})
    assert r.status_code == 422 and "Unknown option" in r.json()["error"]["message"]
    r = c.post(f"{url}/card_nothing/decide", json={"option": "cap", "reason": "x"})
    assert r.status_code == 404
    r = c.post(f"{url}/Card-Bad!/decide", json={"option": "cap", "reason": "x"})
    assert r.status_code == 404
    r = c.post(f"{url}/card_undetermined/decide", json={"option": "cap", "reason": "x" * 501})
    assert r.status_code == 422
    r = c.post(
        f"{url}/card_undetermined/decide",
        json={"option": "cap", "reason": "x"},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "cross_origin"
    assert walked["store"].chain_head(study) == head, "no refusal writes anything"


def test_an_agents_request_waits_and_can_be_turned_down(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    QpilotTools(store).qpcr_decide(study, "card_undetermined", "cap", "the agent prefers cap")
    cards = c.get(f"/api/studies/{study}/cards").json()
    assert cards["pending_requests"] == 1
    card = next(v for v in cards["cards"] if v["card"]["id"] == "card_undetermined")
    assert card["pending"][0]["option"] == "cap" and card["pending"][0]["actor"] == "agent"
    assert next(o for o in card["options"] if o["id"] == "cap")["requested"]
    assert card["card"]["decision"] == "drop", "a request applies nothing"
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/reject-request",
        json={"reason": "we keep dropping them", "expected_head": cards["head"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"]["status"] == "rejected" and not r.json()["card"]["pending"]
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/reject-request",
        json={"reason": "again"},
    )
    assert r.status_code == 409 and "no request" in r.json()["error"]["message"]
    chain = c.get(f"/api/studies/{study}/decisions").json()
    assert not chain["pending"] and any(
        e["entry"]["status"] == "rejected" for e in chain["entries"]
    )


def test_explain_needs_a_model(walked):
    c, study = walked["client"], walked["study"]
    r = c.post(f"/api/studies/{study}/cards/card_undetermined/explain")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_model"


def test_results_are_blind_again_when_the_design_changes(walked):
    c, study, store, studio = walked["client"], walked["study"], walked["store"], walked["studio"]
    sid = walked["sid"]
    assert c.get(f"/api/studies/{study}/results").status_code == 200
    # an agent proposes another group and a person accepts it: the confirmed design changed
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_2", {"group": "KO"})
    pending = [p for p in studio.inbox(sid, "design", "proposed") if p.subject == "WT_2"]
    assert pending
    studio.accept(sid, pending[0].id, "human", "checked")
    assert not studio.results_visible(sid)
    for path in ("results", "flips", "cards", "decisions", "genes/1-Mar", "cards/card_refset"):
        r = c.get(f"/api/studies/{study}/{path}")
        assert r.status_code == 403 and r.json()["error"]["code"] == "blind", path
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/decide",
        json={"option": "cap", "reason": "x"},
    )
    assert r.status_code == 403
    frame = c.get(f"/api/sessions/{sid}").json()
    assert not frame["results_visible"] and frame["study_id"] is None


def test_ids_are_checked(walked):
    c = walked["client"]
    for key in ("../etc", "ABCDEF123456", "0" * 12):
        r = c.get(f"/api/studies/{key}/results")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
