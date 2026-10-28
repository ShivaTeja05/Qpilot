"""The qPCR workflow end to end: one RDML file in, a checked, recorded, audited result out.

Stages, in the fixed order of qPilot Studio plus the simulator and the record::

    1 intake      the file (and optional sample sheet, one sentence); every name quarantined
    2 design      blind: the rules / Design Interpreter propose, the engine checks, a person decides
    3 curves      blind: the Curve Judge vs LinRegPCR, disagreements that matter, a person decides
    4 choices     results appear: the engine's analysis, robustness grid and Decision Cards
    5 simulator   the Decision Simulator audits the confirmed analysis (every combination of
                  its decisions), bound to the study; refused if it does not reproduce qPilot
    6 prism       the Prism draft, a person accepts it, Send to Prism writes the bundle
    7 roundtrip   what changed in Prism comes back as questions; an accepted exclusion re-runs
                  the analysis (and the audit)
    8 record      the Analysis Record of the final analysis, verified, with the audit bound to it
    9 agents      the MCP server with the simulator's read-only tools; an agent cannot decide

**Who decides.** Every accept, reject, decision, Prism export and launch is a person's action
(``actor="human"``); the pipeline itself proposes and computes only. In Studio the person is
the page. Here the person is an explicit :class:`Person` object passed in by the caller, and
every one of its actions is logged with its reason in ``workflow.json``. :class:`ScriptedPerson`
is the policy of ``qpilot studio demo --check`` (accept what the engine finds consistent,
reject what it contradicts, keep the recommended options). It exists for checks and demos; it is
not a substitute for a scientist reading the cards.

Nothing is written outside ``out_dir`` and the study store passed in.
"""

from __future__ import annotations

import json
import shutil
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from qpilot.explain.words import plural

HUMAN = "human"
STAGES = (
    "intake",
    "design",
    "curves",
    "choices",
    "simulator",
    "prism",
    "roundtrip",
    "record",
    "agents",
)


# ---------------------------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------------------------


@dataclass
class Step:
    """One thing that happened: who did it (``system`` or ``human``), with what reason."""

    stage: str
    action: str
    actor: str
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Check:
    """One checked expectation; ``ok`` False is a failure the report names."""

    stage: str
    label: str
    ok: bool
    got: Any = ""
    want: Any = ""


@dataclass
class WorkflowReport:
    """Everything one run did and found; ``ok`` when no check failed."""

    out_dir: str
    rdml: str
    session_id: str = ""
    study_id: str = ""
    final_study_id: str = ""
    steps: list[Step] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    timings_s: dict[str, float] = field(default_factory=dict)
    paths: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when no check failed."""
        return all(c.ok for c in self.checks)

    @property
    def failed(self) -> list[Check]:
        """The checks that failed."""
        return [c for c in self.checks if not c.ok]

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form, with the totals."""
        out = asdict(self)
        out["ok"] = self.ok
        out["n_checks"] = len(self.checks)
        out["n_failed"] = len(self.failed)
        return out


class Recorder:
    """Collects steps and checks into the report, and prints each as it happens."""

    def __init__(self, report: WorkflowReport, out: Callable[[str], None]) -> None:
        self.report, self.out = report, out
        self.stage = "intake"

    def begin(self, stage: str, title: str) -> None:
        self.stage = stage
        self.out(f"\n[{STAGES.index(stage) + 1}/{len(STAGES)}] {title}")

    def step(self, action: str, actor: str, reason: str = "", **detail: Any) -> None:
        self.report.steps.append(Step(self.stage, action, actor, reason, detail))
        who = "person" if actor == HUMAN else actor
        self.out(f"  {who:>7}: {action}" + (f"  (reason: {reason})" if reason else ""))

    def check(self, label: str, ok: bool, got: Any = "", want: Any = "") -> bool:
        self.report.checks.append(Check(self.stage, label, bool(ok), _plain(got), _plain(want)))
        if ok:
            self.out(f"     ok  {label}" + (f": {got}" if got != "" else ""))
        else:
            self.out(f"   FAIL  {label}: got {got!r}, expected {want!r}")
        return bool(ok)

    def note(self, stage: str, **values: Any) -> None:
        self.report.stages.setdefault(stage, {}).update({k: _plain(v) for k, v in values.items()})


def _plain(value: Any) -> Any:
    """JSON-ready (tuples, sets, numpy scalars, paths)."""
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
    except ImportError:  # pragma: no cover
        pass
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set | frozenset):
        return sorted(_plain(v) for v in value)
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------------------------
# The person
# ---------------------------------------------------------------------------------------------


