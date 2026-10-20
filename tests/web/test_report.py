"""The study report: every number a fact, MIQE 2.0 on the demo, the reviewer's report, the exports.

The demo tests run on the real demo study (Vermeulen 2013, 64 plates) with a real robustness
audit (the Decision Simulator, 99 permutations); every number the report cites is checked against
the store, the audit or the input file, independently of the report's code. The quick tests use
the Studio tests' walked mini file: the route, groups from a confirmed design, the blind rule and
text from the study that tries to be markup.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.core.validator import names_from_result, validate
from qpilot.report import html as report_html
from qpilot.report import markdown as report_md
from qpilot.report.context import METHOD_NAMES
from qpilot.report.model import ReportView
from qpilot.report.text import ProseError, Q, ReportFacts
from qpilot.schemas import Fact
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job
from tests.web.test_studio_flow import no_html

HOSTILE = '<script>alert(1)</script><img src=x onerror="alert(2)">'


def texts(view: dict) -> list[dict]:
    """Every fact-bound text of a report (as JSON)."""
    out = [view["summary"], view["miqe"]["headline"], view["review"]["lead"]]
    out += [p["text"] for p in view["methods"]["paragraphs"]]
    out += [i["evidence"] for i in view["miqe"]["items"] if i["evidence"]]
    out += [f["text"] for f in view["review"]["findings"]]
    out += [c["text"] for c in view["review"]["passed"]]
    out += [x["text"] for x in view["limitations"]]
    return out


def export(client: TestClient, study: str, fmt: str, **body: Any) -> dict:
    r = client.post(f"/api/studies/{study}/report/export", json={"format": fmt, **body})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    assert job["result_type"] == "ReportExported"
    return job["result"]


# ---- the fact-bound text itself ------------------------------------------------------------------


def test_a_sentence_with_a_naked_number_raises():
    facts = ReportFacts({"f_n": Fact(id="f_n", value=3, fmt="{}", unit="", path="study")})
    assert facts.text("{{f_n}} genes").plain == "3 genes"
    with pytest.raises(ProseError):
        facts.text("{{f_n}} of 58 genes")
    with pytest.raises(ProseError):
        facts.text("{{f_unknown}} genes")
    quoted = facts.text("the reason: ", Q("58 is not a fact, it is the person's text"))
    assert quoted.segments[-1].quote and quoted.facts == []


def test_a_derived_fact_cannot_change_its_value():
    facts = ReportFacts({})
    fid = facts.derive("n_x", 4, "results.json:/x@len")
    assert facts.derive("n_x", 4, "results.json:/x@len") == fid
    with pytest.raises(ValueError):
        facts.derive("n_x", 5, "results.json:/x@len")


# ---- the walked mini study (groups from a confirmed design) -----------------------------------


def test_the_report_of_a_walked_study(walked):
    c, study = walked["client"], walked["study"]
    r = c.get(f"/api/studies/{study}/report")
    assert r.status_code == 200, r.text
    view = r.json()
    no_html(view)
    assert view["header"]["study_id"] == study and view["header"]["session"] == walked["sid"]
    assert view["audit"]["status"] == "none"
    assert "no_audit" in {f["id"] for f in view["review"]["findings"]}
    groups = next(p for p in view["methods"]["paragraphs"] if p["id"] == "comparison")
    assert "confirmed design" in groups["text"]["plain"]
    assert sum(view["miqe"]["counts"].values()) == view["miqe"]["n_items"] == 53
    for copy in (view["methods"]["plain"], view["methods"]["with_citations"]):
        assert not re.search(r"\s[,.;:]|\.\.", copy), "no space before punctuation"
    for text in texts(view):
        for seg in text["segments"]:
            assert seg["fact"] is None or seg["fact"] in view["facts"], seg


def test_unknown_studies_and_bad_formats(walked):
    c, study = walked["client"], walked["study"]
    assert c.get("/api/studies/0123456789ab/report").json()["error"]["code"] == "not_found"
    assert c.get("/api/studies/not-an-id/report").status_code == 404
    r = c.post(f"/api/studies/{study}/report/export", json={"format": "pdf"})
    assert r.status_code == 422


def test_a_blind_session_gets_no_report(walked):
    from qpilot.mcp_server import QpilotTools

    c, store, sid, study = walked["client"], walked["store"], walked["sid"], walked["study"]
    done = export(c, study, "md")
    assert c.get(done["download"]["url"]).status_code == 200
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
    for response in (
        c.get(f"/api/studies/{study}/report"),
        c.post(f"/api/studies/{study}/report/export", json={"format": "passport"}),
        c.get(f"/api/studies/{study}/report/exports"),
        c.get(done["download"]["url"]),
    ):
        assert response.status_code == 403, response.text[:200]
        assert response.json()["error"]["code"] == "blind"


def test_text_from_the_study_is_never_markup(walked):
    """A person's reason (typed on the page) and every string from the file arrive escaped."""
    c, store, study = walked["client"], walked["store"], walked["study"]
    card = next(x for x in store.cards(study) if x.options)
    head = c.get(f"/api/studies/{study}/cards").json()["head"]
    r = c.post(
        f"/api/studies/{study}/cards/{card.id}/decide",
        json={"option": card.options[-1].id, "reason": HOSTILE, "expected_head": head},
    )
    assert r.status_code == 200, r.text
    view = c.get(f"/api/studies/{study}/report").json()
    assert any(d["reason"] == HOSTILE for d in view["decisions"])  # kept as data
    quoted = [s for t in texts(view) for s in t["segments"] if s["quote"] and HOSTILE in s["text"]]
    assert quoted, "the reason is quoted data in the Methods"
    for fmt, raw in (("passport", True), ("html", True), ("md", False)):
        done = export(c, study, fmt)
        body = c.get(done["download"]["url"]).content.decode("utf-8")
        assert "<script" not in body and "<img" not in body, fmt
        assert "&lt;script&gt;" in body, fmt
        if raw:
            assert "onerror=" not in body.replace("onerror=&quot;", ""), fmt

    # every other channel (gene, file, option and group names), straight through the renderers
    model = ReportView.model_validate(view)
    genes = [g.model_copy(update={"gene": HOSTILE, "verdict_label": HOSTILE}) for g in model.genes]
    header = model.header.model_copy(update={"source_name": HOSTILE, "title": HOSTILE})
    decisions = [
        d.model_copy(update={"option_label": HOSTILE, "card_title": HOSTILE})
        for d in model.decisions
    ]
    hostile = model.model_copy(update={"genes": genes, "header": header, "decisions": decisions})
    for page in (
        report_html.document(hostile, passport=True),
        report_html.document(hostile),
        report_md.document(hostile),
    ):
        assert "<script" not in page and "<img" not in page


