"""The robustness audit's API on a real audit: status, every view, what-if, verify, blind.

The audit is real: a copy of a store with an audited Studio study when
``QPILOT_TEST_AUDIT_STORE`` names one (the UI team's seeded store: a scripted person confirmed
the demo's design and curves through the real service, then the audit ran), otherwise the demo
study audited here once per module (demo data, about a minute).
"""

from __future__ import annotations

import json
import math
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.integration import simulator as sim
from qpilot.web.context import make_context
from qpilot.web.routers import audit as audit_router
from qpilot.web.server import create_app

pytestmark = [
    pytest.mark.demo_data,  # the audited study's input file is the demo's
    pytest.mark.skipif(not sim.available(), reason="the Decision Simulator is not installed"),
]

TOKEN = "test-token"
BASE = "http://127.0.0.1:7860"
WRITE = {"origin": BASE}
GENE_VIEWS = ("gene", "analyses", "effects", "lab")


def _seed(root: Path) -> str:
    """Fill ``root`` with a store holding one audited study; return the study id."""
    seeded = os.environ.get("QPILOT_TEST_AUDIT_STORE")
    if seeded and any(Path(seeded, "simulator_audits").glob("*/audit_manifest.json")):
        shutil.copytree(seeded, root)
        manifests = sorted(root.glob("simulator_audits/*/audit_manifest.json"))
        return manifests[0].parent.name
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    store = StudyStore(root)
    study_id = store.ensure_study(DEMO_RDML)
    sim.audit(store, study_id, root / "simulator_audits" / study_id)
    return study_id


@pytest.fixture(scope="module")
def seeded(tmp_path_factory) -> tuple[Path, str]:
    root = tmp_path_factory.mktemp("audit") / "studies"
    return root, _seed(root)


def _client(store: StudyStore, **ctx_args):
    ctx = make_context(store, token=TOKEN, watch=False, **ctx_args)
    client = TestClient(create_app(ctx), base_url=BASE)
    client.headers["x-qpilot-token"] = TOKEN
    return ctx, client


def _close(ctx) -> None:
    """Let the server's background jobs (pre-check, loading the views) finish, then close it."""
    import time

    deadline = time.monotonic() + 900
    while ctx.jobs.active() and time.monotonic() < deadline:
        time.sleep(0.1)
    ctx.close()


@pytest.fixture(scope="module")
def served(seeded):
    """One server over the seeded store for the whole module (its audit screen is built once)."""
    root, study_id = seeded
    ctx, client = _client(StudyStore(root))
    with client:
        _loaded(client, f"/api/studies/{study_id}/audit")
        yield {"client": client, "ctx": ctx, "study": study_id, "root": root}
    _close(ctx)


def _loaded(client, url: str) -> dict:
    """Open an audit (its status, or an attached folder) and wait for its live views."""
    body = client.get(url).json()
    if body.get("loading"):
        assert _job(client, body["loading"]["id"])["status"] == "done"
    return body


@pytest.fixture(scope="module")
def screen(served):
    """The server's own cached screen (loaded when the module's server opened the audit)."""
    client, study = served["client"], served["study"]
    assert client.get(f"/api/studies/{study}/audit/overview").status_code == 200
    return audit_router.screens(served["ctx"])._entries[study].screen


def _copy(seeded, tmp_path: Path, audits: bool = True) -> Path:
    root = tmp_path / "studies"
    ignore = None if audits else shutil.ignore_patterns("simulator_audits")
    shutil.copytree(seeded[0], root, ignore=ignore)
    return root


def _plain(data):
    """JSON as the API sends it: tuples as lists, NaN as null, dropped keys gone."""
    return json.loads(json.dumps(audit_router._finite(data), allow_nan=False))


def _genes(screen) -> list[str]:
    return sorted(screen.explain)


# ---- status -----------------------------------------------------------------------------------


