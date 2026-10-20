"""Studio's safety properties, checked on the one server (tests/web/PARITY.md §1).

Ported from the old Gradio Studio and results pages (``tests/studio/test_studio_app.py``,
``tests/app/test_app.py``): a person is the only actor the page writes as, reading writes
nothing, nothing about the results leaks while the session is blind, and text from a file or an
agent comes back as data. The sweeps enumerate the server's own routes (its OpenAPI document),
so a route added later is checked too.
"""

from __future__ import annotations

import ast
import itertools
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import qpilot.web
from qpilot.mcp_server import QpilotTools
from tests.web.conftest import wait_job
from tests.web.test_studio_flow import accept_all, confirm, design_ready, propose

WEB = Path(qpilot.web.__file__).parent
HOSTILE = "<script>alert(1)</script>"
HOSTILE_NAME = f"KO_2{HOSTILE}"
HOSTILE_SENTENCE = 'WT vs KO <img src=x onerror="alert(2)">'
TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
#: Files a decision or a proposal writes. Reading may cache an analysis, never touch these.
DECISION_FILES = ("proposals.jsonl", "decisions.jsonl", "cards.json", "quarantine.json")
#: Keys that carry a result (a contrast, its robustness or its confidence): never while blind.
RESULT_KEYS = {
    "fc", "fold", "fold_change", "log2fc", "log2_fc", "ci", "ci_low", "ci_high", "p", "p_value",
    "t", "n_hi", "n_lo", "conclusion", "holds", "robustness", "contrasts", "confidence",
}  # fmt: skip
#: A number written as a fold change or a p-value in a sentence.
RESULT_TEXT = re.compile(r"\d\s*×|\bp\s*[<=]\s*0?\.\d|fold change of \d")


# ---- helpers ---------------------------------------------------------------------------------


