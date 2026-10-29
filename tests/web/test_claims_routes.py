"""Claim Auditor routes over a study walked through Studio (the synthetic mini file, KO vs WT).

Sentences are written from the study's own result as the API serves it (its gene, its groups,
its call), so the expected verdicts follow from the record, not from numbers typed here. Also:
every number in a reason is a cited fact; the refusals (blind, unknown study, too long, empty,
another site); the examples come out as described; the model may only propose.
"""

from __future__ import annotations

import json
import re

import pytest

from qpilot.ai.client import MockBackend, ModelClient
from qpilot.mcp_server import QpilotTools
from tests.web.conftest import wait_job
from tests.web.test_studio_flow import no_html

GENE = "1-Mar"  # the mini file's target, named the way Excel writes MARCH1
METHOD = ("95 % CI", "p < 0.05", "at least 2-fold", "significance level 0.05", "80 %")


def post(c, study: str, text: str):  # noqa: ANN001, ANN201
    return c.post(f"/api/studies/{study}/claims", json={"text": text})


def facts_only(text: dict, names: set[str]) -> None:
    """Every digit in a claim text is in a cited fact, a name of the study or the method."""
    assert "".join(s["text"] for s in text["segments"]) == text["plain"]
    cited = {f["id"] for f in text["facts"]}
    for seg in text["segments"]:
        if seg["fact"] is not None:
            assert seg["fact"] in cited
            continue
        rest = seg["text"]
        for name in sorted(names | set(METHOD), key=len, reverse=True):
            rest = rest.replace(name, " ")
        assert not re.search(r"\d", rest), (seg["text"], text["plain"])


def all_texts(claim: dict) -> list[dict]:
    out = [claim["headline"], *[c["text"] for c in claim["checks"]]]
    out += [ch["label"] for ch in claim["choices"]]
    return out + ([claim["suggestion"]] if claim["suggestion"] else [])


@pytest.fixture
def study(walked):
    c, study = walked["client"], walked["study"]
    results = c.get(f"/api/studies/{study}/results").json()
    row = next(g for g in results["genes"] if g["gene"] == GENE)
    a, b = (g["label"] for g in results["summary"]["groups"])
    return {**walked, "row": row, "a": a, "b": b, "refs": results["references"]["used"]}