class Person:
    """Who presses the buttons. Each method acts through Studio with ``actor="human"``.

    Subclass it to change the policy; every action must go through ``rec.step(..., HUMAN,
    reason)`` so the report says what the person did and why.
    """

    name = "person"

    def design(self, studio: Any, sid: str, rec: Recorder) -> None:
        """Decide the design stage's proposals, then confirm the stage."""
        raise NotImplementedError

    def curves(self, studio: Any, sid: str, rec: Recorder) -> None:
        """Decide the curve stage's proposals, then confirm the stage."""
        raise NotImplementedError

    def choices(self, studio: Any, sid: str, study: str, rec: Recorder) -> None:
        """Decide every open Decision Card, then confirm the choices."""
        raise NotImplementedError

    def prism(self, studio: Any, sid: str, rec: Recorder) -> None:
        """Have the Prism project drafted and accept it (or not)."""
        raise NotImplementedError

    def roundtrip(self, studio: Any, sid: str, rec: Recorder) -> None:
        """Answer each question that came back from Prism."""
        raise NotImplementedError


class ScriptedPerson(Person):
    """The policy of ``qpilot studio demo --check``, with its reasons (for checks and demos)."""

    name = "scripted person (qpilot studio demo --check policy)"

    def __init__(self, reasons: dict[str, str] | None = None) -> None:
        from qpilot.cli.studio_cmds import REASONS

        self.reasons = {**REASONS, **(reasons or {})}

    def design(self, studio: Any, sid: str, rec: Recorder) -> None:
        """Decide the design stage's proposals, then confirm the stage."""
        inbox = studio.inbox(sid, "design", "proposed")
        preset = next((p for p in inbox if p.kind == "design.preset"), None)
        if preset is not None:
            studio.accept(sid, preset.id, HUMAN, self.reasons["preset"])
            rec.step("accepted the published design preset", HUMAN, self.reasons["preset"])
        ids = studio.consistent_ids(sid, "design")
        listed = len(ids)
        if ids:
            studio.accept_all_consistent(sid, "design", HUMAN, ids, self.reasons["consistent"])
        rec.step(
            f"accepted the {listed} proposals the engine finds consistent",
            HUMAN,
            self.reasons["consistent"],
            n=listed,
        )
        rec.note("design", consistent_listed=listed)
        if preset is None:
            comparison = studio.propose_comparison(sid)
            if comparison is not None and comparison.proposal is not None:
                studio.accept(sid, comparison.proposal.id, HUMAN, self.reasons["consistent"])
                rec.step(
                    "accepted the comparison of the two groups",
                    HUMAN,
                    self.reasons["consistent"],
                    payload=comparison.proposal.payload,
                )
        left = studio.inbox(sid, "design", "proposed")
        statuses = Counter(p.check.status for p in left)
        rec.note("design", left_after_accept=len(left), left_by_check=dict(statuses))
        if left:
            studio.reject_many(sid, [p.id for p in left], HUMAN, self.reasons["design_rejects"])
            rec.step(
                f"rejected the {len(left)} proposals left",
                HUMAN,
                self.reasons["design_rejects"],
                by_check=dict(statuses),
            )
        confirm = studio.propose_confirm(sid, "design").proposal
        studio.accept(sid, confirm.id, HUMAN, "checked the design")
        rec.step("confirmed the design stage", HUMAN, "checked the design")

    def curves(self, studio: Any, sid: str, rec: Recorder) -> None:
        """Decide the curve stage's proposals, then confirm the stage."""
        inbox = studio.inbox(sid, "curves", "proposed")
        calls = [p for p in inbox if p.kind == "curve.well_call"]
        contradicted = [p.id for p in calls if p.check.status == "contradicted"]
        if contradicted:
            studio.reject_many(sid, contradicted, HUMAN, self.reasons["well_calls"])
            rec.step(
                f"rejected {len(contradicted)} Curve Judge well calls LinRegPCR contradicts",
                HUMAN,
                self.reasons["well_calls"],
            )
        rest = [p.id for p in calls if p.check.status != "contradicted"]
        if rest:
            studio.reject_many(sid, rest, HUMAN, "kept LinRegPCR's call for these wells")
            rec.step(
                f"kept LinRegPCR's call for {len(rest)} other wells",
                HUMAN,
                "kept LinRegPCR's call for these wells",
            )
        rule = next((p for p in inbox if p.kind == "curve.call_rule"), None)
        if rule is not None:
            studio.accept(sid, rule.id, HUMAN, self.reasons["rule"])
            rec.step(
                "accepted LinRegPCR as the amplification call rule",
                HUMAN,
                self.reasons["rule"],
                payload=rule.payload,
            )
        left = studio.inbox(sid, "curves", "proposed")
        if left:
            studio.reject_many(sid, [p.id for p in left], HUMAN, "not needed for this analysis")
            rec.step(
                f"rejected {len(left)} other curve proposals", HUMAN, "not needed for this analysis"
            )
        confirm = studio.propose_confirm(sid, "curves").proposal
        studio.accept(sid, confirm.id, HUMAN, "checked the curves")
        rec.step("confirmed the curves stage", HUMAN, "checked the curves")

    def choices(self, studio: Any, sid: str, study: str, rec: Recorder) -> None:
        """Decide every open Decision Card, then confirm the choices."""
        decided = 0
        for card in studio.store.cards(study):
            if card.status in ("auto_decided", "decided"):
                continue
            head = studio.store.chain_head(study)
            outcome = studio.decide(
                sid, card.id, card.recommended, self.reasons["cards"], HUMAN, head
            )
            decided += 1
            rec.step(
                f"decided {card.id}: {card.recommended}",
                HUMAN,
                self.reasons["cards"],
                status=getattr(outcome, "status", None),
                genes_it_can_flip=card.impact.get("n_genes_flipped"),
            )
        confirm = studio.propose_confirm(sid, "choices").proposal
        studio.accept(sid, confirm.id, HUMAN, "checked the analysis choices")
        rec.step(
            "confirmed the choices stage",
            HUMAN,
            "checked the analysis choices",
            cards_decided=decided,
        )

    def prism(self, studio: Any, sid: str, rec: Recorder) -> None:
        """Have the Prism project drafted and accept it (or not)."""
        project = studio.propose_prism(sid).proposal
        rec.step(
            "drafted the Prism project",
            "system",
            genes=project.payload.get("genes"),
            template=project.payload.get("template_id"),
        )
        studio.accept(sid, project.id, HUMAN, self.reasons["project"])
        rec.step("accepted the Prism project", HUMAN, self.reasons["project"])

    def roundtrip(self, studio: Any, sid: str, rec: Recorder) -> None:
        """Answer each question that came back from Prism."""
        for proposal in studio.inbox(sid, "roundtrip", "proposed"):
            if proposal.kind == "prism.exclusion_reason":
                studio.accept(sid, proposal.id, HUMAN, self.reasons["exclusion"])
                rec.step(
                    f"gave the reason for the exclusion of {proposal.subject}",
                    HUMAN,
                    self.reasons["exclusion"],
                    consequence=proposal.consequence,
                )
            else:
                studio.reject(sid, proposal.id, HUMAN, "restore the value from the record")
                rec.step(f"restored {proposal.subject}", HUMAN, "restore the value from the record")


