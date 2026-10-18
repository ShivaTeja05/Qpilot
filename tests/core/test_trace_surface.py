"""Trace and the Spreadsheet Check on every surface: CLI, MCP tools and Ask your data."""

import json
import time

import anyio
import pytest

from qpilot.ai.ask import ADDRESS_FACT, HIDDEN_ADDRESS, _Context, answer_facts, ask, route
from qpilot.ai.ask import template_answer as answer_template
from qpilot.ai.client import MockBackend, ModelClient, NoneBackend
from qpilot.cli import build_parser, main
from qpilot.core.store import StudyStore, sha256_file
from qpilot.core.validator import render_tokens, validate
from qpilot.core.vocabulary import banned_words
from qpilot.mcp_server import (
    MAX_TRACE_TOP,
    TOOL_META,
    TOOL_NAMES,
    TRACE_ROOT,
    UNKNOWN_STUDY,
    QpilotTools,
    create_server,
)
from qpilot.qpcr.sheetcheck import MAPPING_CONFIRMED, MAPPING_GUESSED
from tests.conftest import DEMO_RDML
from tests.engine.test_sheetcheck import clean_sheet

NEW_TOOLS = ("qpcr_trace", "qpcr_check_sheet")


def _code(argv):
    try:
        return main(argv)
    except SystemExit as err:  # argparse and _fail exit through SystemExit
        return err.code


def _sub(parser, name):
    return parser._subparsers._group_actions[0].choices[name]


def _none_client():
    return ModelClient(backend=NoneBackend())


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    return root


@pytest.fixture
def demo(data_root, tmp_studies_dir, fixture_result, fixture_cards):
    """The fixture study under a fake RDML file inside the data root (as the sweep uses it)."""
    rdml = data_root / "demo.rdml"
    rdml.write_bytes(b"<rdml>fixture stand-in for trace tools</rdml>")
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    StudyStore(tmp_studies_dir).put(result, fixture_cards)
    return rdml, result.study_id


@pytest.fixture
def tools(tmp_studies_dir):
    return QpilotTools(StudyStore(tmp_studies_dir))


def _state(store, study_id):
    workspace = store.workspace(study_id)
    return (
        (workspace / "results.json").read_bytes(),
        (workspace / "cards.json").read_bytes(),
        store.chain_head(study_id),
        [(p.card_id, p.option) for p in store.pending(study_id)],
    )


# ---- CLI -----------------------------------------------------------------------------------------


def test_trace_and_check_are_registered_and_cannot_decide():
    parser = build_parser()
    names = set(parser._subparsers._group_actions[0].choices)
    assert {"trace", "check"} <= names
    check = _sub(parser, "check")
    assert next(a for a in check._actions if a.dest == "what").choices == ["sheet"]
    trace = _sub(parser, "trace")
    options = {o for a in trace._actions for o in a.option_strings}
    assert {"--gene", "--sample", "--well", "--top", "--json"} <= options
    for forbidden in ("--decide", "--set-aside", "--apply", "--open-card"):
        assert forbidden not in options


def test_cli_trace_needs_exactly_one_root(store, study):
    assert _code(["trace"]) == 2
    assert _code(["trace", "--gene", "ODC1", "--sample", "2016"]) == 2