def test_a_true_sentence_is_supported_and_every_number_is_a_fact(study):
    c, sid, row, a, b = study["client"], study["study"], study["row"], study["a"], study["b"]
    if row["conclusion"] == "none":
        text = f"{GENE} did not differ between {a} and {b}."
    else:
        word = "higher" if row["conclusion"] == "up" else "lower"
        text = f"{GENE} was {word} in {a} than in {b}."
    r = post(c, sid, text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["study_id"] == sid and body["length"] == len(text)
    assert body["groups"] == [a, b] and body["head"] == study["store"].chain_head(sid)
    (claim,) = body["claims"]
    assert claim["verdict"] == "supported" and claim["verdict_label"] == "Supported"
    assert claim["gene"] == GENE and claim["reading"]["gene"] == GENE
    assert claim["suggestion"] is None and claim["severity"] == 0
    assert body["summary"] == {
        "n": 1,
        "supported": 1,
        "counts": {**dict.fromkeys(body["verdicts"], 0), "supported": 1},
        "sentence": "1 of 1 claim supported by this study's record.",
    }
    roles = {s["role"]: s["written"] for s in claim["spans"]}
    assert roles["gene"] == GENE and text[claim["sentence"]["start"] : claim["sentence"]["end"]]
    for span in claim["spans"]:
        assert text[span["start"] : span["end"]] == span["written"]
    for t in all_texts(claim):
        facts_only(t, {GENE, *study["refs"], a, b})
    no_html(body)


def words(row: dict) -> tuple[str, str]:
    """The word for the study's sign of change, and the other one."""
    return ("higher", "lower") if row["log2fc"] >= 0 else ("lower", "higher")


def test_the_other_direction_is_contradicted_and_a_sentence_is_suggested(study):
    c, sid, row, a, b = study["client"], study["study"], study["row"], study["a"], study["b"]
    same, other = words(row)
    (claim,) = post(c, sid, f"{GENE} tended to be {other} in {a} than in {b}.").json()["claims"]
    assert claim["reading"]["hedged"] and claim["verdict"] in ("contradicted", "choices")
    direction = next(ch for ch in claim["checks"] if ch["check"] == "direction")
    assert direction["status"] == "opposite"
    suggestion = claim["suggestion"]
    assert suggestion and suggestion["plain"].startswith(GENE)
    assert any(f["origin"] == "result" for f in suggestion["facts"])
    facts_only(suggestion, {GENE, a, b})
    (claim,) = post(c, sid, f"{GENE} tended to be {same} in {a} than in {b}.").json()["claims"]
    assert claim["verdict"] == "supported"


def test_a_change_the_rule_does_not_call_is_overstated(study):
    c, sid, row, a, b = study["client"], study["study"], study["row"], study["a"], study["b"]
    same, _ = words(row)
    (claim,) = post(c, sid, f"{GENE} was {same} in {a} than in {b}.").json()["claims"]
    direction = next(ch for ch in claim["checks"] if ch["check"] == "direction")
    if row["conclusion"] == "none":
        assert direction["status"] == "stronger" and claim["verdict"] in ("overstated", "choices")
        assert "at least 2-fold" in direction["text"]["plain"]
    else:
        assert direction["status"] == "ok" and claim["verdict"] == "supported"


def test_the_same_sentence_about_the_second_group_is_read_the_other_way(study):
    c, sid, row, a, b = study["client"], study["study"], study["row"], study["a"], study["b"]
    _, other = words(row)  # said of the second group, the other word is the same change
    (claim,) = post(c, sid, f"{GENE} tended to be {other} in {b} than in {a}.").json()["claims"]
    assert claim["reading"]["inverted"] and claim["verdict"] == "supported"


def test_a_fold_inside_and_far_outside_the_interval(study):
    c, sid, row, a = study["client"], study["study"], study["row"], study["a"]
    same, _ = words(row)
    size = row["fc"] if row["fc"] >= 1 else 1 / row["fc"]
    inside = f"{float(f'{size:.2g}'):g}"  # the estimate, as a paper would round it
    text = f"{GENE} tended to be {inside}-fold {same} in {a}."
    (claim,) = post(c, sid, text).json()["claims"]
    assert claim["verdict"] == "supported", claim["headline"]["plain"]
    fold = next(ch for ch in claim["checks"] if ch["check"] == "fold")
    quoted = [f for f in fold["text"]["facts"] if f["origin"] == "text"]
    assert quoted and quoted[0]["value"] == f"{inside}-fold"
    assert quoted[0]["path"].startswith("your text, characters")
    far = int(size * 1000)
    (claim,) = post(c, sid, f"{GENE} tended to be {far}-fold {same} in {a}.").json()["claims"]
    assert claim["verdict"] == "overstated"
    assert next(ch for ch in claim["checks"] if ch["check"] == "fold")["status"] == "stronger"


def test_a_named_group_study_flags_groups_it_does_not_compare(study):
    """On a lab's own file (KO vs WT): a claim about stage or another gene's status is a
    different comparison; one naming the study's groups is checked as before."""
    c, sid, row, a, b = study["client"], study["study"], study["row"], study["a"], study["b"]
    word = "higher" if row["conclusion"] in ("up", "none") else "lower"
    (claim,) = post(c, sid, f"{GENE} was {word} in TP53-mutant mice.").json()["claims"]
    assert claim["verdict"] == "mismatch", claim["headline"]["plain"]
    assert f"compares {a} against {b}, not TP53 status" in claim["headline"]["plain"]
    (claim,) = post(c, sid, f"{GENE} was {word} in stage 4 tumours.").json()["claims"]
    assert claim["verdict"] == "mismatch"
    (claim,) = post(c, sid, f"{GENE} was {word} in {a} than in {b}.").json()["claims"]
    assert claim["verdict"] != "mismatch" and claim["reading"]["other_groups"] == []


def test_normalisers_and_genes_the_study_did_not_measure(study):
    c, sid, refs = study["client"], study["study"], study["refs"]
    (claim,) = post(c, sid, f"Expression was normalised to {refs[0]}.").json()["claims"]
    assert claim["kind"] == "normaliser" and claim["verdict"] == "supported"
    (claim,) = post(c, sid, "Expression was normalised to ACTB.").json()["claims"]
    assert claim["verdict"] == "contradicted" and "ACTB" in claim["headline"]["plain"]
    assert claim["suggestion"]["plain"].endswith(f"{refs[0]}.")
    (claim,) = post(c, sid, "TP53 was up-regulated in these samples.").json()["claims"]
    assert claim["verdict"] == "unchecked" and claim["reading"]["gene_status"] == "absent"
    assert "not measured" in claim["headline"]["plain"]
    (claim,) = post(c, sid, f"{refs[0]} was higher in KO.").json()["claims"]
    assert claim["verdict"] == "unchecked" and "control gene" in claim["headline"]["plain"]


def test_no_claim_found_says_what_to_write(study):
    body = post(study["client"], study["study"], "RNA was extracted with TRIzol.").json()
    assert body["claims"] == [] and body["summary"]["n"] == 0
    assert "name a gene" in body["summary"]["sentence"]


def test_refusals_in_words(study):
    c, sid = study["client"], study["study"]
    r = post(c, sid, "x" * 5001)
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"
    assert "5 000" in r.json()["error"]["message"] or "5,000" in r.json()["error"]["message"]
    r = post(c, sid, "   \n ")
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    for key in ("0" * 12, "../etc", "ABCDEF123456"):
        r = post(c, key, "ODC1 was up.")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = c.post(
        f"/api/studies/{sid}/claims", json={"text": "x"}, headers={"origin": "https://evil.example"}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "cross_origin"
    assert c.post(f"/api/studies/{sid}/claims", json={}).status_code == 422
    assert c.post(f"/api/studies/{sid}/claims", json={"text": 5}).status_code == 422


def test_claims_are_blind_until_the_design_and_curves_are_confirmed(study):
    c, sid, store, studio = study["client"], study["study"], study["store"], study["studio"]
    session = study["sid"]
    assert post(c, sid, f"{GENE} was higher in KO.").status_code == 200
    QpilotTools(store).qpcr_propose(session, "design.group", "WT_2", {"group": "KO"})
    pending = [p for p in studio.inbox(session, "design", "proposed") if p.subject == "WT_2"]
    studio.accept(session, pending[0].id, "human", "checked")
    assert not studio.results_visible(session)
    for r in (
        post(c, sid, f"{GENE} was higher in KO."),
        c.get(f"/api/studies/{sid}/claims/examples"),
        c.post(f"/api/studies/{sid}/claims/read", json={"text": f"{GENE} was higher in KO."}),
    ):
        assert r.status_code == 403 and r.json()["error"]["code"] == "blind"


def test_examples_are_written_from_the_study_and_come_out_as_described(study):
    c, sid = study["client"], study["study"]
    r = c.get(f"/api/studies/{sid}/claims/examples")
    assert r.status_code == 200
    body = r.json()
    assert body["study_id"] == sid and body["note"]
    assert body["paragraph"] == " ".join(e["text"] for e in body["examples"])
    for example in body["examples"]:
        (claim,) = post(c, sid, example["text"]).json()["claims"]
        assert claim["verdict"] == example["intent"], example
    no_html(body)


def test_the_text_is_not_stored(study):
    c, sid, store = study["client"], study["study"], study["store"]
    secret = f"{GENE} was higher in KO (unpublished-7f3a)."

    def files() -> dict:
        return {
            p: p.stat().st_mtime_ns
            for p in store.root.rglob("*")
            if p.is_file() and p.name != ".lock"  # the store's lock is taken to read
        }

    before = files()
    assert post(c, sid, secret).status_code == 200
    after = files()
    assert before == after
    for path in after:
        assert b"unpublished-7f3a" not in path.read_bytes()


# ---- the model may only propose ----------------------------------------------------------


def test_with_no_model_the_rules_read_alone(study):
    c, sid = study["client"], study["study"]
    r = c.post(f"/api/studies/{sid}/claims/read", json={"text": f"{GENE} rose in KO."})
    assert r.status_code == 202
    job = wait_job(c, r.json()["job"])
    assert job["status"] == "done" and job["kind"] == "claims.read"
    result = job["result"]
    assert result["proposed"] == 0 and result["report"]["reader"] == "rules"
    assert "No model" in result["report"]["model_note"]


class LocalMock(MockBackend):
    """A model on this machine (as a local server would be)."""

    remote = False


def with_model(study, reply):  # noqa: ANN001, ANN201
    study["ctx"].studio._client = ModelClient(backend=LocalMock(lambda s, m: reply(m)))
    return study["ctx"].studio.client.backend


def test_a_model_proposal_is_kept_only_when_its_words_are_in_the_sentence(study):
    c, sid, a = study["client"], study["study"], study["a"]
    text = f"In {a} animals the expression of membrane-associated ring finger 1 went way up."

    def reply(messages):  # noqa: ANN001, ANN202
        assert "Sentences:" in messages[0]["content"]
        return json.dumps(
            {
                "claims": [
                    {"sentence": 1, "gene_text": "membrane-associated ring finger 1",
                     "gene": GENE, "direction_text": "went way up"},
                    {"sentence": 1, "gene_text": "MARCH1", "gene": GENE,
                     "fold_text": "4.2-fold"},
                    {"sentence": 1, "gene_text": "ring finger", "gene": "TP53",
                     "direction_text": "up"},
                ]
            }
        )  # fmt: skip

    backend = with_model(study, reply)
    r = c.post(f"/api/studies/{sid}/claims/read", json={"text": text})
    job = wait_job(c, r.json()["job"])
    assert job["status"] == "done", job
    result = job["result"]
    assert backend.calls and result["proposed"] == 3 and result["accepted"] == 1
    assert len(result["rejected"]) == 2
    report = result["report"]
    assert report["reader"] == "rules+model"
    (claim,) = report["claims"]
    assert claim["reading"]["source"] == "model" and claim["gene"] == GENE
    assert claim["verdict"] in ("supported", "contradicted", "overstated", "choices")


def test_a_remote_model_is_never_sent_the_text(study):
    c, sid, a = study["client"], study["study"], study["a"]

    class Remote(MockBackend):
        remote = True

    study["ctx"].studio._client = ModelClient(backend=Remote(['{"claims": []}']))
    text = f"In {a} animals membrane-associated ring finger 1 went way up."
    job = wait_job(c, c.post(f"/api/studies/{sid}/claims/read", json={"text": text}).json()["job"])
    assert job["status"] == "done"
    assert study["ctx"].studio.client.backend.calls == []
    assert "remote" in job["result"]["report"]["model_note"]
