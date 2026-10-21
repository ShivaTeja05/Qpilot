"""Typed refusals: every reply that does not do what an agent asked says why, in a stable code.

A refusal carries ``error`` (one plain sentence), ``code`` (:class:`qpilot.agents.refusals.Code`)
and ``fix``, and the MCP server marks it ``isError``. A request that waits for a person is not a
refusal: it was recorded, and its ``code`` says why it waits. The human-only rule is unchanged: a
card that can flip a conclusion comes back ``pending_human`` to an agent at every autonomy level.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import anyio
import pytest

from qpilot.agents.outputs import DecideOut, Refusal
from qpilot.agents.refusals import REFUSALS, Code, is_error, table
from qpilot.core.store import StudyStore
from qpilot.integration.mcp_tools import SimulatorTools
from qpilot.mcp_server import QpilotTools, _studio_refusal, create_server
from qpilot.studio_service import StudioError

ROOT = Path(__file__).resolve().parents[2]


def assert_refusal(out: dict, code: str, field: str | None = None) -> None:
    """``out`` is a refusal with ``code``: one plain sentence, the code's fix, the right field."""
    assert is_error(out), out
    Refusal.model_validate(out)
    assert out["code"] == code, out
    assert out["error"].strip() and "\n" not in out["error"]
    assert out["fix"] == REFUSALS[Code(code)].fix
    if field is not None:
        assert out.get("field") == field, out
    json.dumps(out, allow_nan=False)


# ---- the codes ----------------------------------------------------------------------------------


def test_every_code_has_a_meaning_and_a_fix_an_agent_can_repeat():
    assert set(REFUSALS) == set(Code)
    rows = table()
    assert [r["code"] for r in rows] == [c.value for c in Code]
    for row in rows:
        assert row["meaning"].endswith(".") and row["fix"].endswith(".")
        assert not re.search(r"\d", row["fix"]), row  # prose only: numbers live in fields


def test_the_codes_are_a_stable_contract():
    """Codes are never renamed or reused; new ones are only added at the end."""
    published = [
        "needs_human_decision",
        "autonomy_forbids",
        "stale_head",
        "proposal_refused",
        "human_only",
        "results_hidden",
        "path_not_allowed",
        "unsupported_input",
        "input_unreadable",
        "unknown_study",
        "unknown_item",
        "invalid_argument",
        "idempotency_key_reused",
        "integrity_failed",
        "not_installed",
        "not_ready",
        "not_applicable",
        "engine_refused",
    ]
    assert [c.value for c in Code][: len(published)] == published


# ---- every tool's refusals, as plain methods ----------------------------------------------------

