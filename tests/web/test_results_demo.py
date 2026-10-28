"""Results routes on the real demo study (Vermeulen 2009, 64 plates), analysed once per module.

The views find the planned analysis and each card option in the robustness grid by value; here
they are checked against the numbers the engine stored on the cards themselves.
"""

from __future__ import annotations

import math
import shutil

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN
from tests.web.test_studio_flow import no_html

pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def demo_study(tmp_path_factory):
    from qpilot.io.datasets import default_cache_dir

    rdml = default_cache_dir() / "data_vermeulen_raw.rdml"
    if not rdml.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    base = tmp_path_factory.mktemp("demo") / "studies"
    store = StudyStore(base)
    return base, store.ensure_study(rdml)


@pytest.fixture
def demo(demo_study, tmp_path):
    base, study_id = demo_study
    shutil.copytree(base, tmp_path / "studies")
    store = StudyStore(tmp_path / "studies")
    ctx = make_context(store, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield c, store, study_id
    ctx.close()


def test_the_demo_results(demo):
    c, store, study = demo
    body = c.get(f"/api/studies/{study}/results").json()
    assert body["session"] is None and len(body["genes"]) == body["summary"]["n_genes"] == 58
    assert body["summary"]["n_plates"] == 64 and body["summary"]["mode"] == "marker_split"
    assert [g["label"] for g in body["summary"]["groups"]] == ["MYCN-high", "rest"]
    assert set(body["headline"]) == {"ODC1", "BIRC5", "NTRK1", "NM23A"}
    odc1 = next(g for g in body["genes"] if g["gene"] == "ODC1")
    assert odc1["conclusion"] == "up" and odc1["at_your_choices"] is None
    nc = body["summary"]["not_compared"]
    grouped = sum(g["n"] for g in body["summary"]["groups"])
    assert nc["n"] == body["summary"]["n_samples"] - grouped == 19
    no_html(body)
    frame = c.get(f"/api/studies/{study}").json()
    assert frame["kind"] == "study" and frame["results_visible"]


def test_flip_matrix_matches_the_cards(demo):
    c, store, study = demo
    flips = c.get(f"/api/studies/{study}/flips").json()
    rows = {r["dimension"]: r for r in flips["rows"]}
    cards = {card.id: card for card in store.cards(study)}
    refs = rows["refs"]
    assert refs["card_id"] == "card_refset"
    mapped = {o["card_option"]: o for o in refs["options"] if o["card_option"]}
    assert set(mapped) == {o.id for o in cards["card_refset"].options}
    assert mapped["recommended"]["planned"]
    for option in cards["card_refset"].options:
        row = mapped[option.id]
        assert row["label"] == option.label
        for gene, effect in option.per_gene.items():
            i = flips["genes"].index(gene)
            assert math.isclose(row["log2fc"][i], effect.log2fc, abs_tol=1e-9)
            assert row["conclusion"][i] == effect.conclusion
    # a decision 'flips' a gene exactly when one of its options gives another call
    for row in flips["rows"]:
        for i, flips_gene in enumerate(row["flips"]):
            assert flips_gene == any(o["flips"][i] for o in row["options"])


def test_your_choices_follow_the_cards(demo):
    c, store, study = demo
    url = f"/api/studies/{study}/cards/card_refset"
    for option in ("recommended", "top3"):
        r = c.post(
            f"{url}/decide",
            json={"option": option, "reason": "geNorm", "expected_head": store.chain_head(study)},
        )
        assert r.status_code == 200, r.text
    assert r.json()["card"]["undo_option"] == "recommended"
    body = c.get(f"/api/studies/{study}/results").json()
    flips = c.get(f"/api/studies/{study}/flips").json()
    top3 = next(
        o for row in flips["rows"] if row["dimension"] == "refs"
        for o in row["options"] if o["card_option"] == "top3"
    )  # fmt: skip
    assert top3["chosen"]
    differs = {g["gene"] for g in body["genes"] if g["at_your_choices"]["differs"]}
    assert differs == {g for g, f in zip(flips["genes"], top3["flips"], strict=True) if f}
    card = next(card for card in store.cards(study) if card.id == "card_refset")
    odc1 = next(g for g in body["genes"] if g["gene"] == "ODC1")
    want = next(o for o in card.options if o.id == "top3").per_gene["ODC1"]
    assert math.isclose(odc1["at_your_choices"]["log2fc"], want.log2fc, abs_tol=1e-9)
    r = c.post(
        f"{url}/undo",
        json={"reason": "back to all five", "expected_head": store.chain_head(study)},
    )
    assert r.status_code == 200, r.text
    after = c.get(f"/api/studies/{study}/results").json()
    assert all(g["at_your_choices"] is None for g in after["genes"])
    gene = c.get(f"/api/studies/{study}/genes/ODC1").json()
    assert {card["card"]["id"] for card in gene["cards"]} >= {"card_refset"}
    assert len(gene["grid"]["cells"]) == gene["row"]["n_cells"]
