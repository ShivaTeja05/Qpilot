"""Open Decision Card kinds (gap G3): a registry with validated names; the escalation rule holds."""

import pydantic
import pytest

from qpilot.ai.explain import KIND_TITLE
from qpilot.core import card_kinds as ck
from qpilot.core import robustness as rb
from qpilot.core.decisions import (
    CardSpec,
    OptionSpec,
    apply_decision,
    build_cards,
    effective_level,
    needs_human,
)
from qpilot.schemas import DecisionCard
from tests.core.toy_space import ToySpace

LEGACY = {
    "reference_set": ("Which control genes to normalise to", "refs"),
    "group_cutoff": ("Where to cut the comparison groups", "cut"),
    "undetermined": ("What to do with wells that never amplified", "undetermined"),
    "amp_call": ("Which curves count as amplified", "amp_call"),
}

# Kinds registered by these tests live in their own namespace (the registry is process-wide).
ck.register_card_kind("testonly.plain", "A test kind", "testonly")
ck.register_card_kind("testonly.strict", "A test kind people decide", "testonly", always_human=True)


def _card(kind: str, **impact) -> DecisionCard:
    return DecisionCard(
        id="card_x",
        kind=kind,
        rank=1,
        impact={"flips": False, "n_genes_flipped": 0, "max_delta_log2fc": 0.0} | impact,
        evidence={},
        options=[],
        recommended="keep",
        rationale_template="t",
        facts=[],
    )


def _spec(kind: str, dimension: str = "b") -> CardSpec:
    return CardSpec(
        card_id="card_k",
        kind=kind,
        dimension=dimension,
        options=[
            OptionSpec(id="x", label="X", value="x"),
            OptionSpec(id="y", label="Y", value="y"),
        ],
        recommended="x",
        rationale_template="t",
    )


def test_the_original_four_kinds_keep_their_titles_and_dimensions():
    for name, (title, dimension) in LEGACY.items():
        kind = ck.card_kind(name)
        assert (kind.title, kind.dimension, kind.always_human) == (title, dimension, False)
        assert KIND_TITLE[name] == title == ck.kind_title(name)
        assert not ck.requires_human(name)


def test_kind_titles_view_is_live_and_falls_back():
    assert KIND_TITLE.get("testonly.plain") == "A test kind"
    assert KIND_TITLE.get("never_registered", "never_registered") == "never_registered"
    assert ck.kind_title("never_registered") == "never registered"
    assert [k.name for k in ck.registered_kinds()] == sorted(k.name for k in ck.registered_kinds())


@pytest.mark.parametrize("name", ["gate", "gate.rule", "efficiency_model", "a1", "trust.import_v2"])
def test_well_spelt_kinds_load_even_when_unregistered(name):
    assert _card(name).kind == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "Gate",
        "gate rule",
        "gate..rule",
        "a.b.c",
        "1gate",
        "_gate",
        "gate-rule",
        "<b>x</b>",
        "gate.",
        ".gate",
        "x" * 65,
        "ünïcode",
        "gate\n",
    ],
)
def test_misspelt_kinds_are_refused_on_load_and_on_registration(name):
    with pytest.raises(pydantic.ValidationError):
        _card(name)
    with pytest.raises(ck.CardKindError):
        ck.register_card_kind(name, "title", "testonly")


def test_registration_is_idempotent_and_conflicts_are_refused():
    again = ck.register_card_kind("testonly.plain", "A test kind", "testonly")
    assert again is ck.card_kind("testonly.plain")
    with pytest.raises(ck.CardKindError, match="different definition"):
        ck.register_card_kind("testonly.plain", "Another meaning", "testonly")
    with pytest.raises(ck.CardKindError, match="different definition"):
        ck.register_card_kind("reference_set", "Which control genes", "qpcr", dimension="refs")
    with pytest.raises(ck.CardKindError):
        ck.register_card_kind("testonly.untitled", "   ", "testonly")
    with pytest.raises(ck.CardKindError):
        ck.register_card_kind("testonly.owner", "t", "Not An Owner")