CASES = [
    pytest.param(
        lambda t, s, r, i: t.qpcr_study("/etc/hosts"),
        "path_not_allowed",
        "rdml_path",
        id="study outside the roots",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_study(str(r / "no.rdml")),
        "path_not_allowed",
        "rdml_path",
        id="study missing file",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_study(""), "invalid_argument", "rdml_path", id="study no path"
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_study(str(r / "notes.txt")),
        "unsupported_input",
        "rdml_path",
        id="study not an export",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_study(str(r / "demo.rdml"), {"x": 1}),
        "invalid_argument",
        "design",
        id="study bad design",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_study(str(r / "demo.rdml"), {"session": "abcdef123456"}),
        "unknown_study",
        None,
        id="study unknown session",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_study(str(r / "demo.rdml"), response_format="short"),
        "invalid_argument",
        "response_format",
        id="study bad format",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_robustness("abcdef123456", "ODC1"),
        "unknown_study",
        None,
        id="robustness unknown study",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_robustness("../../etc", "ODC1"),
        "unknown_study",
        None,
        id="robustness bad id",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_robustness(i, "GAPDH"),
        "unknown_item",
        "gene",
        id="robustness unknown gene",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_decide(i, "card_refset", "top3", "x", actor="human"),
        "human_only",
        "actor",
        id="decide as a person",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_decide(i, "card_nope", "top3", "x"),
        "unknown_item",
        "card_id",
        id="decide unknown card",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_decide(i, "card_refset", "nope", "x"),
        "unknown_item",
        "option",
        id="decide unknown option",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_decide(i, "card_refset", "top3", "  "),
        "invalid_argument",
        "reason",
        id="decide no reason",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_decide("abcdef123456", "card_refset", "top3", "x"),
        "unknown_study",
        None,
        id="decide unknown study",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_decide(i, "card_refset", "top3", "x", expected_head=3),
        "invalid_argument",
        "expected_head",
        id="decide bad head",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_plan(fc=1), "invalid_argument", None, id="plan impossible"
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_propose(i, "design.anything", "S1", {}),
        "invalid_argument",
        "kind",
        id="propose unknown kind",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_propose(i, "stage.confirm", "design", {}),
        "human_only",
        "kind",
        id="propose a stage confirm",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_propose("abcdef123456", "design.group", "S1", {"group": "x"}),
        "unknown_study",
        None,
        id="propose unknown study",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_propose(i, "design.group", "S1", {"group": "x"}, level="Certain"),
        "invalid_argument",
        None,
        id="propose malformed",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_proposals(i, status="pending_human"),
        "invalid_argument",
        "status",
        id="proposals bad status",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_proposals("abcdef123456"),
        "unknown_study",
        None,
        id="proposals unknown study",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_inspect("/etc/hosts"),
        "path_not_allowed",
        "rdml_path",
        id="inspect outside the roots",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_inspect(str(r / "demo.rdml"), str(r / "notes.txt")),
        "unsupported_input",
        "sheet_path",
        id="inspect a sheet of the wrong kind",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_inspect(str(r / "demo.rdml")),
        "input_unreadable",
        None,
        id="inspect an unreadable file",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_check_design(i, "design.anything", "S1", {}),
        "invalid_argument",
        "kind",
        id="check unknown kind",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_check_design(
            "abcdef123456", "design.group", "S1", {"group": "x"}
        ),
        "unknown_study",
        None,
        id="check unknown session",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_curve_calls("abcdef123456", "ODC1"),
        "unknown_study",
        None,
        id="curve calls unknown session",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_prism_preview("abcdef123456"),
        "unknown_study",
        None,
        id="prism preview unknown study",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_prism_diff(i, "/etc", str(r)),
        "path_not_allowed",
        "bundle_dir",
        id="prism diff outside the roots",
    ),
    pytest.param(
        lambda t, s, r, i: t.qpcr_prism_diff(i, str(r), str(r / "notes.txt")),
        "unsupported_input",
        "sent_back_dir",
        id="prism diff not a folder",
    ),
    pytest.param(
        lambda t, s, r, i: s.sim_audit("abcdef123456"),
        "unknown_study",
        None,
        id="sim audit unknown study",
    ),
    pytest.param(
        lambda t, s, r, i: s.sim_audit(i), "not_ready", None, id="sim audit not written yet"
    ),
    pytest.param(
        lambda t, s, r, i: s.sim_gene(i, "ODC1"), "not_ready", None, id="sim gene not written yet"
    ),
    pytest.param(
        lambda t, s, r, i: s.sim_decisions(i), "not_ready", None, id="sim decisions not written yet"
    ),
    pytest.param(
        lambda t, s, r, i: s.sim_whatif(i, {"refs": 3}),
        "invalid_argument",
        "changes",
        id="sim whatif bad changes",
    ),
    pytest.param(
        lambda t, s, r, i: s.sim_findings(i, table="secrets"),
        "invalid_argument",
        "table",
        id="sim findings bad table",
    ),
    pytest.param(
        lambda t, s, r, i: s.sim_findings(i, limit=0),
        "invalid_argument",
        "limit",
        id="sim findings bad page",
    ),
    pytest.param(
        lambda t, s, r, i: s.sim_audit(i, response_format="short"),
        "invalid_argument",
        "response_format",
        id="sim bad format",
    ),
]


@pytest.fixture
def world(tools, store, demo, data_root):
    (data_root / "notes.txt").write_text("not a qPCR file\n", encoding="utf-8")
    return tools, SimulatorTools(store), data_root, demo[1]