def strings(value) -> Iterator[str]:
    """Every string in a JSON value (keys included)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def dicts(value) -> Iterator[dict]:
    """Every object in a JSON value."""
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from dicts(v)
    elif isinstance(value, list):
        for v in value:
            yield from dicts(v)


def get_routes(client, prefix: str) -> list[tuple[str, list[str], dict[str, bool]]]:
    """``(path, path params, {query param: required})`` of every GET route under ``prefix``."""
    spec = client.get("/api/openapi.json").json()
    routes = []
    for path, operations in spec["paths"].items():
        if not path.startswith(prefix) or "get" not in operations:
            continue
        params = operations["get"].get("parameters", [])
        in_path = [p["name"] for p in params if p["in"] == "path"]
        query = {p["name"]: bool(p.get("required")) for p in params if p["in"] == "query"}
        routes.append((path, in_path, query))
    assert routes, f"no GET route under {prefix}"
    return routes


def candidates(client, sid: str) -> dict[str, list[str]]:
    """Plausible values for each parameter name, read from the session itself."""
    plate = client.get(f"/api/sessions/{sid}/plate").json()
    wells = [w["key"] for w in plate.get("wells", []) if w.get("key")]
    genes = sorted({w["target"] for w in plate.get("wells", []) if w.get("target")})
    proposals = client.get(f"/api/sessions/{sid}/proposals").json().get("proposals", [])
    quarantine = client.get(f"/api/sessions/{sid}/quarantine").json()
    texts = [e["text_id"] for e in quarantine.get("entries", []) if "text_id" in e]
    stages = ["design", "curves", "choices", "prism", "roundtrip"]
    return {
        "sid": [sid],
        "pid": [p["id"] for p in proposals[:3]],
        "stage": stages,
        "action": ["accept", "reject"],
        "well": wells[:2],
        "gene": genes[:2],
        "ids": texts[:2],
        "status": ["proposed", "accepted"],
    }


def sweep(client, sid: str) -> Iterator[tuple[str, object]]:
    """Call every GET route of a session with plausible values; yield (url, response)."""
    values = candidates(client, sid)
    for path, in_path, query in get_routes(client, "/api/sessions/{sid}"):
        options = [[(name, v) for v in values.get(name, [])] or [(name, None)] for name in in_path]
        for combo in itertools.product(*options):
            if any(v is None for _, v in combo):
                continue  # a path parameter this sweep cannot fill
            url = path.format(**dict(combo))
            params_sets = [{}]
            for name in query:
                filled = [{**p, name: v} for p in params_sets for v in values.get(name, [])[:2]]
                params_sets = filled if filled and query[name] else params_sets + filled
            for params in params_sets[:6]:
                yield f"{url}?{params}", client.get(url, params=params)


def reveals(body) -> list[str]:
    """What in a JSON answer shows a result: result keys, a group next to numbers, result text."""
    found = []
    for obj in dicts(body):
        shown = sorted(k for k, v in obj.items() if k in RESULT_KEYS and v not in (None, [], {}))
        if shown:
            found.append(f"result keys {shown}")
        numbers = {k: v for k, v in obj.items() if isinstance(v, int | float) and k != "group"}
        if obj.get("group") and numbers:
            found.append(f"group {obj['group']!r} next to {sorted(numbers)}")
    found += [f"text {s!r}" for s in strings(body) if RESULT_TEXT.search(s)]
    return found


def decision_files(store) -> dict[str, bytes]:
    return {
        str(p.relative_to(store.root)): p.read_bytes()
        for p in store.root.rglob("*")
        if p.is_file() and p.name in DECISION_FILES
    }


# ---- a person is the only actor (P1) ---------------------------------------------------------


def _constants(tree: ast.Module) -> dict[str, object]:
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value.value
    return found


def test_the_web_code_writes_only_as_a_person():
    """Every ``actor`` the server passes is ``"human"``; no write goes around the core rules."""
    modules = {path: ast.parse(path.read_text(encoding="utf-8")) for path in WEB.rglob("*.py")}
    constants: dict[str, object] = {}
    for tree in modules.values():
        constants.update({k: v for k, v in _constants(tree).items() if k == "HUMAN"})
    assert constants.get("HUMAN", "human") == "human"

    def is_human(node: ast.expr) -> bool:
        if isinstance(node, ast.Constant):
            return node.value == "human"
        return isinstance(node, ast.Name) and constants.get(node.id) == "human"

    problems = []
    for path, tree in modules.items():
        where = path.relative_to(WEB)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
            name = name or (node.func.id if isinstance(node.func, ast.Name) else "")
            for keyword in node.keywords:
                if keyword.arg == "actor" and not is_human(keyword.value):
                    problems.append(f"{where}:{node.lineno} {name}(actor={ast.unparse(keyword)})")
            if name == "apply_decision" and len(node.args) > 5 and not is_human(node.args[5]):
                problems.append(
                    f"{where}:{node.lineno} apply_decision as {ast.unparse(node.args[5])}"
                )
            if name in ("append_decision", "request_human"):
                problems.append(f"{where}:{node.lineno} {name}: writes around core.decisions")
            if name in ("run", "Popen", "call", "check_output") and "subprocess" in ast.unparse(
                node.func
            ):
                problems.append(f"{where}:{node.lineno} starts a process")
    assert not problems, problems


def test_no_request_body_carries_an_actor(client):
    spec = client.get("/api/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas", {})
    bodies = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for media in operation.get("requestBody", {}).get("content", {}).values():
                ref = media.get("schema", {}).get("$ref", "")
                schema = schemas.get(ref.rsplit("/", 1)[-1], media.get("schema", {}))
                bodies.append((f"{method.upper()} {path}", schema))
                params = {p["name"] for p in operation.get("parameters", [])}
                assert "actor" not in params, f"{method.upper()} {path} takes an actor"
    assert bodies, "the API has request bodies"
    for where, schema in bodies:
        assert "actor" not in schema.get("properties", {}), f"{where} takes an actor"


# ---- reading writes nothing (P2) -------------------------------------------------------------


def test_every_get_route_writes_nothing(sclient, web_store, opened):
    sid = opened
    design_ready(sclient, web_store, sid)
    confirm(sclient, sid, "design")
    propose(sclient, sid, "curves")

    before = decision_files(web_store)
    assert any(name.endswith("proposals.jsonl") for name in before)
    heads = sclient.get(f"/api/sessions/{sid}/proposals").json()["head"]
    calls = list(sweep(sclient, sid))
    assert len(calls) >= 10
    assert all(r.status_code < 500 for _, r in calls), [u for u, r in calls if r.status_code >= 500]
    assert decision_files(web_store) == before, "a GET wrote a decision or a proposal (blind)"
    assert sclient.get(f"/api/sessions/{sid}/proposals").json()["head"] == heads

    accept_all(sclient, sid, "curves")
    done = confirm(sclient, sid, "curves")
    assert done["results_visible"]
    if done["job"]:
        assert wait_job(sclient, done["job"])["status"] == "done"
    before = decision_files(web_store)
    calls = list(sweep(sclient, sid))
    assert all(r.status_code < 500 for _, r in calls), [u for u, r in calls if r.status_code >= 500]
    assert decision_files(web_store) == before, "a GET wrote a decision or a proposal (results)"
    # the blind sweep's detector is not blind itself: once results are visible, it sees them
    assert any(reveals(r.json()) for _, r in calls if r.status_code == 200)


# ---- blind until both stages are confirmed (P3) ----------------------------------------------


def test_no_get_route_reveals_results_while_blind(sclient, web_store, opened):
    """The design is confirmed and the curves are proposed: still blind. Nothing pairs a group
    with a number and no result (fold change, p, conclusion, holds, confidence) is served."""
    sid = opened
    design_ready(sclient, web_store, sid)
    confirm(sclient, sid, "design")
    r = sclient.post(f"/api/sessions/{sid}/propose/curves")
    assert r.status_code == 202, r.text
    job = wait_job(sclient, r.json()["job"])
    assert job["status"] == "done", job
    assert not sclient.get(f"/api/sessions/{sid}").json()["results_visible"]

    extra = [
        (f"/api/jobs/{job['id']}", sclient.get(f"/api/jobs/{job['id']}")),
        ("/api/jobs", sclient.get("/api/jobs")),
        ("/api/workspaces", sclient.get("/api/workspaces")),
    ]
    served = 0
    for url, r in [*sweep(sclient, sid), *extra]:
        if r.status_code == 403:
            assert r.json()["error"]["code"] == "blind", url
            continue
        if r.status_code != 200:
            continue
        served += 1
        assert not reveals(r.json()), f"{url}: {reveals(r.json())[:3]}"
    assert served >= 10


# ---- text is text (P12) ----------------------------------------------------------------------


@pytest.fixture
def evil_rdml(mini_rdml):
    """The mini file again, with one sample named in markup (same curves, same type)."""
    from tests.fixtures.studio.studio_mini import write_studio_mini

    return write_studio_mini(mini_rdml.parent / "evil.rdml", rename={"KO_2": HOSTILE_NAME})


def test_hostile_names_come_back_as_data_in_json_only(sclient, web_store, evil_rdml):
    with evil_rdml.open("rb") as fh:
        r = sclient.post(
            "/api/workspaces",
            files={"rdml": ("evil.rdml", fh, "text/xml")},
            data={"sentence": HOSTILE_SENTENCE},
        )
    assert r.status_code == 202, r.text
    job = wait_job(sclient, r.json()["job"])
    assert job["status"] == "done", job
    sid = job["result"]["key"]
    propose(sclient, sid, "design")
    QpilotTools(web_store).qpcr_propose(sid, "design.group", HOSTILE_NAME, {"group": HOSTILE})

    hostile = (HOSTILE, HOSTILE_SENTENCE)
    seen_name = False
    for url, r in sweep(sclient, sid):
        assert r.headers["content-type"].startswith("application/json"), url
        assert r.headers["x-content-type-options"] == "nosniff", url
        body = r.json()
        for text in strings(body):
            if TAG.search(text):
                assert any(h in text or text in h for h in hostile), f"{url}: markup {text!r}"
            seen_name = seen_name or HOSTILE_NAME in text
    assert seen_name, "the hostile name comes back verbatim, as data"

    page = sclient.get("/", params={"q": HOSTILE})
    assert HOSTILE not in page.text, "the page never echoes what it is sent"
    assert json.dumps(HOSTILE)[1:-1] not in page.text
