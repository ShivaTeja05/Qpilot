"""The Results API with several comparisons, on the synthetic three-group file (no download).

``?comparison=`` on /results, /flips and /genes/{gene}; ``GET /comparisons``; the choices a person
made on the cards applied to every comparison; plain-words refusals; a study with one comparison
(q-values, no picker); the MCP tools and the Analysis Record following the comparisons.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qpilot.core import record
from qpilot.mcp_server import QpilotTools
from qpilot.qpcr.contrast import bh
from tests.fixtures.studio.compare_mini import design, write_compare_mini
from tests.web.test_studio_flow import no_html

B = "drug_b_vs_control"


@pytest.fixture
def studies(web_store, tmp_path, monkeypatch):
    """Two studies of one file: each drug vs Control paired by donor, and the plain comparison."""
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    path = write_compare_mini(tmp_path / "compare_mini.rdml", missing_well=True)
    several = web_store.ensure_study(path, design(paired=True))
    one = web_store.ensure_study(path, design().model_copy(update={"comparisons": None}))
    return {"several": several, "one": one, "store": web_store}


def test_results_show_one_comparison_at_a_time(client, studies):
    sid = studies["several"]
    first = client.get(f"/api/studies/{sid}/results").json()
    assert first["comparison"] == "drug_a_vs_control"
    assert [t["id"] for t in first["comparisons"]] == ["drug_a_vs_control", B]
    assert first["comparisons"][0]["primary"] and first["comparisons"][1]["n_up"] == 2
    assert all(g["p_adjusted"] is not None and g["q"] is not None for g in first["genes"])
    assert "corrected p < 0.05" in first["rule"]["text"]
    second = client.get(f"/api/studies/{sid}/results", params={"comparison": B}).json()
    assert second["comparison"] == B
    assert [g["label"] for g in second["summary"]["groups"]] == ["Drug B", "Control"]
    assert {g["gene"]: g["conclusion"] for g in second["genes"]} == {
        "IL6": "up",
        "MYC": "up",
        "TP53": "none",
    }
    tp53 = next(g for g in second["genes"] if g["gene"] == "TP53")
    assert tp53["n_hi"] == 3  # DrugB_D4 was not measured for TP53: its pair is left out
    assert second["summary"]["text"] is None  # the summary sentence is the first comparison's
    reasons = second["summary"]["not_compared"]["reasons"]
    assert reasons == [
        {
            "reason": "in group Drug A, compared in another comparison",
            "n": 4,
            "samples": ["DrugA_D1", "DrugA_D2", "DrugA_D3", "DrugA_D4"],
        }
    ]
    no_html(second)


def test_flips_and_one_gene_follow_the_comparison(client, studies):
    sid = studies["several"]
    flips = client.get(f"/api/studies/{sid}/flips", params={"comparison": B}).json()
    assert flips["comparison"] == B and flips["genes"] == ["IL6", "MYC", "TP53"]
    assert flips["planned"] == ["up", "up", "none"]
    for row in flips["rows"]:
        assert sum(o["planned"] for o in row["options"]) == 1
    gene = client.get(f"/api/studies/{sid}/genes/MYC", params={"comparison": B}).json()
    assert gene["comparison"] == B and gene["row"]["conclusion"] == "up"
    assert gene["confidence_text"] is None and len(gene["grid"]["cells"]) == 6
    first = client.get(f"/api/studies/{sid}/genes/MYC").json()
    assert first["comparison"] == "drug_a_vs_control" and first["row"]["conclusion"] == "none"


def test_unknown_comparisons_are_refused_in_words(client, studies):
    sid = studies["several"]
    r = client.get(f"/api/studies/{sid}/results", params={"comparison": "nope"})
    assert r.status_code == 404
    assert "it has: drug_a_vs_control, drug_b_vs_control" in r.json()["error"]["message"]
    for bad in ("DROP TABLE", "../x", "x" * 300):
        assert (
            client.get(f"/api/studies/{sid}/flips", params={"comparison": bad}).status_code == 404
        )
    one = studies["one"]
    r = client.get(f"/api/studies/{one}/results", params={"comparison": B})
    assert r.status_code == 404 and "one comparison" in r.json()["error"]["message"]


def test_every_comparison_side_by_side(client, studies):
    sid = studies["several"]
    view = client.get(f"/api/studies/{sid}/comparisons").json()
    assert view["several"] and view["test"] == "paired_t" and view["correction"] == "holm"
    assert view["pair_by"] == "donor" and view["control"] == "Control"
    assert [c["id"] for c in view["comparisons"]] == ["drug_a_vs_control", B]
    assert [c["n_pairs"] for c in view["comparisons"]] == [4, 4]
    by_gene = {g["gene"]: g for g in view["genes"]}
    assert [c["conclusion"] for c in by_gene["MYC"]["cells"]] == ["none", "up"]
    assert by_gene["IL6"]["n_called"] == 2 and by_gene["TP53"]["n_called"] == 0
    second = client.get(f"/api/studies/{sid}/results", params={"comparison": B}).json()
    for g in second["genes"]:  # the side-by-side cells are the per-comparison results
        cell = by_gene[g["gene"]]["cells"][1]
        assert cell["fc"] == g["fc"] and cell["p_adjusted"] == g["p_adjusted"]
        assert cell["q"] == g["q"]
    kinds = [n["kind"] for n in view["notes"]]
    assert kinds == ["correction", "paired", "primary_only", "q_value", "not_measured"]
    assert view["not_measured"] == {"TP53": "DrugB_D4"}
    no_html(view)


def test_a_study_with_one_comparison_gets_q_values_and_no_picker(client, studies):
    one = studies["one"]
    results = client.get(f"/api/studies/{one}/results").json()
    assert results["comparison"] is None and results["comparisons"] == []
    p = np.array([g["p"] for g in results["genes"]])
    assert [g["q"] for g in results["genes"]] == pytest.approx(list(bh(p)))
    assert all(g["p_adjusted"] is None for g in results["genes"])
    view = client.get(f"/api/studies/{one}/comparisons").json()
    assert not view["several"] and len(view["comparisons"]) == 1
    assert view["comparisons"][0]["id"] == "primary"
    assert "corrected" not in view["rule_text"]


def test_a_choice_on_a_card_applies_to_every_comparison(client, studies):
    store, sid = studies["store"], studies["several"]
    card = store.card(sid, "card_refset")
    other = next(o.id for o in card.options if o.id != card.recommended)
    outcome = store.append_decision(
        sid, "card_refset", other, "our lab normalises to ACTB", "human", store.chain_head(sid)
    )
    assert outcome.status == "applied"
    second = client.get(f"/api/studies/{sid}/results", params={"comparison": B}).json()
    every = pd.read_csv(store.workspace(sid) / "grid_comparisons.csv")
    rows = every[(every["comparison"] == B) & (every["refs"] == other.split("_")[0].upper())]
    for gene in second["genes"]:
        yours = gene["at_your_choices"]
        assert yours is not None, gene["gene"]
        want = rows[(rows["item"] == gene["gene"]) & (rows["undetermined"] == "drop")]
        assert yours["fc"] == pytest.approx(float(want["fc"].iloc[0]))
        assert yours["conclusion"] == want["conclusion"].iloc[0]


def test_the_record_and_mcp_follow_the_comparisons(studies, tmp_path):
    store, sid = studies["store"], studies["several"]
    record.write_record(store, sid, tmp_path / "rec")
    assert (tmp_path / "rec" / "grid_comparisons.csv").exists()
    assert record.verify(tmp_path / "rec").ok
    report = record.rerun_compare(tmp_path / "rec", tmp_path / "again")
    assert report.same and "grid_comparisons.csv" in report.compared

    tools = QpilotTools(store)
    study = tools.qpcr_robustness(sid, "MYC", comparison=B)
    assert study["comparison"] == B and study["conclusion"] == "up"
    assert study["fact_ids"]["p_adjusted"] == "f_cmp2_padj_myc"
    facts = store.get(sid).facts
    assert facts["f_cmp2_padj_myc"].value == study["p_adjusted"]
    assert tools.qpcr_robustness(sid, "MYC", comparison="nope")["code"]
    assert tools.qpcr_robustness(studies["one"], "MYC", comparison=B)["code"]
