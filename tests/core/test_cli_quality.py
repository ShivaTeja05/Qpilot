"""The evidence, run-review and instrument commands (read-only, except the instrument registry)."""

import json

import pytest

from qpilot.cli import build_parser, main
from qpilot.core.instruments import Logbook, Registry, log_incident, log_typed
from qpilot.core.store import ON_DEMAND_KINDS, StudyStore
from qpilot.qpcr.evidence import evidence_for
from qpilot.studio_service import _decisions
from tests.core.ondemand_helpers import trace_card
from tests.engine import instrument_files as F
from tests.engine.evidence_toys import toy_design, toy_model, toy_table

SERIALS = ("278880001", "BLK-1001", "HC-2001")


def _sub(parser, name):
    return parser._subparsers._group_actions[0].choices[name]


def _code(argv):
    try:
        return main(argv)
    except SystemExit as err:  # argparse and _fail exit through SystemExit
        return err.code


@pytest.fixture
def with_ledger(store, study, fixture_result):
    table, design = toy_table(), toy_design()
    ledger = evidence_for(table, toy_model(table, design), design)
    ledger = ledger.model_copy(
        update={"study_id": study, "input_sha256": fixture_result.input_sha256}
    )
    store.put_artifact(study, "evidence.json", ledger.model_dump(mode="json"))
    return ledger


def _registry(store):
    return Registry(store.root / "instruments")


# ---- registration --------------------------------------------------------------------------------


def test_commands_are_registered_and_cannot_decide():
    parser = build_parser()
    names = set(parser._subparsers._group_actions[0].choices)
    assert {"evidence", "report", "instrument"} <= names
    report = _sub(parser, "report")
    what = next(a for a in report._actions if a.dest == "what")
    assert what.choices == ["run-review"]  # rendering only: no sign-off, no decide
    instrument = _sub(parser, "instrument")
    actions = next(a for a in instrument._actions if a.dest == "action")
    assert set(actions.choices) == {"inspect", "list", "add", "history", "lookback", "position"}
    for forbidden in ("sign-off", "signoff", "decide", "accept", "confirm"):
        assert forbidden not in names and forbidden not in actions.choices


# ---- evidence ------------------------------------------------------------------------------------


def test_evidence_without_a_ledger_is_refused(store, study, capsys):
    assert _code(["evidence"]) == 2
    assert "no Evidence Ledger" in capsys.readouterr().err
    assert _code(["evidence", "abcdef123456"]) == 2


def test_evidence_prints_the_stored_ledger(store, study, with_ledger, capsys):
    assert main(["evidence"]) == 0
    assert capsys.readouterr().out.startswith("Evidence Ledger:")
    assert main(["evidence", study, "--json"]) == 0
    text = capsys.readouterr().out
    data = json.loads(text)
    assert data["counts"] == with_ledger.counts() and len(data["items"]) == 11
    assert text == json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ---- report run-review ---------------------------------------------------------------------------