def exclude_demo_sample(sent_back: Path) -> dict[str, str]:
    """What a scientist might do in Prism on the demo: leave ODC1's sample 1496 out."""
    odc1 = sent_back / "ODC1.csv"
    lines = odc1.read_text(encoding="utf-8").split("\n")
    lines = [",".join([ln.split(",")[0], "", ""]) if ln.startswith("1496,") else ln for ln in lines]
    odc1.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {"gene": "ODC1", "row": "1496", "edit": "value removed in Prism"}


# ---------------------------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------------------------


@dataclass
class Options:
    """How much of the pipeline to run and with what settings."""

    sheet: str | Path | None = None
    sentence: str = ""
    simulator: bool = True
    permutations: int = 999
    roundtrip_edit: Callable[[Path], dict[str, Any]] | None = None
    reaudit_after_roundtrip: bool = True
    agents: bool = True
    expected: dict[str, Any] | None = None  # demo numbers to check (None: no number checks)


def _blind(studio: Any, sid: str) -> bool:
    from qpilot.cli.studio_cmds import _hidden

    return _hidden(studio, sid)


def _timed(report: WorkflowReport, stage: str, started: float) -> None:
    report.timings_s[stage] = round(
        report.timings_s.get(stage, 0.0) + time.perf_counter() - started, 2
    )


