"""The results screen: plain words, numbers traced to the engine, live what-if and Ask."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from qpilot.ai.client import ModelClient
from qpilot.ai.config import ModelConfig

from qsim.app import PAGE, Screen, make_handler
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
    text += PAGE.read_text()
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


def test_page_markup_types_no_numbers():
    html = PAGE.read_text()
    markup = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", markup)
    assert not re.findall(r"\d", text)


def test_whatif_matches_the_engine(screen):
    changes = {"late_cq": "cq35", "refs": "HMBS"}
    view = screen.run_whatif(changes, ["PLAT"])
    table = whatif(screen.engine, changes)
    flipped = table[table["call"] != table["base_call"]]
    assert view["n_changed"] == len(flipped)
    assert view["changed_genes"] == list(flipped["gene"])
    assert [r["gene"] for r in view["rows"]][-1] == "PLAT"
    assert screen.run_whatif({})["n_changed"] == 0
    with pytest.raises(KeyError):
        screen.run_whatif({"late_cq": "cq99"})


def test_http_endpoints(screen):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(screen))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=30) as r:
            return r.read().decode()

    def post(path, body):
        req = urllib.request.Request(
            base + path, json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    try:
        assert "Does your qPCR result hold up?" in get("/")
        assert json.loads(get("/api/overview"))["study"]["genes"] == len(screen.explain)
        assert json.loads(get("/api/gene/NM23A"))["gene"] == "NM23A"
        assert "Evidence for NM23A" in get("/evidence/NM23A")
        assert json.loads(get("/files/explain.json")) == screen.explain
        assert post("/api/whatif", {"changes": {"late_cq": "cq35"}})["n_changed"] > 0
        ans = post("/api/ask", {"question": "Does NM23A depend on the reference genes?"})
        assert ans["tool"] == "gene" and ans["written_by"] == "the engine's checked template"
        fold = next(f["value"] for f in ans["facts"] if f["meaning"] == "fold change at baseline")
        assert fold in ans["text"]
        for bad in ("/files/../summary.json", "/files/lock.json", "/api/gene/NOPE"):
            with pytest.raises(urllib.error.HTTPError):
                get(bad)
    finally:
        httpd.shutdown()
        httpd.server_close()
