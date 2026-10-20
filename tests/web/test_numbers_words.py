"""Every share of analyses the API writes names its set and carries its own denominator.

Decision #0254 (bus): qPilot's grid and the audit's reasonable set are different sets of
analyses, so a sentence never says "reasonable analyses" bare, never "N of 100" unless exactly
100 analyses were run, and a share written as ``k of n`` or ``x % of the n analyses`` uses the
right ``n``: the study's grid size (744 or 186 on the demo) for qPilot, the audit's reasonable
count (144) or full grid (90,396) for the audit.
"""

from __future__ import annotations

import re
import shutil
import time
from collections.abc import Iterator
from typing import Any

import pytest

from tests.conftest import DEMO_RDML
from tests.web.numbers_world import BASE, World, api_client, call_ready, demo_world, get_json

pytestmark = pytest.mark.demo_data

BARE = re.compile(r"reasonable analyses", re.I)
PER_100 = re.compile(r"\b\d+ of 100\b")
SHARE = re.compile(r"(\d+(?:\.\d+)?) ?% of (?:the |all )?(\d[\d,  ]*)\s+(?:\w+\s+)?analyses")
UNDENOMINATED = re.compile(r"\d+ ?% of (?:the )?(?:reasonable )?analyses")


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return demo_world(tmp_path_factory.getbasetemp() / "numbers-demo", DEMO_RDML)


@pytest.fixture(scope="module")
def api(world, tmp_path_factory):
    from qpilot.core.store import StudyStore

    root = tmp_path_factory.mktemp("numbers-words") / "studies"
    shutil.copytree(world.store.root, root)
    with api_client(StudyStore(root)) as client:
        client.headers["origin"] = BASE
        yield client


def strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in a JSON answer, with where it is."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from strings(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from strings(v, f"{path}[{i}]")


def problems(texts: Iterator[tuple[str, str]], allowed: set[int]) -> list[str]:
    """Sentences that break #0254, with where they are."""
    out = []
    for where, text in texts:
        for m in BARE.finditer(text):
            if "audit" not in text[max(0, m.start() - 40) : m.start()]:
                out.append(f"{where}: bare 'reasonable analyses': {text!r}")
        if PER_100.search(text):
            out.append(f"{where}: 'of 100': {text!r}")
        if UNDENOMINATED.search(text):
            out.append(f"{where}: a share without its count: {text!r}")
        for m in SHARE.finditer(text):
            n = int(re.sub(r"[,  ]", "", m.group(2)))
            if n not in allowed:
                out.append(f"{where}: '% of {n}' is not one of {sorted(allowed)}: {text!r}")
    return out


def _texts(api, study_id: str, genes: list[str]) -> Iterator[tuple[str, str]]:
    for tail in ("results", "cards", "flips", *(f"genes/{g}" for g in genes)):
        yield from strings(get_json(api, f"/api/studies/{study_id}/{tail}"), tail)


@pytest.mark.xfail(
    strict=False,  # a store analysed after #0286 already passes; strict once #0358 merges
    reason="#0358 to api: studies analysed before #0286 keep 'holds in fewer than 80 % of the "
    "reasonable analyses' in results.json; the views are to re-word it on read",
)
@pytest.mark.parametrize("which", ["legacy", "study"])
def test_results_shares_name_qpilot_s_grid(api, world, which):
    study_id = getattr(world, which)
    n_cells = world.store.get(study_id).robustness["ODC1"].n_cells
    found = problems(_texts(api, study_id, ["ODC1", "NM23A", "CLSTN1"]), {n_cells})
    assert not found, "\n".join(found[:8])


def _ask(api, study_id: str, question: str) -> dict:
    r = api.post(f"/api/studies/{study_id}/ask", json={"question": question})
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    deadline = time.monotonic() + 300
    while (view := get_json(api, f"/api/jobs/{job['id']}"))["status"] not in ("done", "failed"):
        assert time.monotonic() < deadline, view
        time.sleep(0.1)
    assert view["status"] == "done", view
    return view["result"]


def test_ask_shares_name_qpilot_s_grid(api, world):
    n_cells = world.store.get(world.study).robustness["ODC1"].n_cells
    texts = []
    for gene in ("ODC1", "NM23A"):
        answer = _ask(api, world.study, f"How robust is {gene}?")
        texts += list(strings(answer["answer"], f"ask {gene}"))
    found = problems(iter(texts), {n_cells})
    assert not found, "\n".join(found)


def test_audit_shares_name_the_audit_s_set(api, world):
    pytest.importorskip("qpilot.web.routers.audit", reason="the audit routes are not merged yet")
    if not world.audited:
        pytest.skip("the Decision Simulator is not installed")
    base = f"/api/studies/{world.study}/audit"
    overview = call_ready(api, f"{base}/overview")
    texts = [*strings(overview, "overview"), *strings(call_ready(api, f"{base}/how"), "how")]
    for gene in ("ODC1", "NM23A", "CLSTN1"):
        texts += strings(call_ready(api, f"{base}/gene/{gene}"), f"gene {gene}")
    allowed = {overview["study"]["reasonable"], overview["study"]["analyses"]}
    found = problems(iter(texts), allowed)
    assert not found, "\n".join(found[:8])


@pytest.mark.xfail(
    strict=True,
    reason="#0333/#0334 to api-files: qpilot/prism/provenance.py writes 'holds in 99% of 744 "
    "reasonable analyses' into the Prism caption",
)
def test_the_prism_caption_names_qpilot_s_grid(api, world):
    pytest.importorskip("qpilot.web.routers.files", reason="the Prism routes are not merged")
    preview = get_json(api, f"/api/sessions/{world.sid}/prism/preview")
    n_cells = world.store.get(world.study).robustness["ODC1"].n_cells
    found = problems(iter([("caption", preview["caption"] or "")]), {n_cells})
    assert not found, "\n".join(found)
