"""The Run Gate route over studies walked through Studio (the synthetic mini file, 2 vs 2).

The first gate runs in a job (409 ``loading`` with the job), then the route answers what
``run_gate`` says on the same model, in words whose numbers are cited facts; a person's
decision is measured again at the analysis it moves to; the route is blind like every result
until the session's design and curves are confirmed again; and reading it writes nothing.

A second walk of the mini file has a no-template control that amplifies early on ``1-Mar``, so
the route's card path is checked without the demo: leaving the tainted wells out leaves no
knock-out sample for the gene (its call can no longer be made, a flip), and only a person
decides. The demo-based checks are marked ``demo_data``.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from qpilot.core import gate as core_gate
from qpilot.core.store import StudyStore
from qpilot.mcp_server import QpilotTools
from qpilot.qpcr.gate_rules import OPTION_LABELS, resolve_pack
from qpilot.web.context import make_context
from qpilot.web.routers import gate as gate_router
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job, walk_mini
from tests.web.test_parity_studio import decision_files
from tests.web.test_studio_flow import no_html

TOKEN_RE = re.compile(r"\{\{([a-z0-9_]+)\}\}")
BANNED = re.compile(r"\b(valid|validated|invalid|compliant|diagnostic|QC passed)\b", re.I)


@pytest.fixture(autouse=True)
def fresh_gate_cache():
    gate_router.clear()
    yield
    gate_router.clear()


def ready(c: TestClient, study: str):
    """GET the gate, following the ``gate.run`` job the first answer may name."""
    url = f"/api/studies/{study}/gate"
    r = c.get(url)
    if r.status_code == 409 and r.json()["error"]["code"] == "loading":
        job = wait_job(c, r.json()["error"]["details"]["job"])
        assert job["status"] == "done", job
        assert job["result_type"] == "GateLoaded" and job["result"]["study_id"] == study
        r = c.get(url)
    return r


def check_texts(body: dict) -> None:
    """Every sentence is text whose numbers are cited facts; no clinical or QC words."""
    no_html(body)
    texts = [body["headline"]]
    texts += [e["reason"] for e in body["evaluations"]]
    texts += [o["text"] for c in body["consequences"] for o in c["options"]]
    texts += [t for card in body["cards"] for t in (card["impact"], card["explanation"])]
    for text in texts:
        assert "".join(s["text"] for s in text["segments"]) == text["plain"]
        assert "{{" not in text["plain"], text["plain"]
        cited = {s["fact"] for s in text["segments"] if s["fact"]}
        assert cited == {f["id"] for f in text["facts"]}
        assert all(f["id"].startswith("f_gate_") for f in text["facts"])
    words = [body["headline"]["plain"], body["how_to_apply"], body["pack"]["label"]]
    words += [c["triage_text"] for c in body["consequences"]]
    words += [card["status_line"] for card in body["cards"]]
    for line in words:
        assert not BANNED.search(line), line


def same_as_report(body: dict, report: core_gate.GateReport) -> None:
    """The view says exactly what the engine's report says."""
    assert body["counts"] == report.counts and body["triage"] == report.triage
    assert {p["plate"]: p["status"] for p in body["plates"]} == report.units
    assert body["pack"]["hash"] == report.pack["hash"] == resolve_pack().hash
    assert [e["id"] for e in body["evaluations"]] == [core_gate.eval_id(e) for e in report.evals]
    for row, ev in zip(body["evaluations"], report.evals, strict=True):
        assert (row["rule_id"], row["verdict"], row["outcome"], row["code"]) == (
            ev.rule_id,
            ev.verdict,
            ev.outcome,
            ev.code,
        )
        assert row["flagged"] == ev.flagged
        assert row["plate"] == ev.scope.get("plate") and row["target"] == ev.scope.get("target")
        tokens = TOKEN_RE.findall(ev.reason)
        cited = [s["fact"] for s in row["reason"]["segments"] if s["fact"]]
        assert cited == tokens
        for ref in row["reason"]["facts"]:
            assert ref["value"] == report.facts[ref["id"]].value
    assert len(body["consequences"]) == len(report.consequences)
    for view, c in zip(body["consequences"], report.consequences, strict=True):
        assert (view["consequence"], view["triage"], view["card_id"]) == (
            c.consequence,
            c.triage,
            c.card_id,
        )
        for o_view, o in zip(view["options"], c.options, strict=True):
            assert o_view["id"] == o.option and o_view["excluded"] == o.excluded
            assert o_view["label"] == OPTION_LABELS[o.option]
            assert (o_view["n_flipped"], o_view["flipped"]) == (o.n_flipped, o.flipped)
            assert o_view["flipped_elsewhere"] == core_gate.elsewhere(o)
            assert o_view["max_delta_log2fc"] == pytest.approx(o.max_delta_log2fc)
    assert [c["card"]["id"] for c in body["cards"]] == [c.id for c in report.cards]
    for view, card in zip(body["cards"], report.cards, strict=True):
        assert view["card"]["kind"] == "gate.rule" and view["needs_human"]
        assert view["card"]["status"] == card.status
        assert [o["id"] for o in view["options"]] == [o.id for o in card.options]
        for o_view, o in zip(view["options"], card.options, strict=True):
            assert {e["gene"]: e["conclusion"] for e in o_view["effects"]} == {
                g: r.conclusion for g, r in o.per_gene.items()
            }


