"""The Studio dashboard: hardening, who may act, escaping and the blind stages, headlessly.

Two kinds of drive: every handler wired in ``qpilot/studio.py`` is run directly against a fake
service that records each call and its actor (``fake_studio.py``), and the real service on a
small synthetic RDML file is driven through ``Blocks.process_api`` with a simulated browser
session, so Gradio's own preprocessing runs as it does for a person clicking.
"""

import ast
import asyncio
import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import gradio as gr
import pytest
from gradio.routes import App
from gradio.state_holder import SessionState
from pytest_socket import disable_socket, enable_socket
from starlette.testclient import TestClient

import qpilot.studio as st
from qpilot import studio_state as ss
from qpilot.ai import payload_log
from qpilot.ai.client import ModelClient, NoneBackend
from qpilot.ai.prompts import SYSTEM_INTERPRET
from qpilot.cli import main as cli_main
from qpilot.core.store import StudyStore
from qpilot.schemas_studio import Evidence, MadeBy, Proposal
from qpilot.studio_service import STAGES, Studio
from tests.fixtures.studio.studio_mini import INJECTION, write_studio_mini
from tests.studio.fake_studio import DECIDING, PROPOSING, SID, WELL, FakeStudio

REPO = Path(__file__).resolve().parents[2]
HOSTILE = "<script>alert(1)</script>"
GENES = ("ODC1", "NTRK1", "BIRC5", "NM23A")  # the fixture study's headline genes

#: The only service methods each click may call to decide, by handler name (prefix).
MAY_DECIDE = {
    "on_accept_": {"accept"},
    "on_reject_": {"reject"},
    "on_edit_": {"edit"},
    "on_confirm": {"accept"},
    "on_confirm_withdraw": {"reject"},
    "on_bulk_accept": {"accept_all_consistent"},
    "on_reject_all": {"reject_many"},
    "on_decide": {"decide"},
    "on_send": {"send_to_prism", "launch_prism"},
}


# ---------- fixtures and helpers ----------


@pytest.fixture
def fake(fixture_result, fixture_cards, tmp_path):
    return FakeStudio(fixture_result, fixture_cards, tmp_path)


@pytest.fixture
def fake_page(fake, tmp_path):
    rdml = tmp_path / "demo.rdml"
    rdml.write_bytes(b"not read by the fake")
    return st.build_app(fake, rdml, tmp_path / "exports", tmp_path / "inputs")


def handlers(page):
    return list(page.fns.values())


def by_name(page, name):
    return next(fn for fn in page.fns.values() if fn.name == name)


def is_click(page, fn) -> bool:
    """True when every trigger of ``fn`` is a click on a button (a person's explicit act)."""
    targets = [(page.blocks.get(block_id), event) for block_id, event in fn.targets]
    return bool(targets) and all(
        event == "click" and isinstance(block, gr.Button) for block, event in targets
    )


def run(fn, values):
    """Call a handler directly; its outputs as ``{component: value}``."""
    result = fn.fn(*values)
    if isinstance(result, dict) and all(hasattr(k, "_id") for k in result):
        return result
    return {fn.outputs[0]: result}


def text_of(value) -> str:
    if isinstance(value, dict):
        value = value.get("value")
    if value is None:
        return ""
    if hasattr(value, "to_plotly_json"):
        return json.dumps(value.to_plotly_json(), default=str)
    return str(value)


def html_outputs(outputs) -> list[str]:
    return [text_of(v) for c, v in outputs.items() if isinstance(c, gr.HTML | gr.Plot)]


def loaded_session(page, sid=SID):
    """The session the page itself makes when it shows ``sid`` (an honest tab)."""
    out = run(by_name(page, "on_load"), [{**st.new_session(), "sid": sid}])
    return out[page.qpilot_ui.session]