def test_run_review_renders_text_json_and_html(store, study, with_ledger, tmp_path, capsys):
    before = (store.workspace(study) / "results.json").read_bytes()
    store.append_review(study, "accept", "fine by me", "A. Person", actor="human")
    head = store.chain_head(study)
    assert main(["report", "run-review"]) == 0
    out = capsys.readouterr().out
    assert "Sign-off: a person signs off this review in the qPilot app." in out
    page = tmp_path / "review.html"
    assert main(["report", "run-review", study, "--out", str(page)]) == 0
    capsys.readouterr()
    html = page.read_text()
    assert "<html" in html.lower() and "A. Person" in html
    assert main(["report", "run-review", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["reviews"][0]["outcome"] == "accept" and data["ledger"]["study_id"] == study
    assert _code(["report", "run-review", "--out", str(tmp_path / "review.txt")]) == 2
    assert _code(["report", "sign-off"]) == 2
    assert store.chain_head(study) == head
    assert (store.workspace(study) / "results.json").read_bytes() == before


def test_run_review_says_why_the_ledger_is_missing(store, study, capsys):
    assert main(["report", "run-review", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ledger"] is None and data["ledger_note"]


# ---- instrument inspect --------------------------------------------------------------------------


def test_inspect_hides_serials_unless_asked(tmp_path, tmp_studies_dir, capsys):
    path = F.qs_v1_expired(tmp_path / "run.eds")
    assert main(["instrument", "inspect", str(path)]) == 0
    out = capsys.readouterr().out
    assert "paused" in out and "serials in file" in out
    assert not [s for s in SERIALS if s in out]
    assert main(["instrument", "inspect", str(path), "--json"]) == 0
    text = capsys.readouterr().out
    data = json.loads(text)
    assert not [s for s in SERIALS if s in text] and F.OPERATOR not in text
    assert {"interrupted", "calibration_expired"} <= {g["code"] for g in data["gate"]}
    assert main(["instrument", "inspect", str(path), "--show-serials"]) == 0
    assert "278880001" in capsys.readouterr().out
    assert main(["instrument", "inspect", str(path), "--json", "--show-serials"]) == 0
    assert json.loads(capsys.readouterr().out)["serials"]["block_serial"] == "BLK-1001"


def test_inspect_date_order_and_bad_files(tmp_path, tmp_studies_dir, capsys):
    path = F.quantstudio_csv(tmp_path / "export.csv")
    assert main(["instrument", "inspect", str(path), "--json"]) == 0
    loose = json.loads(capsys.readouterr().out)
    assert main(["instrument", "inspect", str(path), "--json", "--date-order", "DMY"]) == 0
    dmy = json.loads(capsys.readouterr().out)
    assert loose["context"]["calibrations"] != dmy["context"]["calibrations"]
    assert _code(["instrument", "inspect", str(tmp_path / "missing.eds")]) == 2
    (tmp_path / "junk.txt").write_text("hello\n")
    assert _code(["instrument", "inspect", str(tmp_path / "junk.txt")]) == 2
    assert _code(["instrument", "inspect", str(path), "--date-order", "YMD"]) == 2


# ---- instrument add / list / history -------------------------------------------------------------


def test_add_and_list_keep_serials_local(tmp_studies_dir, capsys):
    assert main(["instrument", "list"]) == 0
    assert "no instruments registered" in capsys.readouterr().out
    argv = ["instrument", "add", "qs-1", "--name", "QS by the window", "--model", "QS5"]
    argv += ["--location", "Lab 2", "--shared", "--alias", "QS5-A", "--serial", "278880001"]
    assert main(argv) == 0
    assert "registered qs-1" in capsys.readouterr().out
    assert main(["instrument", "list"]) == 0
    out = capsys.readouterr().out
    assert "qs-1: QS by the window (QS5), Lab 2, shared" in out and "278880001" not in out
    assert main(["instrument", "list", "--json"]) == 0
    text = capsys.readouterr().out
    assert json.loads(text)[0]["instrument_id"] == "qs-1"
    assert "278880001" not in text and "QS5-A" not in text
    assert _code(argv) == 2  # already registered
    assert _code(["instrument", "add", "Bad Id", "--name", "x"]) == 2
    reg = _registry(StudyStore())
    assert reg.get("qs-1").serials == ("278880001",)


def test_history_shows_events_and_verifies(tmp_studies_dir, capsys):
    reg = _registry(StudyStore())
    reg.register("qs-1", "QS")
    book = reg.logbook("qs-1")
    log_typed(book, "service", actor="human", note="lamp swapped", at="2026-01-02")
    log_incident(book, actor="agent", wells=["B3"], signature={"metric": "plateau"})
    assert main(["instrument", "history", "qs-1"]) == 0
    out = capsys.readouterr().out
    assert "service" in out and "incident" in out and "wells B3" in out
    assert "lamp swapped" not in out and "logbook verifies (2 events shown)" in out
    assert main(["instrument", "history", "qs-1", "--show-notes"]) == 0
    assert "lamp swapped" in capsys.readouterr().out
    assert main(["instrument", "history", "qs-1", "--json", "--since", "2026-06-01"]) == 0
    assert [e["kind"] for e in json.loads(capsys.readouterr().out)["events"]] == ["incident"]
    assert _code(["instrument", "history", "nope"]) == 2
    book.path.write_text(book.path.read_text().replace('"service"', '"move"'))
    assert main(["instrument", "history", "qs-1"]) == 1
    assert "does not verify" in capsys.readouterr().out


# ---- instrument lookback / position --------------------------------------------------------------


def test_lookback_without_the_input_file(store, study, capsys):
    argv = ["instrument", "lookback", "--instrument", "qs-1", "--from", "2008-03-18",
            "--to", "2008-03-18"]  # fmt: skip
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert f"Study {study}: cannot evaluate" in out
    assert main([*argv, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["studies"][0]["reason"] == "input_missing"
    assert _code([*argv[:-1], "18 March"]) == 2
    assert _code([*argv, "--map", "no-equals-sign"]) == 2
    assert _code([*argv, "--map", "R=qs-1", "--all-runs", "qs-1"]) == 2  # one or the other
    assert main([*argv, "--map", "HMBS_20080318=qs-1", "--study", study]) == 0
    capsys.readouterr()
    assert _code([*argv, "--log"]) == 2  # qs-1 is not registered: nothing to log into


def test_position_without_runs(store, study, capsys):
    assert main(["instrument", "position", "--instrument", "qs-1"]) == 0
    assert capsys.readouterr().out.strip()
    assert main(["instrument", "position", "--instrument", "qs-1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["instruments"] == []


# ---- Studio: an on-demand card is not an analysis choice -----------------------------------------


def test_studio_choices_leave_on_demand_cards_out(fixture_result, fixture_cards):
    card = trace_card(fixture_result).model_copy(update={"decision": "keep", "status": "decided"})
    assert card.kind in ON_DEMAND_KINDS
    assert _decisions([*fixture_cards, card]) == _decisions(fixture_cards)


# ---- demo data -----------------------------------------------------------------------------------


@pytest.mark.demo_data
def test_demo_evidence_run_context_and_lookback(demo_rdml_path, tmp_studies_dir, capsys):
    store = StudyStore()
    sid = store.ensure_study(demo_rdml_path)
    ledger = store.get_artifact(sid, "evidence.json")
    assert ledger["study_id"] == sid and len(ledger["items"]) == 11
    contexts = store.get_artifact(sid, "run_context.json")["runs"]
    assert len(contexts) == 67 and sum(1 for c in contexts if c["run"]["start"]) == 64
    assert all(v is None for c in contexts for k, v in c["identity"].items() if "serial" in k)
    assert main(["evidence", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"] == {"absent": 6, "not_applicable": 1, "present": 3, "unknown": 1}
    assert main(["instrument", "lookback", "--instrument", "cfx-1", "--from", "2008-03-18",
                 "--to", "2008-03-18"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert f"Study {sid}: 5 of 58 conclusions change" in out
    assert "DPYSL3, PAICS, PDE4DIP, PLAGL1, SLC25A5" in out
    assert "every run counted as on cfx-1" in out
    assert main(["report", "run-review", "--json"]) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["ledger"]["study_id"] == sid and review["ledger_note"] == ""
    _registry(store).register("cfx-1", "CFX")
    log = ["instrument", "lookback", "--instrument", "cfx-1", "--from", "2008-03-11",
           "--to", "2008-03-11", "--log"]  # fmt: skip
    assert main(log) == 0
    assert "0 of 58 conclusions change" in capsys.readouterr().out
    [event] = Logbook("cfx-1", store.root / "instruments").events(kinds=["lookback"])
    assert event.actor == "human" and event.payload["studies"][0]["n_changed"] == 0