@pytest.mark.parametrize(("case", "code", "field"), CASES)
def test_every_refusal_has_an_error_a_code_and_a_fix(world, case, code, field):
    tools, sim, root, study_id = world
    before = sorted(p.relative_to(tools.store.root) for p in tools.store.root.rglob("*.jsonl"))
    assert_refusal(case(tools, sim, root, study_id), code, field)
    after = sorted(p.relative_to(tools.store.root) for p in tools.store.root.rglob("*.jsonl"))
    assert after == before  # a refusal records nothing: no log, no request, no inbox


def test_a_stale_request_is_a_refusal_that_keeps_its_status(tools, demo):
    _, study_id = demo
    out = tools.qpcr_decide(study_id, "card_undetermined", "cap", "try", expected_head="0" * 64)
    assert_refusal(out, "stale_head")
    assert out["status"] == "stale" and out["applied"] is False and out["error"] == out["reason"]
    assert out["chain_head"] == tools.store.chain_head(study_id)  # the head to retry with
    DecideOut.model_validate(out)


def test_a_proposal_the_rules_refuse_is_a_refusal_that_keeps_its_status(tools, demo):
    _, study_id = demo
    out = tools.qpcr_propose(study_id, "design.group", "S1", {"group": "x" * 3000})
    assert_refusal(out, "proposal_refused")
    assert out["status"] == "refused" and out["error"] == out["reason"]
    assert tools.qpcr_proposals(study_id)["proposals"] == []


# ---- the human-only rule, unchanged -------------------------------------------------------------


@pytest.mark.parametrize("autonomy", ["suggest", "decide_and_tell"])
def test_a_card_that_can_flip_a_conclusion_waits_for_a_person(tools, demo, autonomy):
    _, study_id = demo
    tools.store.set_autonomy(study_id, autonomy)
    before = tools.store.card(study_id, "card_refset")
    out = tools.qpcr_decide(study_id, "card_refset", "hmbs_alone", "HMBS is the most stable")
    assert out["status"] == "pending_human" and out["applied"] is False
    assert out["code"] == "needs_human_decision" and out["card"]["needs_human"] is True
    assert not is_error(out)  # recorded: it waits in the person's queue
    DecideOut.model_validate(out)
    after = tools.store.card(study_id, "card_refset")
    assert (after.decision, after.decided_by) == (before.decision, before.decided_by)
    assert [(p.card_id, p.actor) for p in tools.store.pending(study_id)] == [
        ("card_refset", "agent")
    ]


def test_suggest_mode_holds_even_a_choice_that_changes_no_conclusion(tools, demo):
    _, study_id = demo
    out = tools.qpcr_decide(study_id, "card_undetermined", "cap", "try cap")
    assert (out["status"], out["code"]) == ("pending_human", "autonomy_forbids")
    tools.store.set_autonomy(study_id, "decide_and_tell")
    applied = tools.qpcr_decide(study_id, "card_undetermined", "cap", "try cap")
    assert applied["status"] == "applied" and applied["applied"] is True
    assert "code" not in applied and applied["card"]["decided_by"] == "agent"


def test_over_mcp_a_waiting_request_is_not_an_error_and_a_refusal_is(store, demo):
    _, study_id = demo
    server = create_server(store, simulator=False)
    wait = anyio.run(
        server.call_tool,
        "qpcr_decide",
        {"study_id": study_id, "card_id": "card_refset", "option": "top3", "reason": "x"},
    )
    assert wait.is_error is False and wait.structured_content["code"] == "needs_human_decision"
    refused = anyio.run(
        server.call_tool,
        "qpcr_decide",
        {"study_id": study_id, "card_id": "card_refset", "option": "top3", "reason": "x",
         "actor": "human"},
    )  # fmt: skip
    assert refused.is_error is True
    assert json.loads(refused.content[0].text) == refused.structured_content
    assert_refusal(refused.structured_content, "human_only", "actor")


# ---- refusals the MCP layer adds -----------------------------------------------------------------