def armed_session(page, fake, root: Path):
    """A tab that has seen every list and card, so each click can act."""
    session = loaded_session(page)
    stage = session["shown"]
    pending = fake.inbox(SID, stage, "proposed")
    bundle = root / "exports" / "prism-armed"
    (bundle / "sent_back").mkdir(parents=True, exist_ok=True)
    (bundle / "qpilot_bundle.json").write_text("{}")
    return {
        **session,
        "bulk": {"stage": stage, "ids": fake.consistent_ids(SID, stage)},
        "reject": {"stage": stage, "ids": [p.id for p in pending]},
        "confirm": {"stage": stage, "id": "p_d5"},
        "card_id": "card_refset",
        "card_head": "dhead",
        "card_study": "study1",
        "bundle": str(bundle),
        "gene": "ODC1",
    }


def values_for(fn, session, root: Path):
    """Plausible input values for each of a handler's inputs (by the component's elem_id)."""
    bundle = root / "exports" / "prism-armed"
    fixed = {
        "qs-sentence": "LPS vs PBS",
        "qs-stage": "design",
        "qs-card": "card_refset",
        "qs-option": "recommended",
        "qs-gene": "ODC1",
        "qs-well": WELL,
        "qs-bundle": str(bundle),
        "qs-sent-back": str(bundle / "sent_back"),
        "qs-upload": None,
        "qs-sheet": None,
    }
    values = []
    for component in fn.inputs:
        if isinstance(component, gr.State):
            values.append(copy.deepcopy(session))
        elif component.elem_id in fixed:
            values.append(fixed[component.elem_id])
        elif str(component.elem_id).startswith("qs-edit-"):
            values.append(json.dumps({"group": "KO", "role": "unkn", "amplified": False}))
        else:  # every reason box
            values.append("a reason the person typed")
    return values


def drive_everything(page, fake, root: Path):
    """Run every handler, in every stage, from a fresh, an honest and an armed tab."""
    seen = []  # (handler, calls made, outputs)
    for phase in STAGES:
        fake.phase = phase
        sessions = [
            st.new_session(),
            loaded_session(page),
            armed_session(page, fake, root),
        ]
        for session in sessions:
            for fn in handlers(page):
                before = len(fake.calls)
                outputs = run(fn, values_for(fn, session, root))
                seen.append((phase, fn, fake.calls[before:], outputs))
    return seen


class Tab:
    """One simulated browser tab on a real page (Gradio's preprocessing included)."""

    def __init__(self, page):
        self.page = page
        self.ui = page.qpilot_ui
        self.session = SessionState(page)
        self.fns = {}
        for fn in page.fns.values():
            self.fns.setdefault(fn.name, fn)

    def __call__(self, name, *inputs):
        fn = self.fns[name]
        out = asyncio.run(
            self.page.process_api(block_fn=fn, inputs=list(inputs), state=self.session)
        )
        return {c: v for c, v in zip(fn.outputs, out["data"], strict=True)}

    @property
    def state(self):
        return self.session[self.ui.session._id]


def real_page(tmp_path, rename=None):
    rdml = write_studio_mini(tmp_path / "mini.rdml", rename=rename)
    studio = Studio(StudyStore(tmp_path / "studies"), client=ModelClient(backend=NoneBackend()))
    page = st.build_app(studio, rdml, tmp_path / "exports", tmp_path / "inputs")
    return studio, page


@pytest.fixture
def mini(tmp_path):
    """A real Studio over the small synthetic file (its names include an instruction)."""
    return real_page(tmp_path)


@pytest.fixture
def evil_mini(tmp_path):
    """The same file with a sample whose name is markup."""
    return real_page(tmp_path, rename={"KO_2": f"KO_2{HOSTILE}"})


def open_and_propose(tab, sentence=f"WT vs KO {HOSTILE}"):
    tab("on_load", None)
    tab("on_open", None, None, None)
    return tab("on_propose_design", None, sentence)


