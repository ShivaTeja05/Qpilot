"""Studio's gates against an agent over MCP, on the synthetic file (no download, no model).

Each test drives the real entry points (``Studio``, the MCP tools, the proposal store) the way a
person in the dashboard and an agent over MCP share one study store, and pins one gate:

- the sheet's unit column holds the hard ban through every propose and accept;
- an agent's flood never refuses the system's proposals or a person's confirm step;
- a dilution series in any other shape than ``{sample: quantity}`` is refused;
- only the system's confirm step confirms a stage; an agent cannot propose one;
- an agent's ``qpcr_inspect`` never re-binds the sheet or the input of an open session;
- the study analysed is exactly the design the blind gate checked;
- an agent's pending request on a Decision Card never re-opens a confirmed Choices stage;
- a down local model is reported as such, with the reason, and a partial answer as partial;
- a model that hangs never stalls the page; a misconfigured one says what is wrong;
- a failing Design Interpreter still leaves the rules' proposals in the inbox;
- "Does this matter?" assembles each reading as accepting it would;
- a file the Curve Judge cannot read leaves LinRegPCR alone instead of failing every target;
- a curve the Curve Judge cannot score is never shown or proposed as "not amplified".
"""

from __future__ import annotations

import re
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from qpilot import studio_service
from qpilot.ai.client import ModelClient, ModelUnavailable, NoneBackend
from qpilot.core import proposals as proposals_module
from qpilot.core.proposals import ProposalStore
from qpilot.core.store import StudyStore
from qpilot.mcp_server import QpilotTools
from qpilot.qpcr import curve_judge, design_checks
from qpilot.qpcr import inspect as qinspect
from qpilot.qpcr.designs import design_curves
from qpilot.schemas_studio import DesignField, MadeBy, Proposal
from qpilot.studio_service import CURVE_JUDGE_FILE, Studio, StudioError
from qpilot.studio_state import model_line_html
from tests.fixtures.studio.studio_mini import INJECTION, write_studio_mini

GROUPS = {"WT_1": "WT", "WT_2": "WT", "KO_1": "KO", "KO_2": "KO"}
PERSON_SHEET = "Sample,Group,Mouse\nWT_1,WT,M1\nWT_2,WT,M2\nKO_1,KO,M3\nKO_2,KO,M4\n"
AGENT_SHEET = "Sample,Group,Mouse\nWT_1,KO,M1\nWT_2,WT,M1\nKO_1,WT,M3\nKO_2,KO,M3\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """The mini file in a data root, one store, the person's Studio and the agent's tools."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    qinspect.clear_cache()
    store = StudyStore(tmp_path / "studies")
    out = SimpleNamespace(
        root=root,
        rdml=write_studio_mini(root / "mini.rdml"),
        store=store,
        studio=Studio(store, client=ModelClient(backend=NoneBackend())),
        tools=QpilotTools(store),
    )
    yield out
    design_checks._DECLARED.clear()
    design_checks.set_input_resolver(None)
    qinspect.clear_cache()