def run_workflow(
    rdml: str | Path,
    out_dir: str | Path,
    store: Any,
    *,
    person: Person | None = None,
    client: Any = None,
    options: Options | None = None,
    out: Callable[[str], None] = print,
) -> WorkflowReport:
    """Run every stage on one RDML file; write ``workflow.json`` and ``WORKFLOW.md``.

    ``store`` is the :class:`qpilot.core.store.StudyStore` to use (give a new one for a check).
    ``client`` is the model client for the Design Interpreter and the Prism draft (default: no
    model, the rules alone, so every number is deterministic).
    """
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.studio_service import Studio

    options = options or Options()
    person = person or ScriptedPerson()
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"{out_dir} is not empty; give a new folder for the workflow")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = WorkflowReport(out_dir=str(out_dir), rdml=str(Path(rdml).resolve()))
    rec = Recorder(report, out)
    studio = Studio(store, client=client or ModelClient(backend=NoneBackend()))
    want = options.expected or {}
    out(
        f"qPilot workflow: {Path(rdml).name}; the person is: {person.name}; "
        f"model: {studio.model_status()['provider']}; study store {store.root}"
    )
    try:
        _stages(studio, Path(rdml), out_dir, person, options, want, rec)
    except Exception as err:  # a stage that stops is reported as a failed check, not a crash
        rec.check(
            f"the workflow stopped early in {rec.stage} ({type(err).__name__})",
            False,
            str(err),
            "no error",
        )
    _write_report(report, out_dir)
    out(
        f"\n{len(report.checks) - len(report.failed)} of {len(report.checks)} checks passed"
        + ("." if report.ok else f"; FAILED: {[c.label for c in report.failed]}")
    )
    out(f"report: {out_dir / 'WORKFLOW.md'}")
    return report