def agent_proposals(studio, sid):
    """An agent proposes: one contradicted (no such sample), one cannot-check; hostile text.

    Both cite the sentence and every sample name (the instruction-like one included).
    """
    cited = [
        Evidence(kind="text", ref=e.text_id, note=HOSTILE)
        for e in studio.quarantined(sid)
        if e.origin in ("studio:sentence", "rdml:sample.id")
    ]
    inbox = studio.store.proposals(sid)
    made = []
    for subject, group in ((f"ghost{HOSTILE}", HOSTILE), ("KO_1", "KO")):
        proposal = Proposal(
            study_id=sid,
            kind="design.group",
            subject=subject,
            payload={"group": group},
            evidence=cited,
            reasons=[HOSTILE],
            made_by=MadeBy(kind="agent", agent=HOSTILE),
        )
        made.append(inbox.propose(proposal, "agent").proposal)
    return made


# ---------- hardening (mirrors tests/app/test_app.py) ----------


def test_telemetry_is_forced_off_even_when_the_environment_turns_it_on():
    env = {**os.environ, "GRADIO_ANALYTICS_ENABLED": "True", "HF_HUB_DISABLE_TELEMETRY": "0"}
    code = (
        "import qpilot.studio, os, gradio.analytics as a, huggingface_hub.constants as c; "
        "print(os.environ['GRADIO_ANALYTICS_ENABLED'], a.analytics_enabled(), "
        "c.HF_HUB_DISABLE_TELEMETRY)"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "False", "True"]


def test_launch_options_are_the_apps_hardening(fake, tmp_path):
    options = st.launch_options(fake, tmp_path)
    for key, value in st.LAUNCH_OPTIONS.items():
        assert options[key] == value, key
    assert options["server_name"] == "127.0.0.1" and options["share"] is False
    assert options["enable_monitoring"] is False and options["run_history"] is False
    assert options["mcp_server"] is False and options["footer_links"] == []
    assert options["ssr_mode"] is False
    assert options["allowed_paths"] == [str(tmp_path)]
    assert str(fake.store.root) in options["blocked_paths"]
    assert "qs-card" in options["css"]
    source = (REPO / "qpilot" / "studio.py").read_text()
    assert "share=True" not in source and "0.0.0.0" not in source


def test_main_launches_with_every_hardening_option(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gr.Blocks, "launch", lambda self, **kw: captured.update(kw))
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(tmp_path / "studies"))
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))  # no demo cached
    assert cli_main(["studio", "--port", "7998"]) == 0
    for key, value in st.LAUNCH_OPTIONS.items():
        assert captured[key] == value, key
    assert captured["server_port"] == 7998
    (export_root,) = captured["allowed_paths"]
    assert Path(export_root).is_dir() and Path(export_root).name.startswith("qpilot-exports-")
    assert captured["app_kwargs"]["middleware"]


def test_foreign_hosts_and_store_files_are_refused(mini, tmp_path):
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    options = st.launch_options(studio, page.qpilot_export_root)
    page.allowed_paths, page.blocked_paths = options["allowed_paths"], options["blocked_paths"]
    client = TestClient(App.create_app(page, app_kwargs=options["app_kwargs"]))
    local, rebound = {"host": "127.0.0.1:7860"}, {"host": "evil.example:7860"}
    assert client.get("/config", headers=local).status_code == 200
    assert client.get("/config", headers=rebound).status_code == 400  # DNS rebinding
    chain = studio.store.find_session(tab.state["sid"]) / "proposals.jsonl"
    assert chain.exists()
    assert client.get(f"/gradio_api/file={chain}", headers=local).status_code == 403


def test_the_page_opens_and_proposes_with_the_network_switched_off(mini):
    studio, page = mini
    disable_socket(allow_unix_socket=True)
    try:
        out = open_and_propose(Tab(page))
    finally:
        enable_socket()
    assert "design proposal(s) added" in out[page.qpilot_ui.notice]