def test_a_ready_audit_says_what_it_audited(served):
    client, study, root = served["client"], served["study"], served["root"]
    body = client.get(f"/api/studies/{study}/audit").json()
    manifest = json.loads((root / "simulator_audits" / study / "audit_manifest.json").read_text())
    assert body["status"] == "ready" and body["study_id"] == study
    view = body["manifest"]
    assert view["verdict_counts"] == manifest["verdict_counts"]
    assert sum(view["verdict_counts"].values()) == manifest["scope"]["n_genes_compared"]
    assert view["analyses"] == manifest["analyses"] == manifest["scope"]["analyses_in_full_grid"]
    assert view["reproduces_qpilot"]["ok"] is True
    assert view["lock_sha256"] == manifest["lock_sha256"]
    assert view["chain_head"] == manifest["chain_head"]
    sums = root / "simulator_audits" / study / "AUDIT.sha256"
    assert view["checksums_sha256"] == sim.sha256_file(sums)
    assert view["seconds"] and view["seconds"] > 0
    assert body["current"] is True and body["decisions_since"] == 0
    assert body["typical_s"] > 0


def test_unknown_or_malformed_studies_are_not_found(served):
    client = served["client"]
    for key in ("../etc", "ABCDEF123456", "0" * 12, "abc"):
        r = client.get(f"/api/studies/{key}/audit")
        assert r.status_code == 404, key
        assert r.json()["error"]["code"] == "not_found"


def test_a_study_without_an_audit_says_none_and_its_views_say_run_it(seeded, tmp_path):
    root = _copy(seeded, tmp_path, audits=False)
    ctx, client = _client(StudyStore(root))
    with client:
        body = client.get(f"/api/studies/{seeded[1]}/audit").json()
        assert body["status"] == "none" and body["manifest"] is None
        assert body["checking"]["kind"] == "audit.check"  # what a run would cover, found now
        r = client.get(f"/api/studies/{seeded[1]}/audit/overview")
        assert r.status_code == 404 and r.json()["error"]["code"] == "no_audit"
        r = client.post(f"/api/studies/{seeded[1]}/audit/verify", json={}, headers=WRITE)
        assert r.status_code == 404 and r.json()["error"]["code"] == "no_audit"
    _close(ctx)


def test_a_decision_after_the_audit_makes_it_not_current(seeded, tmp_path, monkeypatch):
    monkeypatch.setattr(audit_router, "_load_job", lambda *a: None)  # no screen needed here
    root = _copy(seeded, tmp_path)
    store = StudyStore(root)
    study = seeded[1]
    card = next(c for c in store.cards(study) if len(c.options) > 1)
    option = next(o.id for o in card.options if o.id != card.recommended)
    store.append_decision(
        study, card.id, option, "a later choice", "human", store.chain_head(study)
    )
    ctx, client = _client(store)
    with client:
        body = client.get(f"/api/studies/{study}/audit").json()
        assert body["status"] == "ready"
        assert body["current"] is False and body["decisions_since"] == 1
        check = client.post(f"/api/studies/{study}/audit/verify", json={}, headers=WRITE).json()
        assert check["ok"] is True, check["problems"]  # the audited head is still in the chain
        assert check["decisions_since"] == 1
        assert check["head_in_chain"] is True and check["is_current"] is False
        assert check["record_chain_head"] == store.chain_head(study)
        assert check["record_chain_head"] != check["audit_chain_head"]
    _close(ctx)


