"""Decision Cards in a study with several comparisons: a flip in any comparison is a flip.

On the synthetic three-group file with ACTB lowered by Drug B (``ref_shift``), which control
genes normalise changes TP53's call in Drug B vs Control and no call in Drug A vs Control (the
first comparison). The reference-set card must then wait for a person (it was auto-decided
when only the first comparison counted), name the comparison it changes, show each option's
consequence there, say that deciding applies to the whole study, and a decision must move every
comparison. A study with one comparison keeps its cards exactly as before.
"""

from __future__ import annotations

import pytest

from qpilot.core.decisions import asked_again, needs_human, stakes
from tests.fixtures.studio.compare_mini import design, write_compare_mini
from tests.web.test_studio_flow import no_html

A, B = "drug_a_vs_control", "drug_b_vs_control"
SHIFT = {("ACTB", "Drug B"): 2.5}


@pytest.fixture
def studies(web_store, tmp_path, monkeypatch):
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    path = write_compare_mini(tmp_path / "shift.rdml", ref_shift=SHIFT)
    several = web_store.ensure_study(path, design())
    one = web_store.ensure_study(path, design().model_copy(update={"comparisons": None}))
    return {"several": several, "one": one, "store": web_store}


def test_a_choice_that_flips_only_another_comparison_waits_for_a_person(studies):
    store, sid = studies["store"], studies["several"]
    card = store.card(sid, "card_refset")
    assert card.status == "open" and card.decided_by is None
    assert card.impact["flips"] and needs_human(card) and stakes(card) == 2
    assert card.impact["n_genes_flipped"] == 0  # none in the first comparison
    first, second = card.impact["views"]
    assert (first["id"], first["flips"]) == (A, False)
    assert (second["id"], second["flips"], second["genes"]) == (B, True, ["TP53"])
    assert card.impact["n_calls_flipped"] == 1
    facts = store.get(sid).facts
    assert facts["f_cmp2_n_flipped_refset"].value == 1
    assert facts["f_cmp1_n_flipped_refset"].value == 0
    undetermined = store.card(sid, "card_undetermined")
    assert undetermined.status == "auto_decided"  # no comparison's call changes with it


def test_the_card_names_the_comparison_and_says_the_choice_is_the_studys(client, studies):
    sid = studies["several"]
    view = client.get(f"/api/studies/{sid}/cards").json()
    card = next(c for c in view["cards"] if c["card"]["id"] == "card_refset")
    assert card["needs_human"]
    assert card["impact"]["plain"] == "Calls that change with this choice: 1 in Drug B vs Control"
    cited = {f["id"] for f in card["impact"]["facts"]}
    assert cited == {"f_cmp2_n_flipped_refset", "f_cmp2_label"}
    assert [(c["id"], c["flips"], c["genes"]) for c in card["comparisons"]] == [
        (A, False, []),
        (B, True, ["TP53"]),
    ]
    assert "whole study" in card["study_wide"]
    options = {o["id"]: o for o in card["options"]}
    actb = options["actb_alone"]["by_comparison"]
    assert [b["comparison"] for b in actb] == [B]
    tp53 = next(e for e in actb[0]["effects"] if e["gene"] == "TP53")
    assert tp53["conclusion"] == "up" and tp53["changes_call"]
    rec = next(e for e in options["recommended"]["by_comparison"][0]["effects"])
    assert not rec["changes_call"]
    no_html(view)


def test_deciding_the_card_moves_every_comparison(client, studies):
    store, sid = studies["store"], studies["several"]
    head = store.chain_head(sid)
    r = client.post(
        f"/api/studies/{sid}/cards/card_refset/decide",
        json={
            "option": "actb_alone",
            "reason": "ACTB is our lab's reference",
            "expected_head": head,
        },
    )
    assert r.status_code == 200, r.text
    second = client.get(f"/api/studies/{sid}/results", params={"comparison": B}).json()
    tp53 = next(g for g in second["genes"] if g["gene"] == "TP53")
    assert tp53["conclusion"] == "none"  # the planned call
    assert tp53["at_your_choices"]["conclusion"] == "up"  # the call at the person's choice
    first = client.get(f"/api/studies/{sid}/results").json()
    for gene in first["genes"]:
        assert gene["at_your_choices"] is not None
        assert gene["at_your_choices"]["conclusion"] == gene["conclusion"]
    side = client.get(f"/api/studies/{sid}/comparisons").json()
    row = next(g for g in side["genes"] if g["gene"] == "TP53")
    assert [c["at_your_choices"] for c in row["cells"]] == ["none", "up"]


def test_a_decision_is_asked_again_when_another_comparison_now_flips():
    from qpilot.schemas import DecisionCard

    base = {
        "id": "card_refset",
        "kind": "reference_set",
        "rank": 1,
        "evidence": {},
        "options": [],
        "recommended": "recommended",
        "rationale_template": "refset_v1",
        "facts": [],
        "autonomy": "suggest",
        "effective_autonomy": "suggest",
    }
    flat = {"flips": True, "n_genes_flipped": 1, "max_delta_log2fc": 1.0}
    before = DecisionCard(**base, impact={**flat, "n_calls_flipped": 1})
    after = DecisionCard(**base, impact={**flat, "n_calls_flipped": 2})
    assert asked_again(before, after) == "in this analysis the choice changes more conclusions"
    assert asked_again(before, before) is None


def test_a_study_with_one_comparison_keeps_its_cards(studies):
    store, one = studies["store"], studies["one"]
    for card in store.cards(one):
        assert "views" not in card.impact and "n_calls_flipped" not in card.impact
    assert not any(k.startswith("f_cmp") for k in store.get(one).facts)


def test_an_axis_that_matters_only_in_another_comparison_enters_the_grid(tmp_path, monkeypatch):
    """Screening an opt-in axis (efficiency, normaliser, inter-run, amplification rule) varies it
    alone from the planned analysis; with several comparisons it must look at every one, or a
    choice that changes a call only in Drug B vs Control would be left out of the grid."""
    from qpilot.core import robustness
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.study import StudySettings, _screen_every, build_model

    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    path = write_compare_mini(tmp_path / "shift.rdml", ref_shift=SHIFT)
    settings = StudySettings.from_design(design())
    model = build_model(analyse_study(path, settings.experiment_id, settings.candidates), settings)
    first = robustness.screen_axis(model.space, "refs")
    every = _screen_every(model.space, "refs")
    assert not any(first.flipped.values())  # the first comparison: nothing flips
    assert "TP53" in {g for genes in every.flipped.values() for g in genes}
    assert every.admitted and every.max_delta_log2fc >= first.max_delta_log2fc
