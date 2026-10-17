"""Studio end to end on the demo: blind stages, human-only gates, Prism round trip.

The plan's ``qpilot studio demo --check``: demo -> proposals -> a person's accepts (the test's
human actor) -> Prism export -> a value excluded in Prism -> re-read -> the engine's numbers.
"""

import math
import shutil
from collections import Counter
from pathlib import Path

import pytest

from qpilot.ai.client import ModelClient, NoneBackend
from qpilot.core.proposals import ProposalError
from qpilot.core.store import StudyStore
from qpilot.studio_service import Studio, StudioError

pytestmark = pytest.mark.demo_data
REASON = "checked the evidence"


@pytest.fixture(scope="module")
def walk(tmp_path_factory):
    """Walk the demo through every stage once; the tests below read what happened."""
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    root = tmp_path_factory.mktemp("studio")
    studio = Studio(StudyStore(root / "studies"), client=ModelClient(backend=NoneBackend()))
    log: dict = {"root": root}
    sid = studio.open(DEMO_RDML)
    log["sid"] = sid
    log["design_report"] = studio.propose_design(sid)
    log["design_inbox"] = studio.inbox(sid, "design", "proposed")
    log["blind_design"] = _hidden(studio, sid)
    preset = next(p for p in log["design_inbox"] if p.kind == "design.preset")
    studio.accept(sid, preset.id, "human")
    ids = studio.consistent_ids(sid, "design")
    log["bulk"] = studio.accept_all_consistent(sid, "design", "human", ids)
    left = studio.inbox(sid, "design", "proposed")
    log["design_left"] = left
    studio.reject_many(sid, [p.id for p in left], "human", "contradicted by the engine check")
    confirm = studio.propose_confirm(sid, "design").proposal
    studio.accept(sid, confirm.id, "human")
    log["curves_report"] = studio.propose_curves(sid)
    log["curves_inbox"] = studio.inbox(sid, "curves", "proposed")
    log["blind_curves"] = _hidden(studio, sid)
    calls = [p.id for p in log["curves_inbox"] if p.kind == "curve.well_call"]
    studio.reject_many(sid, calls, "human", "LinRegPCR fitted a complete early curve")
    rule = next(p for p in log["curves_inbox"] if p.kind == "curve.call_rule")
    studio.accept(sid, rule.id, "human")
    studio.accept(sid, studio.propose_confirm(sid, "curves").proposal.id, "human")
    study = studio.study(sid)
    log["study"] = study
    for card in studio.store.cards(study):
        if card.status != "auto_decided":
            head = studio.store.chain_head(study)
            studio.decide(sid, card.id, card.recommended, REASON, "human", head)
    studio.accept(sid, studio.propose_confirm(sid, "choices").proposal.id, "human")
    project = studio.propose_prism(sid).proposal
    studio.accept(sid, project.id, "human")
    bundle = root / "bundle"
    log["export"] = studio.send_to_prism(sid, bundle, "human")
    sent_back = root / "sent_back"
    sent_back.mkdir()
    for table in log["export"].bundle.tables:
        shutil.copy(bundle / table.csv, sent_back / Path(table.csv).name)
    odc1 = sent_back / "ODC1.csv"
    lines = odc1.read_text().split("\n")
    lines = [",".join([ln.split(",")[0], "", ""]) if ln.startswith("1496,") else ln for ln in lines]
    odc1.write_text("\n".join(lines))
    log["roundtrip"] = studio.round_trip(sid, bundle, sent_back)
    exclusion = next(iter(studio.inbox(sid, "roundtrip", "proposed")))
    log["exclusion"] = exclusion
    studio.accept(sid, exclusion.id, "human", "failed RNA extraction")
    log["stages_after"] = {s.stage: s for s in studio.stages(sid)}
    log["new_study"] = studio.study(sid)
    log["studio"] = studio
    return log


def _hidden(studio: Studio, sid: str) -> bool:
    try:
        studio.study(sid)
    except StudioError:
        pass
    else:
        return False
    try:
        studio.preview_prism(sid)
    except StudioError:
        return not studio.results_visible(sid)
    return False