def _sheet(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.write_text(text)
    return path


def _design_ready(env, sid: str) -> None:
    """The rules propose, the agent proposes the groups, a person accepts everything."""
    env.studio.propose_design(sid)
    for sample, group in GROUPS.items():
        env.tools.qpcr_propose(sid, "design.group", sample, {"group": group})
    for p in env.studio.inbox(sid, "design", "proposed"):
        env.studio.accept(sid, p.id, "human", "checked" if p.check.status == "contradicted" else "")
    comparison = env.studio.propose_comparison(sid)
    if comparison is not None and comparison.status == "proposed":
        env.studio.accept(sid, comparison.proposal.id, "human", "checked")


def _confirm(env, sid: str, stage: str) -> None:
    outcome = env.studio.propose_confirm(sid, stage)
    assert outcome.status == "proposed", outcome.reason
    assert env.studio.accept(sid, outcome.proposal.id, "human").status == "accepted"


def _blind_stages_confirmed(env, sid: str) -> None:
    _design_ready(env, sid)
    _confirm(env, sid, "design")
    env.studio.propose_curves(sid)
    for p in env.studio.inbox(sid, "curves", "proposed"):
        env.studio.accept(sid, p.id, "human", "checked")
    _confirm(env, sid, "curves")
    assert env.studio.results_visible(sid)


def _confirmed(env, sid: str) -> dict[str, bool]:
    return {s.stage: s.confirmed for s in env.studio.stages(sid)}


# ---- c5: the sheet's unit column holds the hard ban through propose and accept --------------


def test_a_sheets_units_hold_the_ban_through_every_propose_and_accept(env):
    sheet = _sheet(env.root, "person.csv", PERSON_SHEET)
    sid = env.studio.open(env.rdml, sheet)
    report = env.studio.propose_design(sid)  # every rule proposal runs the engine check first
    assert report["proposed"]
    merge = env.tools.qpcr_propose(sid, "design.bio_unit", "WT_1", {"biological_unit": "M2"})
    assert merge["status"] == "refused" and "merges two confirmed units" in merge["reason"]
    model = Proposal(
        study_id=sid,
        kind="design.bio_unit",
        subject="KO_1",
        payload={"biological_unit": "M4"},
        made_by=MadeBy(kind="model"),
    )
    refused = env.store.proposals(sid).propose(model, "system")
    assert refused.status == "refused" and "merges" in refused.reason

    # one stored before this rule (written without the guard) is still refused on accept, also
    # in a process that has not read the input yet
    home, root = env.store.proposal_home(sid)
    legacy = ProposalStore.at(home, root).propose(
        Proposal(
            study_id=sid,
            kind="design.bio_unit",
            subject="WT_2",
            payload={"biological_unit": "M1"},
            made_by=MadeBy(kind="agent"),
        ),
        "agent",
    )
    assert legacy.status == "proposed"
    design_checks._DECLARED.clear()
    qinspect.clear_cache()
    outcome = env.studio.accept(sid, legacy.proposal.id, "human", "looks right")
    assert outcome.status == "refused" and "merges" in outcome.reason
    units = {p.subject for p in env.store.proposals(sid).accepted("design.bio_unit")}
    assert "WT_2" not in units


def test_a_changed_sheet_fails_closed_for_units(env):
    sheet = _sheet(env.root, "person.csv", PERSON_SHEET)
    sid = env.studio.open(env.rdml, sheet)
    sheet.write_text(PERSON_SHEET.replace("M4", "M9"))
    design_checks._DECLARED.clear()
    out = env.tools.qpcr_propose(sid, "design.bio_unit", "WT_1", {"biological_unit": "M2"})
    assert out["status"] == "refused" and "sample sheet" in out["reason"]
    with pytest.raises(StudioError, match="sample sheet"):
        env.studio.sheet(sid)


# ---- c6 and c8: an agent's flood never refuses the system or a person's confirm step -------


def test_an_agent_flood_of_history_cannot_stop_the_design_confirm(env, monkeypatch):
    sid = env.studio.open(env.rdml)
    _design_ready(env, sid)
    size = env.store.proposals(sid).path.stat().st_size
    monkeypatch.setattr(proposals_module, "MAX_CHAIN_BYTES", size + 150_000)
    big = {"group": "WT", "note": "x" * 1_900}
    evidence = [{"kind": "sample", "ref": "WT_1", "note": "y" * 1_900}] * 30
    statuses = []
    for _ in range(12):
        out = env.tools.qpcr_propose(sid, "design.group", "WT_1", big, evidence=evidence)
        statuses.append(out["status"])
        if out["status"] == "refused":
            break
    assert statuses[-1] == "refused"
    for p in env.studio.inbox(sid, "design", "proposed"):
        env.studio.reject(sid, p.id, "human", "not this")
    _confirm(env, sid, "design")  # the system's confirm step and the person's click both work
    assert _confirmed(env, sid)["design"]
    assert env.studio.propose_curves(sid)["proposed"]  # and the rules can still propose


def test_hidden_agent_proposals_cannot_fill_the_pending_cap_for_a_person(env, monkeypatch):
    sid = env.studio.open(env.rdml)
    _design_ready(env, sid)
    monkeypatch.setattr(proposals_module, "MAX_PENDING", 3)
    outcomes = [  # in the closed curves stage: no person sees them yet
        env.tools.qpcr_propose(sid, "curve.well_call", f"GAPDH_plate/{well}", {"amplified": True})
        for well in ("A1", "A2", "A3", "A4")
    ]
    assert [o["status"] for o in outcomes] == ["proposed"] * 3 + ["refused"]
    hidden = env.tools.qpcr_propose(sid, "stage.confirm", "s7", {"stage": "s7"})
    assert "error" in hidden and "stage.confirm" in hidden["error"]
    assert {s.stage: s.pending for s in env.studio.stages(sid)}["design"] == 0
    _confirm(env, sid, "design")
    assert _confirmed(env, sid)["design"]
    assert env.studio.propose_curves(sid)["proposed"]  # the rule's call proposal is not refused


# ---- c7: a dilution series is an object of sample to quantity, or it is refused -------------


def test_a_series_given_as_a_list_cannot_demote_a_confirmed_control(env):
    sid = env.studio.open(env.rdml)
    water = env.tools.qpcr_propose(sid, "design.well_role", "water", {"role": "ntc"})
    assert env.studio.accept(sid, water["proposal"]["id"], "human", "checked").status == "accepted"
    pairs = [["water", 1], ["STD_100", 100], ["STD_1000", 1000], ["STD_10000", 10000]]
    as_list = env.tools.qpcr_propose(sid, "design.dilution_series", "STD", {"samples": pairs})
    assert as_list["status"] == "refused" and "sample to quantity" in as_list["reason"]
    clean = [["STD_100", 100], ["STD_1000", 1000]]
    shape = env.tools.qpcr_propose(sid, "design.dilution_series", "STD", {"samples": clean})
    assert shape["status"] == "refused"
    as_mapping = env.tools.qpcr_propose(
        sid, "design.dilution_series", "STD", {"samples": dict(pairs)}
    )
    assert as_mapping["status"] == "refused" and "control" in as_mapping["reason"]

    # a list-form series already in an inbox can never be accepted either
    home, root = env.store.proposal_home(sid)
    legacy = ProposalStore.at(home, root).propose(
        Proposal(
            study_id=sid,
            kind="design.dilution_series",
            subject="STD",
            payload={"samples": pairs},
            made_by=MadeBy(kind="agent"),
        ),
        "agent",
    )
    outcome = env.studio.accept(sid, legacy.proposal.id, "human", "ok")
    assert outcome.status == "refused"
    roles = [p.effective_payload() for p in env.store.proposals(sid).accepted("design.")]
    assert roles == [{"role": "ntc"}]


# ---- s2, s3: only the system's confirm step confirms a stage --------------------------------


def test_an_agent_cannot_propose_a_confirm_step(env):
    sid = env.studio.open(env.rdml)
    _design_ready(env, sid)
    design_hash = env.studio.assemble(sid).design_hash
    out = env.tools.qpcr_propose(
        sid, "stage.confirm", "design", {"stage": "design", "design_hash": design_hash}
    )
    assert "error" in out and not env.store.proposals(sid).proposals(kind_prefix="stage.")
    inbox = env.store.proposals(sid)
    for maker, actor in (("agent", "agent"), ("rule", "agent"), ("model", "system")):
        confirm = Proposal(
            study_id=sid,
            kind="stage.confirm",
            subject="design",
            payload={"stage": "design", "design_hash": design_hash, "covers": []},
            made_by=MadeBy(kind=maker),
        )
        refused = inbox.propose(confirm, actor)
        assert refused.status == "refused", (maker, actor)
    assert not _confirmed(env, sid)["design"]
    _confirm(env, sid, "design")  # the system's own confirm step still works
    assert _confirmed(env, sid)["design"]


def test_an_agents_confirm_already_in_an_inbox_neither_shows_nor_counts(env, monkeypatch):
    sid = env.studio.open(env.rdml)
    _design_ready(env, sid)
    design_hash = env.studio.assemble(sid).design_hash
    with monkeypatch.context() as earlier:  # an inbox written before the store refused them
        earlier.setattr(proposals_module, "_check_maker", lambda p, actor: None, raising=False)
        planted = env.store.proposals(sid).propose(
            Proposal(
                study_id=sid,
                kind="stage.confirm",
                subject="design",
                payload={"stage": "design", "design_hash": design_hash, "covers": []},
                made_by=MadeBy(kind="agent"),
            ),
            "agent",
        )
    assert planted.status == "proposed"
    assert planted.proposal.id not in {p.id for p in env.studio.inbox(sid, "design")}
    assert env.studio.accept(sid, planted.proposal.id, "human").status == "accepted"
    assert not _confirmed(env, sid)["design"]
    _confirm(env, sid, "design")
    assert _confirmed(env, sid)["design"]


# ---- c9: an agent's inspect never re-binds an open session ----------------------------------


def test_an_agents_inspect_never_rebinds_the_sheet_or_the_input(env):
    person_sheet = _sheet(env.root, "person.csv", PERSON_SHEET)
    agent_sheet = _sheet(env.root, "agent.csv", AGENT_SHEET)
    sid = env.studio.open(env.rdml, person_sheet)
    agents_copy = env.root / "agents_copy.rdml"
    agents_copy.write_bytes(env.rdml.read_bytes())

    plain = env.tools.qpcr_inspect(str(agents_copy))  # no sheet: the person's stays
    assert plain["session_id"] == sid
    assert env.studio.sheet(sid) == person_sheet.resolve()
    assert env.store.session_source(sid) == env.rdml.resolve()
    swapped = env.tools.qpcr_inspect(str(env.rdml), str(agent_sheet))
    assert "error" in swapped and "sample sheet" in swapped["error"]
    assert env.studio.sheet(sid) == person_sheet.resolve()
    same = env.tools.qpcr_inspect(str(env.rdml), str(person_sheet))
    assert same["session_id"] == sid

    env.studio.propose_design(sid)
    groups = {
        p.subject: p.payload["group"]
        for p in env.studio.inbox(sid, "design", "proposed")
        if p.kind == "design.group" and p.made_by.kind == "rule"
    }
    assert all(groups.get(sample) == group for sample, group in GROUPS.items())
    cited = {e.ref for p in env.studio.inbox(sid, "design") for e in p.evidence}
    assert any(ref.startswith("person!") for ref in cited)
    assert not any(ref.startswith("agent!") for ref in cited)
    assert not any("agent.csv" in q.origin for q in env.studio.quarantined(sid))


def test_a_person_binds_what_they_open(env):
    agent_sheet = _sheet(env.root, "agent.csv", AGENT_SHEET)
    first = env.tools.qpcr_inspect(str(env.rdml), str(agent_sheet))  # a new session: bound
    sid = first["session_id"]
    assert env.studio.sheet(sid) == agent_sheet.resolve()
    assert env.studio.open(env.rdml) == sid  # the person opens it without a sheet
    assert env.studio.sheet(sid) is None
    again = env.tools.qpcr_inspect(str(env.rdml), str(agent_sheet))
    assert "error" in again and env.studio.sheet(sid) is None


# ---- c10: the study analysed is the design the gate checked ---------------------------------


def test_the_study_analysed_is_the_design_the_gate_checked(env, monkeypatch):
    sid = env.studio.open(env.rdml)
    _blind_stages_confirmed(env, sid)
    confirmed = env.studio.study(sid)
    agent = env.tools.qpcr_propose(sid, "design.group", INJECTION, {"group": "KO"})
    assert agent["status"] == "proposed"
    real = Studio.assemble
    fired: list[str] = []

    def racing(pid: str):
        def assemble(self, session_id, *args, **kwargs):
            out = real(self, session_id, *args, **kwargs)
            if not fired:  # a person's accept lands right after the gate read the inbox
                fired.append(pid)
                env.studio.accept(session_id, pid, "human")
            return out

        return assemble

    with monkeypatch.context() as race:
        race.setattr(Studio, "assemble", racing(agent["proposal"]["id"]))
        out = env.tools.qpcr_study(str(env.rdml), design={"session": sid})
    assert fired and out.get("study_id") == confirmed
    assert not env.studio.results_visible(sid)  # the accept re-opened the design
    with pytest.raises(StudioError, match="results stay hidden"):
        env.studio.study(sid)

    # the dashboard's own path: confirm the changed design, then race a change back
    _confirm(env, sid, "design")
    _confirm(env, sid, "curves")
    second = env.studio.study(sid)
    back = env.tools.qpcr_propose(sid, "design.group", INJECTION, {"group": "WT"})
    fired.clear()
    with monkeypatch.context() as race:
        race.setattr(Studio, "assemble", racing(back["proposal"]["id"]))
        assert env.studio.study(sid) == second
    assert fired and not env.studio.results_visible(sid)


# ---- s1: an agent's request never re-opens a confirmed Choices stage ------------------------


def test_an_agents_request_does_not_reopen_confirmed_choices(env):
    sid = env.studio.open(env.rdml)
    _blind_stages_confirmed(env, sid)
    study = env.studio.study(sid)
    for card in env.store.cards(study):
        if card.status != "auto_decided":
            head = env.store.chain_head(study)
            env.studio.decide(sid, card.id, card.recommended, "checked", "human", head)
    _confirm(env, sid, "choices")
    card = next(c for c in env.store.cards(study) if len(c.options) > 1)
    other = next(o.id for o in card.options if o.id != card.decision)
    asked = env.tools.qpcr_decide(study, card.id, other, "just asking")
    assert asked["status"] == "pending_human"
    assert _confirmed(env, sid)["choices"]
    project = env.studio.propose_prism(sid)
    assert env.studio.accept(sid, project.proposal.id, "human").status == "accepted"
    sent = env.studio.send_to_prism(sid, env.root / "bundle", "human")
    assert Path(sent.out_dir).exists()
    # a person who changes an applied option does re-open it
    head = env.store.chain_head(study)
    env.studio.decide(sid, card.id, other, "the other one after all", "human", head)
    assert not _confirmed(env, sid)["choices"]


# ---- c24: a down model is reported, with the reason; a partial answer is partial -----------


class _Down:
    """A local endpoint that refuses every connection (nothing listens)."""

    name = "openai_compatible"
    model = "qwen2.5:7b"
    url = "http://127.0.0.1:9/v1/chat/completions"
    timeout = 60.0

    def __init__(self, cause: Exception | None = None):
        self.cause = cause
        self.calls: list[int] = []  # shared with any copy of this backend

    def complete(self, system, messages, max_tokens, temperature):
        self.calls.append(max_tokens)
        name = type(self.cause).__name__ if self.cause else "ConnectError"
        raise ModelUnavailable(f"endpoint call failed: {name}") from self.cause


class _NotFound(Exception):
    response = SimpleNamespace(status_code=404)


def test_a_down_local_model_is_reported_with_its_reason(env):
    down = _Down()
    studio = Studio(env.store, client=ModelClient(backend=down))
    status = studio.model_status()
    assert status["local"] and status["configured"]
    assert status["available"] is False and "ConnectError" in status["reason"]
    assert studio.model_status()["available"] is False and down.calls == [1]  # once a minute
    sid = studio.open(env.rdml)
    report = studio.propose_design(sid)
    assert report["fallback"] is True and report["model_fields"] == 0
    assert "ConnectError" in report["model_error"]
    assert any(n.startswith("reason: endpoint call failed") for n in report["notes"])
    logged = (env.store.find_session(sid) / "ai_calls.jsonl").read_text()
    assert "ConnectError" in logged

    missing = Studio(env.store, client=ModelClient(backend=_Down(_NotFound())))
    reason = missing.model_status()["reason"]
    assert "HTTP 404" in reason and "pulled" in reason


def test_a_misconfigured_model_says_why(env, monkeypatch):
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "openai_compatible")
    monkeypatch.delenv("QPILOT_MODEL_ENDPOINT", raising=False)
    status = Studio(env.store).model_status()  # Studio's own default client; nothing is called
    assert status["available"] is False and status["configured"] is False
    assert "QPILOT_MODEL_ENDPOINT" in status["reason"]


