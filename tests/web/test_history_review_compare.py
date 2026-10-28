"""History and the Run Review in a study with several comparisons (synthetic three-group file).

History replays the comparison picked (``?comparison=``): the choices in force are the study's,
each step's calls are that comparison's rows of ``grid_comparisons.csv`` at the same analysis,
and a decision on the reference-set card (which changes TP53's call in Drug B vs Control only)
shows there and nowhere else. The Run Review names each comparison with the p each call used,
in the API's view, the text and the HTML; a study with one comparison keeps both as they were.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qpilot.report.run_review import build_review, render_html, render_text
from tests.fixtures.studio.compare_mini import design, write_compare_mini
from tests.web.test_studio_flow import no_html

A, B = "drug_a_vs_control", "drug_b_vs_control"


@pytest.fixture
def studies(web_store, tmp_path, monkeypatch):
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    path = write_compare_mini(tmp_path / "shift.rdml", ref_shift={("ACTB", "Drug B"): 2.5})
    several = web_store.ensure_study(path, design())
    one = web_store.ensure_study(path, design().model_copy(update={"comparisons": None}))
    return {"several": several, "one": one, "store": web_store}


def _decide(client, store, sid):
    r = client.post(
        f"/api/studies/{sid}/cards/card_refset/decide",
        json={
            "option": "actb_alone",
            "reason": "ACTB only",
            "expected_head": store.chain_head(sid),
        },
    )
    assert r.status_code == 200, r.text


def test_history_replays_each_comparison(client, studies):
    store, sid = studies["store"], studies["several"]
    _decide(client, store, sid)
    first = client.get(f"/api/studies/{sid}/history").json()
    second = client.get(f"/api/studies/{sid}/history", params={"comparison": B}).json()
    assert first["comparison"] == A and second["comparison"] == B
    assert [c["id"] for c in second["comparisons"]] == [A, B]
    assert "applies to every one" in second["comparison_note"]
    assert first["steps"][-1]["conclusions"]["changed"] == []  # no call moves in the first
    assert second["steps"][-1]["conclusions"]["changed"] == ["TP53"]
    for view in (first, second):  # the choices in force are the study's, the same in both
        assert [s["choices"] for s in view["steps"]] == [s["choices"] for s in first["steps"]]
    # each analysis is the comparison's rows of grid_comparisons.csv at that analysis
    every = pd.read_csv(store.workspace(sid) / "grid_comparisons.csv")
    rows = every[(every["comparison"] == B) & (every["refs"] == "ACTB")]
    rows = rows[rows["undetermined"] == "drop"].set_index("item")
    after = second["analyses"][second["steps"][-1]["analysis"]]
    for gene in after["genes"]:
        assert gene["conclusion"] == rows.loc[gene["gene"], "conclusion"]
        assert gene["fc"] == pytest.approx(float(rows.loc[gene["gene"], "fc"]))
    last = second["steps"][-1]["seq"]
    diff = client.get(
        f"/api/studies/{sid}/history/diff", params={"from": 0, "to": last, "comparison": B}
    ).json()
    assert [c["gene"] for c in diff["calls_changed"]] == ["TP53"]
    plain = client.get(f"/api/studies/{sid}/history/diff", params={"from": 0, "to": last}).json()
    assert plain["calls_changed"] == []
    r = client.get(f"/api/studies/{sid}/history", params={"comparison": "nope"})
    assert r.status_code == 404
    no_html(second)


def test_the_run_review_names_the_comparisons(client, studies):
    store, sid = studies["store"], studies["several"]
    view = client.get(f"/api/studies/{sid}/review").json()
    lines = [c["plain"] for c in view["comparisons"]]
    assert lines[0].startswith("Drug A vs Control (the first comparison): IL6 called up")
    assert lines[1].startswith("Drug B vs Control:") and "corrected p" in lines[1]
    assert "Holm's correction" in lines[-1]
    for line in view["comparisons"]:
        assert all(f["id"].startswith(("f_rr_", "f_")) for f in line["facts"])
    review = build_review(store.get(sid), headline=("IL6", "MYC"))
    text, html = render_text(review), render_html(review)
    assert "Comparisons\n- Drug A vs Control (the first comparison)" in text
    assert "<h2>Comparisons</h2>" in html and "Drug B vs Control" in html
    outcome = store.get(sid).comparisons.comparisons[1]
    assert review.facts["f_rr_cmp2_gene2_p"].value == pytest.approx(outcome.p_adjusted["MYC"])
    no_html(view)


def test_one_comparison_keeps_its_history_and_review(client, studies):
    one = studies["one"]
    history = client.get(f"/api/studies/{one}/history").json()
    assert history["comparison"] is None and history["comparisons"] == []
    assert history["comparison_note"] is None
    view = client.get(f"/api/studies/{one}/review").json()
    assert view["comparisons"] == []
    text = render_text(build_review(studies["store"].get(one), headline=("IL6",)))
    assert "Comparisons" not in text
