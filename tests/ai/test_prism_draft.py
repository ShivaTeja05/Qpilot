"""The Prism draft: qPilot's template unless a model's rewording passes every check."""

import json

import pytest

from qpilot.ai.client import ModelClient
from qpilot.ai.prism_draft import draft_prism_project, log_lines
from qpilot.core.pseudonym import Pseudonymiser
from qpilot.core.validator import TOKEN, names_from_result, validate
from qpilot.schemas import Fact
from tests.ai.interpret_helpers import local_client, remote_client


def test_the_template_draft(fixture_result, fixture_cards):
    draft = draft_prism_project(fixture_result, fixture_cards, None)
    assert draft.template_id == "two_groups_log2"
    assert draft.genes == ["ODC1", "BIRC5", "NTRK1", "NM23A"]
    assert not draft.made_by_model and not draft.fallback and draft.validated
    assert draft.test["id"] == "welch_log2" and draft.test["scale"] == "log2_rq"
    assert draft.graph["points"] == "every biological unit"
    assert draft.graph["error_bars"] == "95 % confidence interval"
    assert "{{f_fc_odc1_recommended}}" in draft.caption
    assert "{{f_holds_odc1}}" in draft.caption and "{{f_n_cells}}" in draft.caption
    assert "ODC1: 3.6×" in draft.caption_plain
    names = names_from_result(fixture_result) | set(draft.genes) | {"log2", "MYCN high"}
    for text in (draft.caption, *draft.test["why"]):
        assert validate(text, fixture_result.facts, names).ok, text
    assert draft.robustness["ODC1"] == {
        "holds": "{{f_holds_odc1}}",
        "level": "{{f_level_odc1}}",
        "of_analyses": "{{f_n_cells}}",
    }
    assert draft.routes == {}  # the legacy demo output has no route facts
    payload = draft.payload()
    assert set(payload) >= {"template_id", "genes", "test", "graph", "caption", "facts"}
    assert set(payload["facts"]) == set(TOKEN.findall(json.dumps(payload)))
    assert all(f in fixture_result.facts for f in payload["facts"])


def test_route_facts_and_unknown_genes(fixture_result, fixture_cards):
    facts = dict(fixture_result.facts)
    for route, n in (("ddcq", 4), ("linear_welch", 14), ("linear_student", 21)):
        facts[f"f_n_differ_route_{route}"] = Fact(id=f"f_n_differ_route_{route}", value=n)
        facts[f"f_genes_differ_route_{route}"] = Fact(
            id=f"f_genes_differ_route_{route}", value="CAMTA2, IGSF4"
        )
    result = fixture_result.model_copy(update={"facts": facts})
    draft = draft_prism_project(result, fixture_cards, ["ODC1", "GAPDH"])
    assert draft.genes == ["ODC1"] and "GAPDH" in draft.notes[0]
    assert draft.routes["linear_student"]["n_differ"] == "{{f_n_differ_route_linear_student}}"
    assert any("{{f_n_differ_route_ddcq}}" in w for w in draft.test["why"])
    assert "f_n_differ_route_linear_welch" in draft.fact_ids
    with pytest.raises(ValueError):
        draft_prism_project(result, fixture_cards, ["GAPDH"])
    with pytest.raises(ValueError):
        draft_prism_project(result, fixture_cards, None, template_id="pie_chart")


def test_a_rewording_that_passes_is_used(fixture_result, fixture_cards):
    template = draft_prism_project(fixture_result, fixture_cards, ["ODC1"]).caption

    def reply(system, messages):
        caption = json.loads(messages[0]["content"])["caption"]
        tokens = TOKEN.findall(caption)
        fc, lo, hi, p, holds, cells = ("{{" + t + "}}" for t in tokens)
        return (
            f"Each point is one biological unit (log2 scale); bars show the mean and 95 % "
            f"confidence interval. ODC1 changes {fc} ({lo} to {hi}; Welch's t test, p = {p}) "
            f"and the conclusion holds in {holds} of {cells} reasonable analyses."
        )

    client = local_client(reply)
    draft = draft_prism_project(fixture_result, fixture_cards, ["ODC1"], client=client)
    assert draft.made_by_model and draft.validated and not draft.fallback
    assert draft.caption != template and draft.template_caption == template
    assert len(draft.meta) == 1 and log_lines(draft, client)[0]["purpose"] == "prism_draft"


@pytest.mark.parametrize(
    "bad",
    [
        "ODC1 is 3.6-fold up.",  # a naked number
        "ODC1 changes {{f_fc_odc1_recommended}}.",  # facts dropped
        "{{f_fc_odc1_recommended}} {{f_ci_lo_odc1_recommended}} {{f_ci_hi_odc1_recommended}} "
        "{{f_p_odc1_recommended}} {{f_holds_odc1}} {{f_n_cells}} {{f_n_genes}} for ODC1.",
    ],
)
def test_a_rewording_that_fails_twice_leaves_the_template(fixture_result, fixture_cards, bad):
    client = local_client([bad])
    draft = draft_prism_project(fixture_result, fixture_cards, ["ODC1"], client=client)
    assert not draft.made_by_model and draft.fallback and draft.validated
    assert draft.caption == draft.template_caption
    assert len(client.backend.calls) == 2 and draft.error


def test_no_model_and_a_remote_model_without_pseudonyms(fixture_result, fixture_cards):
    none = draft_prism_project(fixture_result, fixture_cards, None, client=ModelClient())
    assert not none.fallback and not none.made_by_model and none.meta == []
    client = remote_client(["x"])
    remote = draft_prism_project(fixture_result, fixture_cards, None, client=client)
    assert client.backend.calls == [] and remote.fallback and "pseudonymiser" in remote.error


def test_a_remote_model_sees_no_gene_name(fixture_result, fixture_cards, tmp_path):
    pseudonymiser = Pseudonymiser(tmp_path)

    def reply(system, messages):
        return json.loads(messages[0]["content"])["caption"]  # echo: tokens and pseudonyms

    client = remote_client(reply)
    draft = draft_prism_project(
        fixture_result, fixture_cards, ["ODC1", "NTRK1"], client=client, pseudonymiser=pseudonymiser
    )
    sent = json.dumps(client.backend.calls)
    assert "ODC1" not in sent and "NTRK1" not in sent and "MYCN" not in sent
    assert pseudonymiser.pseudonymise("ODC1") in sent
    assert draft.made_by_model and "ODC1" in draft.caption and "NTRK1" in draft.caption


def test_a_remote_model_sees_no_gene_name_in_any_form(fixture_result, fixture_cards, tmp_path):
    from qpilot.ai.prism_draft import private_names
    from qpilot.core.facts import slug

    pseudonymiser = Pseudonymiser(tmp_path)
    genes = ["ODC1", "NTRK1"]

    def reply(system, messages):
        caption = json.loads(messages[0]["content"])["caption"]
        if len(messages) == 1:  # leave a fact and a gene out, so the retry message is sent too
            return " ".join(TOKEN.findall(caption)[1:])
        return caption

    client = remote_client(reply)
    draft = draft_prism_project(
        fixture_result, fixture_cards, genes, client=client, pseudonymiser=pseudonymiser
    )
    assert len(client.backend.calls) == 2 and draft.made_by_model
    sent = json.dumps([c["messages"] for c in client.backend.calls], ensure_ascii=False).lower()
    for name in private_names(fixture_result):
        assert name.lower() not in sent and slug(name) not in sent, name
    assert "{{f_fc_odc1_recommended}}" in draft.caption and "ODC1" in draft.caption
    assert set(TOKEN.findall(draft.caption)) == set(TOKEN.findall(draft.template_caption))