def test_arguments_that_fail_the_input_schema_are_named_never_echoed(served, demo):
    _, study_id = demo
    out = served("qpcr_robustness", {"study_id": "SECRET-VALUE-42", "gene": ["SECRET-GENE"]})
    assert out.is_error is True
    assert_refusal(out.structured_content, "invalid_argument")
    assert out.structured_content["fields"] == ["gene"]
    assert "SECRET" not in out.content[0].text
    missing = served("qpcr_decide", {"study_id": study_id})
    assert missing.structured_content["fields"] == ["card_id", "option", "reason"]


def test_a_tool_that_fails_unexpectedly_says_so_without_its_details(store, monkeypatch):
    def boom(self, fc: float = 2.0) -> dict:
        raise RuntimeError("secret detail from inside the engine")

    monkeypatch.setattr(QpilotTools, "qpcr_plan", boom)
    out = anyio.run(create_server(store, simulator=False).call_tool, "qpcr_plan", {"fc": 2.0})
    assert out.is_error is True
    assert_refusal(out.structured_content, "engine_refused")
    assert "secret detail" not in out.content[0].text


# ---- qPilot Studio's sentences, each with its code ----------------------------------------------

STUDIO_SENTENCES = [
    ("only a person can confirm a stage", "human_only"),
    (
        "this session was already opened with its own sample sheet (or none); only a person can "
        "change it, in qPilot Studio",
        "human_only",
    ),
    ("the input file is missing or has changed since it was opened", "integrity_failed"),
    ("the sample sheet is missing or has changed since it was opened", "integrity_failed"),
    ("confirm the design first: the curves stage follows it", "results_hidden"),
    ("confirm the design and the curves first: results stay hidden", "results_hidden"),
    ("confirm the analysis choices first: the Prism draft follows them", "not_ready"),
    ("confirm the analysis choices first", "not_ready"),
    ("accept the Prism project for this analysis first", "not_ready"),
    ("decide every analysis choice first (still open: card_refset)", "not_ready"),
    ("the design cannot be confirmed yet: no comparison yet", "not_ready"),
    ("the curves stage is not open yet", "not_ready"),
    ("the design stage still has proposals waiting for a decision", "not_ready"),
    ("no confirm step for stage 'roundtrip'", "not_ready"),
    ("no well of this target in the analysed experiment", "unknown_item"),
    ("no curve for this well in the analysed experiment", "unknown_item"),
    ("this bundle was not sent to Prism from this session", "invalid_argument"),
    ("these wells are already left out of the analysis", "invalid_argument"),
    ("nothing to decide: none of these wells is in the analysis", "invalid_argument"),
    ("there is no further choice called 'efficiency' to test", "unknown_item"),
    ("this choice is already tested in the current analysis", "invalid_argument"),
    ("no other option of this choice applies to this study (one run)", "not_applicable"),
    ("this is already the decision on the Import Trust card", "invalid_argument"),
    (
        "this study's curves call for no Import Trust card: they are raw, normalised to a "
        "passive reference, or were not opened from an instrument export",
        "not_applicable",
    ),
    (
        "the export has no Cq values from the instrument, so it cannot be analysed without its "
        "curves",
        "not_applicable",
    ),
    ("a sentence qPilot Studio does not say yet", "engine_refused"),
]


@pytest.mark.parametrize(("sentence", "code"), STUDIO_SENTENCES)
def test_each_studio_sentence_has_its_code(sentence, code):
    out = _studio_refusal(StudioError(sentence))
    assert_refusal(out, code)
    assert out["error"] == sentence


def test_every_sentence_qpilot_studio_refuses_with_has_a_code():
    """A new ``raise StudioError("...")`` must be given a code here, not fall to engine_refused."""
    source = (ROOT / "qpilot" / "studio_service.py").read_text(encoding="utf-8")
    found = re.findall(r'raise StudioError\(\s*f?"([^"]+)"', source)
    assert len(found) >= 15
    for literal in found:
        sentence = re.sub(r"\{[^}]*\}", "design", literal)
        assert _studio_refusal(StudioError(sentence))["code"] != "engine_refused", sentence


def test_an_unknown_session_is_an_unknown_study(tmp_studies_dir):
    from qpilot.core.store import StudyNotFound

    assert_refusal(_studio_refusal(StudyNotFound("x")), "unknown_study")
    assert StudyStore(tmp_studies_dir).list_studies() == []