# ---- the mini study ------------------------------------------------------------------------


def test_a_cold_gate_answers_loading_with_the_job(walked, monkeypatch):
    c, study = walked["client"], walked["study"]
    monkeypatch.setattr(gate_router, "WAIT_S", 0.0)
    r = c.get(f"/api/studies/{study}/gate")
    assert r.status_code == 409, r.text
    error = r.json()["error"]
    assert error["code"] == "loading" and error["details"]["job"]["kind"] == "gate.run"
    assert "controls" in error["message"]
    job = wait_job(c, error["details"]["job"])
    assert job["status"] == "done" and job["result_type"] == "GateLoaded"
    assert job["result"]["n_evaluations"] >= 1
    assert c.get(f"/api/studies/{study}/gate").status_code == 200


def test_the_view_is_run_gate_on_the_same_model(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    r = ready(c, study)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["study_id"] == study and body["session"] == walked["sid"]
    assert body["head"] == store.chain_head(study)
    assert body["analysis"] == "planned" and body["exclude_in"] == "curves"
    assert "Curves" in body["how_to_apply"]
    same_as_report(body, gate_router.compute(store, study, None))
    check_texts(body)
    # the mini file: two typed plates; the late NTC on 1-Mar warns and points at nothing
    assert body["n_gated"] == 2 and body["n_ungated"] == 0
    ntc = [e for e in body["evaluations"] if e["rule_id"] == "G-NTC-1"]
    warn = next(e for e in ntc if e["target"] == "1-Mar")
    assert warn["verdict"] == "warn" and warn["flagged"] == [] and warn["consequence"] is None
    assert warn["title"] == resolve_pack().rule("G-NTC-1").name
    assert body["consequences"] == [] and body["cards"] == []
    assert body["headline"]["plain"].startswith("All 2 plates are gated. 1 rule check warns.")
    na = {
        (e["rule_id"], e["code"]) for e in body["evaluations"] if e["verdict"] == "not_applicable"
    }
    assert ("G-NAC", "no_nac_typed") in na and all(code for _, code in na)
    rules = {r["rule_id"]: r for r in body["pack"]["rules"]}
    assert rules["G-STD"]["informational"] and not rules["G-NTC-1"]["informational"]
    assert rules["G-NTC-1"]["sources"][0]["url"].startswith("https://")
    assert "research use" in body["pack"]["label"].lower()
    # the answer is kept: the same body until something changes
    assert c.get(f"/api/studies/{study}/gate").json() == body


def test_a_persons_decision_is_measured_again_at_the_analysis_it_moves_to(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    before = ready(c, study).json()
    assert before["analysis"] == "planned"
    cards = c.get(f"/api/studies/{study}/cards").json()
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/decide",
        json={
            "option": "cap",
            "reason": "our lab caps empty wells",
            "expected_head": cards["head"],
        },
    )
    assert r.status_code == 200, r.text
    after = ready(c, study)
    assert after.status_code == 200, after.text
    body = after.json()
    assert body["head"] == store.chain_head(study) != before["head"]
    assert body["analysis"] == "your_choices"
    choice = gate_router._choice(walked["ctx"], study)
    assert choice is not None and choice["undetermined"] == "cap"
    same_as_report(body, gate_router.compute(store, study, choice))


def test_the_gate_is_blind_until_the_session_is_confirmed_again(walked):
    c, study, sid, store, studio = (
        walked["client"], walked["study"], walked["sid"], walked["store"], walked["studio"]
    )  # fmt: skip
    assert ready(c, study).status_code == 200
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says KO")
    assert not studio.results_visible(sid)
    r = c.get(f"/api/studies/{study}/gate")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind", r.text
    assert "verdict" not in r.text and "flagged" not in r.text


def test_reading_the_gate_writes_nothing(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    before = decision_files(store)
    head = store.chain_head(study)
    assert ready(c, study).status_code == 200
    assert decision_files(store) == before and store.chain_head(study) == head
    assert store.cards(study) == store.cards(study)  # no gate card is stored
    assert not any(card.kind.startswith("gate.") for card in store.cards(study))


def test_the_imports_rawness_verdict_reaches_the_gate(walked, monkeypatch):
    """A study opened from an instrument export is gated with the import's raw-ness verdict."""
    from qpilot.io.connectors.base import CaptureMeta, ConnectorInfo, Layers
    from qpilot.qpcr import gate_rules
    from qpilot.web import intake

    store, sid, study = walked["store"], walked["sid"], walked["study"]
    assert gate_router.import_rawness(store, study) is None  # opened from an RDML file
    meta = CaptureMeta(
        connector=ConnectorInfo(id="cfx", version="1", label="Bio-Rad CFX export"),
        dialect="cfx.amplification",
        sources=[],
        experiment_id="qpilot_import",
        layers=Layers(),
        rawness={"study_verdict": "baseline_subtracted"},
    )
    intake.save(store, sid, meta, [])
    assert gate_router.import_rawness(store, study) == "baseline_subtracted"
    seen: dict = {}
    real = gate_rules.run_gate

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(gate_rules, "run_gate", spy)
    gate_router.compute(store, study, None)
    assert seen["rawness"] == "baseline_subtracted"


def test_names_that_are_not_studies_and_a_missing_file(walked, monkeypatch):
    c, study, store = walked["client"], walked["study"], walked["store"]
    assert c.get("/api/studies/0123456789ab/gate").status_code == 404
    assert c.get("/api/studies/not-a-key/gate").status_code == 404
    monkeypatch.setattr(store, "source", lambda study_id: None)
    r = c.get(f"/api/studies/{study}/gate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_source"
    assert "Open the file again" in r.json()["error"]["message"]


# ---- a control that taints the knock-outs --------------------------------------------------


@pytest.fixture(scope="module")
def tainted_walked(tmp_path_factory):
    """The mini file with an early no-template control on 1-Mar, walked and analysed once."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio
    from tests.fixtures.studio import studio_mini

    base = tmp_path_factory.mktemp("tainted")
    root = base / "data"
    root.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_DATA_ROOTS", str(root))
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        # amplifies at 30.5: the knock-outs (27-27.4) and one late replicate are within 5 cycles
        mp.setitem(studio_mini.PLATES["1-Mar"], "NTC", [None, None, 30.5])
        qinspect.clear_cache()
        rdml = studio_mini.write_studio_mini(root / "mini.rdml")
        studio = Studio(StudyStore(base / "studies"), client=ModelClient(backend=NoneBackend()))
        sid, study_id = walk_mini(studio, rdml)
        design_checks._DECLARED.clear()
        design_checks.set_input_resolver(None)
        qinspect.clear_cache()
    return {"base": base, "root": root, "sid": sid, "study": study_id}


@pytest.fixture
def tainted(tainted_walked, tmp_path, monkeypatch):
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio

    shutil.copytree(tainted_walked["base"], tmp_path / "w", symlinks=False)
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(tainted_walked["root"]))
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(tmp_path / "w" / "studies"))
    qinspect.clear_cache()
    store = StudyStore(tmp_path / "w" / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(store, studio, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield {"client": c, "store": store, "ctx": ctx, **tainted_walked}
    ctx.close()
    design_checks._DECLARED.clear()
    design_checks.set_input_resolver(None)
    qinspect.clear_cache()


def test_a_control_that_can_change_a_call_is_a_card_only_a_person_decides(tainted):
    c, study, store = tainted["client"], tainted["study"], tainted["store"]
    r = ready(c, study)
    assert r.status_code == 200, r.text
    body = r.json()
    same_as_report(body, gate_router.compute(store, study, None))
    check_texts(body)
    ntc = next(
        e for e in body["evaluations"] if e["rule_id"] == "G-NTC-1" and e["target"] == "1-Mar"
    )
    assert ntc["verdict"] == "fail" and ntc["flagged"] and ntc["consequence"] == ntc["id"]
    assert all(w.startswith("1-Mar_plate/") for w in ntc["flagged"])
    (conseq,) = (x for x in body["consequences"] if x["id"] == ntc["id"])
    assert (conseq["consequence"], conseq["triage"]) == ("flip", "human")
    assert "only a person decides" in conseq["triage_text"]
    (option,) = conseq["options"]
    assert option["id"] == "exclude_flagged" and option["excluded"] == ntc["flagged"]
    assert option["flipped"] == ["1-Mar"] and option["n_flipped"] == 1
    assert option["text"]["plain"].startswith(f"Leaving these {len(ntc['flagged'])} wells out")
    assert "changes 1 call at the analysis in use: 1-Mar." in option["text"]["plain"]
    (card,) = body["cards"]
    assert card["card"]["id"] == conseq["card_id"] and card["card"]["status"] == "open"
    assert card["needs_human"] and card["card"]["recommended"] == "keep"
    assert [o["id"] for o in card["options"]] == ["keep", "exclude_flagged"]
    keep, leave_out = card["options"]
    assert keep["recommended"] and [e["gene"] for e in keep["effects"]] == ["1-Mar"]
    assert leave_out["effects"] == []  # 1-Mar can no longer be compared without them
    assert card["genes"] == ["1-Mar"] and card["pending"] == []
    assert card["status_line"].startswith("Waiting for a person")
    assert "only you decide" in body["headline"]["plain"]
    # nothing is applied: the study's own cards and chain are as they were
    assert not any(k.kind.startswith("gate.") for k in store.cards(study))


# ---- the demo ------------------------------------------------------------------------------


@pytest.mark.demo_data
def test_the_demo_gate_route(tmp_path):
    from qpilot.io.datasets import default_cache_dir
    from qpilot.qpcr.gate_rules import gate_file

    rdml = default_cache_dir() / "data_vermeulen_raw.rdml"
    if not rdml.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    store = StudyStore(tmp_path / "studies")
    study = store.ensure_study(rdml)
    ctx = make_context(store, token=TOKEN, watch=False)
    try:
        with TestClient(create_app(ctx), base_url=BASE) as c:
            c.headers["x-qpilot-token"] = TOKEN
            r = ready(c, study)
            assert r.status_code == 200, r.text
            body = r.json()
    finally:
        ctx.close()
    assert body["session"] is None and body["exclude_in"] == "none"
    assert "Trace" in body["how_to_apply"]
    check_texts(body)
    same_as_report(body, gate_router.compute(store, study, None))
    expected = gate_file(rdml)
    # the seven rules of research-default 1.0.0 as before; G-RT (no RT replicates marked) and
    # G-INSTR (the RDML says nothing about the runs) add 1 + 64 "not applicable"
    assert (
        body["counts"]
        == expected.counts
        == {
            "pass": 491,
            "warn": 8,
            "fail": 14,
            "not_applicable": 192 + 1 + 64,
        }
    )
    new = [e for e in body["evaluations"] if e["rule_id"] in ("G-RT", "G-INSTR")]
    assert {(e["rule_id"], e["verdict"]) for e in new} == {
        ("G-RT", "not_applicable"),
        ("G-INSTR", "not_applicable"),
    }
    assert len(body["runs"]) == 64 and {r["source"] for r in body["runs"]} == {"study_file"}
    assert body["n_gated"] == 64 and len(body["consequences"]) == 10
    assert all(o["n_flipped"] == 0 for x in body["consequences"] for o in x["options"])
    assert [card["card"]["status"] for card in body["cards"]] == ["auto_decided"] * 3
    assert all(card["needs_human"] for card in body["cards"])
    assert body["headline"]["plain"] == (
        "All 64 plates are gated. 14 rule checks fail and 8 warn. Leaving out the wells they "
        "point at changes no call at the analysis in use; 3 of them can change one at other "
        "settings, so an agent would have to ask you."
    )