def _stages(  # noqa: PLR0915 (one function per stage would hide the order)
    studio: Any,
    rdml: Path,
    out_dir: Path,
    person: Person,
    options: Options,
    want: dict[str, Any],
    rec: Recorder,
) -> None:
    from qpilot.core.record import verify, write_record
    from qpilot.integration import simulator as sim

    report = rec.report

    # 1 intake -----------------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin("intake", "Intake: open the file; every name is quarantined, nothing is analysed")
    sid = studio.open(rdml, options.sheet)
    report.session_id = sid
    summary = studio.summary(sid)
    rec.step("opened the file", "system", session=sid)
    rec.note(
        "intake",
        samples=summary.n_samples,
        declared_types=summary.declared_types,
        experiments=summary.experiments,
        quarantined=len(studio.quarantined(sid)),
        model=studio.model_status(),
    )
    if "samples" in want:
        rec.check(
            "samples in the file",
            summary.n_samples == want["samples"],
            summary.n_samples,
            want["samples"],
        )
    rec.check(
        "nothing is visible before the design and curves are confirmed",
        _blind(studio, sid),
        True,
        True,
    )
    _timed(report, "intake", t)

    # 2 design (blind) ---------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin(
        "design",
        "Design (blind): the rules and the Design Interpreter propose, the engine "
        "checks, the person decides",
    )
    proposed = studio.propose_design(sid, options.sentence)
    inbox = studio.inbox(sid, "design", "proposed")
    by_kind = Counter(f"{p.kind}:{p.check.status}" for p in inbox)
    rec.step(
        f"proposed {len(proposed['proposed'])} design items",
        "system",
        fallback=proposed.get("fallback"),
        refused=len(proposed.get("refused", [])),
    )
    rec.note(
        "design",
        proposals=len(proposed["proposed"]),
        by_kind_and_check=dict(by_kind),
        interpreter_fallback=proposed.get("fallback"),
    )
    if "design_proposals" in want:
        rec.check(
            "design proposals (rules alone)",
            len(proposed["proposed"]) == want["design_proposals"],
            len(proposed["proposed"]),
            want["design_proposals"],
        )
    rec.check("still blind while the design is open", _blind(studio, sid), True, True)
    person.design(studio, sid, rec)
    if "consistent_listed" in want:
        got = report.stages["design"].get("consistent_listed")
        rec.check(
            "consistent proposals listed for the person",
            got == want["consistent_listed"],
            got,
            want["consistent_listed"],
        )
    if "contradicted_left" in want:
        got = report.stages["design"].get("left_after_accept")
        rec.check(
            "contradicted proposals left for the person",
            got == want["contradicted_left"],
            got,
            want["contradicted_left"],
        )
    _timed(report, "design", t)

    # 3 curves (blind) ---------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin("curves", "Curves (blind): the Curve Judge against LinRegPCR, only what matters")
    curves = studio.propose_curves(sid)
    cinbox = studio.inbox(sid, "curves", "proposed")
    well_calls = [p for p in cinbox if p.kind == "curve.well_call"]
    rec.step(
        f"proposed the call rule and {len(well_calls)} well calls",
        "system",
        disagreements=curves.get("disagreements"),
        targets_that_matter=curves.get("targets_that_matter"),
    )
    rec.note(
        "curves",
        disagreements=curves.get("disagreements"),
        well_calls=len(well_calls),
        targets_that_matter=curves.get("targets_that_matter"),
    )
    if "curve_judge_disagreements" in want:
        rec.check(
            "Curve Judge disagreements with LinRegPCR",
            curves.get("disagreements") == want["curve_judge_disagreements"],
            curves.get("disagreements"),
            want["curve_judge_disagreements"],
        )
    if "curve_judge_well_calls" in want:
        rec.check(
            "well calls that could matter",
            len(well_calls) == want["curve_judge_well_calls"],
            len(well_calls),
            want["curve_judge_well_calls"],
        )
    rec.check(
        "blind cards name no gene and no number",
        all(p.consequence in (None, {"matters": True}, {"matters": False}) for p in well_calls),
        True,
        True,
    )
    rec.check("still blind while the curves are open", _blind(studio, sid), True, True)
    person.curves(studio, sid, rec)
    rec.check(
        "results visible once both blind stages are confirmed",
        studio.results_visible(sid),
        True,
        True,
    )
    _timed(report, "curves", t)

    # 4 choices ----------------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin("choices", "Choices: the engine's analysis, robustness grid and Decision Cards")
    study = studio.study(sid)
    report.study_id = study
    result = studio.store.get(study)
    rec.step("analysed the confirmed design", "system", study=study)
    _note_result(rec, "choices", result, studio.store.cards(study))
    if "odc1_fc" in want and "ODC1" in result.contrasts:
        got = round(result.contrasts["ODC1"].fc, 3)
        rec.check("ODC1 fold change", got == want["odc1_fc"], got, want["odc1_fc"])
    if "grid_cells" in want:
        cells = next(iter(result.robustness.values())).n_cells
        rec.check(
            "analyses in qPilot's robustness grid",
            cells == want["grid_cells"],
            cells,
            want["grid_cells"],
        )
    if "route_linear_welch_differ" in want and "f_n_differ_route_linear_welch" in result.facts:
        got = result.facts["f_n_differ_route_linear_welch"].value
        rec.check(
            "conclusions the usual Excel->Prism route changes",
            got == want["route_linear_welch_differ"],
            got,
            want["route_linear_welch_differ"],
        )
    person.choices(studio, sid, study, rec)
    _timed(report, "choices", t)

    # 5 simulator --------------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin(
        "simulator",
        "Decision Simulator: audit the confirmed analysis under every "
        "combination of its analysis decisions",
    )
    audit_dir = out_dir / "simulator_audit"
    first_audit = _run_audit(rec, sim, studio.store, study, audit_dir, options, want)
    if first_audit is not None:
        report.paths["simulator_audit"] = str(audit_dir)
    _timed(report, "simulator", t)

    # 6 prism ------------------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin("prism", "Prism: the draft, the person's accept, Send to Prism")
    person.prism(studio, sid, rec)
    bundle_dir = out_dir / "prism_bundle"
    export = studio.send_to_prism(sid, bundle_dir, HUMAN)
    rec.step(
        "sent the study to Prism (bundle written)",
        HUMAN,
        "send to Prism",
        tables=len(export.bundle.tables),
        bundle_sha256=export.bundle.bundle_sha256,
    )
    report.paths["prism_bundle"] = str(bundle_dir)
    launch = studio.launch_prism(export, HUMAN, wait_s=0)
    rec.step("asked to open it in Prism", HUMAN, "open in Prism", **launch)
    from qpilot.prism import verify_provenance

    problems = verify_provenance(bundle_dir)
    rec.check("the bundle's provenance verifies", not problems, problems or "ok", "ok")
    rec.note(
        "prism",
        tables=[tb.gene for tb in export.bundle.tables],
        bundle_sha256=export.bundle.bundle_sha256,
        notes=list(export.notes),
        prism_launched=launch.get("launched"),
    )
    if first_audit is not None:
        bound = _bind_bundle(bundle_dir, first_audit)
        rec.check(
            "the audit is bound to the bundle (same study, input file and chain head)",
            bound["ok"],
            bound,
            "same study",
        )
        rec.note("prism", audit_binding=bound)
    _timed(report, "prism", t)

    # 7 roundtrip --------------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin("roundtrip", "Round trip: what changed in Prism comes back as questions")
    final_study = study
    if options.roundtrip_edit is None:
        rec.step("no Prism edit to bring back (skipped)", "system")
    else:
        sent_back = out_dir / "prism_sent_back"
        sent_back.mkdir()
        for table in export.bundle.tables:
            shutil.copy(bundle_dir / table.csv, sent_back / Path(table.csv).name)
        edit = options.roundtrip_edit(sent_back)
        rec.step("edited the tables in Prism and sent them back", HUMAN, "edited in Prism", **edit)
        trip = studio.round_trip(sid, bundle_dir, sent_back)
        items = [(i["kind"], i["gene"], i.get("row")) for i in trip["items"]]
        rec.step(f"found {len(items)} change(s) since export", "system", items=items)
        rec.note("roundtrip", items=items)
        questions = studio.inbox(sid, "roundtrip", "proposed")
        exclusion = next((p for p in questions if p.kind == "prism.exclusion_reason"), None)
        if exclusion is not None:
            c = exclusion.consequence or {}
            rec.note("roundtrip", consequence=c)
            if "odc1_fc_after" in want:
                rec.check(
                    "the exclusion's consequence, before the person answers",
                    round(c.get("fc_after", 0), 3) == want["odc1_fc_after"]
                    and c.get("n_conclusions_changed") == want["conclusions_changed"],
                    {k: c.get(k) for k in ("fc_before", "fc_after", "n_conclusions_changed")},
                    {
                        "fc_after": want["odc1_fc_after"],
                        "n_conclusions_changed": want["conclusions_changed"],
                    },
                )
        person.roundtrip(studio, sid, rec)
        status = {s.stage: s for s in studio.stages(sid)}
        if not status["choices"].confirmed:
            final_study = studio.study(sid)
            rec.step("re-analysed with the exclusion", "system", study=final_study)
            new = studio.store.get(final_study)
            _note_result(rec, "roundtrip", new, studio.store.cards(final_study))
            if "odc1_fc_after" in want and "ODC1" in new.contrasts:
                got = round(new.contrasts["ODC1"].fc, 3)
                rec.check(
                    "ODC1 after the exclusion (re-analysed)",
                    got == want["odc1_fc_after"],
                    got,
                    want["odc1_fc_after"],
                )
            person.choices(studio, sid, final_study, rec)
            if options.reaudit_after_roundtrip and first_audit is not None:
                again = out_dir / "simulator_audit_after_roundtrip"
                second = _run_audit(rec, sim, studio.store, final_study, again, options, {})
                if second is not None:
                    report.paths["simulator_audit_after_roundtrip"] = str(again)
                    changes = {
                        g: [first_audit.verdicts.get(g), v]
                        for g, v in second.verdicts.items()
                        if first_audit.verdicts.get(g) != v
                    }
                    rec.note("roundtrip", verdicts_changed_by_the_exclusion=changes)
                    rec.step(
                        f"the exclusion changes {plural(len(changes), 'simulator verdict')}",
                        "system",
                        changes=changes,
                    )
                    rec.check(
                        "the re-audit sees the person's exclusion",
                        second.manifest["scope"]["wells_excluded_by_a_person"] >= 1,
                        second.manifest["scope"]["wells_excluded_by_a_person"],
                        ">= 1",
                    )
    report.final_study_id = final_study
    _timed(report, "roundtrip", t)

    # 8 record -----------------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin("record", "Analysis Record: export, verify, and bind the audit")
    info = write_record(studio.store, final_study, out_dir / "record")
    verified = verify(info.record_dir)
    rec.step("exported the Analysis Record", "system", record_id=info.record_id, files=info.n_files)
    rec.check(
        "the record verifies (checksums, decision and proposal chains)",
        verified.ok,
        verified.summary(),
        "ok",
    )
    report.paths["record"] = str(info.record_dir)
    audit_for_record = (
        report.paths.get("simulator_audit_after_roundtrip")
        if final_study != study
        else report.paths.get("simulator_audit")
    )
    if audit_for_record:
        check = sim.verify_audit(audit_for_record, info.record_dir)
        rec.check(
            "the simulator audit verifies and belongs to this record",
            check.ok,
            check.summary(),
            "audit OK",
        )
        if final_study != study and report.paths.get("simulator_audit"):
            old = sim.verify_audit(report.paths["simulator_audit"], info.record_dir)
            rec.check(
                "the first audit is NOT accepted for the re-analysed record",
                not old.ok,
                old.summary(),
                "refused",
            )
    rec.note(
        "record", record_id=info.record_id, files=info.n_files, input_included=info.input_included
    )
    _timed(report, "record", t)

    # 9 agents -----------------------------------------------------------------------------------
    t = time.perf_counter()
    rec.begin("agents", "Agents (MCP): qPilot's tools plus the simulator's, read-only")
    if options.agents:
        _agents_stage(rec, studio.store, final_study, report)
    else:
        rec.step("skipped", "system")
    _timed(report, "agents", t)


