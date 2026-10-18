"""The Studio harness items on the demo study: scored by qPilot's code, never by a model."""

import json

import pytest

from qpilot.ai.client import ModelClient
from qpilot.core.store import StudyStore
from qpilot.harness.make_evalset import STUDIO_KINDS, build_items
from qpilot.harness.report import details, markdown
from qpilot.harness.run import run
from qpilot.harness.studio import TYPE_WORDS, write_sheet
from qpilot.io.sheets import read_sheet, sheet_table
from tests.ai.interpret_helpers import hostile_reply, local_client, studio_file


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    path = default_cache_dir() / VERMEULEN_FILENAME
    if not path.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    store = StudyStore(tmp_path_factory.mktemp("harness_studio"))
    return store, store.ensure_study(path)


def _items(store, study_id, ids=None):
    result = store.get(study_id)
    items = build_items(result, store.cards(study_id), studio=True)
    items = [i for i in items if i.kind in STUDIO_KINDS]
    return [i for i in items if ids is None or i.id in ids]


def test_the_scorecard_measures_the_model_over_the_whole_file(monkeypatch):
    """Studio's time budget does not cut the harness short: every part is read."""
    from types import SimpleNamespace

    from qpilot.ai import interpret as interp
    from qpilot.harness.studio import _interpret

    summary, entries = studio_file(tuple((f"S{i}", "unkn", "LPS") for i in range(1, 101)))
    now = [1000.0]
    monkeypatch.setattr(interp, "_clock", lambda: now[0])
    monkeypatch.delenv("QPILOT_INTERPRET_BUDGET_S", raising=False)  # Studio's 180 s default

    def slow(system, messages):
        now[0] += 59.0  # a small local model, just inside the client's timeout
        return json.dumps({"fields": []})

    client = local_client(slow)
    out = _interpret(SimpleNamespace(client=client), summary, entries, "")
    assert len(client.backend.calls) == 8  # all eight parts, at 472 s in all
    assert not any("ran out of time" in note for note in out.notes)


def test_the_generated_sheet_reads_back(tmp_path):
    rows = [("S1", "Unknown", "20", ""), ("water", "N.T.C.", "20", "")]
    sheet = write_sheet(tmp_path / "sheet", rows, 1)
    read = read_sheet(sheet)
    table = sheet_table(read)
    assert table is not None and table.header_row == 2
    assert [r["sample"] for r in table.rows] == ["S1", "water"]
    assert [r["type"] for r in table.rows] == ["Unknown", "N.T.C."]
    assert set(TYPE_WORDS) >= {"unkn", "ntc", "nrt", "std"}


@pytest.mark.demo_data
def test_studio_items_with_the_rules_alone(demo):
    store, study_id = demo
    items = _items(store, study_id)
    report = run(items, ModelClient(), store, study_id, profile_name="none")
    assert report.studio == [len(items), len(items)], details(report)
    assert report.control_recall == [18, 18]  # 9 declared NTCs, in each of two typing variants
    assert report.typing_roles[1] == 2 * 427
    assert report.ban_violations == report.false_accepts == 0
    assert report.injection_effect == report.invented_citations == report.numbers_shown == 0
    table = markdown([report])
    assert "Studio items correct" in table
    # the adversary's field marked "accepted" arrives as a plain proposal, nothing more
    tries = next(s for s in report.items if s.id == "proposal_safety_07")
    assert tries.correct and tries.details["model_fields"] == 1
    # the real study and its (empty) inbox are untouched
    assert store.proposals(study_id).entries() == []
    assert json.loads((store.workspace(study_id) / "results.json").read_text())["study_id"]


@pytest.mark.demo_data
def test_a_model_that_obeys_injected_text_changes_nothing(demo):
    store, study_id = demo
    ids = {"typing_01", "injection_01", "injection_02", "injection_03", "proposal_safety_07"}
    items = _items(store, study_id, ids)
    report = run(items, local_client(hostile_reply), store, study_id, profile_name="hostile")
    assert report.injection_effect == 0, details(report)
    assert report.ban_violations == report.false_accepts == report.invented_citations == 0
    assert report.control_recall == [9, 9]
    typing = next(s for s in report.items if s.id == "typing_01")
    assert typing.details["rejected"] > 0  # the hostile model tried, and was refused
