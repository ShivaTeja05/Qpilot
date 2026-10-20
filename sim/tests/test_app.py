"""The results screen's views: plain words, numbers traced to the engine, live what-if and Ask.

qPilot's one page serves these views (``qpilot/web/routers/audit.py``; its tests are
``tests/web/test_audit*.py``); here they are checked on the committed run in ``sim/results``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from qpilot.ai.client import ModelClient
from qpilot.ai.config import ModelConfig

from qsim.app import Screen
from qsim.ask import Asker
from qsim.compare import whatif

RESULTS = Path(__file__).resolve().parents[1] / "results"
JARGON = re.compile(r"fragility|multiverse|\bSE\b|\brings?\b", re.I)


@pytest.fixture(scope="module")
def screen():
    asker = Asker(RESULTS, client=ModelClient(config=ModelConfig()))
    return Screen(RESULTS, asker=asker)


def test_counts_match_the_engine_files(screen):
    ov = screen.overview()
    counts = {v["key"]: v["count"] for v in ov["verdicts"]}
    assert counts == screen.summary["verdicts"]["counts"]
    assert len(ov["genes"]) == len(screen.explain)
    assert {d["id"] for d in ov["decisions"]} == set(screen.space.names)


def test_no_statistics_jargon_on_any_screen(screen):
    text = json.dumps(screen.overview())
    for gene in screen.explain:
        text += json.dumps(screen.gene_card(gene), ensure_ascii=False)
        text += screen.evidence_html(gene)
    for gene in ("NM23A", "NTRK1", "DPYSL3", "CAMTA2"):
        views = [screen.gene_effects(gene), screen.lab_parameters(gene), screen.gene_samples(gene)]
        text += json.dumps(views, ensure_ascii=False)
    text += json.dumps([screen.study_view(), screen.how_view()], ensure_ascii=False)
    assert not JARGON.findall(text)


def test_card_numbers_come_from_explain_json(screen):
    for gene, e in screen.explain.items():
        card = screen.gene_card(gene)
        assert card["holds"]["n"] == round(100 * e["holds_defensible"])
        fold = e["fold"] if e["fold"] >= 1 else 1 / e["fold"]
        assert f"{fold:.2f}×" in card["result"]["headline"]
        assert len(card["changes"]) == len(e["flips"])
        for shown, flip in zip(card["changes"], e["flips"], strict=True):
            f = flip["fold"] if flip["fold"] >= 1 else 1 / flip["fold"]
            assert f"{f:.2f}×" in shown["fold"]
        if e["drop_k"] == 1 and card["singles"]:  # one sample is enough: the card lists them
            assert any(f"any one of {len(card['singles'])}" in line for line in card["leans"])
        elif e["drop_k"]:
            assert any(f"Removing {e['drop_k']} of" in line for line in card["leans"])


def test_whatif_matches_the_engine(screen):
    changes = {"late_cq": "cq35", "refs": "HMBS"}
    view = screen.run_whatif(changes, ["PLAT"])
    table = whatif(screen.engine, changes)
    flipped = table[table["call"] != table["base_call"]]
    assert view["n_changed"] == len(flipped)
    assert view["changed_genes"] == list(flipped["gene"])
    assert [r["gene"] for r in view["rows"] if r["picked"]] == ["PLAT"]
    assert len(view["rows"]) == len(table)
    assert screen.run_whatif({})["n_changed"] == 0
    with pytest.raises(KeyError):
        screen.run_whatif({"late_cq": "cq99"})


def test_live_analyses_reproduce_the_run(screen):
    """The 144 analyses recomputed live give the same share of same calls as explain.json."""
    for gene, e in screen.explain.items():
        an = screen.gene_analyses(gene)
        assert an["n"] == e["analyses_defensible"]
        assert an["n_same"] / an["n"] == pytest.approx(e["holds_defensible"])
        assert sum(r["planned"] for r in an["rows"]) == 1


def test_samples_and_choices_match_the_engine(screen):
    for gene in ("NM23A", "NTRK1", "ODC1", "BIRC5"):
        e = screen.explain[gene]
        sm = screen.gene_samples(gene)
        assert sm["fold_log2"] == pytest.approx(e["log2fc"])
        ef = screen.gene_effects(gene)
        for d in ef["decisions"]:
            planned = [o for o in d["options"] if o["planned"]]
            assert len(planned) == 1 and planned[0]["log2"] == pytest.approx(e["log2fc"])
    changes = {"late_cq": "cq35", "refs": "HMBS"}
    row = next(r for r in screen.run_whatif(changes)["rows"] if r["gene"] == "NTRK1")
    assert screen.gene_samples("NTRK1", changes)["fold_log2"] == pytest.approx(row["new_log2"])


def test_every_view_the_page_serves(screen):
    assert screen.overview()["study"]["genes"] == len(screen.explain)
    assert screen.gene_card("NM23A")["gene"] == "NM23A"
    assert "Evidence for NM23A" in screen.evidence_html("NM23A")
    assert screen.run_whatif({"late_cq": "cq35"})["n_changed"] > 0
    assert screen.gene_analyses("NM23A")["n"] == 144
    assert screen.gene_effects("NM23A")["decisions"]
    assert screen.lab_parameters("NM23A")["rows"]
    assert screen.study_view()["map"]
    assert screen.how_view()["stages"]
    assert screen.gene_samples("NM23A", {})["points"]
    ans = screen.ask("Does NM23A depend on the reference genes?")
    assert ans["tool"] == "gene" and ans["written_by"] == "the engine's checked template"
    fold = next(f["value"] for f in ans["facts"] if f["meaning"] == "fold change at baseline")
    assert fold in ans["text"]
    with pytest.raises(KeyError):
        screen.gene_card("NOPE")