def test_the_page_actions_are_not_published_as_api_endpoints(fake_page):
    assert all(fn.api_visibility == "private" for fn in fake_page.fns.values())


def test_the_cli_studio_command_is_registered(capsys):
    assert cli_main(["studio", "demo"]) == 2  # demo needs --check
    assert "--check" in capsys.readouterr().err


# ---------- only a person's click decides (the handler-coverage gate) ----------


def test_every_handler_decides_only_on_a_click_and_only_as_human(fake, fake_page, tmp_path):
    """Run every wired handler in every stage; record every service call and its actor."""
    seen = drive_everything(fake_page, fake, tmp_path)
    decided, proposed = set(), set()
    for phase, fn, calls, _ in seen:
        click = is_click(fake_page, fn)
        for method, actor in calls:
            if method in DECIDING:
                decided.add(method)
                assert click, f"{fn.name} ({phase}) calls {method} without a click"
                assert type(actor) is str and actor == "human", (fn.name, method, actor)
                prefix = max((k for k in MAY_DECIDE if fn.name.startswith(k)), key=len)
                assert method in MAY_DECIDE[prefix], f"{fn.name} calls {method}"
            if method in PROPOSING:
                proposed.add(method)
                assert click, f"{fn.name} ({phase}) proposes ({method}) without a click"
    assert decided == DECIDING, "every way of deciding was exercised"
    assert proposed == PROPOSING, "every way of proposing was exercised"


def test_reading_handlers_write_nothing(fake, fake_page, tmp_path):
    readers = [fn for fn in handlers(fake_page) if not is_click(fake_page, fn)]
    assert {fn.name for fn in readers} >= {"on_load", "on_stage", "on_card_pick", "on_gene"}
    for phase, fn, calls, _ in drive_everything(fake_page, fake, tmp_path):
        if fn in readers:
            assert not {m for m, _ in calls} & (DECIDING | PROPOSING), (phase, fn.name)


def test_every_button_is_wired_and_every_handler_is_enumerated(fake_page):
    wired = {block_id for fn in fake_page.fns.values() for block_id, _ in fn.targets}
    buttons = [b for b in fake_page.blocks.values() if type(b) is gr.Button]
    assert buttons and all(b._id in wired for b in buttons)
    names = {fn.name for fn in fake_page.fns.values()}
    for i in range(st.PAGE_SIZE):
        assert {f"on_accept_{i}", f"on_reject_{i}", f"on_edit_{i}", f"on_matters_{i}"} <= names


def test_the_source_passes_only_human_as_actor_and_never_writes_around_the_service():
    source = (REPO / "qpilot" / "studio.py").read_text()
    tree = ast.parse(source)
    n_decisions = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "actor":
            assert isinstance(node.value, ast.Constant) and node.value.value == "human"
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in DECIDING
        ):
            n_decisions += 1
            actors = [k.value for k in node.keywords if k.arg == "actor"]
            assert len(actors) == 1 and actors[0].value == "human", ast.unparse(node)
    assert n_decisions >= len(DECIDING)
    for banned in (
        "apply_decision(",
        ".append_decision(",
        ".bulk_accept(",
        ".edit_and_accept(",
        "export_study(",
        "write_record(",
        ".request_human(",
        ".proposals(",
        "subprocess",
    ):
        assert banned not in source, banned


# ---------- escaping, end to end ----------


def test_hostile_text_is_escaped_in_every_html_output(fake, fake_page, tmp_path):
    rendered = []
    for _, _, _, outputs in drive_everything(fake_page, fake, tmp_path):
        rendered += html_outputs(outputs)
    assert rendered
    for html in rendered:
        assert not re.search(r"<\s*(script|img)", html, re.IGNORECASE), html[:300]
    joined = "\n".join(rendered)
    assert joined.count("&lt;script&gt;") > 20  # the hostile text was shown, as text