def test_building_a_card_needs_a_registered_kind():
    assert _spec("testonly.plain").kind == "testonly.plain"
    with pytest.raises(pydantic.ValidationError, match="not registered"):
        _spec("testonly.nobody_registered_this")
    with pytest.raises(ck.CardKindError, match="not registered"):
        ck.card_kind("testonly.nobody_registered_this")


def test_escalation_ignores_the_kind_when_a_card_flips():
    for kind in ["testonly.plain", "reference_set", "testonly.strict", "unknown_kind"]:
        assert needs_human(_card(kind, flips=True))
        assert needs_human(_card(kind, flips_anywhere=True))


def test_a_kind_can_only_make_the_rule_stricter():
    assert not needs_human(_card("testonly.plain"))  # unchanged behaviour for ordinary kinds
    assert not needs_human(_card("amp_call"))
    assert needs_human(_card("testonly.strict"))  # always human
    assert needs_human(_card("from_a_newer_build"))  # unknown here: fail closed
    assert ck.requires_human("from_a_newer_build")
    assert effective_level("decide_and_tell", {"flips": False}, always_human=True) == "suggest"
    assert effective_level("automatic", {"flips": False}, always_human=True) == "suggest"
    assert effective_level("teach", {"flips": False}, always_human=True) == "teach"
    assert effective_level("decide_and_tell", {"flips": False}) == "decide_and_tell"


def _built(kind: str) -> DecisionCard:
    space = ToySpace()
    summary = rb.summary(rb.run_grid(space), space)
    for s in summary.values():
        s.impact["b"]["flips"] = False  # nothing flips at the recommended settings
    (card,) = build_cards(space, summary, [_spec(kind)], ["g1"], "decide_and_tell")
    return card


def test_an_always_human_kind_is_never_auto_decided():
    plain, strict = _built("testonly.plain"), _built("testonly.strict")
    assert plain.status == "auto_decided" and plain.effective_autonomy == "decide_and_tell"
    assert strict.status == "open" and strict.decision is None
    assert strict.effective_autonomy == "suggest"


def test_an_agent_on_an_always_human_card_gets_pending_human(store, fixture_result):
    card = _card("testonly.strict").model_copy(
        update={"id": "card_strict", "options": [], "recommended": "keep"}
    )
    plain = _card("testonly.plain").model_copy(update={"id": "card_plain"})
    from qpilot.schemas import CardOption

    keep = CardOption(id="keep", label="Keep", per_gene={})
    store.put(
        fixture_result,
        [card.model_copy(update={"options": [keep]}), plain.model_copy(update={"options": [keep]})],
    )
    sid = fixture_result.study_id
    out = apply_decision(store, sid, "card_strict", "keep", "looks fine", "agent")
    assert out.status == "pending_human"
    assert apply_decision(store, sid, "card_plain", "keep", "fine", "agent").status == "applied"
    human = apply_decision(store, sid, "card_strict", "keep", "I checked the wells", "human")
    assert human.status == "applied" and human.card.decided_by == "human"


def test_existing_records_load_unchanged(fixture_cards):
    assert {c.kind for c in fixture_cards} <= set(LEGACY)
    for card in fixture_cards:
        assert DecisionCard.model_validate(card.model_dump(mode="json")) == card


EMITTED = {
    *LEGACY,
    "numbers.efficiency_model",
    "capture.import_trust",
    "gate.rule",
    "gate.invalidate_plate",
}


@pytest.mark.parametrize("module", ["qpilot.mcp_server", "qpilot.qpcr.study", "qpilot.qpcr.plan"])
def test_every_kind_is_registered_whichever_module_a_process_imports(module):
    import subprocess
    import sys

    code = (
        f"import {module}\n"
        "from qpilot.core.card_kinds import registered_kinds\n"
        "print(' '.join(k.name for k in registered_kinds()))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert EMITTED <= set(out.stdout.split())


def test_gate_and_capture_kinds():
    import qpilot.qpcr  # noqa: F401  (registers the plugin's kinds)

    assert ck.card_kind("gate.invalidate_plate").always_human
    assert not ck.card_kind("gate.rule").always_human
    assert ck.card_kind("capture.import_trust").always_human
    assert ck.card_kind("numbers.efficiency_model").dimension == "efficiency"