def test_cli_trace_without_the_input_file_is_refused(store, study, capsys):
    before = _state(store, study)
    assert _code(["trace", "--gene", "CAMTA2"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("qpilot trace:") and "input file" in err
    assert _code(["trace", "abcdef123456", "--well", "HMBS_20080318:K22"]) == 2
    assert _code(["trace", study, "--gene", "CAMTA2", "--json"]) == 2
    assert _state(store, study) == before


def test_cli_check_sheet_marks_the_guess_and_never_edits(tmp_path, tmp_studies_dir, capsys):
    sheet = clean_sheet(tmp_path)
    raw = sheet.read_bytes()
    assert main(["check", "sheet", str(sheet)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"Column mapping ({MAPPING_GUESSED}; wide sheet):")
    assert "  A: sample (from the header)" in out and "Not confirmed" in out
    assert "10 of 10 fold changes reproduce" in out and "never edited" in out
    assert main(["check", "sheet", str(sheet), "--confirm"]) == 0
    out = capsys.readouterr().out
    assert MAPPING_CONFIRMED in out and "Not confirmed" not in out
    assert main(["check", "sheet", str(sheet), "--json"]) == 0
    first = capsys.readouterr().out
    assert main(["check", "sheet", str(sheet), "--json"]) == 0
    assert capsys.readouterr().out == first  # byte-stable
    data = json.loads(first)
    assert data["mapping_status"] == MAPPING_GUESSED and data["mapping"]["confirmed"] is False
    assert sheet.read_bytes() == raw


def test_cli_check_sheet_map_sets_a_column_and_confirms(tmp_path, tmp_studies_dir, capsys):
    sheet = clean_sheet(tmp_path)
    assert main(["check", "sheet", str(sheet), "--map", "f=ignored", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    column = next(c for c in data["mapping"]["columns"] if c["column"] == "F")
    assert (column["role"], column["basis"]) == ("ignored", "user")
    assert data["mapping"]["confirmed"] is True and data["mapping_status"] == MAPPING_CONFIRMED
    assert main(["check", "sheet", str(sheet), "--map", "C=cq:GAPDH"]) == 0
    assert "  C: cq GAPDH (set by you)" in capsys.readouterr().out
    for bad in ("F=bogus", "F", "1=cq", "=cq"):
        assert _code(["check", "sheet", str(sheet), "--map", bad]) == 2
    assert "--map takes COL=ROLE" in capsys.readouterr().err


def test_cli_check_sheet_against_a_study_and_refusals(store, study, tmp_path, capsys):
    sheet = clean_sheet(tmp_path)
    assert main(["check", "sheet", str(sheet), "--study", study]) == 0
    assert "never edited" in capsys.readouterr().out
    assert _code(["check", "sheet", str(sheet), "--study", "abcdef123456"]) == 2
    assert _code(["check", "sheet", str(tmp_path / "missing.csv")]) == 2
    old = tmp_path / "old.xls"
    old.write_bytes(b"\xd0\xcf\x11\xe0 not a workbook")
    assert _code(["check", "sheet", str(old)]) == 2
    assert capsys.readouterr().err.startswith("qpilot check sheet:")


# ---- MCP -----------------------------------------------------------------------------------------


def test_trace_and_sheet_tools_are_registered_read_only(tmp_studies_dir):
    assert set(NEW_TOOLS) <= set(TOOL_NAMES) and set(TOOL_META) == set(TOOL_NAMES)
    listed = {t.name: t for t in anyio.run(create_server(StudyStore(tmp_studies_dir)).list_tools)}
    for name in NEW_TOOLS:
        assert TOOL_META[name][1] == "read"
        ann = listed[name].annotations
        assert ann.read_only_hint is True and ann.destructive_hint is False
        assert ann.open_world_hint is False and listed[name].title == TOOL_META[name][0]


def test_qpcr_trace_answers_errors_fast_on_the_fixture_study(tools, demo):
    _, study_id = demo
    before = _state(tools.store, study_id)
    start = time.perf_counter()
    out = tools.qpcr_trace(study_id, gene="CAMTA2")
    assert "input file" in out["error"]
    for kwargs in ({}, {"gene": "CAMTA2", "sample": "2016"}, {"gene": ""}, {"gene": {"a": 1}},
                   {"well": ["HMBS_20080318:K22"]}, {"sample": True}):  # fmt: skip
        assert tools.qpcr_trace(study_id, **kwargs) == {"error": TRACE_ROOT}, kwargs
    for top in (0, MAX_TRACE_TOP + 1, True, "3", 2.5, None):
        assert "top must be" in tools.qpcr_trace(study_id, gene="CAMTA2", top=top)["error"]
    for sid in ("abcdef123456", "../../etc", None, {"actor": "human"}):
        assert tools.qpcr_trace(sid, gene="CAMTA2") == {"error": UNKNOWN_STUDY}
    out = tools.qpcr_trace(study_id, well="HMBS_20080318:K22", top=MAX_TRACE_TOP)
    json.dumps(out)
    assert set(out) == {"error"}
    assert time.perf_counter() - start < 5  # no curve analysis on a fake input file
    assert _state(tools.store, study_id) == before


def test_qpcr_check_sheet_guesses_the_mapping_and_never_confirms(tools, demo, data_root, tmp_path):
    _, study_id = demo
    sheet = clean_sheet(data_root)
    raw = sheet.read_bytes()
    out = tools.qpcr_check_sheet(str(sheet))
    json.dumps(out)
    assert "error" not in out and out["saved"] is False
    assert out["confirmed"] is False and out["mapping_status"] == MAPPING_GUESSED
    assert out["mapping"]["confirmed"] is False and "--confirm" in out["next"]
    assert out["summary"]["n_reproduced"] == out["summary"]["n_fold_changes"] == 10
    assert out["text"].startswith(f"Column mapping: {MAPPING_GUESSED}.")
    assert "mouse-c1" not in json.dumps(out) and "vehicle" not in json.dumps(out)  # no labels
    with_study = tools.qpcr_check_sheet(str(sheet), study_id)
    assert "error" not in with_study and with_study["confirmed"] is False
    assert sheet.read_bytes() == raw
    outside = clean_sheet(tmp_path, name="outside.csv")
    assert "outside" in tools.qpcr_check_sheet(str(outside))["error"]
    assert "not an .xlsx" in tools.qpcr_check_sheet(str(demo[0]))["error"]
    assert "error" in tools.qpcr_check_sheet({"path": str(sheet)})
    assert "error" in tools.qpcr_check_sheet(str(sheet), ["x"])
    assert tools.qpcr_check_sheet(str(sheet), "abcdef123456") == {"error": UNKNOWN_STUDY}
    bad = data_root / "bad.csv"
    bad.write_text("nothing,to,see\n1,2,3\n", encoding="utf-8")
    assert tools.qpcr_check_sheet(str(bad))["error"].startswith("could not check this sheet")


# ---- Ask your data -------------------------------------------------------------------------------


def test_ask_routes_trace_questions(store, study):
    ctx = _Context(store, study)
    assert route(ctx, "Why is CAMTA2 no call?") == ("qpcr_trace", {"gene": "CAMTA2"})
    assert route(ctx, "Where should I look for CAMTA2?") == ("qpcr_trace", {"gene": "CAMTA2"})
    assert route(ctx, "what should I check for camta2") == ("qpcr_trace", {"gene": "CAMTA2"})
    assert route(ctx, "trace HMBS_20080318:K22") == (
        "qpcr_trace",
        {"well": "HMBS_20080318:K22"},
    )
    assert route(ctx, "Trace UBC(2)_20080220/O13 please") == (
        "qpcr_trace",
        {"well": "UBC(2)_20080220:O13"},
    )
    assert route(ctx, "Trace sample 2016") == ("qpcr_trace", {"sample": "2016"})
    assert route(ctx, "Where should I look?") == ("qpcr_trace", {})
    assert route(ctx, "trace TP53")[0] == "none"
    # the routing that was there before is unchanged
    assert route(ctx, "is odc1 up?") == ("qpcr_robustness", {"gene": "ODC1"})
    assert route(ctx, "Is ODC1 robust if HMBS is used?")[0] == "qpcr_robustness"
    assert route(ctx, "Why is ODC1 up if HMBS is used?")[0] == "qpcr_robustness"
    assert route(ctx, "How many plates are there?") == ("qpcr_study", {})
    assert route(ctx, "use SDHA(1) alone please")[0] == "qpcr_decide"
    assert route(ctx, "Why shouldn't I use HMBS alone?")[0] not in ("qpcr_decide", "qpcr_trace")


def test_ask_trace_without_the_input_file_answers_in_fixed_words(store, study):
    before = _state(store, study)
    for question in ("Why is CAMTA2 no call?", "Where should I look?", "trace sample 2016"):
        out = ask(question, store, study, client=_none_client(), log=False)
        assert out.tool_calls[0]["tool"] == "qpcr_trace" and out.validated, question
        assert out.plain.startswith("qPilot could not trace that")
        assert not any(ch.isnumeric() for ch in out.plain)
    assert _state(store, study) == before


def _trace_out():
    """A qpcr_trace answer shaped like the demo's CAMTA2 trace (top place only)."""
    place = {
        "sample": "2016",
        "plate": "HMBS_20080318",
        "well": "K22",
        "target": "HMBS",
        "checks": ["S1"],
        "fold_off": 5.5523342332,
        "feeds": 58,
        "consequence": "changes_call",
    }
    return {
        "root": {"kind": "gene", "id": "CAMTA2"},
        "answer": "place_to_look",
        "places": [place, {**place, "sample": "1924", "plate": None, "well": None}],
        "summary": {"call": "none", "n_more": 12},
    }


def test_the_trace_answer_is_tokens_only(store, study):
    ctx = _Context(store, study)
    out = _trace_out()
    view, facts = answer_facts(ctx, "qpcr_trace", out)
    assert "2016" not in json.dumps(view) and "K22" not in json.dumps(view)
    text = answer_template(ctx, "qpcr_trace", out, view)
    all_facts = {**ctx.result.facts, **facts}
    assert validate(text, all_facts, ctx.names).ok
    plain = render_tokens(text, all_facts)
    assert plain.startswith("Trace for CAMTA2 (no call). Where to look first: sample 2016, ")
    assert "plate HMBS_20080318, well K22: changes the call" in plain
    assert "Then sample 1924: changes the call" in plain and "decision for a person" in plain
    assert banned_words(plain) == []
    addresses = [f for f in facts if ADDRESS_FACT.match(f)]
    assert {"f_ans_trace_1_sample", "f_ans_trace_1_plate", "f_ans_trace_1_well"} <= set(addresses)
    for answer in ("nothing_to_look_at", "choice_to_look_at", "absent"):
        empty = {**out, "answer": answer, "places": [], "summary": {"call": "up"}}
        view, facts = answer_facts(ctx, "qpcr_trace", empty)
        text = answer_template(ctx, "qpcr_trace", empty, view)
        assert validate(text, {**ctx.result.facts, **facts}, ctx.names).ok
        assert banned_words(text) == [] and "{{" not in text
    sample = {**out, "root": {"kind": "sample", "id": "2016"}}
    view, facts = answer_facts(ctx, "qpcr_trace", sample)
    text = answer_template(ctx, "qpcr_trace", sample, view)
    assert text.startswith("Trace for sample {{f_ans_trace_root}}.")
    assert validate(text, {**ctx.result.facts, **facts}, ctx.names).ok


# ---- the demo study ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_store(tmp_path_factory):
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    store = StudyStore(tmp_path_factory.mktemp("studies"))
    return store, store.ensure_study(DEMO_RDML)


@pytest.mark.demo_data
def test_demo_qpcr_trace_camta2_ranks_2016_k22_first(demo_store):
    store, sid = demo_store
    out = QpilotTools(store).qpcr_trace(sid, gene="CAMTA2")
    assert "error" not in out and out["saved"] is False and out["study_id"] == sid
    first = out["places"][0]
    assert (first["sample"], first["plate"], first["well"]) == ("2016", "HMBS_20080318", "K22")
    assert first["consequence"] == "changes_call" and first["feeds"] == 58
    assert [p["sample"] for p in out["places"]] == ["2016", "1924", "1772"]
    assert "nodes" not in out and len(out["places"]) == 3
    assert out["summary"]["n_places"] == 15 and out["n_absent"] == 19
    assert "Sample 2016 · plate HMBS_20080318 · well K22: changes the call." in out["text"]
    assert out["facts"] and all(f.startswith("f_trace_camta2_") for f in out["facts"])
    assert len(json.dumps(out)) < 64_000
    one = QpilotTools(store).qpcr_trace(sid, gene="CAMTA2", top=1)
    assert len(one["places"]) == 1 and one["summary"]["n_places"] == 15


@pytest.mark.demo_data
def test_demo_well_k22_feeds_58_values(demo_store):
    store, sid = demo_store
    out = QpilotTools(store).qpcr_trace(sid, well="HMBS_20080318:K22")
    assert out["root"] == {"kind": "well", "id": "HMBS_20080318/K22"}
    assert out["places"][0]["feeds"] == 58 == out["summary"]["feeds"]
    assert out["places"][0]["sample"] == "2016"
    assert "It feeds all 58 values of sample 2016." in out["text"]


@pytest.mark.demo_data
def test_demo_cli_trace_json_is_byte_stable(demo_store, monkeypatch, capsys):
    from qpilot.qpcr.trace import trace_store

    store, sid = demo_store
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(store.root))
    assert main(["trace", sid, "--gene", "CAMTA2", "--json"]) == 0
    first = capsys.readouterr().out
    assert main(["trace", "--gene", "CAMTA2", "--json"]) == 0  # the only study
    assert capsys.readouterr().out == first == trace_store(store, sid, gene="CAMTA2").to_json()
    assert main(["trace", sid, "--well", "HMBS_20080318:K22", "--top", "1"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Well K22 on plate HMBS_20080318 (HMBS, sample 2016).")


@pytest.mark.demo_data
def test_demo_ask_why_camta2_is_no_call(demo_store):
    store, sid = demo_store
    out = ask("Why is CAMTA2 no call?", store, sid, client=_none_client(), log=False)
    assert out.tool_calls[0] == {
        "tool": "qpcr_trace",
        "args": {"gene": "CAMTA2"},
        "status": None,
        "error": None,
    }
    assert out.validated and "2016" not in out.answer
    assert "sample 2016, plate HMBS_20080318, well K22: changes the call" in out.plain
    # a model writes the answer from tokens: the addresses are not in what it reads
    backend = MockBackend(
        [
            '{"tool": "qpcr_trace", "args": {"gene": "CAMTA2"}}',
            "Look first at sample {{f_ans_trace_1_sample}}, well {{f_ans_trace_1_well}}.",
        ]
    )
    out = ask("Where should I look for CAMTA2?", store, sid, client=ModelClient(backend), log=False)
    assert out.tool_from_model and out.validated and not out.fallback
    assert out.plain == "Look first at sample 2016, well K22."
    shown = backend.calls[1]["messages"][0]["content"]
    assert "2016" not in shown and "K22" not in shown and HIDDEN_ADDRESS in shown


@pytest.mark.demo_data
def test_demo_agent_decide_on_a_trace_card_a_person_opened_waits(demo_store):
    from qpilot.qpcr.trace import trace_store

    store, sid = demo_store
    card = store.open_card(sid, trace_store(store, sid, gene="CAMTA2").card(1))
    assert card.kind == "trace_set_aside" and card.impact["flips"] is True
    out = QpilotTools(store).qpcr_decide(sid, card.id, "set_aside", "the agent asks")
    assert out["status"] == "pending_human" and out["card"]["card_id"] == card.id
    assert store.card(sid, card.id).decision is None  # nothing applied: a person decides
    assert (card.id, "set_aside") in [(p.card_id, p.option) for p in store.pending(sid)]