# ---- the demo study with a real audit ---------------------------------------------------------


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """The demo study analysed and audited into a store: ``(client, store, study, audit dir)``."""
    from qpilot.integration import simulator
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    if not simulator.available():
        pytest.skip("the Decision Simulator (qsim) is not installed")
    root = tmp_path_factory.mktemp("report-demo")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_STUDIES_DIR", str(root / "studies"))
        store = StudyStore(root / "studies")
        study = store.ensure_study(DEMO_RDML)
        audit_dir = store.root / "simulator_audits" / study
        simulator.audit(store, study, audit_dir, permutations=99)
        ctx = make_context(store, token=TOKEN, watch=False)
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})
            yield client, store, study, audit_dir
        ctx.close()


def unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def walk(data: Any, pointer: str) -> Any:
    for token in pointer.split("/")[1:] if pointer else []:
        key = unescape(token)
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


def matches(row: dict, conditions: str) -> bool:
    """``key:value`` (``a|b`` alternatives), or a bare flag, joined by commas."""
    for cond in conditions.split(","):
        key, _, want = cond.partition(":")
        if key == "made_by":
            value = ((row.get("proposal") or {}).get("made_by") or {}).get("kind")
        elif key == "flips":
            value = bool((row.get("impact") or {}).get("flips"))
        elif key == "quantity":
            value = bool(row.get("quantity"))
        else:
            value = row.get(key)
        if want and str(value) not in want.split("|"):
            return False
        if not want and not value:
            return False
    return True