def test_names_from_the_file_and_agent_text_are_escaped_with_the_real_service(evil_mini):
    studio, page = evil_mini
    tab = Tab(page)
    open_and_propose(tab)
    agent_proposals(studio, tab.state["sid"])
    rendered = []
    for _ in range(3):
        rendered += html_outputs(tab("on_load", None))
        rendered += html_outputs(tab("on_next", None))
    html = "\n".join(rendered)
    assert "<script" not in html.lower()
    assert "KO_2&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert INJECTION in html and "reads like an instruction" in html  # quoted, as data


# ---------- blind stages, enforced by the page too ----------


def test_nothing_of_the_analysis_is_read_or_shown_before_both_blind_stages(
    fake, fake_page, tmp_path
):
    ui = fake_page.qpilot_ui
    for phase, fn, _, outputs in drive_everything(fake_page, fake, tmp_path):
        if phase not in ("design", "curves"):
            continue
        for html in html_outputs(outputs):
            assert "×" not in html and "data-fact" not in html, (fn.name, html[:200])
            assert not re.search(r"\bp\s*=\s*\d", html), fn.name
            assert not any(gene in html for gene in GENES), (fn.name, html[:200])
        if ui.right in outputs:
            assert outputs[ui.right]["visible"] is False
            assert outputs[ui.summary] == "" and outputs[ui.preview] == ""
    fake.calls.clear()
    for phase in ("design", "curves"):
        fake.phase = phase
        session = loaded_session(fake_page)
        for name in (
            "on_load",
            "on_stage",
            "on_prev",
            "on_next",
            "on_gene",
            "on_send",
            "on_decide",
            "on_propose_prism",
            "on_bulk_show",
        ):
            fn = by_name(fake_page, name)
            run(fn, values_for(fn, session, tmp_path))
    read = {m for m, _ in fake.calls}
    assert not read & {"study", "preview_prism", "store.get", "store.snapshot"}, read


def test_results_shown_once_both_blind_stages_are_confirmed_and_never_kept(fake, fake_page):
    ui = fake_page.qpilot_ui
    fake.phase = "choices"
    out = run(by_name(fake_page, "on_load"), [{**st.new_session(), "sid": SID}])
    assert out[ui.right]["visible"] is True
    assert "3.6×" in out[ui.summary] and "Which control genes" in out[ui.card]
    assert "Prism preview" in out[ui.preview]
    session = out[ui.session]
    assert session["card_study"] == "study1"
    fake.phase = "design"  # e.g. a design proposal accepted later re-opens the design
    out = run(by_name(fake_page, "on_load"), [session])
    assert out[ui.right]["visible"] is False
    for html in html_outputs(out):
        assert "×" not in html and "data-fact" not in html
    assert out[ui.session]["card_study"] is None and out[ui.session]["send"] is None


def test_the_round_trip_says_what_all_exclusions_do_together_and_marks_stale_cards(
    fake, fake_page, tmp_path, monkeypatch
):
    ui = fake_page.qpilot_ui
    fake.phase = "roundtrip"
    session = armed_session(fake_page, fake, tmp_path)
    sent_back = str(Path(session["bundle"]) / "sent_back")
    out = run(by_name(fake_page, "on_roundtrip"), [session, session["bundle"], sent_back])
    notice = out[ui.notice]
    assert "All 2 exclusions together change 1 of" in notice and "<script" not in notice
    cards = "".join(text_of(out[slot.html]) for slot in ui.slots)
    assert "with the other exclusions found in this round trip" in cards
    reason = "computed before the exclusions accepted since then"
    monkeypatch.setattr(
        fake, "stale_consequence", lambda sid, p: reason if p.id == "p_r1" else None
    )
    out = run(by_name(fake_page, "on_load"), [out[ui.session]])
    cards = "".join(text_of(out[slot.html]) for slot in ui.slots)
    assert "Out of date" in cards and reason in cards and "3.590×" not in cards