def test_the_design_stage_proposes_with_engine_checks_and_stays_blind(walk):
    kinds = Counter((p.kind, p.check.status) for p in walk["design_inbox"])
    assert kinds[("design.preset", "cannot_check")] == 1
    assert kinds[("design.dilution_series", "consistent")] >= 6  # comp 00-40 (+ standards)
    assert kinds[("design.dilution_series", "contradicted")] >= 1  # comp 50, R2 0.707
    assert kinds[("design.well_role", "contradicted")] == 7  # the conc-64 level never amplified
    assert walk["blind_design"] and walk["blind_curves"]
    assert all(o.status == "accepted" for o in walk["bulk"])
    assert all(p.check.status == "contradicted" for p in walk["design_left"])


def test_the_curve_judge_blind_spot_reaches_the_scientist_as_contradicted(walk):
    calls = [p for p in walk["curves_inbox"] if p.kind == "curve.well_call"]
    assert calls, "the Curve Judge's disagreements that matter are proposed"
    assert {p.evidence[0].note for p in calls} == {"target ALUsq(Eurogentec)"}
    assert all(p.check.status == "contradicted" and p.check.rule_ids == ["D-CURVE"] for p in calls)
    assert all(p.consequence == {"matters": True} for p in calls)  # blind: no gene, no number


def test_the_analysis_is_the_engines(walk):
    result = walk["studio"].store.get(walk["study"])
    assert math.isclose(result.contrasts["ODC1"].fc, 3.5899, rel_tol=1e-4)
    assert result.robustness["ODC1"].n_cells == 744
    assert result.facts["f_n_differ_route_linear_welch"].value == 14


def test_prism_exclusion_becomes_a_question_with_its_consequence(walk):
    items = walk["roundtrip"]["items"]
    assert [(i["kind"], i["gene"], i["row"]) for i in items] == [("missing", "ODC1", "1496")]
    consequence = walk["exclusion"].consequence
    assert round(consequence["fc_before"], 3) == 3.590
    assert round(consequence["fc_after"], 3) == 3.319
    assert consequence["conclusion_after"] == "up"
    assert consequence["n_conclusions_changed"] == 0


def test_an_accepted_exclusion_reanalyses_and_reopens_the_choices(walk):
    stages = walk["stages_after"]
    assert stages["design"].confirmed and stages["curves"].confirmed
    assert not stages["choices"].confirmed  # a new analysis: its cards are decided afresh
    new = walk["studio"].store.get(walk["new_study"])
    assert walk["new_study"] != walk["study"]
    assert round(new.contrasts["ODC1"].fc, 3) == 3.319
    assert new.contrasts["ODC1"].conclusion == "up"


def test_only_a_person_decides_anything_in_studio(walk):
    studio, sid = walk["studio"], walk["sid"]
    before = studio.head(sid)
    pending = studio.propose_confirm(sid, "choices").proposal
    for actor in ("agent", "system"):
        with pytest.raises(ProposalError):
            studio.accept(sid, pending.id, actor)
        with pytest.raises((ProposalError, StudioError)):
            studio.edit(sid, pending.id, actor, {}, "x")
        with pytest.raises(StudioError):
            studio.send_to_prism(sid, walk["root"] / f"never-{actor}", actor)
        with pytest.raises(StudioError):
            studio.launch_prism(walk["export"], actor)
    assert not (walk["root"] / "never-agent").exists()
    assert studio.head(sid) != before  # only the system's confirm proposal was added
    assert studio.inbox(sid, status="proposed")[-1].id == pending.id


def test_the_record_carries_the_whole_studio_history(walk, tmp_path):
    from qpilot.core.record import verify, write_record

    studio = walk["studio"]
    info = write_record(studio.store, walk["new_study"], tmp_path / "record")
    report = verify(info.record_dir)
    assert report.ok, report.summary()
    assert (Path(info.record_dir) / "proposals.jsonl").exists()
    assert (Path(info.record_dir) / "study_design.json").exists()
