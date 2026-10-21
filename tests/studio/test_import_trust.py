"""The Import Trust card in the engine: the cap, Cq only, and a person's choice in Studio.

The policy (:mod:`qpilot.io.trust`), the cap (:mod:`qpilot.core.confidence`), the Cq-only
quantities (:mod:`qpilot.qpcr.curves`), the design that carries both
(``StudyDesign.import_trust``) and :meth:`qpilot.studio_service.Studio.decide_import_trust` on
the mini file walked as if opened from an instrument export (``tests/fixtures/studio/trust.py``):
its curves were baseline-subtracted by the vendor, and its gene is Moderate before any cap.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qpilot.core.card_kinds import requires_human
from qpilot.core.confidence import Cap, grade
from qpilot.core.proposals import verify_proposal_chain
from qpilot.core.record import rerun_compare, write_record
from qpilot.core.store import StudyStore
from qpilot.io import trust
from qpilot.io.rdml_io import load
from qpilot.qpcr import curves as qcurves
from qpilot.qpcr.study import StudySettings
from qpilot.schemas import Check
from qpilot.schemas_studio import ImportTrust, MarkerSplit, StudyDesign
from qpilot.studio_service import TRUST_KIND, Studio, StudioError, trust_option
from tests.fixtures.studio import trust as fixture

REASON = "the CFX export was baseline-subtracted; the instrument's Cq values are what we report"


def chk(cid: str, passed: bool) -> Check:
    return Check(id=cid, passed=passed, note=f"{cid} {'ok' if passed else 'failed'}")


# ---- the cap ---------------------------------------------------------------------------------

CAP = Cap(level="Moderate", check_id="import_trust", note="qPilot caps confidence at Moderate")


def test_a_cap_holds_a_grade_down_and_says_why():
    g = grade("High", [chk("precision", True)], cap=CAP)
    assert g.level == "Moderate"
    assert g.reasons == ["qPilot caps confidence at Moderate"]
    assert g.checks[-1] == Check(id="import_trust", passed=False, note=CAP.note)


def test_a_cap_never_lets_an_upgrade_through():
    g = grade("Moderate", [chk("normalisation", True)], lambda c: True, cap=CAP)
    assert g.level == "Moderate" and g.reasons == [CAP.note]


def test_a_cap_above_the_grade_changes_nothing_but_is_reported():
    g = grade("High", [chk("precision", False), chk("robustness", False)], cap=CAP)
    assert g.level == "Low"
    assert g.reasons == ["precision failed", "robustness failed"]  # not the cap: it did not bind
    assert [c.id for c in g.checks] == ["precision", "robustness", "import_trust"]


def test_no_cap_is_the_grade_as_before():
    checks = [chk("precision", False), chk("assay", True)]
    assert grade("High", checks) == grade("High", checks, cap=None)
    assert [c.id for c in grade("High", checks).checks] == ["precision", "assay"]


def test_a_cap_is_never_one_more_downgrading_check():
    with pytest.raises(ValueError, match="downgrading"):
        grade("High", [], cap=Cap(level="Low", check_id="precision", note="x"))


# ---- the policy ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verdict", "card"),
    [
        ("baseline_subtracted", True),
        ("unknown", True),
        ("normalized", False),  # Rn keeps the ground phase: what LinRegPCR expects from ABI
        ("raw", False),
        ("scaled", False),
        ("cq_only", False),
        (None, False),
    ],
)
def test_which_imports_get_the_card(verdict, card):
    assert (trust.card_verdict(verdict) is not None) is card


def test_the_caps_are_moderate_as_imported_and_low_on_cq_only():
    for verdict in trust.CARD_VERDICTS:
        caps = trust.caps(verdict)
        assert {o: c.level for o, c in caps.items()} == {
            "reexport_raw": "Moderate",
            "analyse_as_is": "Moderate",
            "cq_only": "Low",
        }
        for cap in caps.values():
            assert cap.note.startswith("qPilot caps confidence at")  # policy, said as policy
            assert not any(ch.isdigit() for ch in cap.note)  # no naked number in a reason
    assert "vendor-baselined curves" in trust.caps("baseline_subtracted")["analyse_as_is"].note
    assert "efficiency assumed" in trust.caps("baseline_subtracted")["cq_only"].note
    assert trust.cap_for(None) is None


def test_the_card_is_a_registered_kind_only_a_person_decides():
    card = trust.trust_card("baseline_subtracted", connector_id="cfx", n_instrument_cq=10)
    assert card.kind == "capture.import_trust" and card.id == "card_import_trust"
    assert [o.id for o in card.options] == ["reexport_raw", "analyse_as_is", "cq_only"]
    assert card.recommended == "reexport_raw" and card.evidence["in_use"] == "analyse_as_is"
    assert requires_human(card)
    assert "No Baseline Subtraction" in card.evidence["recipe"]
    assert "Delta Rn" in trust.recipe("quantstudio") and trust.recipe("tidy") == trust._RECIPE
    with pytest.raises(ValueError):
        trust.trust_card("raw", connector_id="cfx")


@pytest.mark.parametrize(
    ("option", "verdict", "n_cq", "status"),
    [
        ("analyse_as_is", "baseline_subtracted", 0, "consistent"),
        ("cq_only", "unknown", 3, "consistent"),
        ("cq_only", "baseline_subtracted", 0, "contradicted"),  # nothing left without curves
        ("reexport_raw", None, 3, "contradicted"),  # this import calls for no card
        ("trust_me", "baseline_subtracted", 3, "contradicted"),
        (None, "baseline_subtracted", 3, "contradicted"),
    ],
)
def test_d_trust_refutes_only_what_the_engine_can_see(option, verdict, n_cq, status):
    found = trust.check(option, verdict, n_cq)
    assert found.status == status and found.rule_ids == ["D-TRUST"]


def test_the_sessions_verdict_is_read_from_capture_json(tmp_path):
    assert trust.session_verdict(tmp_path) is None
    (tmp_path / "capture.json").write_text(
        json.dumps({"schema": "x", "meta": {"rawness": {"study_verdict": "normalized"}}})
    )
    assert trust.session_verdict(tmp_path) is None  # Rn: no card
    record = {"schema": "x", "meta": {"rawness": {"study_verdict": "baseline_subtracted"}}}
    (tmp_path / "capture.json").write_text(json.dumps(record) + " ")
    assert trust.session_verdict(tmp_path) == "baseline_subtracted"
    (tmp_path / "capture.json").write_text("{not json")
    assert trust.session_verdict(tmp_path) is None


# ---- the design and the curves ---------------------------------------------------------------


def _design(**extra) -> StudyDesign:
    return StudyDesign(mode="marker_split", marker_split=MarkerSplit(marker="X"), **extra)


def test_no_import_trust_leaves_every_design_hash_as_it_was():
    plain = _design()
    assert "import_trust" not in plain.canonical()
    trusted = _design(import_trust=ImportTrust(verdict="baseline_subtracted"))
    assert trusted.design_hash() != plain.design_hash()
    cq_only = _design(import_trust=ImportTrust(verdict="baseline_subtracted", analysis="cq_only"))
    assert cq_only.design_hash() != trusted.design_hash()
    assert StudySettings.from_design(trusted).curves == qcurves.CurveSettings()
    assert StudySettings.from_design(cq_only).curves.quantities == "instrument_cq"


def test_the_default_curve_settings_keep_every_cache_key():
    """``quantities`` at its default is not hashed: caches written before it stay valid."""
    default = qcurves.CurveSettings()
    before = {
        "pcrEfficiencyExl": 0.05,
        "excludeNoPlateau": True,
        "excludeEfficiency": "outlier",
        "maxCycExpPhase": 9,
        "ignoreExclusion": False,
    }
    assert default.fields() == before == default.linregpcr()
    assert qcurves.CurveSettings(quantities="instrument_cq").key() != default.key()
    path = qcurves.cache_path("ab" * 32, "e", ("R",), default, Path("/c"))
    config = json.dumps({"experiment": "e", "refs": ["R"], "settings": before}, sort_keys=True)
    import hashlib

    assert path.name == f"{'ab' * 32}.{hashlib.sha256(config.encode()).hexdigest()[:12]}.curves.csv"
    with pytest.raises(ValueError):
        qcurves.CurveSettings(quantities="vendor")


def test_cq_only_quantities_are_two_to_the_minus_instrument_cq():
    table = pd.DataFrame(
        {
            "run_id": ["p", "p", "p"],
            "well": ["A1", "A2", "A3"],
            "sample": ["s1", "s2", "s3"],
            "sample_type": ["unkn", "unkn", "ntc"],
            "target": ["G", "G", "G"],
            "target_raw": ["G", "G", "G"],
            "target_type": ["toi"] * 3,
            "excluded": ["", "amplification in negative control", ""],
            "note": ["", "", ""],
            "baseline": [1.0, 1.0, 1.0],
            "eff_indiv": [1.9, 1.8, np.nan],
            "r2": [0.99, 0.98, np.nan],
            "eff_target": [1.85] * 3,
            "eff_target_sd": [0.02] * 3,
            "cq": [21.0, 25.0, np.nan],
            "n0": [1e-6, 1e-7, np.nan],
            "amplification": [True, True, False],
            "plateau": [True, True, False],
        }
    )
    out = qcurves.instrument_quantities(table, {("p", "A1", "G"): 20.0, ("p", "A3", "G"): 33.5})
    assert out["cq"].tolist()[0] == 20.0 and math.isnan(out["cq"][1]) and out["cq"][2] == 33.5
    assert out["n0"][0] == 2.0**-20 and math.isnan(out["n0"][1]) and out["n0"][2] == 2.0**-33.5
    assert out["amplification"].tolist() == [True, False, True] == out["plateau"].tolist()
    assert (out["eff_target"] == 2.0).all() and out["eff_indiv"].isna().all()
    assert out["r2"].isna().all() and out["baseline"].isna().all()
    assert (out["excluded"] == "").all() and (out["note"] == qcurves.INSTRUMENT_NOTE).all()
    assert list(out.columns) == list(qcurves.COLUMN_ORDER)


def test_the_instrument_cq_is_read_from_the_rdml_cq_elements(tmp_path):
    from tests.fixtures.studio import studio_mini

    path = studio_mini.write_studio_mini(tmp_path / "m.rdml", instrument_cq=True)
    found = qcurves.instrument_cq(load(path), "mini_set")
    assert found[("GAPDH_plate", "A1", "GAPDH")] == 22.0  # WT_1's first replicate
    assert len(found) == 49  # 60 wells but the flat ones (water and NTC; one NTC on 1-Mar)
    plain = studio_mini.write_studio_mini(tmp_path / "plain.rdml")
    assert qcurves.instrument_cq(load(plain), "mini_set") == {}
    settings = qcurves.CurveSettings(quantities="instrument_cq")
    table = qcurves.analyse_study(path, "mini_set", ("GAPDH",), settings, cache_dir=tmp_path / "c")
    keyed = {(r.run_id, r.well, r.target_raw): r.cq for r in table.itertuples()}
    assert all(keyed[k] == v for k, v in found.items())
    assert table["n0"].isna().sum() == len(table) - len(found)  # the flat wells: no Cq
    again = qcurves.analyse_study(path, "mini_set", ("GAPDH",), settings, cache_dir=tmp_path / "c")
    pd.testing.assert_frame_equal(table, again)  # its own cache entry


# ---- a person decides in Studio --------------------------------------------------------------


@pytest.fixture(scope="module")
def trusted_base(tmp_path_factory):
    """The mini file walked as an instrument export with baseline-subtracted curves (once)."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect

    base = tmp_path_factory.mktemp("trusted")
    root = base / "data"
    root.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_DATA_ROOTS", str(root))
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        qinspect.clear_cache()
        rdml = fixture.write_trusted_mini(root)
        studio = Studio(StudyStore(base / "studies"), client=ModelClient(backend=NoneBackend()))
        sid, study = fixture.walk_trusted(studio, rdml)
        design_checks._DECLARED.clear()
        design_checks.set_input_resolver(None)
        qinspect.clear_cache()
    return {"base": base, "root": root, "sid": sid, "study": study}