def resolve(path: str, store: StudyStore, study: str, audit_dir: Path, view: dict) -> Any:
    """The value a derived fact's path names, read here without the report's code."""
    from qpilot.core.record import versions
    from qpilot.qpcr.confidence_checks import HOLDS_MIN
    from qpilot.report.rdml_meta import read_meta

    ws = store.workspace(study)
    source, _, rest = path.partition(":")
    if source.startswith("qpilot."):
        return getattr(importlib.import_module(source), rest.strip("/"))
    if source == "audit":
        name, _, rest = rest.partition(":")
        data: Any = json.loads((audit_dir / name).read_text())
    elif source == "versions":
        data = versions()
    elif source == "report":
        data = view
    elif source in ("decisions.jsonl", "pending.jsonl", "proposals.jsonl"):
        file = (
            store.root / "sessions" / store.get(study).input_sha256 / source
            if source == "proposals.jsonl"
            else ws / source
        )
        data = [json.loads(x) for x in file.read_text().splitlines() if x.strip()]
    elif source == "grid.csv":
        import pandas as pd

        column, _, agg = rest.strip("/").partition("@")
        assert agg == "len"
        return int(pd.read_csv(ws / "grid.csv", usecols=[column])[column].nunique())
    elif source == "input.rdml":
        meta = read_meta(store.source(study))
        if rest.startswith("/sample/type@count="):
            return meta.sample_types.get(rest.split("=", 1)[1], 0)
        return {
            "/rdml/version": meta.version,
            "/target@len": meta.n_targets,
            "/react/data/adp@count": meta.n_reactions_with_curves,
            "/react/vol@distinct": ", ".join(f"{v:g}" for v in meta.volumes),
            "/target/sequences@count": meta.n_targets_with_primers,
        }[rest]
    else:
        data = json.loads((ws / source).read_text())
    pointer, _, agg = rest.partition("@")
    data = walk(data, pointer)
    if agg == "":
        return data
    if agg == "len":
        return len(data)
    if agg == "head":
        return store.chain_head(study)
    values = list(data.values()) if isinstance(data, dict) else data
    if agg == "min":
        return min(values)
    if agg == "max":
        return max(values)
    if agg.startswith("below="):
        return sum(1 for v in values if v < float(agg[len("below=") :]))
    if agg == "count=called,holds_below_min,not_headline":
        headline = {g["gene"] for g in view["genes"] if g["headline"]}
        results = json.loads((ws / "results.json").read_text())
        return sum(
            1
            for g, r in results["robustness"].items()
            if g not in headline
            and results["contrasts"][g]["conclusion"] != "none"
            and r["holds"] < HOLDS_MIN
        )
    if agg.startswith("count="):
        return sum(1 for v in values if isinstance(v, dict) and matches(v, agg[len("count=") :]))
    raise AssertionError(f"unknown aggregate in {path}")


@pytest.mark.demo_data
def test_every_number_in_the_report_is_the_stores(demo):
    client, store, study, audit_dir = demo
    view = client.get(f"/api/studies/{study}/report").json()
    no_html(view)
    result = store.get(study)
    engine = result.facts
    assert view["facts"], "the report cites facts"
    for fid, fact in view["facts"].items():
        if fact["derived"]:
            assert fid.startswith("f_rpt_"), fid
            expected = resolve(fact["path"], store, study, audit_dir, view)
            assert fact["value"] == expected, (fid, fact["path"], fact["value"], expected)
        else:
            assert fid in engine, fid
            assert fact["value"] == engine[fid].value and fact["path"] == engine[fid].path, fid
    # every number outside a fact is a method name or the stated rule; strings from the study
    # are quoted data
    names = names_from_result(result) | METHOD_NAMES
    for text in texts(view):
        tokens = "".join(
            "{{" + s["fact"] + "}}"
            if s["fact"]
            else (" " if s["quote"] or s["cite"] else s["text"])
            for s in text["segments"]
        )
        check = validate(
            tokens, {k: engine.get(k) or _fact(v) for k, v in view["facts"].items()}, names
        )
        assert check.ok, (text["plain"], check.error())
    # the Methods carry the study's own key numbers
    methods = view["methods"]["plain"]
    for fid in ("f_n_reactions", "f_n_samples", "f_n_cells", "f_n_genes", "f_eff_median"):
        assert fid in {f for p in view["methods"]["paragraphs"] for f in p["text"]["facts"]}, fid
    assert "Welch's t-test" in methods and "geNorm" in methods and "TD0" in methods
    audit = next(p for p in view["methods"]["paragraphs"] if p["id"] == "audit")
    manifest = json.loads((audit_dir / "audit_manifest.json").read_text())
    assert f"{manifest['analyses']:,}" in audit["text"]["plain"]
    refs = [c["id"] for c in view["methods"]["citations"]]
    assert refs[0] == "rdml" and "miqe2" in refs and "vermeulen2009" in refs
    assert (
        "[" in view["methods"]["with_citations"]
        and "References" in view["methods"]["with_citations"]
    )