def test_without_the_simulator_the_audit_says_so(served, monkeypatch):
    client, study = served["client"], served["study"]
    monkeypatch.setattr(sim, "available", lambda: False)
    body = client.get(f"/api/studies/{study}/audit").json()
    assert body["status"] == "unavailable" and "pip install" in body["reason"]
    r = client.post(f"/api/studies/{study}/audit", json={}, headers=WRITE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "unavailable"
    r = client.get(f"/api/studies/{study}/audit/overview")
    assert r.status_code == 409 and r.json()["error"]["code"] == "unavailable"


def test_running_it_again_needs_again(served):
    client, study = served["client"], served["study"]
    r = client.post(f"/api/studies/{study}/audit", json={}, headers=WRITE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "audit_exists"
    r = client.post(f"/api/studies/{study}/audit", headers=WRITE)  # no body: same
    assert r.status_code == 409


# ---- the views: the screen's own dicts, typed ------------------------------------------------


def test_every_view_is_the_screens_own_dict(served, screen):
    client, study = served["client"], served["study"]
    url = f"/api/studies/{study}/audit"
    overview = screen.overview()
    overview.pop("model")
    assert client.get(f"{url}/overview").json() == _plain(overview)
    assert client.get(f"{url}/study").json() == _plain(screen.study_view())
    how = {"faults": None, "known": None, **screen.how_view()}  # checks not made: null
    assert client.get(f"{url}/how").json() == _plain(how)
    for gene in _genes(screen)[:6] + ["NM23A"] * ("NM23A" in screen.explain):
        card = screen.gene_card(gene)
        card.pop("evidence")
        assert client.get(f"{url}/gene/{gene}").json() == _plain(card), gene
        assert client.get(f"{url}/analyses/{gene}").json() == _plain(screen.gene_analyses(gene))
        assert client.get(f"{url}/effects/{gene}").json() == _plain(screen.gene_effects(gene))
        assert client.get(f"{url}/lab/{gene}").json() == _plain(screen.lab_parameters(gene))


def test_every_gene_has_every_view(served, screen):
    client, study = served["client"], served["study"]
    for gene in _genes(screen):
        for view in GENE_VIEWS:
            r = client.get(f"/api/studies/{study}/audit/{view}/{gene}")
            assert r.status_code == 200, (view, gene, r.text[:300])


def test_the_live_views_are_the_audited_analysis(served, screen):
    """Built on the audit's own engine: the planned analysis is the one in explain.json."""
    client, study = served["client"], served["study"]
    for gene in _genes(screen):
        e = screen.explain[gene]
        effects = client.get(f"/api/studies/{study}/audit/effects/{gene}").json()
        assert math.isclose(effects["planned_log2"], e["log2fc"], abs_tol=1e-9), gene
        analyses = client.get(f"/api/studies/{study}/audit/analyses/{gene}").json()
        assert analyses["n"] == e["analyses_defensible"]
        assert math.isclose(analyses["n_same"] / analyses["n"], e["holds_defensible"]), gene
        assert analyses["base_call_key"] == e["call"]
        planned = [r for r in analyses["rows"] if r["planned"]]
        assert len(planned) == 1 and math.isclose(planned[0]["log2"], e["log2fc"], abs_tol=1e-9)


def test_call_keys_say_what_the_words_say(served, screen):
    client, study = served["client"], served["study"]
    url = f"/api/studies/{study}/audit"
    gene = "NM23A" if "NM23A" in screen.explain else _genes(screen)[0]
    card = client.get(f"{url}/gene/{gene}").json()
    assert card["call_key"] == screen.explain[gene]["call"]
    for row in card["changes"] + card["singles"]:
        assert row["call"] == screen.call_words(row["call_key"])
    analyses = client.get(f"{url}/analyses/{gene}").json()
    assert analyses["base_call"] == screen.call_words(analyses["base_call_key"])
    for row in analyses["rows"]:
        assert row["call"] == screen.call_words(row["call_key"])
    for decision in client.get(f"{url}/effects/{gene}").json()["decisions"]:
        for option in decision["options"]:
            assert option["call"] == screen.call_words(option["call_key"])
    rows = client.post(f"{url}/whatif", json={"changes": {}}, headers=WRITE).json()["rows"]
    short = {"up": "called up", "down": "called down", "none": "no call"}
    for row in rows:
        assert row["base_call"] == short[row["base_call_key"]]
        assert row["new_call"] == short[row["new_call_key"]]
    for row in client.get(f"{url}/overview").json()["genes"]:
        assert row["call_key"] == row["call"] == screen.explain[row["gene"]]["call"]


def test_a_gene_outside_the_audit_is_not_found(served, screen):
    client, study = served["client"], served["study"]
    for view in GENE_VIEWS:
        r = client.get(f"/api/studies/{study}/audit/{view}/NOT_A_GENE")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    control = screen.engine.study.candidates[0]
    r = client.get(f"/api/studies/{study}/audit/gene/{control}")
    assert r.status_code == 404 and "control gene" in r.json()["error"]["message"]


# ---- what-if and samples (live engine runs) --------------------------------------------------


def _a_flipping_choice(client, study, screen) -> tuple[str, str, str, str]:
    """(gene, decision, option, new call key) where one option alone changes that gene's call."""
    for gene in _genes(screen):
        effects = client.get(f"/api/studies/{study}/audit/effects/{gene}").json()
        for decision in effects["decisions"]:
            for option in decision["options"]:
                if option["changes_call"]:
                    space = screen.space.decision(decision["id"])
                    option_id = next(o.id for o in space.options if o.label == option["label"])
                    return gene, decision["id"], option_id, option["call_key"]
    raise AssertionError("no single choice changes any call in this audit")


def test_whatif_with_no_change_changes_nothing(served):
    client, study = served["client"], served["study"]
    body = client.post(
        f"/api/studies/{study}/audit/whatif", json={"changes": {}}, headers=WRITE
    ).json()
    assert body["n_changed"] == 0 and body["changed_genes"] == [] and body["changes"] == []
    assert all(r["base_call_key"] == r["new_call_key"] and not r["changed"] for r in body["rows"])


def test_whatif_changes_a_call_as_one_choice_at_a_time_says(served, screen):
    client, study = served["client"], served["study"]
    gene, decision, option, new_call = _a_flipping_choice(client, study, screen)
    body = client.post(
        f"/api/studies/{study}/audit/whatif",
        json={"changes": {decision: option}, "genes": [gene]},
        headers=WRITE,
    ).json()
    assert gene in body["changed_genes"] and body["n_changed"] == len(body["changed_genes"]) >= 1
    row = next(r for r in body["rows"] if r["gene"] == gene)
    assert row["changed"] and row["picked"] and row["new_call_key"] == new_call
    assert row["base_call_key"] == screen.explain[gene]["call"]
    assert len(body["changes"]) == 1  # the option, as its label


def test_whatif_refuses_unknown_choices_in_words(served, screen):
    client, study = served["client"], served["study"]
    url = f"/api/studies/{study}/audit/whatif"
    r = client.post(url, json={"changes": {"colour": "blue"}}, headers=WRITE)
    assert r.status_code == 422 and "There is no analysis choice 'colour'" in r.text
    r = client.post(url, json={"changes": {"test": "blue"}}, headers=WRITE)
    assert r.status_code == 422 and "is not an option of 'test'" in r.text
    many = {f"d{i}": "x" for i in range(17)}
    r = client.post(url, json={"changes": many}, headers=WRITE)
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"


def test_samples_follow_the_choices(served, screen):
    client, study = served["client"], served["study"]
    gene, decision, option, _ = _a_flipping_choice(client, study, screen)
    url = f"/api/studies/{study}/audit/samples"
    planned = client.post(url, json={"gene": gene}, headers=WRITE).json()
    groups = planned["groups"]
    assert len(planned["points"]) == groups["high"]["n"] + groups["rest"]["n"]
    assert planned["changes"] == []
    changed = client.post(
        url, json={"gene": gene, "changes": {decision: option}}, headers=WRITE
    ).json()
    assert len(changed["changes"]) == 1
    r = client.post(url, json={"gene": "NOT_A_GENE"}, headers=WRITE)
    assert r.status_code == 404


def test_concurrent_whatifs_answer_as_if_alone(served, screen):
    """The engine is not thread-safe: calls are serialised, answers equal one-at-a-time ones."""
    client, study = served["client"], served["study"]
    url = f"/api/studies/{study}/audit"
    gene, decision, option, _ = _a_flipping_choice(client, study, screen)
    requests = [
        ("whatif", {"changes": {decision: option}}),
        ("whatif", {"changes": {}}),
        ("whatif", {"changes": {"test": "mann_whitney"}}),
        ("samples", {"gene": gene, "changes": {decision: option}}),
    ] * 2
    alone = [client.post(f"{url}/{v}", json=b, headers=WRITE).json() for v, b in requests]
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        together = list(
            pool.map(
                lambda vb: client.post(f"{url}/{vb[0]}", json=vb[1], headers=WRITE).json(),
                requests,
            )
        )
    assert together == alone


def test_one_screen_is_built_once_for_concurrent_requests(tmp_path):
    cache = audit_router.Screens()
    folder = tmp_path / "audit"
    folder.mkdir()
    built: list[int] = []

    def build():
        import time

        built.append(1)
        time.sleep(0.2)
        return object()

    with ThreadPoolExecutor(max_workers=8) as pool:
        screens = list(pool.map(lambda _: cache.call("s", folder, build, lambda s: s), range(8)))
    assert len(built) == 1 and len({id(s) for s in screens}) == 1
    (folder / "explain.json").write_text("{}")  # the audit changed: built again
    cache.call("s", folder, build, lambda s: s)
    assert len(built) == 2


# ---- verify -----------------------------------------------------------------------------------


def test_the_audit_verifies_and_is_bound_to_the_studys_record(served):
    client, study, root = served["client"], served["study"], served["root"]
    body = client.post(f"/api/studies/{study}/audit/verify", json={}, headers=WRITE).json()
    assert body["ok"] is True and body["problems"] == [] and body["summary"] == "audit OK"
    assert body["bound_to_record"] is True and body["decisions_since"] == 0
    assert body["audit_chain_head"] == body["record_chain_head"]
    assert body["head_in_chain"] is True and body["is_current"] is True
    sums = root / "simulator_audits" / study / "AUDIT.sha256"
    assert body["files_checked"] == len(sums.read_text().splitlines())
    assert {f["name"] for f in body["files"]} == {
        line.split("  ", 1)[1] for line in sums.read_text().splitlines()
    } | {"AUDIT.sha256"}
    alone = client.post(
        f"/api/studies/{study}/audit/verify", json={"bind_to_record": False}, headers=WRITE
    ).json()
    assert alone["ok"] is True and alone["bound_to_record"] is False


def test_a_changed_audit_file_fails_verification(seeded, tmp_path):
    root = _copy(seeded, tmp_path)
    genes = root / "simulator_audits" / seeded[1] / "genes.csv"
    genes.write_text(genes.read_text() + "\n")
    ctx, client = _client(StudyStore(root))
    with client:
        body = client.post(f"/api/studies/{seeded[1]}/audit/verify", json={}, headers=WRITE).json()
    _close(ctx)
    assert body["ok"] is False and "changed: genes.csv" in body["problems"]


# ---- blind --------------------------------------------------------------------------------------


def test_a_blind_session_hides_the_audit(seeded, tmp_path, monkeypatch):
    root = _copy(seeded, tmp_path, audits=False)
    store = StudyStore(root)
    study = seeded[1]
    session = root / "sessions" / store.get(study).input_sha256
    session.mkdir(parents=True, exist_ok=True)
    meta_path = session / "studio.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.setdefault("studies", {})[study] = "design hash"
    meta_path.write_text(json.dumps(meta))
    ctx, client = _client(store)
    monkeypatch.setattr(ctx.studio, "results_visible", lambda sid: False)
    url = f"/api/studies/{study}/audit"
    with client:
        answers = [
            client.get(url),
            client.post(url, json={}, headers=WRITE),
            client.get(f"{url}/overview"),
            client.get(f"{url}/gene/ANY"),
            client.post(f"{url}/whatif", json={}, headers=WRITE),
            client.post(f"{url}/samples", json={"gene": "ANY"}, headers=WRITE),
            client.post(f"{url}/verify", json={}, headers=WRITE),
        ]
        for r in answers:
            assert r.status_code == 403, r.request.url
            assert r.json()["error"]["code"] == "blind"
        # once confirmed, the same study answers (here: it has no audit yet)
        monkeypatch.setattr(ctx.studio, "results_visible", lambda sid: True)
        assert client.get(url).json()["status"] == "none"
    _close(ctx)


def test_a_study_made_outside_the_session_is_not_blind(seeded, tmp_path, monkeypatch):
    root = _copy(seeded, tmp_path, audits=False)
    store = StudyStore(root)
    study = seeded[1]
    session = root / "sessions" / store.get(study).input_sha256
    session.mkdir(parents=True, exist_ok=True)
    (session / "studio.json").write_text(json.dumps({"studies": {"0123456789ab": "other"}}))
    ctx, client = _client(store)
    monkeypatch.setattr(ctx.studio, "results_visible", lambda sid: False)
    with client:
        assert client.get(f"/api/studies/{study}/audit").json()["status"] == "none"
    _close(ctx)


# ---- attached folders (qpilot app --audit DIR) -------------------------------------------


def test_an_attached_audit_has_the_same_views(served, seeded, tmp_path):
    root, study = seeded
    folder = root / "simulator_audits" / study
    ctx, client = _client(StudyStore(root), audit_dirs={"mine": folder})
    with client:
        listed = client.get("/api/audits").json()["audits"]
        assert [a["name"] for a in listed] == ["mine"]
        assert listed[0]["qpilot_audit"] and listed[0]["available"]
        assert listed[0]["study_id"] == study and not listed[0]["views_ready"]
        r = client.get("/api/audits/mine/overview")
        assert r.status_code == 409 and r.json()["error"]["code"] == "loading"
        _loaded(client, "/api/audits/mine")
        assert client.get("/api/audits").json()["audits"][0]["views_ready"]
        ours = client.get("/api/audits/mine/overview").json()
        theirs = served["client"].get(f"/api/studies/{study}/audit/overview").json()
        assert ours == theirs
        assert client.get("/api/audits/mine/how").status_code == 200
        check = client.post("/api/audits/mine/verify", json={}, headers=WRITE).json()
        assert check["ok"] and check["bound_to_record"]
        assert client.get("/api/audits/other/overview").status_code == 404
    _close(ctx)


def test_an_attached_audit_without_its_study_says_why(seeded, tmp_path):
    root, study = seeded
    empty = StudyStore(tmp_path / "empty")
    ctx, client = _client(empty, audit_dirs={"theirs": root / "simulator_audits" / study})
    with client:
        info = client.get("/api/audits/theirs").json()
        assert info["qpilot_audit"] and not info["available"]
        assert study in info["reason"] and "not in this store" in info["reason"]
        r = client.get("/api/audits/theirs/overview")
        assert r.status_code == 409 and r.json()["error"]["code"] == "unavailable"
        check = client.post("/api/audits/theirs/verify", json={}, headers=WRITE).json()
        assert check["ok"] and not check["bound_to_record"]  # checksums only
    _close(ctx)


@pytest.mark.demo_data
def test_a_plain_simulator_run_can_be_attached(tmp_path):
    from qsim.app import Screen

    results = Path(__file__).resolve().parents[2] / "sim" / "results"
    if not (results / "explain.json").exists():
        pytest.skip("the simulator's results folder is not in this checkout")
    ctx, client = _client(StudyStore(tmp_path / "studies"), audit_dirs={"results": results})
    with client:
        info = _loaded(client, "/api/audits/results")
        assert info["available"] and not info["qpilot_audit"] and info["study_id"] is None
        overview = client.get("/api/audits/results/overview").json()
        expected = Screen(results).overview()
        expected.pop("model")
        assert overview == _plain(expected)
        verify = client.post("/api/audits/results/verify", json={}, headers=WRITE).json()
        assert not verify["ok"] and "AUDIT.sha256 missing" in verify["problems"]
    _close(ctx)


# ---- the pre-check, issues, files, lab numbers, Ask -------------------------------------


def _job(client, job_id: str, timeout: float = 900.0) -> dict:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def test_before_a_run_the_check_says_what_it_would_cover(seeded, tmp_path):
    root = _copy(seeded, tmp_path, audits=False)
    study = seeded[1]
    manifest = json.loads(
        (seeded[0] / "simulator_audits" / study / "audit_manifest.json").read_text()
    )
    ctx, client = _client(StudyStore(root))
    with client:
        first = client.get(f"/api/studies/{study}/audit").json()
        assert first["status"] == "none" and first["check"] is None
        assert _job(client, first["checking"]["id"])["status"] == "done"
        body = client.get(f"/api/studies/{study}/audit").json()
        assert body["status"] == "none" and body["checking"] is None
        assert body["check"]["applicable"] is True and body["check"]["reason"] is None
        assert body["check"]["scope"] == manifest["scope"]
    _close(ctx)


def test_the_whole_issue_queue(served, screen):
    client, study = served["client"], served["study"]
    body = client.get(f"/api/studies/{study}/audit/issues").json()
    assert body["n_issues"] == len(body["issues"]) == len(screen.issues)
    overview = client.get(f"/api/studies/{study}/audit/overview").json()
    assert body["issues"][: len(overview["issues"])] == overview["issues"]
    assert overview["n_issues"] == body["n_issues"]


def test_the_audits_files_can_be_listed_and_downloaded(served):
    client, study, root = served["client"], served["study"], served["root"]
    folder = root / "simulator_audits" / study
    files = client.get(f"/api/studies/{study}/audit/files").json()["files"]
    listed = dict(
        line.split("  ", 1)[::-1] for line in (folder / "AUDIT.sha256").read_text().splitlines()
    )
    assert {f["name"] for f in files} == set(listed) | {"AUDIT.sha256"}
    for f in files:
        assert f["bytes"] == (folder / f["name"]).stat().st_size
        assert f["sha256"] == listed.get(f["name"])
    r = client.get(f"/api/studies/{study}/audit/files/genes.csv")
    assert r.status_code == 200 and r.content == (folder / "genes.csv").read_bytes()
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("text/csv")
    for bad in ("nope.csv", "..%2Fsessions", "%2E%2E", ".DS_Store"):
        r = client.get(f"/api/studies/{study}/audit/files/{bad}")
        assert r.status_code == 404, bad


def test_a_file_the_audit_does_not_list_is_not_served(seeded, tmp_path):
    root = _copy(seeded, tmp_path)
    folder = root / "simulator_audits" / seeded[1]
    (folder / "notes.txt").write_text("not part of the audit")
    ctx, client = _client(StudyStore(root))
    with client:
        r = client.get(f"/api/studies/{seeded[1]}/audit/files/notes.txt")
        names = [
            f["name"] for f in client.get(f"/api/studies/{seeded[1]}/audit/files").json()["files"]
        ]
    _close(ctx)
    assert r.status_code == 404 and "notes.txt" not in names


def test_lab_numbers_are_the_worded_rows(served, screen):
    client, study = served["client"], served["study"]
    for gene in _genes(screen)[:8]:
        lab = client.get(f"/api/studies/{study}/audit/lab/{gene}").json()
        n, rows = lab["numbers"], {r["label"]: r["value"] for r in lab["rows"]}
        assert rows["Samples in each group"].startswith(f"{n['n_high']} ")
        assert rows["Plates for this assay"] == str(n["n_plates"])
        if n["cq_median"] is not None:
            assert rows["Cq, median (lowest to highest)"].startswith(f"{n['cq_median']:.1f} (")
        assert rows["Wells that never amplified"] == str(n["n_nondetect"])
        for cut, count in n["n_cq_above"].items():
            assert rows[f"Wells with Cq above {cut}"] == str(count)
        for ref in lab["references"]:
            assert ref["m_value"] is None or ref["m"] == f"{ref['m_value']:.2f}"


def test_ask_uses_the_same_screen_safely(served, screen):
    """api-ops' Ask reaches the audit through audit_screen; its engine calls are serialised."""
    client, study, ctx = served["client"], served["study"], served["ctx"]
    assert audit_router.audit_screen(ctx, study) is screen
    answer = screen.ask("What if we use the student test?")
    assert answer["routed_code"] in ("rules", "keywords", "model")
    assert answer["written_code"] in ("template", "model")
    assert all({"id", "meaning", "value"} <= set(f) for f in answer["facts"])
    assert isinstance(answer["problems"], list)
    from qsim.app import LockedEngine

    assert isinstance(screen.asker._engine, LockedEngine)
    url = f"/api/studies/{study}/audit/whatif"
    alone = client.post(url, json={"changes": {"test": "student"}}, headers=WRITE).json()
    with ThreadPoolExecutor(max_workers=4) as pool:
        asks = [pool.submit(screen.ask, "What if we use the student test?") for _ in range(2)]
        views = [
            pool.submit(
                lambda: client.post(
                    url, json={"changes": {"test": "student"}}, headers=WRITE
                ).json()
            )
            for _ in range(2)
        ]
        assert [v.result() for v in views] == [alone, alone]
        assert [a.result()["text"] for a in asks] == [answer["text"]] * 2


def test_no_audit_screen_without_an_audit(seeded, tmp_path):
    root = _copy(seeded, tmp_path, audits=False)
    ctx = make_context(StudyStore(root), token=TOKEN, watch=False)
    try:
        assert audit_router.audit_screen(ctx, seeded[1]) is None
    finally:
        _close(ctx)


def test_views_never_wait_for_a_build(seeded, monkeypatch):
    """While the screen loads, views answer at once with the one job loading it."""
    root, study = seeded
    built: list[int] = []
    real = audit_router._build_for_study

    def counting(ctx, study_id, folder):
        build = real(ctx, study_id, folder)

        def wrapped():
            built.append(1)
            return build()

        return wrapped

    monkeypatch.setattr(audit_router, "_build_for_study", counting)
    ctx, client = _client(StudyStore(root))  # a new server: nothing loaded
    url = f"/api/studies/{study}/audit"
    with client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(lambda _: client.get(f"{url}/overview"), range(8)))
        jobs = set()
        for r in answers:
            assert r.status_code == 409 and r.json()["error"]["code"] == "loading", r.text
            if r.json()["error"]["details"]["job"]:
                jobs.add(r.json()["error"]["details"]["job"]["id"])
        assert len(jobs) == 1
        assert _job(client, jobs.pop())["status"] == "done"
        assert client.get(f"{url}/overview").status_code == 200
        assert client.get(url).json()["views_ready"] is True
    _close(ctx)
    assert built == [1]


def test_the_audits_set_is_always_named_with_its_size(served, screen):
    """Never "N of 100" and never "reasonable analyses" bare (qPilot's grid is another set)."""
    import re

    client, study = served["client"], served["study"]
    url = f"/api/studies/{study}/audit"
    texts = [client.get(f"{url}/overview").text, client.get(f"{url}/how").text]
    texts += [client.get(f"{url}/gene/{g}").text for g in _genes(screen)]
    n = screen.explain[_genes(screen)[0]]["analyses_defensible"]
    for text in texts:
        assert " of 100" not in text
        bare = re.findall(r"(?<!audit's )(?<!ran \d{3} )(?<!ran \d{2} )reasonable analyses", text)
        assert not bare, text[:300]
    card = client.get(f"{url}/gene/{_genes(screen)[0]}").json()
    holds = card["holds"]
    assert holds["of"] == n and 0 <= holds["same"] <= n
    assert holds["n"] == round(100 * holds["same"] / n)
    assert f"{holds['same']} of {n}" in " ".join(card["holds"]["lines"])