def test_a_blind_card_says_at_most_that_it_matters(fake, fake_page):
    ui = fake_page.qpilot_ui
    fake.phase = "curves"
    out = run(by_name(fake_page, "on_load"), [{**st.new_session(), "sid": SID}])
    cards = "".join(text_of(out[slot.html]) for slot in ui.slots)
    assert "This matters for at least one conclusion; decide on the evidence." in cards
    assert "fc_before" not in cards and "3.59" not in cards


@pytest.fixture
def prism_payload():
    """The last model call was a Prism draft: its payload holds the fact table's values."""
    payload_log.clear()
    payload_log.record_payload(
        {
            "system": "You reword a figure caption.",
            "messages": [{"role": "user", "content": "f_fc_1_mar_recommended: 0.56×, p 0.094"}],
        }
    )
    yield
    payload_log.clear()


def test_what_the_model_saw_shows_no_result_once_a_stage_is_blind_again(
    fake, fake_page, prism_payload
):
    ui = fake_page.qpilot_ui
    fake.phase = "choices"  # both blind stages confirmed: the results are visible
    out = run(by_name(fake_page, "on_seen"), [loaded_session(fake_page)])
    assert out[ui.seen]["visible"] is True and "0.56×" in text_of(out[ui.seen])
    session = out[ui.session]
    fake.phase = "design"  # an accepted design change re-opens the design stage
    out = run(by_name(fake_page, "on_load"), [session])
    assert out[ui.seen]["visible"] is True  # the open panel is re-drawn, not left as it was
    shown = [text_of(out[ui.seen]), *(text_of(out[slot.html]) for slot in ui.slots)]
    assert "qs-saw" in "".join(shown)  # a model-made card's footer is on the page
    for html in shown:  # neither the panel nor any card footer shows the earlier results
        assert "0.56" not in html and "f_fc_" not in html
    assert ss.SEEN_HIDDEN_TEXT in text_of(out[ui.seen])
    out = run(by_name(fake_page, "on_seen"), [out[ui.session]])
    assert "0.56" not in text_of(out[ui.seen]) and ss.SEEN_HIDDEN_TEXT in text_of(out[ui.seen])
    payload_log.record_payload({"system": SYSTEM_INTERPRET, "messages": [{"content": "S1, S2"}]})
    out = run(by_name(fake_page, "on_seen"), [out[ui.session]])
    assert "S1, S2" in text_of(out[ui.seen])  # the Design Interpreter's own call is shown


def test_the_seen_panel_stays_closed_until_asked_for(fake, fake_page, prism_payload):
    ui = fake_page.qpilot_ui
    fake.phase = "choices"
    out = run(by_name(fake_page, "on_load"), [{**st.new_session(), "sid": SID}])
    assert out[ui.seen]["visible"] is False and out[ui.seen]["value"] == ""
    out = run(by_name(fake_page, "on_load"), [st.new_session()])  # no file open: blind
    assert out[ui.seen]["visible"] is False


def test_a_does_this_matter_answer_is_dropped_once_the_chain_moves_on(mini, monkeypatch):
    """The engine's answer holds for the design it was computed on; asking again is possible."""
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    sid = tab.state["sid"]
    inbox = studio.store.proposals(sid)
    asked = next(
        p for p in studio.inbox(sid, "design", "proposed") if p.subject == "water"
    )  # design.well_role water: ntc, or unkn
    assert asked.alternatives

    def card_of(out):
        slot = tab.state["slots"].index(asked.id)
        return text_of(out[tab.ui.slots[slot].html]), out[tab.ui.slots[slot].matters]

    answers = iter([False, True])
    monkeypatch.setattr(studio, "matters", lambda session_id, proposal: next(answers))
    slot = tab.state["slots"].index(asked.id)
    card, button = card_of(tab(f"on_matters_{slot}", None))
    assert ss.NOT_MATTERS_TEXT in card and button["visible"] is False
    card, button = card_of(tab("on_load", None))  # nothing changed: the answer is kept
    assert ss.NOT_MATTERS_TEXT in card and button["visible"] is False
    other = next(p for p in studio.inbox(sid, "design", "proposed") if p.subject == "NTC")
    head = inbox.head()
    out = tab(f"on_accept_{tab.state['slots'].index(other.id)}", None, "")
    assert inbox.head() != head and "Accepted" in out[tab.ui.notice]
    card, button = card_of(out)
    assert ss.NOT_MATTERS_TEXT not in card and ss.BLIND_TEXT in card
    assert button["visible"] is True  # the person can ask again
    card, button = card_of(tab(f"on_matters_{tab.state['slots'].index(asked.id)}", None))
    assert ss.MATTERS_TEXT in card and button["visible"] is False


