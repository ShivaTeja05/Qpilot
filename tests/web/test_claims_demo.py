"""The Claim Auditor on the real demo study (Vermeulen 2013, 64 plates), analysed once per module.

The paragraph of the Claim Auditor proposal (``qPilot-AI-USE-CASES.md``), written against this
study's own results: the verdicts follow from its record (calls, intervals, the share of qPilot's
choice grid where each call holds, its control genes and assay efficiencies).
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN

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
        results = c.get(f"/api/studies/{study_id}/results").json()
        rows = {g["gene"]: g for g in results["genes"]}
        yield {"c": c, "study": study_id, "results": results, "rows": rows}
    ctx.close()


def check(demo, text: str) -> list[dict]:
    r = demo["c"].post(f"/api/studies/{demo['study']}/claims", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["claims"]


def test_the_proposal_paragraph(demo):
    rows = demo["rows"]
    odc1, nm23a = rows["ODC1"], rows["NM23A"]
    assert odc1["conclusion"] == "up" and nm23a["conclusion"] == "up"
    assert nm23a["holds"] < 0.8 <= odc1["holds"]
    n_hi, n_lo = (g["n"] for g in demo["results"]["summary"]["groups"])
    fold = "{:g}".format(float(f"{odc1['fc']:.2g}"))
    text = (
        f"ODC1 was {fold}-fold higher in MYCN-high tumours (p < 0.001) and NM23A was robustly "
        "up-regulated. All assays had efficiencies of 90–110 %. Expression was normalised to "
        f"GAPDH. n = {n_hi} vs {n_lo} tumours."
    )
    claims = check(demo, text)
    got = [(c["kind"], c["gene"], c["verdict"]) for c in claims]
    assert got == [
        ("gene", "ODC1", "supported"),
        ("gene", "NM23A", "overstated"),
        ("efficiency", None, "contradicted"),
        ("normaliser", None, "contradicted"),
        ("n", None, "supported"),
    ]
    robust = next(ch for ch in claims[1]["checks"] if ch["check"] == "robust")
    assert robust["status"] == "stronger" and "qPilot checks" in robust["text"]["plain"]
    holds = next(f for f in robust["text"]["facts"] if f["id"] == "f_holds_nm23a")
    assert holds["value"] == pytest.approx(nm23a["holds"])
    eff = claims[2]
    assert "assays are outside" in eff["headline"]["plain"] and eff["suggestion"]
    outside = sum(
        1 for g in demo["results"]["genes"] if g["efficiency"] and not 1.9 <= g["efficiency"]
    )
    assert outside > 0


def test_a_call_one_choice_removes_holds_only_under_that_choice(demo):
    headline = demo["results"]["headline"]
    rows = sorted(demo["rows"].values(), key=lambda g: g["gene"] not in headline)
    row = next((g for g in rows if g["conclusion"] != "none" and g["flips_by"]), None)
    if row is None:
        pytest.skip("no call in this study is removed by one choice")
    gene = row["gene"]
    (claim,) = check(demo, f"{gene} did not differ between MYCN-high tumours and the rest.")
    assert claim["verdict"] == "choices", claim["headline"]["plain"]
    assert any(ch["holds"] and ch["dimension"] in row["flips_by"] for ch in claim["choices"])
    assert claim["headline"]["plain"].startswith("Not in the planned analysis")
    word = "higher" if row["conclusion"] == "up" else "lower"
    assert claim["suggestion"]["plain"].startswith(f"{gene} was {word}")


def test_a_fold_another_normaliser_gives(demo):
    (claim,) = check(demo, "Expression was normalised to UBC.")
    assert claim["kind"] == "normaliser" and claim["verdict"] == "choices"
    (choice,) = claim["choices"]
    assert choice["dimension"] == "refs" and choice["option"] == "UBC(2)"
    assert choice["card_id"] == "card_refset"


def test_an_overstated_fold(demo):
    birc5 = demo["rows"]["BIRC5"]
    far = int(birc5["ci"][1] * 3)
    (claim,) = check(demo, f"BIRC5 was {far}-fold higher in MYCN-high tumours.")
    assert claim["verdict"] == "overstated"
    assert "larger than the study's 95 % CI" in claim["headline"]["plain"]


def test_examples_cover_every_kind_of_error_and_come_out_as_described(demo):
    c, study = demo["c"], demo["study"]
    body = c.get(f"/api/studies/{study}/claims/examples").json()
    intents = [e["intent"] for e in body["examples"]]
    assert {"supported", "overstated", "choices", "contradicted"} <= set(intents)
    genes = {g for g in demo["results"]["headline"]}
    assert any(g in body["paragraph"] for g in genes)
    claims = check(demo, body["paragraph"])
    for example in body["examples"]:
        start = body["paragraph"].index(example["text"])
        mine = [cl for cl in claims if cl["sentence"]["start"] == start]
        assert mine and {cl["verdict"] for cl in mine} == {example["intent"]}, example
