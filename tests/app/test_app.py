"""Task 10 gate: the app's hardening and its decide flow, driven headlessly (no browser).

Events go through ``Blocks.process_api`` with a simulated browser session, so Gradio's own
preprocessing (for example: a Radio refuses a value that is not one of the current choices)
runs exactly as it does for a person clicking.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import gradio as gr
import pytest
from gradio.routes import App
from gradio.state_holder import SessionState
from pytest_socket import disable_socket, enable_socket
from starlette.testclient import TestClient

import qpilot.app as app
from qpilot.ai import payload_log
from qpilot.ai.client import MockBackend, ModelClient
from qpilot.cli import main
from qpilot.core.decisions import apply_decision
from qpilot.core.record import unzip_record, verify
from qpilot.core.store import StudyStore

REPO = Path(__file__).resolve().parents[2]
# Card outputs, in order: session, card, counter, options, reason, notice, figure, undo, reject,
# picker, download; Analyse adds summary, meter, confidence, results.
CARD, COUNTER, OPTIONS, REASON_OUT, NOTICE, UNDO, REJECT, PICKER = 1, 2, 3, 4, 5, 7, 8, 9
SUMMARY, METER = 11, 12
REASON = "All five: none is stable on its own, and the set is the least arbitrary."
EVIL = '<img src=x onerror="alert(1)">'
CAP = "Please switch to: Count empty wells as very low (cap)"


@pytest.fixture
def store(tmp_studies_dir, fixture_result, fixture_cards):
    store = StudyStore(tmp_studies_dir)
    store.put(fixture_result, fixture_cards)
    return store


@pytest.fixture
def page(store, tmp_path):
    return app.build_app(store, None, tmp_path / "exports")


class Tab:
    """One simulated browser tab on the page."""

    def __init__(self, page):
        self.page = page
        self.session = SessionState(page)
        self.fns = {}
        for fn in page.fns.values():
            self.fns.setdefault(fn.name, fn)

    def __call__(self, name, *inputs):
        fn = self.fns[name]
        out = asyncio.run(
            self.page.process_api(block_fn=fn, inputs=list(inputs), state=self.session)
        )
        return out["data"]

    @property
    def state(self):
        return self.session[self.fns["on_decide"].inputs[0]._id]

    @property
    def settings(self):
        return self.session[self.fns["on_autonomy"].inputs[0]._id]

    def open(self):
        self("on_load", None)
        return self("on_analyse", None, None)

    def decide(self, option, reason=REASON):
        return self("on_decide", None, option, reason)

    def pick(self, card_id):
        return self("on_pick", None, card_id)

    def ask(self, question):
        return self("on_ask", None, None, question)


# ---------- hardening ----------


def test_telemetry_is_forced_off_even_when_the_environment_turns_it_on():
    """In a fresh interpreter whose environment asks for telemetry, importing the app wins."""
    env = {**os.environ, "GRADIO_ANALYTICS_ENABLED": "True", "HF_HUB_DISABLE_TELEMETRY": "0"}
    code = (
        "import qpilot.app, os, gradio.analytics as a, huggingface_hub.constants as c; "
        "print(os.environ['GRADIO_ANALYTICS_ENABLED'], a.analytics_enabled(), "
        "c.HF_HUB_DISABLE_TELEMETRY)"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "False", "True"]


def test_launch_options_are_local_only(store, tmp_path):
    options = app.launch_options(store, tmp_path)
    assert options["server_name"] == "127.0.0.1" and options["share"] is False
    assert options["enable_monitoring"] is False and options["run_history"] is False
    assert options["mcp_server"] is False and options["footer_links"] == []
    assert options["allowed_paths"] == [str(tmp_path)]
    assert str(store.root) in options["blocked_paths"]
    assert "share=True" not in (REPO / "qpilot" / "app.py").read_text()


def test_main_launches_with_every_hardening_option(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gr.Blocks, "launch", lambda self, **kw: captured.update(kw))
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(tmp_path / "studies"))
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))  # no demo: nothing analysed
    app.main(port=7999)
    for key, value in app.LAUNCH_OPTIONS.items():
        assert captured[key] == value, key
    assert captured["server_port"] == 7999
    (export_root,) = captured["allowed_paths"]
    assert Path(export_root).is_dir() and Path(export_root).name.startswith("qpilot-exports-")
    assert captured["app_kwargs"]["middleware"]


def test_foreign_hosts_and_store_files_are_refused(store, page):
    options = app.launch_options(store, page.qpilot_export_root)
    page.allowed_paths, page.blocked_paths = options["allowed_paths"], options["blocked_paths"]
    client = TestClient(App.create_app(page, app_kwargs=options["app_kwargs"]))
    local, rebound = {"host": "127.0.0.1:7860"}, {"host": "evil.example:7860"}
    assert client.get("/config", headers=local).status_code == 200
    assert client.get("/config", headers=rebound).status_code == 400  # DNS rebinding
    log = store.workspace("bc1d233e3866") / "decisions.jsonl"
    assert client.get(f"/gradio_api/file={log}", headers=local).status_code == 403


def test_page_builds_and_opens_with_the_network_switched_off(store, tmp_path):
    disable_socket(allow_unix_socket=True)
    try:
        Tab(app.build_app(store, None, tmp_path)).open()
    finally:
        enable_socket()


def test_slow_handlers_never_write_the_settings(page):
    """Autonomy and model settings live in their own state, written only by their own controls."""
    tab = Tab(page)
    settings_id = tab.fns["on_autonomy"].inputs[0]._id
    for name, fn in tab.fns.items():
        writes = {block._id for block in fn.outputs}
        if name not in ("on_autonomy", "on_model"):
            assert settings_id not in writes, name


def test_a_broken_profile_does_not_stop_the_app(monkeypatch, tmp_path, store):
    bad = tmp_path / "profile.yaml"
    bad.write_text("name: [unclosed\n")
    monkeypatch.setenv("QPILOT_PROFILE", str(bad))
    Tab(app.build_app(store, None, tmp_path / "x")).open()


# ---------- the demo path ----------


def test_open_shows_the_first_card_summary_and_meter(page):
    tab = Tab(page)
    out = tab.open()
    assert "Which control genes to normalise to" in out[CARD] and "3.6×" in out[CARD]
    assert out[COUNTER] == "2 decisions could change a conclusion · 1 made automatically"
    assert "plates · " in out[SUMMARY] and "MYCN expression, top 15 %" in out[SUMMARY]
    assert "holds in" in out[METER] and 'data-fact="f_n_cells"' in out[METER]
    assert tab.state["card_id"] == "card_refset" and tab.state["head"]


def test_decide_moves_on_clears_the_reason_and_logs_a_human_entry(page, store):
    tab = Tab(page)
    tab.open()
    assert "Pick an option first" in tab.decide(None)[NOTICE]
    assert "A reason is required" in tab.decide("recommended", "  ")[NOTICE]
    out = tab.decide("recommended")
    assert "Decided: Recommended set (all five)." in out[NOTICE]
    assert out[REASON_OUT]["value"] == ""  # the next card starts with an empty reason
    assert tab.state["card_id"] == "card_cutoff"
    last = store.entries(tab.state["study_id"])[-1]
    assert (last.card_id, last.option, last.actor, last.status) == (
        "card_refset", "recommended", "human", "applied"
    )  # fmt: skip
    assert "Every choice is decided" in tab.decide("cut_15", "The pre-registered cut.")[NOTICE]


def test_a_value_from_an_old_card_is_refused_by_the_page(page):
    tab = Tab(page)
    tab.open()
    tab.decide("recommended")  # now on card_cutoff
    with pytest.raises(Exception, match="not in the list of choices"):
        tab.decide("hmbs_alone")


def test_a_change_elsewhere_makes_the_card_stale(page, store):
    tab = Tab(page)
    tab.open()
    sid = tab.state["study_id"]
    other = apply_decision(store, sid, "card_cutoff", "cut_20", "another tab", "human",
                           store.chain_head(sid))  # fmt: skip
    assert other.status == "applied"
    assert "This card changed since you read it" in tab.decide("recommended")[NOTICE]
    assert store.card(sid, "card_refset").status == "open"  # nothing was applied
    assert "Decided" in tab.decide("recommended")[NOTICE]  # after re-reading, it goes through


def test_a_change_elsewhere_is_flagged_even_when_nothing_is_written(page, store):
    tab = Tab(page)
    tab.open()
    sid = tab.state["study_id"]
    apply_decision(store, sid, "card_cutoff", "cut_20", "other tab", "human", store.chain_head(sid))
    out = tab.decide("recommended", "")  # refused for the missing reason...
    assert "A reason is required" in out[NOTICE]
    assert "Something was decided since this page last showed the study" in out[NOTICE]


def test_undo_steps_back_through_the_history(page, store):
    tab = Tab(page)
    tab.open()
    out = tab.pick("card_undetermined")
    assert out[UNDO]["interactive"] is False
    tab.decide("cap", "Try counting them as very low.")
    out = tab.pick("card_undetermined")
    assert out[UNDO]["value"] == "Undo: back to Drop empty wells"
    assert "Type a reason" in tab("on_undo", None, "")[NOTICE]
    out = tab("on_undo", None, "Back to dropping them.")
    assert "Undone: back to Drop empty wells" in out[NOTICE]
    card = store.card(tab.state["study_id"], "card_undetermined")
    assert card.decision == "drop" and card.reason == "Undo: Back to dropping them."
    assert out[UNDO]["interactive"] is False  # nothing earlier to go back to
    assert "Nothing to undo" in tab("on_undo", None, "again")[NOTICE]


def test_a_decide_reason_cannot_pose_as_an_undo(page, store):
    tab = Tab(page)
    tab.open()
    tab.decide("recommended", "Undo: sneaky")
    entry = store.entries(tab.state["study_id"])[-1]
    assert entry.reason == "sneaky"


def test_picking_the_current_card_changes_nothing(page):
    tab = Tab(page)
    tab.open()
    out = tab.pick("card_refset")
    for item in out[1:]:  # updates that carry no new value
        assert item["__type__"] == "update"
        assert "value" not in item and "value" not in item.get("props", {})


# ---------- escaping, end to end ----------


def test_a_reason_with_markup_is_shown_as_text(page):
    tab = Tab(page)
    tab.open()
    tab.decide("recommended", EVIL)
    card = tab.pick("card_refset")[CARD]
    assert "<img" not in card and "&lt;img" in card


def test_a_hostile_label_from_an_rdml_file_is_shown_as_text(tmp_studies_dir, fixture_result,
                                                            fixture_cards, tmp_path):  # fmt: skip
    first = fixture_cards[0]
    options = [first.options[0].model_copy(update={"label": EVIL}), *first.options[1:]]
    cards = [first.model_copy(update={"options": options}), *fixture_cards[1:]]
    store = StudyStore(tmp_studies_dir)
    store.put(fixture_result, cards)
    card = Tab(app.build_app(store, None, tmp_path)).open()[CARD]
    assert "<img" not in card and "&lt;img" in card


def test_model_text_with_markup_is_escaped(page, monkeypatch):
    markup = "<img src=x onerror=alert(document.cookie)>"  # no digit, so the validator passes it
    reply = f"{markup} {{{{f_n_flipped_refset}}}} genes change."
    client = ModelClient(MockBackend([reply]))
    monkeypatch.setattr(app, "build_client", lambda *args: (client, None))
    tab = Tab(page)
    tab.open()
    html = tab("on_explain", None, None)[0]
    assert "from the model" in html
    assert "<img" not in html and "&lt;img" in html and 'data-fact="f_n_flipped_refset"' in html


# ---------- the model layer, with no model ----------


def test_ask_in_suggest_mode_only_asks_and_shows_the_request(page, store):
    tab = Tab(page)
    tab.open()
    sid = tab.state["study_id"]
    out = tab.ask(CAP)
    assert store.card(sid, "card_undetermined").status == "pending_human"
    assert [p.option for p in store.pending(sid)] == ["cap"]
    assert tab.state["card_id"] == "card_undetermined"  # the page shows the request
    assert "an agent asked to choose Count empty wells as very low (cap)" in out[1 + CARD]
    assert out[1 + REJECT]["visible"] is True
    out = tab("on_reject", None, "Keep dropping them.")
    assert "turned down" in out[NOTICE] and store.pending(sid) == []


def test_decide_right_after_ask_is_not_stale(page):
    tab = Tab(page)
    tab.open()
    tab.ask("Is ODC1 robust?")
    tab.ask(CAP)  # writes a request to the log
    tab.pick("card_refset")
    assert "Decided" in tab.decide("recommended")[NOTICE]


def test_decide_and_tell_applies_only_what_changes_no_conclusion(page, store):
    tab = Tab(page)
    tab.open()
    tab("on_autonomy", None, "decide_and_tell")
    sid = tab.state["study_id"]
    tab.ask(CAP)
    card = store.card(sid, "card_undetermined")
    assert (card.status, card.decision, card.decided_by) == ("decided", "cap", "agent")
    tab.ask("Apply HMBS alone as the control gene")
    assert store.card(sid, "card_refset").status == "pending_human"  # still a person's call


def test_explain_and_seen_without_a_model(page):
    payload_log.clear()  # the log is process-wide; earlier tests may have filled it
    tab = Tab(page)
    tab.open()
    out = tab("on_explain", None, None)
    assert "from the template" in out[0] and 'data-fact="f_n_flipped_refset"' in out[0]
    assert tab("on_seen")[0]["value"] == "No model call yet."


def test_changing_the_model_clears_what_the_model_sees(page):
    payload_log.record_payload({"messages": ["old"]})
    tab = Tab(page)
    tab("on_model", None, "Local", "http://127.0.0.1:1", "m")
    assert payload_log.last_payload() is None
    assert tab.settings["provider"] == "Local"


def test_check_model_with_no_model_scores_templates(page, store):
    tab = Tab(page)
    tab.open()
    table = tab("on_check", None, None)[0]
    assert table.splitlines()[0].startswith("|") and "| none" in table
    assert "Computed now on 9 questions for none" in table
    assert store.scorecard(tab.state["study_id"])["none"]["n_items"] == 9


# ---------- the model's configuration and its key ----------


def test_the_api_key_only_goes_where_it_was_configured(monkeypatch):
    monkeypatch.setenv("QPILOT_API_KEY", "k-123")
    monkeypatch.delenv("QPILOT_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("QPILOT_MODEL_ENDPOINT", raising=False)
    assert app._api_key_for("anthropic", None) == "k-123"
    assert app._api_key_for("openai_compatible", "http://gateway.example:8000") is None
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "openai_compatible")
    monkeypatch.setenv("QPILOT_MODEL_ENDPOINT", "http://127.0.0.1:11434")
    assert app._api_key_for("openai_compatible", "http://127.0.0.1:11434/v1") == "k-123"
    assert app._api_key_for("openai_compatible", "http://gateway.example:8000") is None
    assert app._api_key_for("anthropic", None) is None  # configured for the local endpoint


def test_the_model_selector_starts_from_the_environment(monkeypatch):
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "openai_compatible")
    monkeypatch.setenv("QPILOT_MODEL_ENDPOINT", "http://127.0.0.1:11434")
    monkeypatch.setenv("QPILOT_MODEL_NAME", "llama")
    settings = app.default_settings()
    assert (settings["provider"], settings["endpoint"], settings["model"]) == (
        "Local", "http://127.0.0.1:11434", "llama"
    )  # fmt: skip
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "nonsense")
    assert app.default_settings()["provider"] == "None"


def test_a_missing_key_is_reported_not_hidden(monkeypatch):
    monkeypatch.delenv("QPILOT_API_KEY", raising=False)
    client, error = app.build_client("Anthropic", "", "claude-test")
    assert not client.available and "QPILOT_API_KEY" in error


# ---------- export and the demo workspace ----------


def test_export_writes_one_zip_that_verifies_and_warns_about_open_choices(page, tmp_path):
    tab = Tab(page)
    tab.open()
    _, status = tab("on_export", None)
    assert "still open" in status  # no choice made yet
    tab.decide("recommended")
    tab.decide("cut_15", "Pre-registered.")
    download, status = tab("on_export", None)
    assert "still open" not in status and "qpilot verify" in status
    served = Path(download["value"]["path"])
    assert served.name == f"qpilot-record-{tab.state['study_id']}.zip"
    folders = sorted(page.qpilot_export_root.glob("record-*"))
    assert len(folders) == 2  # a fresh folder per export
    assert all([p.name for p in f.iterdir()] == [served.name] for f in folders)  # zip only
    assert verify(unzip_record(served, tmp_path / "check")).ok


def test_fresh_demo_moves_earlier_decisions_aside(store):
    sid = store.list_studies()[0]
    apply_decision(store, sid, "card_cutoff", "cut_20", "rehearsal", "human", store.chain_head(sid))
    moved = app.archive_demo(store)
    assert moved is not None and (moved / "decisions.jsonl").exists()
    assert store.list_studies() == []
    assert app.archive_demo(store) is None


# ---------- doctor and the profile ----------


def test_doctor_reports_no_outbound_without_a_model(monkeypatch, tmp_path, capsys):
    for var in ("QPILOT_MODEL_PROVIDER", "QPILOT_MODEL_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("QPILOT_API_KEY", "supersecret-123")
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path))  # nothing cached: still no download
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "outbound: none" in out and "provider: none" in out and "OK" in out.splitlines()
    assert "QPILOT_API_KEY: set" in out and "supersecret" not in out
    assert "run `qpilot fetch-demo`" in out
    assert list(tmp_path.iterdir()) == []


def test_doctor_names_the_endpoint_when_a_model_is_set(monkeypatch, capsys):
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "openai_compatible")
    monkeypatch.setenv("QPILOT_MODEL_ENDPOINT", "http://127.0.0.1:11434")
    monkeypatch.setenv("QPILOT_MODEL_NAME", "m")
    assert main(["doctor"]) == 0
    assert "outbound: http://127.0.0.1:11434" in capsys.readouterr().out


def test_example_profile_loads(monkeypatch):
    from qpilot.ai.profile import load_profile

    monkeypatch.setenv("QPILOT_PROFILE", str(REPO / "qpilot_profile.example.yaml"))
    profile = load_profile()
    assert profile.name == "example-lab" and profile.max_fewshots == 3
    assert json.dumps(profile.model_dump())  # plain data only