def _note_result(rec: Recorder, stage: str, result: Any, cards: list[Any]) -> None:
    calls = Counter(c.conclusion for c in result.contrasts.values())
    holds = [r.holds for r in result.robustness.values()]
    rec.note(
        stage,
        study_id=result.study_id,
        genes=len(result.contrasts),
        calls=dict(calls),
        robustness_cells=next(iter(result.robustness.values())).n_cells if holds else 0,
        genes_holding_everywhere=sum(1 for h in holds if h >= 1.0),
        cards=[
            {
                "id": c.id,
                "status": c.status,
                "recommended": c.recommended,
                "genes_it_can_flip": c.impact.get("n_genes_flipped"),
            }
            for c in cards
        ],
        headline={
            g: {
                "fc": round(result.contrasts[g].fc, 4),
                "conclusion": result.contrasts[g].conclusion,
                "holds": round(result.robustness[g].holds, 4),
                "confidence": result.confidence[g].level if g in result.confidence else None,
            }
            for g in ("ODC1", "BIRC5", "NTRK1", "NM23A")
            if g in result.contrasts
        },
    )


def _run_audit(
    rec: Recorder,
    sim: Any,
    store: Any,
    study: str,
    audit_dir: Path,
    options: Options,
    want: dict[str, Any],
) -> Any:
    """Run the audit (or say why not); return the result or ``None``."""
    if not options.simulator:
        rec.step("simulator not requested (skipped)", "system")
        return None
    if not sim.available():
        rec.step("the Decision Simulator (qsim) is not installed (skipped)", "system")
        rec.note("simulator", status="not installed")
        return None
    try:
        result = sim.audit(store, study, audit_dir, permutations=options.permutations)
    except sim.NotApplicable as err:
        rec.step(f"not applicable to this design: {err}", "system")
        rec.note("simulator", status="not applicable", reason=str(err))
        return None
    m = result.manifest
    repro = m["reproduces_qpilot"]
    rec.step(
        f"audited {m['analyses']:,} analyses in {result.seconds:.0f} s",
        "system",
        lock_sha256=m["lock_sha256"],
        study=study,
    )
    rec.check(
        "the simulator's baseline reproduces qPilot (every gene: fold change, p, call)",
        repro["ok"],
        f"{repro['genes']} genes, max |d log2fc| {repro['max_abs_diff_log2fc']:.1e}",
        f"<= {repro['tolerance']}",
    )
    if "sim_analyses" in want:
        rec.check(
            "analyses in the simulator's grid",
            m["analyses"] == want["sim_analyses"],
            m["analyses"],
            want["sim_analyses"],
        )
    s = result.summary
    stage = "simulator" if audit_dir.name == "simulator_audit" else "roundtrip"
    rec.note(
        stage,
        **({"status": "audited"} if stage == "simulator" else {"reaudit_status": "audited"}),
        **{
            ("" if stage == "simulator" else "reaudit_") + k: v
            for k, v in {
                "audit_dir": str(audit_dir),
                "analyses": m["analyses"],
                "verdict_counts": m["verdict_counts"],
                "scope": m["scope"],
                "lock_sha256": m["lock_sha256"],
                "your_choices": m["your_choices"],
                "lock_advisor_headline": s.get("lock_advisor", {}).get("headline_all"),
                "genes_flipped_by_one_sample": s.get("influence", {}).get(
                    "genes_flipped_by_one_sample"
                ),
                "headline_verdicts": {
                    g: result.verdicts.get(g)
                    for g in ("ODC1", "BIRC5", "NTRK1", "NM23A")
                    if g in result.verdicts
                },
                "seconds": round(result.seconds, 1),
            }.items()
        },
    )
    rec.check(
        "the audit verifies (checksums, lock, manifest)", sim.verify_audit(audit_dir).ok, "ok", "ok"
    )
    return result