# ---------- the real service: bulk acceptance, staleness, curves ----------


def test_accept_all_consistent_lists_then_accepts_exactly_that_list(mini):
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    sid = tab.state["sid"]
    agent_proposals(studio, sid)
    statuses = {p.id: p.check.status for p in studio.inbox(sid, "design")}
    assert {"consistent", "contradicted", "cannot_check"} <= set(statuses.values())
    before = len(studio.store.proposals(sid).entries())
    out = tab("on_bulk_show", None)
    listed = tab.state["bulk"]["ids"]
    assert listed == studio.consistent_ids(sid, "design")
    assert all(statuses[pid] == "consistent" for pid in listed)
    assert len(studio.store.proposals(sid).entries()) == before  # showing writes nothing
    assert all(pid in text_of(out[tab.ui.bulk_html]) for pid in listed)
    out = tab("on_bulk_accept", None)
    entries = studio.store.proposals(sid).entries()[before:]
    assert [(e.action, e.actor) for e in entries] == [("accept", "human")] * len(listed)
    assert [e.proposal_id for e in entries] == listed  # one entry per listed proposal
    assert f"Accepted {len(listed)} proposal(s)" in out[tab.ui.notice]
    left = {p.check.status for p in studio.inbox(sid, "design", "proposed")}
    assert left == {"contradicted", "cannot_check"}  # never bulk-accepted
    assert tab.state["bulk"] is None
    assert "Press “Accept all consistent…” first" in tab("on_bulk_accept", None)[tab.ui.notice]


def test_reject_all_lists_contradicted_ai_calls_and_needs_a_reason(mini):
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    sid = tab.state["sid"]
    ghost, _ = agent_proposals(studio, sid)
    tab("on_load", None)
    tab("on_reject_show", None)
    assert tab.state["reject"]["ids"] == [ghost.id]
    assert "Give the reason" in tab("on_reject_all", None, "  ")[tab.ui.notice]
    assert studio.store.proposals(sid).get(ghost.id).status == "proposed"
    tab("on_reject_all", None, "no well carries this sample")
    rejected = studio.store.proposals(sid).get(ghost.id)
    assert (rejected.status, rejected.decided_by, rejected.reason) == (
        "rejected",
        "human",
        "no well carries this sample",
    )


def test_a_decision_on_a_changed_inbox_is_stale_and_writes_nothing(mini):
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    sid = tab.state["sid"]
    first = tab.state["slots"][0]
    studio.reject(sid, tab.state["slots"][1], "human", "decided in another tab")
    before = len(studio.store.proposals(sid).entries())
    out = tab("on_accept_0", None, "")
    assert "The inbox changed since this page showed it" in out[tab.ui.notice]
    assert len(studio.store.proposals(sid).entries()) == before
    assert tab.state["slots"][0] == first
    out = tab("on_accept_0", None, "")
    assert "Accepted" in out[tab.ui.notice]


def test_reject_needs_a_reason_and_a_reason_never_moves_to_another_card(mini):
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    sid = tab.state["sid"]
    out = tab("on_reject_0", None, "")
    assert "Give a reason to reject" in out[tab.ui.notice]
    out = tab("on_reject_0", None, "not a standard here")
    assert studio.store.proposals(sid).entries()[-1].reason == "not a standard here"
    assert out[tab.ui.slots[0].reason]["value"] == ""  # the next card starts empty


