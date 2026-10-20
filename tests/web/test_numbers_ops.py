"""Ask's and the Agents view's numbers are the engine's and the store's.

Ask (no model: qPilot's checked templates) must answer with numbers that are cited facts, and
each cited value must be the engine's number at the precision it is written with. The Agents
view counts what the store's chains hold, after a real agent request through the MCP tool code.
"""

from __future__ import annotations

import re
import shutil
import time

import pytest

from tests.conftest import DEMO_RDML
from tests.web.numbers_engine import engine
from tests.web.numbers_world import BASE, World, api_client, demo_world, get_json

pytestmark = pytest.mark.demo_data

NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return demo_world(tmp_path_factory.getbasetemp() / "numbers-demo", DEMO_RDML)


@pytest.fixture(scope="module")
def copy(world, tmp_path_factory):
    """A private copy of the demo store (Ask logs its calls; an agent request writes)."""
    from qpilot.core.store import StudyStore

    root = tmp_path_factory.mktemp("numbers-ops") / "studies"
    shutil.copytree(world.store.root, root)
    store = StudyStore(root)
    with api_client(store) as client:
        client.headers["origin"] = BASE
        yield client, store


def ask(client, study_id: str, question: str) -> dict:
    """Ask over the API and wait for the job's answer."""
    r = client.post(f"/api/studies/{study_id}/ask", json={"question": question})
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    deadline = time.monotonic() + 300
    while True:
        view = get_json(client, f"/api/jobs/{job['id']}")
        if view["status"] in ("done", "failed"):
            break
        assert time.monotonic() < deadline, view
        time.sleep(0.1)
    assert view["status"] == "done", view
    return view["result"]


def shown(text: str) -> float:
    """The number a cited value shows (``3.3×`` -> 3.3, ``99%`` -> 99)."""
    (number,) = NUMBER.findall(text.replace(",", "").replace(" ", ""))
    return float(number)


def same_at_shown_precision(text: str, value: float) -> bool:
    """``text`` is ``value`` written with as many digits as ``text`` shows."""
    number = NUMBER.findall(text.replace(",", "").replace(" ", ""))[0]
    decimals = len(number.split(".")[1]) if "." in number else 0
    return abs(float(number) - value) <= 0.5 * 10**-decimals + 1e-12


def every_number_is_cited(answer: dict, genes: list[str]) -> None:
    """Each number written in the answer (gene names aside) is one of its cited facts."""
    text = answer["answer"]
    for gene in sorted(genes, key=len, reverse=True):
        text = text.replace(gene, "")
    cited = {str(shown(f["value"])) for f in answer["facts"] if NUMBER.search(f["value"])}
    written = {str(float(n)) for n in NUMBER.findall(text.replace(",", ""))}
    assert written <= cited, (answer["answer"], answer["facts"])


@pytest.mark.parametrize("which", ["legacy", "study"])
@pytest.mark.parametrize("gene", ["ODC1", "NM23A", "CPSG3"])
def test_a_gene_answer_cites_the_engine_numbers(copy, world, which, gene):
    client, _ = copy
    study_id = getattr(world, which)
    eng = engine(world, study_id)
    answer = ask(client, study_id, f"How robust is {gene}?")
    assert (answer["engine"], answer["tool"], answer["validated"]) == (
        "study",
        "qpcr_robustness",
        True,
    )
    facts = {f["id"]: f["value"] for f in answer["facts"]}
    contrast, robust = eng.result.contrasts[gene], eng.result.robustness[gene]
    assert same_at_shown_precision(facts["f_ans_fc"], contrast.fc), facts
    assert same_at_shown_precision(facts["f_ans_ci_lo"], contrast.ci[0]), facts
    assert same_at_shown_precision(facts["f_ans_ci_hi"], contrast.ci[1]), facts
    assert same_at_shown_precision(facts["f_ans_holds"], 100 * robust.holds), facts
    assert shown(facts["f_ans_n_cells"]) == robust.n_cells
    assert facts["f_ans_level"] == eng.result.confidence[gene].level
    every_number_is_cited(answer, list(eng.result.contrasts))


@pytest.mark.parametrize("which", ["legacy", "study"])
def test_the_study_answer_cites_the_engine_counts(copy, world, which):
    client, _ = copy
    study_id = getattr(world, which)
    eng = engine(world, study_id)
    answer = ask(client, study_id, "What is in this study?")
    facts = {f["id"]: shown(f["value"]) for f in answer["facts"]}
    assert facts == {
        "f_ans_n_plates": eng.result.n_plates,
        "f_ans_n_samples": eng.result.n_samples,
        "f_ans_n_genes": len(eng.result.contrasts),
    }
    every_number_is_cited(answer, list(eng.result.contrasts))


def test_an_agent_request_is_counted_where_it_waits(copy, world):
    """One agent request on a card that can flip a call: the Agents view lists exactly it."""
    from qpilot.mcp_server import QpilotTools

    client, store = copy
    eng = engine(world, world.study)
    card = next(c for c in eng.cards if c.id == "card_refset")
    before = get_json(client, "/api/agents")
    out = QpilotTools(store).qpcr_decide(
        world.study, card.id, "top2", "an agent's request, to count it", actor="agent"
    )
    assert out["status"] == "pending_human", out
    view = get_json(client, "/api/agents")
    assert len(view["pending"]) == len(before["pending"]) + 1
    (request,) = (p for p in view["pending"] if p["study_id"] == world.study)
    assert (request["card_id"], request["option"]) == (card.id, "top2")
    assert request["can_change_a_conclusion"] is bool(card.impact["flips"])
    assert request["expected_head"] == store.chain_head(world.study)
    pending = sum(len(store.pending(s)) for s in store.list_studies())
    assert len(view["pending"]) == pending
    results = get_json(client, f"/api/studies/{world.study}/results")
    assert results["pending_requests"] == len(store.pending(world.study)) == 1