def _bind_bundle(bundle_dir: Path, audit: Any) -> dict[str, Any]:
    """Does the audit describe the analysis the Prism bundle was exported from?"""
    path = bundle_dir / "qpilot_provenance.json"
    if not path.exists():
        return {"ok": False, "reason": "no qpilot_provenance.json in the bundle"}
    prov = json.loads(path.read_text(encoding="utf-8"))
    m = audit.manifest
    found = {
        "input_sha256": _find(prov, "input_sha256"),
        "study_id": _find(prov, "study_id"),
        "chain_head": _find(prov, "chain_head"),
    }
    same = {k: found[k] == m.get(k) for k in found if found[k] is not None}
    return {
        "ok": bool(same) and all(same.values()),
        "compared": same,
        "audit_lock": m["lock_sha256"],
    }


def _find(tree: Any, key: str) -> Any:
    if isinstance(tree, dict):
        if key in tree:
            return tree[key]
        for value in tree.values():
            hit = _find(value, key)
            if hit is not None:
                return hit
    if isinstance(tree, list):
        for value in tree:
            hit = _find(value, key)
            if hit is not None:
                return hit
    return None


def _agents_stage(rec: Recorder, store: Any, study: str, report: WorkflowReport) -> None:
    import anyio

    from qpilot.integration.mcp_tools import SIM_TOOL_NAMES, SimulatorTools, create_server
    from qpilot.mcp_server import TOOL_NAMES, QpilotTools

    server = create_server(store, audits=report.paths)
    names = sorted(t.name for t in anyio.run(server.list_tools))
    rec.step(f"the MCP server lists {len(names)} tools", "system", tools=names)
    rec.check(
        "qPilot's and the simulator's tools are all registered",
        set(TOOL_NAMES) | set(SIM_TOOL_NAMES) <= set(names),
        len(names),
        len(TOOL_NAMES) + len(SIM_TOOL_NAMES),
    )
    tools = SimulatorTools(store, audits=report.paths)
    view = tools.sim_audit(study)
    rec.check(
        "an agent reads the audit of the study (read-only)",
        "error" not in view,
        view.get("error", "ok"),
        "ok",
    )
    qp = QpilotTools(store)
    cards = store.cards(study)
    card = next((c for c in cards if c.options), None)
    if card is not None:
        other = next(
            (o.id for o in card.options if o.id != (card.decision or card.recommended)),
            card.recommended,
        )
        before = store.chain_head(study)
        answer = qp.qpcr_decide(study, card.id, other, "an agent tries to change the choice")
        status = answer.get("status") or answer.get("error", "")
        rec.step(
            f"an agent asked to change {card.id} to {other}",
            "agent",
            "an agent tries to change the choice",
            answer=status,
        )
        rec.check(
            "an agent's change waits for a person (nothing applied)",
            status in ("pending_human", "stale") or "error" in answer,
            status,
            "pending_human",
        )
        rec.note(
            "agents",
            tools=names,
            agent_request=status,
            chain_head_before=before,
            chain_head_after=store.chain_head(study),
        )