def test_confirm_shows_what_it_covers_and_only_the_second_click_confirms(mini):
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    sid = tab.state["sid"]
    out = tab("on_confirm_prepare", None)
    assert "Not ready to confirm" in out[tab.ui.notice]  # proposals wait: the service says so
    inbox = studio.store.proposals(sid)
    for sample, group in (("WT_1", "WT"), ("WT_2", "WT"), ("KO_1", "KO"), ("KO_2", "KO")):
        made = MadeBy(kind="agent", agent="test agent")
        inbox.propose(
            Proposal(
                study_id=sid,
                kind="design.group",
                subject=sample,
                payload={"group": group},
                made_by=made,
            ),
            "agent",
        )
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "checked the evidence")
    tab("on_load", None)
    out = tab("on_propose_comparison", None)
    assert "comparison is proposed" in out[tab.ui.notice]
    (comparison,) = studio.inbox(sid, "design", "proposed")
    assert comparison.payload == {"group_a": "KO", "group_b": "WT"}  # WT reads as the control
    studio.accept(sid, comparison.id, "human", "KO relative to WT")
    tab("on_load", None)
    before = len(inbox.entries())
    out = tab("on_confirm_prepare", None)
    shown = text_of(out[tab.ui.confirm_info])
    assert out[tab.ui.confirm_box]["visible"] is True
    assert "Compare group “KO” with group “WT”" in shown and "Design hash" in shown
    assert [e.actor for e in inbox.entries()[before:]] == ["system"]  # only proposed
    assert studio.stages(sid)[0].confirmed is False
    out = tab("on_confirm", None)
    assert "The Design (blind) stage is confirmed." in out[tab.ui.notice]
    assert inbox.entries()[-1].actor == "human" and studio.stages(sid)[0].confirmed
    assert out[tab.ui.right]["visible"] is False  # the curves are still blind


def test_edit_goes_through_the_service_as_the_persons_edit(mini):
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    sid = tab.state["sid"]
    slot = next(
        i
        for i, pid in enumerate(tab.state["slots"])
        if studio.store.proposals(sid).get(pid).kind == "design.target_role"
    )
    pid = tab.state["slots"][slot]
    edit = f"on_edit_{slot}"
    assert "not valid JSON" in tab(edit, None, "{", "")[tab.ui.notice]
    assert "Nothing was changed" in tab(edit, None, '{"role": "ref"}', "")[tab.ui.notice]
    tab(edit, None, '{"role": "toi"}', "the person's correction")
    entry = studio.store.proposals(sid).entries()[-1]
    assert (entry.action, entry.actor, entry.proposal_id) == ("edit", "human", pid)
    assert entry.edits == {"role": "toi"} and entry.reason == "the person's correction"


def test_the_curve_of_a_cited_well_is_drawn(mini):
    """``Studio.curve`` trips over the non-numeric columns today; the page reads the cycles."""
    studio, page = mini
    tab = Tab(page)
    open_and_propose(tab)
    fn = tab.fns["on_curve"]
    out = fn.fn(tab.state, "GAPDH_plate/A1")
    figure = out[tab.ui.curve_plot]["value"]
    assert len(figure.data[0].y) == 40 and min(figure.data[0].y) == pytest.approx(1.0)


def test_a_sent_back_folder_outside_the_export_and_home_folders_is_refused(
    fake, fake_page, tmp_path
):
    fake.phase = "roundtrip"
    session = armed_session(fake_page, fake, tmp_path)
    fn = by_name(fake_page, "on_roundtrip")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = run(fn, [session, session["bundle"], str(elsewhere)])
    assert "inside the export folder or your home folder" in out[fake_page.qpilot_ui.notice]
    assert "round_trip" not in {m for m, _ in fake.calls}
