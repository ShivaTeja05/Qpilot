"""Studio with three groups and a donor column: the rules propose a paired plan, a person decides.

On the synthetic three-group file with a sample sheet (Sample, Group, Donor): the donor column
gives one donor to samples of three groups, so the rules propose pairings (``design.pair``), not
biological units; with three groups and a control-like name the rule proposes each group against
Control, Holm-corrected and paired by donor; accepted, the confirmed design analyses every
comparison. A person can edit the plan before accepting it, e.g. switch the correction off.
"""

from __future__ import annotations

import pytest

from qpilot.ai.client import ModelClient, NoneBackend
from qpilot.core.store import StudyStore
from qpilot.qpcr import design_checks
from qpilot.qpcr import inspect as qinspect
from qpilot.studio_service import _TIME_ZERO, Studio, _all_pairs, _vs_control
from tests.fixtures.studio.compare_mini import samples, write_compare_mini


@pytest.fixture
def walk(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    qinspect.clear_cache()
    rows = ["Sample,Group,Donor"] + [f"{s},{g},{d}" for s, (g, d) in samples().items()]
    sheet = root / "samples.csv"
    sheet.write_text("\n".join(rows) + "\n")
    store = StudyStore(tmp_path / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    yield studio, store, studio.open(write_compare_mini(root / "compare_mini.rdml"), sheet)
    design_checks._DECLARED.clear()
    design_checks.set_input_resolver(None)
    qinspect.clear_cache()


def _accept_design(studio: Studio, sid: str) -> None:
    studio.propose_design(sid)
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "checked" if p.check.status == "contradicted" else "")


def test_a_donor_column_pairs_and_three_groups_get_a_paired_plan(walk):
    studio, store, sid = walk
    _accept_design(studio, sid)
    accepted = store.proposals(sid).accepted("design.")
    pairs = {p.subject: p.effective_payload() for p in accepted if p.kind == "design.pair"}
    assert pairs["DrugA_D2"] == {"pair": "D2", "by": "donor"}
    assert len(pairs) == 12
    assert not [p for p in accepted if p.kind == "design.bio_unit"]
    outcome = studio.propose_comparison(sid)
    assert outcome is not None and outcome.status == "proposed"
    proposal = outcome.proposal
    assert proposal.level == "Moderate"
    payload = proposal.payload
    assert payload["pattern"] == "vs_control" and payload["control"] == "Control"
    assert payload["pair_by"] == "donor" and payload["correction"] == "holm"
    assert [(c["group_a"], c["group_b"]) for c in payload["comparisons"]] == [
        ("Drug A", "Control"),
        ("Drug B", "Control"),
    ]
    assert proposal.alternatives[0]["pattern"] == "all_pairs"
    studio.accept(sid, proposal.id, "human", "Control is the vehicle")
    design = studio.assemble(sid).design
    assert design is not None and design.comparisons is not None
    assert design.comparisons.pair_by == "donor"
    assert design.samples["DrugB_D4"].pair == "D4"


def test_a_person_edits_the_plan_before_accepting_it(walk):
    studio, store, sid = walk
    _accept_design(studio, sid)
    proposal = studio.propose_comparison(sid).proposal
    edits = {"correction": "none", "pair_by": None}
    done = studio.edit(sid, proposal.id, "human", edits, "pre-registered without correction")
    assert done.status in ("edited", "accepted")
    plan = studio.assemble(sid).design.comparisons
    assert plan.correction == "none" and plan.pair_by is None


def test_rule_words_for_controls_and_pairs():
    for name in ("0 h", "0h", "Day 0", "T0", "t=0", "time 0"):
        assert _TIME_ZERO.search(name), name
    for name in ("10 h", "24 h", "DIP 24 h", "day 10", "1.0 h", "Hm"):
        assert not _TIME_ZERO.search(name), name
    plan = _vs_control(["A", "B", "Ctrl"], "Ctrl")
    assert plan["group_a"] == "A" and len(plan["comparisons"]) == 2
    pairs = _all_pairs(["A", "B", "C"])
    assert [(c["group_a"], c["group_b"]) for c in pairs["comparisons"]] == [
        ("B", "A"),
        ("C", "A"),
        ("C", "B"),
    ]