# ---------------------------------------------------------------------------------------------
# The report files
# ---------------------------------------------------------------------------------------------


def _write_report(report: WorkflowReport, out_dir: Path) -> None:
    (out_dir / "workflow.json").write_text(
        json.dumps(report.as_dict(), indent=1, default=str), encoding="utf-8", newline="\n"
    )
    (out_dir / "WORKFLOW.md").write_text(render_markdown(report), encoding="utf-8", newline="\n")


def render_markdown(report: WorkflowReport) -> str:
    """The run in plain words: each stage, who did what and why, the checks."""
    lines = [
        "# qPilot workflow run",
        "",
        f"* Input: `{Path(report.rdml).name}`",
        f"* Studio session `{report.session_id}`, study `{report.study_id}`"
        + (
            f", re-analysed as `{report.final_study_id}`"
            if report.final_study_id and report.final_study_id != report.study_id
            else ""
        ),
        f"* Checks: {len(report.checks) - len(report.failed)} of {len(report.checks)} passed"
        + ("" if report.ok else " — **FAILED**: " + "; ".join(c.label for c in report.failed)),
        f"* Time: {sum(report.timings_s.values()):.0f} s "
        f"({', '.join(f'{k} {v:.0f} s' for k, v in report.timings_s.items())})",
        "",
    ]
    for stage in STAGES:
        steps = [s for s in report.steps if s.stage == stage]
        checks = [c for c in report.checks if c.stage == stage]
        if not steps and not checks and stage not in report.stages:
            continue
        lines += [f"## {STAGES.index(stage) + 1}. {stage}", ""]
        for s in steps:
            who = "**person**" if s.actor == HUMAN else s.actor
            lines.append(f"* {who}: {s.action}" + (f" — reason: *{s.reason}*" if s.reason else ""))
        for c in checks:
            mark = "✔" if c.ok else "✘"
            lines.append(
                f"* {mark} {c.label}"
                + (f": `{c.got}`" if c.got != "" else "")
                + ("" if c.ok else f" (expected `{c.want}`)")
            )
        values = report.stages.get(stage)
        if values:
            lines += [
                "",
                "<details><summary>values</summary>",
                "",
                "```json",
                json.dumps(values, indent=1, default=str)[:6000],
                "```",
                "",
                "</details>",
            ]
        lines.append("")
    if report.paths:
        lines += ["## Files", ""] + [f"* {k}: `{v}`" for k, v in report.paths.items()] + [""]
    lines += [
        "*Every person's action above was taken by the person object passed to the workflow "
        '(`actor="human"`). In this run that was the scripted policy of `qpilot studio demo '
        "--check`; in real use it is the scientist, on the Studio page.*",
        "",
    ]
    return "\n".join(lines)


def demo_expected() -> dict[str, Any]:
    """The demo numbers Studio's own check expects, plus the simulator's."""
    from qpilot.cli.studio_cmds import EXPECTED

    return {**EXPECTED, "sim_analyses": 90_396}


__all__ = [
    "HUMAN",
    "STAGES",
    "Options",
    "Person",
    "ScriptedPerson",
    "WorkflowReport",
    "demo_expected",
    "exclude_demo_sample",
    "render_markdown",
    "run_workflow",
]