@pytest.fixture
def trusted(trusted_base, tmp_path, monkeypatch):
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect

    shutil.copytree(trusted_base["base"], tmp_path / "w", symlinks=False)
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(trusted_base["root"]))
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(tmp_path / "w" / "studies"))
    qinspect.clear_cache()
    store = StudyStore(tmp_path / "w" / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    yield {"store": store, "studio": studio, **trusted_base, "tmp": tmp_path}
    design_checks._DECLARED.clear()
    design_checks.set_input_resolver(None)
    qinspect.clear_cache()


def grades(store: StudyStore, study: str) -> dict[str, tuple[str, list[str], list[str]]]:
    result = store.get(study)
    return {g: (c.level, c.reasons, [k.id for k in c.checks]) for g, c in result.confidence.items()}


def test_curves_as_imported_are_capped_before_anyone_decides(trusted):
    store, studio, sid, study = (
        trusted["store"],
        trusted["studio"],
        trusted["sid"],
        trusted["study"],
    )
    assert studio.results_visible(sid)  # the blind confirmations do not cover the verdict
    design = store.design(study)
    assert design.import_trust == ImportTrust(verdict="baseline_subtracted", analysis="as_is")
    ((level, reasons, checks),) = grades(store, study).values()
    assert level == "Moderate" and checks[-1] == "import_trust"
    assert trust_option(studio.store.proposals(sid).accepted()) is None


def test_the_same_file_opened_as_rdml_has_no_card_and_no_cap(trusted):
    store, studio, sid = trusted["store"], trusted["studio"], trusted["sid"]
    (Path(store.find_session(sid)) / "capture.json").unlink()
    plain = studio.study(sid)
    assert store.design(plain).import_trust is None
    ((_, _, checks),) = grades(store, plain).values()
    assert "import_trust" not in checks
    with pytest.raises(StudioError, match="no Import Trust card"):
        studio.decide_import_trust(sid, "cq_only", "human", REASON, study_id=plain)


def test_analysing_as_is_records_the_choice_and_keeps_the_analysis(trusted):
    store, studio, sid, study = (
        trusted["store"],
        trusted["studio"],
        trusted["sid"],
        trusted["study"],
    )
    done = studio.decide_import_trust(sid, "analyse_as_is", "human", REASON, study_id=study)
    assert done.status == "decided" and not done.changed and done.option == "analyse_as_is"
    assert studio.study(sid) == study
    (p,) = (p for p in studio.inbox(sid, "curves") if p.kind == TRUST_KIND)
    assert p.status == "accepted" and p.made_by.kind == "rule" and p.made_by.provider == trust.MAKER
    assert p.decided_by == "human" and p.reason == REASON and p.check.status == "consistent"
    assert p.consequence == {
        "import_trust": {"option": "analyse_as_is", "analysis": "as_is", "cap": "Moderate"}
    }
    with pytest.raises(StudioError, match="already the decision"):
        studio.decide_import_trust(sid, "analyse_as_is", "human", REASON, study_id=study)
    assert studio.results_visible(sid)
    inbox = store.proposals(sid)
    assert verify_proposal_chain(inbox.entries(), inbox.root) is None


def test_cq_only_is_a_new_analysis_from_the_instruments_cq_capped_at_low(trusted):
    store, studio, sid, study = (
        trusted["store"],
        trusted["studio"],
        trusted["sid"],
        trusted["study"],
    )
    done = studio.decide_import_trust(sid, "cq_only", "human", REASON, study_id=study)
    assert done.status == "decided" and done.changed
    assert studio.results_visible(sid)  # choosing never re-opens the blind stages
    cq = studio.study(sid)
    assert cq != study
    assert store.design(cq).import_trust.analysis == "cq_only"
    ((level, reasons, checks),) = grades(store, cq).values()
    assert level == "Low" and checks[-1] == "import_trust"
    assert reasons[-1] == trust.caps("baseline_subtracted")["cq_only"].note  # the cap binds
    # the numbers are 2^-ΔΔCq on the instrument's Cq: KO is six cycles later on 1-Mar, one
    # (mean of the crossings) later on GAPDH
    contrast = store.get(cq).contrasts["1-Mar"]
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    from tests.fixtures.studio.studio_mini import PLATES

    ko_gene = mean([mean(fixture.STRONG_KO["KO_1"]), mean(fixture.STRONG_KO["KO_2"])])
    wt_gene = mean([mean(PLATES["1-Mar"]["WT_1"]), mean(PLATES["1-Mar"]["WT_2"])])
    ko_ref = mean([mean(PLATES["GAPDH"]["KO_1"]), mean(PLATES["GAPDH"]["KO_2"])])
    wt_ref = mean([mean(PLATES["GAPDH"]["WT_1"]), mean(PLATES["GAPDH"]["WT_2"])])
    expected = -((ko_gene - ko_ref) - (wt_gene - wt_ref))  # KO vs WT (the comparison's order)
    assert abs(abs(contrast.log2fc) - abs(expected)) < 0.05
    # going back to the curves as imported is the first analysis again, decisions and all
    back = studio.decide_import_trust(
        sid, "reexport_raw", "human", "we will re-export", study_id=cq
    )
    assert back.changed and studio.study(sid) == study


def test_a_choice_needs_a_person_a_reason_the_results_and_the_analysis_in_use(trusted):
    studio, sid, study = trusted["studio"], trusted["sid"], trusted["study"]
    from qpilot.core.proposals import ProposalError

    with pytest.raises(StudioError, match="only a person"):
        studio.decide_import_trust(sid, "cq_only", "agent", REASON, study_id=study)
    with pytest.raises(ProposalError, match="reason"):
        studio.decide_import_trust(sid, "cq_only", "human", "  ", study_id=study)
    with pytest.raises(ValueError, match="no option"):
        studio.decide_import_trust(sid, "trust_me", "human", REASON, study_id=study)
    stale = studio.decide_import_trust(sid, "cq_only", "human", REASON, study_id="0" * 12)
    assert stale.status == "stale"
    head = studio.head(sid)
    studio.decide_import_trust(sid, "analyse_as_is", "human", REASON, study_id=study)
    late = studio.decide_import_trust(sid, "cq_only", "human", REASON, expected_head=head)
    assert late.status == "stale"
    assert trust_option(studio.store.proposals(sid).accepted()) == "analyse_as_is"


def test_a_choice_is_refused_while_the_results_are_hidden(trusted):
    from qpilot.mcp_server import QpilotTools

    studio, sid = trusted["studio"], trusted["sid"]
    QpilotTools(studio.store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says KO")
    assert not studio.results_visible(sid)
    with pytest.raises(StudioError, match="results stay hidden"):
        studio.decide_import_trust(sid, "cq_only", "human", REASON)
    with pytest.raises(StudioError, match="results stay hidden"):
        studio.request_import_trust(sid, "cq_only", REASON)


def test_cq_only_needs_the_instruments_cq(trusted_base, tmp_path, monkeypatch):
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import inspect as qinspect

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    qinspect.clear_cache()
    rdml = fixture.write_trusted_mini(root, instrument_cq=False)
    studio = Studio(StudyStore(tmp_path / "studies"), client=ModelClient(backend=NoneBackend()))
    sid, study = fixture.walk_trusted(studio, rdml, instrument_cq=False)
    with pytest.raises(StudioError, match="no Cq values from the instrument"):
        studio.decide_import_trust(sid, "cq_only", "human", REASON, study_id=study)
    assert studio.decide_import_trust(sid, "reexport_raw", "human", REASON).status == "decided"
    qinspect.clear_cache()


def test_an_agent_asks_and_the_persons_click_answers(trusted):
    studio, sid, study = trusted["studio"], trusted["sid"], trusted["study"]
    asked = studio.request_import_trust(sid, "cq_only", "Delta Rn export", agent="claude")
    assert asked.status == "pending_human" and "Only a person" in asked.reason
    (request,) = asked.proposals
    assert request.status == "proposed" and request.made_by.kind == "agent"
    assert studio.study(sid) == study  # nothing applied
    assert request.id not in studio.consistent_ids(sid, "curves")  # never in Accept all
    done = studio.decide_import_trust(sid, "cq_only", "human", REASON, study_id=study)
    (approved,) = done.proposals  # no rule proposal: the agent's request asked for this
    assert approved.id == request.id and approved.status == "accepted"
    assert approved.decided_by == "human" and approved.reason == REASON
    already = studio.request_import_trust(sid, "cq_only", "again", agent="claude")
    assert already.status == "pending_human" and already.proposals == []
    cq = studio.study(sid)
    other = studio.request_import_trust(sid, "analyse_as_is", "as it is", study_id=cq)
    back = studio.decide_import_trust(sid, "reexport_raw", "human", "re-export", study_id=cq)
    by_id = {p.id: p for p in back.proposals}
    assert by_id[other.proposals[0].id].status == "rejected"  # turned down by the same click
    (made,) = (p for p in back.proposals if p.made_by.kind == "rule")
    assert made.status == "accepted" and made.payload == {"option": "reexport_raw"}


def test_the_engine_checks_an_agents_proposal_of_the_kind(trusted):
    from qpilot.mcp_server import QpilotTools

    tools, sid = QpilotTools(trusted["studio"].store), trusted["sid"]
    good = tools.qpcr_propose(sid, TRUST_KIND, "import", {"option": "cq_only"})
    assert good["proposal"]["check"]["status"] == "consistent"
    assert good["proposal"]["check"]["details"] == {
        "n_instrument_cq": 49,
        "verdict": "baseline_subtracted",
    }
    bad = tools.qpcr_propose(sid, TRUST_KIND, "import", {"option": "trust_me"})
    assert bad["proposal"]["check"]["status"] == "contradicted"
    elsewhere = tools.qpcr_propose(sid, TRUST_KIND, "GAPDH", {"option": "cq_only"})
    assert elsewhere["proposal"]["check"]["status"] == "contradicted"


def test_a_record_of_a_cq_only_analysis_re_runs_to_the_same_bytes(trusted):
    store, studio, sid, study = (
        trusted["store"],
        trusted["studio"],
        trusted["sid"],
        trusted["study"],
    )
    studio.decide_import_trust(sid, "cq_only", "human", REASON, study_id=study)
    cq = studio.study(sid)
    record = Path(write_record(store, cq, trusted["tmp"] / "rec").record_dir)
    saved = json.loads((record / "study_design.json").read_text())
    assert saved["import_trust"] == {"verdict": "baseline_subtracted", "analysis": "cq_only"}
    report = rerun_compare(record, trusted["tmp"] / "rerun")
    assert report.same, report.differs


def test_history_names_the_click_that_made_the_cq_only_analysis(trusted):
    from qpilot.history.studio import milestones

    store, studio, sid, study = (
        trusted["store"],
        trusted["studio"],
        trusted["sid"],
        trusted["study"],
    )
    studio.decide_import_trust(sid, "cq_only", "human", REASON, study_id=study)
    studio.study(sid)
    _, producing, intact = milestones(store.find_session(sid))
    assert intact
    words = [said for _, _, said, _ in producing]
    assert words[-1] == f"Import Trust: Use the instrument's Cq values only: {REASON}"
    assert producing[-1][3] == "cq_only"


@pytest.mark.demo_data
def test_on_the_demo_the_cap_is_a_ceiling_never_a_downgrade(demo_rdml_path):
    """The demo with its curves called vendor-baselined: no number moves, no grade goes down.

    The demo's best genes are Moderate (21 of 58), exactly the cap: every grade and reason stays
    as it was, and every grade reports the cap among its checks.
    """
    from qpilot.qpcr.designs import vermeulen_design
    from qpilot.qpcr.study import run_study

    plain, _, _ = run_study(demo_rdml_path)
    design = vermeulen_design().model_copy(
        update={"import_trust": ImportTrust(verdict="baseline_subtracted")}
    )
    capped, _, _ = run_study(demo_rdml_path, StudySettings.from_design(design))
    assert capped.study_id != plain.study_id
    assert sum(c.level == "Moderate" for c in plain.confidence.values()) == 21
    for gene, before in plain.confidence.items():
        after = capped.confidence[gene]
        assert after.level == before.level and after.reasons == before.reasons
        assert after.checks[:-1] == before.checks and after.checks[-1].id == "import_trust"
        assert capped.contrasts[gene] == plain.contrasts[gene]
        assert capped.robustness[gene] == plain.robustness[gene]


def test_processed_curves_rule_out_the_efficiency_models_they_cannot_support(trusted):
    """The efficiency axis (ui/numbers) never tests what the import's processing rules out."""
    from qpilot.qpcr.study import run_study

    store, studio, sid, study = (
        trusted["store"],
        trusted["studio"],
        trusted["sid"],
        trusted["study"],
    )
    design = store.design(study).model_copy(
        update={"axes": {"efficiency": ("linregpcr", "per_well", "assumed_2")}}
    )
    for analysis, gone in (
        ("as_is", {"per_well"}),
        ("cq_only", {"per_well", "assumed_2"}),
    ):
        chosen = design.model_copy(
            update={"import_trust": ImportTrust(verdict="baseline_subtracted", analysis=analysis)}
        )
        result, _, grid = run_study(studio.source(sid), StudySettings.from_design(chosen))
        said = {
            f.id.removeprefix("f_axis_efficiency_unavailable_"): f.value
            for f in result.facts.values()
            if f.id.startswith("f_axis_efficiency_unavailable_")
        }
        assert gone <= set(said), (analysis, said)
        assert said["per_well"] == trust.not_measured(chosen.import_trust)["per_well"]
        tested = set(grid["efficiency"]) if "efficiency" in grid.columns else {"linregpcr"}
        assert not (tested & gone), (analysis, tested)
    assert trust.not_measured(None) == {}