def _fact(view_fact: dict) -> Fact:
    return Fact(id=view_fact["id"], value=view_fact["value"], fmt="{}", unit="", path="")


@pytest.mark.demo_data
def test_miqe_on_the_demo(demo):
    client, _, study, _ = demo
    miqe = client.get(f"/api/studies/{study}/report").json()["miqe"]
    status = {i["id"]: i["status"] for i in miqe["items"]}
    assert len(status) == miqe["n_items"] == 53
    assert sum(miqe["counts"].values()) == 53
    assert miqe["counts"]["met"] == sum(s == "met" for s in status.values())
    for met in ("2.1", "5.1", "5.2", "5.3", "5.4", "5.5", "5.8", "5.9", "5.10", "5.15", "5.16"):
        assert status[met] == "met", met
    assert status["3.5"] == "not_met"  # no no-RT controls in the demo
    assert status["5.13"] == "not_met"  # limits of detection not determined
    assert status["4.6"] == "cannot_tell"  # the demo file names no instrument
    attest = [i for i in miqe["items"] if i["attest"]]
    assert attest and all(i["status"] == "cannot_tell" for i in attest)
    assert (
        miqe["pack"]["sha256"]
        == hashlib.sha256(
            Path(report_html.__file__).with_name("miqe2_items.yaml").read_bytes()
        ).hexdigest()
    )


@pytest.mark.demo_data
def test_the_reviewer_flags_the_demos_weak_points(demo):
    client, _, study, _ = demo
    view = client.get(f"/api/studies/{study}/report").json()
    findings = {f["id"]: f for f in view["review"]["findings"]}
    assert findings["weak_normalisation"]["severity"] == "major"  # no gene below geNorm M 1.5
    assert findings["open_choices"]["severity"] == "major"  # a fresh analysis decides nothing
    assert findings["headline_nm23a"]["genes"] == ["NM23A"]  # holds in fewer than 80 %
    assert "groups_from_data" in findings and "no_nrt" in findings
    order = [f["severity"] for f in view["review"]["findings"]]
    assert order == sorted(order, key=["major", "minor", "note"].index)
    assert view["review"]["counts"] == {s: order.count(s) for s in ("major", "minor", "note")}
    assert {lim["id"] for lim in view["limitations"]} >= {"research_use", "multiplicity", "lod"}


@pytest.mark.demo_data
def test_exports_download_and_the_passport_is_offline_and_bound(demo):
    client, store, study, _ = demo
    head = store.chain_head(study)
    md = export(client, study, "md", expected_head=head)
    page = export(client, study, "html")
    passport = export(client, study, "passport")
    for done in (md, page, passport):
        r = client.get(done["download"]["url"])
        assert r.status_code == 200
        assert r.headers["content-disposition"].startswith("attachment")
        assert done["chain_head"] == head and not done["head_moved"]

    text = client.get(passport["download"]["url"]).content.decode("utf-8")
    assert "<script" not in text.lower()
    assert not re.search(r"\b(?:src|href|action|xlink:href)\s*=", text, re.I)
    assert not re.search(
        r"https?://|//[a-z0-9.-]+\.[a-z]{2,}/", text.replace("http-equiv", ""), re.I
    )
    assert "url(" not in text and "@import" not in text
    assert "default-src 'none'" in text
    record = passport["record"]
    assert record["record_id"] in text and record["verify"] in text
    assert "<svg" in text and "Robustness map" in text

    # the record written with the passport verifies, and its id is what the passport says
    from qpilot.core.record import CHECKSUMS, verify

    data = client.get(record["download"]["url"]).content
    folder = Path(store.root).parent / "unzipped"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(folder)
    record_dir = next(p.parent for p in folder.rglob(CHECKSUMS))
    assert verify(record_dir).ok
    assert hashlib.sha256((record_dir / CHECKSUMS).read_bytes()).hexdigest() == record["record_id"]

    listed = client.get(f"/api/studies/{study}/report/exports").json()["exports"]
    assert [e["format"] for e in listed[:3]] == ["passport", "html", "md"]
    assert listed[0]["record"]["record_id"] == record["record_id"]


@pytest.mark.demo_data
def test_a_decision_after_the_page_loaded_is_said(demo):
    client, _, study, _ = demo
    done = export(client, study, "md", expected_head="0" * 64)
    assert done["head_moved"] and any("decided" in w for w in done["warnings"])