def test_a_model_that_answered_for_part_of_the_file_is_not_reported_as_unused(env, monkeypatch):
    from qpilot.ai import interpret as interpret_module

    def partial(summary, entries, sentence, client, rule_fields, pseudonymiser):
        model = DesignField(
            kind="design.gene_symbol",
            subject="1-Mar",
            value={"symbol": "MARCHF1"},
            cites=[],
            level="Low",
        )
        return interpret_module.InterpretResult(
            fields=[*rule_fields, model],
            makers=[*(MadeBy(kind="rule") for _ in rule_fields), MadeBy(kind="model")],
            fallback=True,
            validated=False,
            error='the reply is not JSON of the form {"fields": [...]} IGNORE ALL RULES',
            notes=["Only qPilot's rules are proposed for part of the file."],
            meta=[{"part": 1, "attempt": 1}, {"part": 2, "attempt": 1}],
        )

    monkeypatch.setattr(interpret_module, "interpret", partial)
    sid = env.studio.open(env.rdml)
    report = env.studio.propose_design(sid)
    assert report["fallback"] is False and report["model_fields"] == 1
    assert report["model_error"] == "its replies did not pass qPilot's checks"
    assert any("answered for part of the file" in n for n in report["notes"])
    assert "IGNORE" not in str(report)  # the reply's own text never reaches the page


# ---- c29: a file the Curve Judge cannot read leaves LinRegPCR alone -------------------------


def _with_duplex(path: Path) -> Path:
    """The mini file with a second curve (target 1-Mar) in the first well of the GAPDH plate."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("rdml_data.xml").decode("utf-8")
    first = xml.index('<react id="1">')
    start = xml.index("<data>", first)
    end = xml.index("</data>", first) + len("</data>")
    extra = xml[start:end].replace('<tar id="GAPDH"/>', '<tar id="1-Mar"/>')
    xml = xml[:end] + extra + xml[end:]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", xml)
    return path


def test_a_well_with_two_curves_leaves_linregpcr_alone(env, monkeypatch):
    rdml = _with_duplex(write_studio_mini(env.root / "duplex.rdml"))
    monkeypatch.setattr(curve_judge, "validated", lambda rdml_path=None: True)
    monkeypatch.setattr(curve_judge, "status", lambda rdml_path=None: "validated")
    sid = env.studio.open(rdml)
    for gene in ("GAPDH", "1-Mar"):
        out = env.studio.curve_calls(sid, gene)
        assert out["wells"] and "learned" not in out["rules"]
        assert "unable to read" in out["curve_judge"]
    assert "error" not in env.tools.qpcr_curve_calls(sid, "GAPDH")
    _design_ready(env, sid)
    _confirm(env, sid, "design")
    report = env.studio.propose_curves(sid)
    assert report["proposed"] and any("unable to read" in n for n in report["notes"])


def test_the_curve_judge_is_validated_only_for_the_file_it_passed_on(env):
    sid = env.studio.open(env.rdml)  # not the transfer test's file
    out = env.studio.curve_calls(sid, "GAPDH")
    assert "learned" not in out["rules"]
    assert out["curve_judge"] == curve_judge.NOT_VALIDATED


# ---- c27: a curve the Curve Judge cannot score is no call, never "not amplified" -----------


def _below_zero(path: Path, run: str) -> Path:
    """The mini file with every curve of one run shifted below zero (an offset export)."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("rdml_data.xml").decode("utf-8")
    start = xml.index(f'<run id="{run}">')
    end = xml.index("</run>", start)
    shifted = re.sub(
        r"<fluor>([-0-9.]+)</fluor>",
        lambda m: f"<fluor>{float(m.group(1)) - 2.0:.4f}</fluor>",
        xml[start:end],
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", xml[:start] + shifted + xml[end:])
    return path


def test_a_curve_the_curve_judge_cannot_score_is_never_not_amplified(env, monkeypatch):
    rdml = _below_zero(write_studio_mini(env.root / "offset.rdml"), "GAPDH_plate")
    calls = curve_judge.predict_calls(rdml, None)  # the real model on the real curves
    unscored = {k for k, v in calls.items() if v is None}
    assert unscored and all(k.startswith("GAPDH_plate/") for k in unscored)
    monkeypatch.setattr(curve_judge, "validated", lambda rdml_path=None: True)
    monkeypatch.setattr(curve_judge, "status", lambda rdml_path=None: "validated")
    sid = env.studio.open(rdml)
    # a cache written before unscored curves had no call held False for each of them
    old = {"key": f"{curve_judge.MODEL_SHA256}:None", "calls": dict.fromkeys(calls.index, False)}
    (env.store.find_session(sid) / CURVE_JUDGE_FILE).write_text(studio_service.dump_json(old))
    gapdh = env.studio.curve_calls(sid, "GAPDH")
    assert gapdh["curve_judge"] == "validated" and gapdh["wells"]
    assert not [w for w in gapdh["wells"] if "learned" in w["calls"]]
    assert all("learned" in w["calls"] for w in env.studio.curve_calls(sid, "1-Mar")["wells"])
    _design_ready(env, sid)
    _confirm(env, sid, "design")
    report = env.studio.propose_curves(sid)
    proposed = env.studio.inbox(sid, "curves", "proposed")
    assert not [p for p in proposed if p.subject.startswith("GAPDH_plate/")]
    assert any("cannot score" in n and "LinRegPCR alone there" in n for n in report["notes"])


# ---- R12: "Does this matter?" assembles each reading as accepting it would -----------------


def _declared(path: Path, sample: str, role: str) -> Path:
    """The mini file with one sample declared as ``role`` instead of a study sample."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("rdml_data.xml").decode("utf-8")
    old = f'<sample id="{sample}"><type>unkn</type>'
    assert old in xml
    xml = xml.replace(old, f'<sample id="{sample}"><type>{role}</type>')
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", xml)
    return path


def _sample_types(studio: Studio, sid: str, design, sample: str) -> dict[str, str]:
    table = design_curves(studio._curves_table(sid), design)
    return {sample: ",".join(sorted(set(table[table["sample"] == sample]["sample_type"])))}


def test_does_this_matter_assembles_each_reading_from_the_base(env, monkeypatch):
    rdml = _declared(write_studio_mini(env.root / "std.rdml"), "STD_100", "std")
    sid = env.studio.open(rdml)
    env.studio.propose_design(sid)
    for sample, group in GROUPS.items():
        env.tools.qpcr_propose(sid, "design.group", sample, {"group": group})
    for p in env.studio.inbox(sid, "design", "proposed"):
        if p.kind in ("design.group", "design.target_role"):
            env.studio.accept(sid, p.id, "human", "checked")
    env.studio.accept(sid, env.studio.propose_comparison(sid).proposal.id, "human", "checked")
    # a person made the declared standard a study sample (written well by well) ...
    unkn = env.tools.qpcr_propose(sid, "design.well_role", "STD_100", {"role": "unkn"})
    assert env.studio.accept(sid, unkn["proposal"]["id"], "human", "checked").status == "accepted"
    # ... and a new proposal says it is a standard after all
    again = env.tools.qpcr_propose(
        sid, "design.well_role", "STD_100", {"role": "std"}, alternatives=[{"role": "unkn"}]
    )
    pending = env.store.proposals(sid).get(again["proposal"]["id"])

    def roles(self, session_id, design):  # stands in for the conclusions: what each reading is
        return _sample_types(self, session_id, design, "STD_100")

    monkeypatch.setattr(Studio, "_primary_conclusions", roles)
    assert env.studio.matters(sid, pending) is True  # a standard and a study sample differ
    env.studio.accept(sid, pending.id, "human", "checked")
    accepted = env.studio.assemble(sid).design
    assert _sample_types(env.studio, sid, accepted, "STD_100") == {"STD_100": "std"}


# ---- R13, c24: the model status never stalls the page and always says why -----------------


class _Hanging:
    """A local endpoint that takes the request and does not answer until released."""

    name = "openai_compatible"
    model = "qwen2.5:7b"
    url = "http://127.0.0.1:11434/v1/chat/completions"
    timeout = 60.0

    def __init__(self, hold_s: float = 3.0):
        self.release = threading.Event()
        self.hold_s = hold_s
        self.calls: list[int] = []  # shared with any copy of this backend

    def complete(self, system, messages, max_tokens, temperature):
        self.calls.append(max_tokens)
        if not self.release.wait(self.hold_s):
            raise ModelUnavailable("endpoint call failed: ReadTimeout")
        return "OK"


def _eventually(check, timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_a_model_that_does_not_answer_never_stalls_the_page(env, monkeypatch):
    assert studio_service.PING_WAIT_S <= 2.0 and studio_service.PING_TTL_S >= 60.0
    # Wall clock on purpose: the property is that nothing waits for the model. A later call
    # must come back well inside the first call's wait (half of it, so a loaded machine's
    # scheduling delay is not mistaken for a wait); the first must end at all.
    wait = 1.0
    monkeypatch.setattr(studio_service, "PING_WAIT_S", wait)
    hanging = _Hanging()
    studio = Studio(env.store, client=ModelClient(backend=hanging))
    try:
        started = time.monotonic()
        status = studio.model_status()
        assert time.monotonic() - started < wait + 2.0
        assert status["checking"] and status["answers"] is None and not status["available"]
        assert "checking whether it answers" in model_line_html(status)
        started = time.monotonic()
        assert studio.model_status()["checking"] and time.monotonic() - started < wait / 2
        assert hanging.calls == [1]  # one request out, not one per page render
        hanging.release.set()
        assert _eventually(lambda: studio.model_status()["available"])
        # asked again once the answer is old, in the background: the last answer stands meanwhile
        hanging.release.clear()
        monkeypatch.setattr(studio_service, "PING_TTL_S", 0.0)
        started = time.monotonic()
        assert studio.model_status()["available"] and time.monotonic() - started < wait / 2
        assert _eventually(lambda: len(hanging.calls) == 2)
    finally:
        hanging.release.set()


def test_a_down_model_is_shown_as_configured_but_not_answering(env):
    studio = Studio(env.store, client=ModelClient(backend=_Down()))
    line = model_line_html(studio.model_status())
    assert "configured but not answering: endpoint call failed: ConnectError" in line
    assert "no model is called" not in line


def test_the_http_status_of_a_down_model_reaches_the_propose_report(env):
    studio = Studio(env.store, client=ModelClient(backend=_Down(_NotFound())))
    assert "HTTP 404" in studio.model_status()["reason"]
    sid = studio.open(env.rdml)
    report = studio.propose_design(sid)
    assert "HTTP 404" in report["model_error"] and "pulled" in report["model_error"]
    assert any("HTTP 404" in n for n in report["notes"])
    assert "HTTP 404" in studio.model_status()["reason"]  # a real call keeps the precise reason


@pytest.mark.parametrize(
    ("env_vars", "why"),
    [
        ({"QPILOT_MODEL_PROVIDER": "openai_compatible"}, "QPILOT_MODEL_ENDPOINT"),
        ({"QPILOT_MODEL_ENDPOINT": "https://models.example.org/v1"}, "not on this machine"),
    ],
)
def test_a_misconfigured_model_says_why_on_the_page_and_with_each_propose(
    env, monkeypatch, env_vars, why
):
    for name in ("QPILOT_MODEL_PROVIDER", "QPILOT_MODEL_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env_vars.items():
        monkeypatch.setenv(name, value)
    studio = Studio(env.store)  # Studio's own default client; nothing is called
    status = studio.model_status()
    assert status["misconfigured"] and why in status["reason"] and not status["available"]
    assert why in model_line_html(status) and "cannot be used" in model_line_html(status)
    sid = studio.open(env.rdml)
    report = studio.propose_design(sid)
    assert report["proposed"] and report["fallback"] is True
    assert why in report["model_error"]
    assert any(why in n for n in report["notes"])


# ---- R15: a failing Design Interpreter never loses the rules' proposals --------------------


def test_a_failing_design_interpreter_still_stores_the_rules_proposals(env, monkeypatch):
    from qpilot.ai import interpret as interpret_module

    def broken(*args, **kwargs):
        raise TypeError("a bug in the interpreter")

    monkeypatch.setattr(interpret_module, "interpret", broken)
    sid = env.studio.open(env.rdml)
    report = env.studio.propose_design(sid)
    stored = env.studio.inbox(sid, "design", "proposed")
    assert report["proposed"] and len(stored) == len(report["proposed"])
    assert all(p.made_by.kind == "rule" for p in stored)
    assert report["fallback"] is True and "failed (TypeError)" in report["model_error"]
    assert any("Design Interpreter failed" in n for n in report["notes"])
