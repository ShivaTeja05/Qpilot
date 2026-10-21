"""Run Gate route: what the controls on each plate say, and whether any of it changes a call.

``GET /studies/{id}/gate`` evaluates the shipped rule pack (``research-default``) on the
study's wells (:func:`qpilot.qpcr.gate_rules.run_gate`) and, for every rule that warns or fails
and points at wells, re-runs the study's whole analysis grid without them (the consequence
test, :mod:`qpilot.core.gate`). It answers every evaluation with its reason in words (each number
a cited fact), every consequence with what each option would change, and the ``gate.rule``
Decision Cards in the shape the Results cards use.

Rules label; nothing is applied until a person decides. A gate card has no grid dimension, so it
is not decided in the study's decision chain: in a Studio session, ``POST /studies/{id}/gate/
cards/{card_id}/decide`` turns a person's option into curve exclusions (one ``curve.exclude_well``
per well, proposed by Run Gate's rule and accepted by the person with the reason, all in one
write to the session's hash-chained inbox; :meth:`qpilot.studio_service.Studio.decide_gate`), and
the study is analysed again (the ``analyse`` job) with the wells left out; the gate is then read
at the new analysis. "Keep every well" puts back what a person left out, or records the keep. A
study analysed outside Studio has no inbox: its wells are left out by opening its file in Studio.
Agents ask through MCP (``qpcr_decide``), which files their request for a person
(``pending_human``); the view shows it with the card.

G-RT and G-INSTR (origin/main's gate lines) are rules of the pack. G-INSTR reads each plate's
run file: one a person linked to the plate here (``POST /studies/{id}/gate/run-files``: an
``.eds`` or an export the instrument wrote, kept by content and read for every analysis of the
same input file, :mod:`qpilot.qpcr.run_links`; ``…/run-files/unlink`` removes it), else, for a
study opened from an instrument export, the plate's run file among the export's own files (a
QuantStudio results export, CFX run information: :mod:`qpilot.qpcr.export_runs`), else the
study's own (``run_context.json``, else the input RDML; the instrument and the run date at
most). Linking changes no number: the gate is read again with the plate's run file.

Like every result, a study analysed from a Studio session answers ``403 blind`` until its design
and curves are confirmed (the results routes' rule). The first gate of a study re-reads its wells
and re-runs the grid once per option (about six seconds on the demo): it runs as a ``gate.run``
job, and a request that finds it still running answers ``409 loading`` with the job to follow.
The answer is kept per store, results version and decision chain head; the consequences are
measured at the analysis in use (each Decision Card's applied option, the planned one
elsewhere), so a decision that moves it measures them again. The view is kept per store, results
version, chain head and (for a session) inbox head. GETs never write.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile

from qpilot.core import gate as core_gate
from qpilot.core.rules import VERDICTS, RuleEval, RulePack
from qpilot.schemas import DecisionCard, Fact
from qpilot.web import results_views as rv
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import (
    CardOptionView,
    CardView,
    FactText,
    JobView,
    OptionEffect,
    PendingRequest,
)
from qpilot.web.contract_gate import (
    GateConsequence,
    GateDecide,
    GateDecided,
    GateDecisionView,
    GateEvaluation,
    GateLoaded,
    GateOption,
    GatePack,
    GatePlate,
    GateRequestView,
    GateRuleInfo,
    GateRunFile,
    GateRunLinked,
    GateRunUnlink,
    GateSource,
    GateView,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["gate"])
JOB_RESULTS = {"gate.run": GateLoaded}

RUN_S = 8.0  # measured: ~6 s on the demo when the laptop is idle (64 plates, 10 re-runs)
WAIT_S = 1.5  # a request waits this long for the job before answering 409 loading
FAILED_S = 10.0  # a run that just failed is reported, not retried, for this long
KEEP = 4
MAX_NAMES = 6
WORST = ("fail", "warn", "pass", "not_applicable")

_lock = threading.Lock()
_reports: OrderedDict[tuple[Any, ...], core_gate.GateReport] = OrderedDict()
_views: OrderedDict[tuple[Any, ...], GateView] = OrderedDict()

NO_SOURCE = (
    "The study's input file is missing or has changed since it was analysed, so its controls "
    "cannot be checked. Open the file again to check them."
)
MISMATCH = (
    "Re-running the study from its file does not give its stored results, so its controls "
    "cannot be checked against them. Analyse the file again."
)
TRIAGE_TEXT = {
    "ignore": "Changes no conclusion: kept in the record and the methods; nothing to decide.",
    "rescue": (
        "Changes no call but moves the numbers; the option that moves them least is the one to "
        "look at. Nothing is applied here."
    ),
    "human": "Can change a conclusion: only a person decides (see its Decision Card).",
    "defer": "Could not be checked yet; it is checked again when the data allow.",
}
ELSEWHERE_TEXT = (
    "Changes no call at the analysis in use, but can change a call at other settings: decided "
    "automatically to keep the wells (see its Decision Card); an agent asking to leave them out "
    "must ask a person."
)
APPLY_SESSION = (
    "Rules label; nothing changes your analysis until a person decides. Choose an option on a "
    "Decision Card below and say why: the wells it leaves out become exclusions in this session "
    "(listed in Curves), the study is analysed again, and the record says who decided and why."
)
APPLY_STUDY = (
    "Rules label; nothing here changes your analysis. This study was analysed outside Studio, "
    "so its wells cannot be left out here: open its file in Studio to leave wells out with a "
    "reason, or follow a call down to its wells in Trace."
)
DECIDE_NOTE = (
    "Deciding writes one entry per well to this session's record, with your reason. Leaving "
    "wells out, or putting them back, analyses the study again. What you chose on the Decision "
    "Cards is carried to the new analysis, each as a new entry that says where it came from, "
    "except a choice that matters more there: that one is asked again. Then confirm the "
    "choices again on Results."
)
OUTSIDE_STUDIO = (
    "This study was analysed outside Studio, so its wells cannot be left out here. Open its "
    "file in Studio (Open, then drop the file): there the controls are checked again and a "
    "person can leave wells out, with a reason kept in the record."
)
NOT_DECIDABLE = (
    "Leaving out the wells of this check changes no conclusion, so there is nothing to decide here."
)
STALE_GATE = (
    "The analysis changed since you loaded this (another tab, a decision or an agent). Here are "
    "the controls at the analysis in use now."
)
KEEP_LABEL = "Keep every well (the analysis as it stands)"
RUN_NOTE = (
    "The study's own file (RDML) names the instrument and the run date at most. A study opened "
    "from an instrument export reads each plate's run file in the export when it has one (a "
    "QuantStudio results export, CFX run information). Link the run file the instrument wrote "
    "for a plate (an .eds file, a QuantStudio results export or CFX run information) and G-INSTR "
    "reads it instead: whether the run completed, its pauses and its calibrations. Linking "
    "changes no number; it is kept for every analysis of this file, with who linked it and "
    "when. Serial numbers in the file are never shown."
)
#: The evidence's ``source`` of a G-INSTR evaluation -> which run file the view says it read.
RUN_SOURCE = {"linked run file": "linked", "export run file": "export", "study file": "study_file"}
RDML_RUN_FILE = (
    "This is an RDML file: the study's own file is already read, and RDML has no field for the "
    "run state, pauses or calibrations. Link the file the instrument wrote: an .eds file, a "
    "QuantStudio results export or CFX run information."
)
NOT_A_PLATE = "This study has no plate called that."
RUN_FILE_HELP = "The plate's run file: an .eds, a QuantStudio results export, CFX run information."
OPTION_CODES = ("already_left_out", "not_study_samples", "cannot_rerun")
CARD_PREFIX = "card_gate_"


# ---- the kept report -----------------------------------------------------------------------


def _visible(ctx: AppContext, study_id: str) -> str | None:
    """The results routes' checks (id, study, blind); returns the study's session, if any."""
    from qpilot.web.routers.results import study

    return study(ctx, study_id)


def _version(ctx: AppContext, study_id: str) -> tuple[str, int]:
    """Which store, and when its results last changed (a re-analysis means a new gate)."""
    path = ctx.store.workspace(study_id) / "results.json"
    try:
        return str(ctx.store.root), path.stat().st_mtime_ns
    except OSError:
        return str(ctx.store.root), 0


def _choice(ctx: AppContext, study_id: str) -> dict[str, str] | None:
    """The options in use as grid text per dimension, or ``None`` for the planned analysis."""
    return analysis_choice(ctx.store, study_id)


def analysis_choice(store: Any, study_id: str) -> dict[str, str] | None:
    """:func:`_choice` for a store (the MCP server has no app context)."""
    result = store.get(study_id)
    grid = rv.load_grid(store, result)
    if grid is None or grid.planned is None:
        return None
    cards = store.cards(study_id)
    cell = rv.current_cell(grid, cards, rv.card_options(grid, cards))
    if cell == grid.planned:
        return None
    return {dim: grid.options[dim][idx] for dim, idx in cell.items()}


def _keep(cache: OrderedDict, key: tuple[Any, ...], value: Any) -> None:
    with _lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > KEEP:
            cache.popitem(last=False)


def _kept(cache: OrderedDict, key: tuple[Any, ...]) -> Any:
    with _lock:
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
    return None


def compute(store: Any, study_id: str, choice: dict[str, str] | None) -> core_gate.GateReport:
    """The gate of a stored study at the analysis ``choice`` names (the planned one if ``None``).

    The study's model is rebuilt from its input file and must give its stored results again
    (:func:`qpilot.trace.model_for_study`); the standards' declared quantities come from the
    file, and the raw-ness verdict from the session's import record when the study was opened
    from an instrument export (:mod:`qpilot.web.intake`; ``None`` for an RDML file).

    Raises:
        JobError: The file is missing or changed, or the rebuilt numbers differ.
    """
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.designs import design_curves
    from qpilot.qpcr.gate_rules import run_gate, study_quantities
    from qpilot.trace import TraceError, model_for_study
    from qpilot.trace.context import cell_of

    source = store.source(study_id)
    if source is None:
        raise JobError("no_source", NO_SOURCE)
    try:
        model = model_for_study(store, study_id)
        cell = cell_of(model, choice) if choice else None
    except TraceError as err:
        raise JobError("not_gated", MISMATCH) from err
    settings = model.settings
    curves = analyse_study(source, settings.experiment_id, settings.candidates, settings.curves)
    typed = design_curves(curves, settings.design) if settings.design is not None else curves
    quantities = study_quantities(source) if (typed["sample_type"] == "std").any() else {}
    return run_gate(
        curves,
        settings,
        quantities=quantities,
        rawness=import_rawness(store, study_id),
        model=model,
        cell=cell,
        runs=study_runs(store, study_id, source),
    )


def input_sha(store: Any, study_id: str) -> str:
    """The sha256 of a study's input file (from its ``source.json``, else its results)."""
    import json

    try:
        data = json.loads((store.workspace(study_id) / "source.json").read_text(encoding="utf-8"))
        digest = str(data.get("sha256") or "")
    except (OSError, ValueError, AttributeError):
        digest = ""
    return digest or str(store.get(study_id).input_sha256)


def links_version(store: Any, study_id: str) -> str:
    """Which run files are linked to the study's plates (part of every cache key)."""
    from qpilot.qpcr import run_links

    try:
        return run_links.version(store.root, input_sha(store, study_id))
    except (OSError, ValueError):
        return ""


def study_links(store: Any, study_id: str) -> dict[str, Any]:
    """The run files a person linked to the plates of the study's input file."""
    from qpilot.qpcr import run_links

    try:
        return run_links.load(store.root, input_sha(store, study_id))
    except (OSError, ValueError):
        return {}


def study_exports(store: Any, study_id: str) -> dict[str, Any]:
    """Plate -> the run file in the instrument export the study was opened from (``ExportRun``).

    Empty for a study opened from an RDML file or analysed outside Studio, and for plates whose
    export has no run file qPilot reads (or whose kept copy is gone or changed).
    """
    from qpilot.qpcr.export_runs import export_runs
    from qpilot.web.views import inputs_dir

    meta = study_capture(store, study_id)
    return export_runs(meta, inputs_dir(store)) if meta is not None else {}


def study_runs(store: Any, study_id: str, source: Any) -> dict[str, Any]:
    """Plate -> the run file G-INSTR reads: a linked one, else the export's, else the RDML's."""
    from qpilot.qpcr import run_links
    from qpilot.qpcr.gate_rules import file_runs, stored_runs, with_export, with_linked
    from qpilot.web.views import inputs_dir

    own = stored_runs(store.get_artifact(study_id, "run_context.json"))
    if own is None:
        own = file_runs(source)
    exported = {plate: run.context for plate, run in study_exports(store, study_id).items()}
    runs = with_export(own, exported)
    links = study_links(store, study_id)
    if not links:
        return runs
    contexts, problems = run_links.read_linked(links, inputs_dir(store))
    return with_linked(runs, contexts, problems)


def report_for(store: Any, study_id: str) -> core_gate.GateReport:
    """The gate of a stored study at the analysis in use, computed here (no job; the MCP server).

    Kept like the page's reports (per store, results version and analysis), so a page and an
    agent in one process share them.

    Raises:
        JobError: The file is missing or changed, or the rebuilt numbers differ.
    """
    choice = analysis_choice(store, study_id)
    try:
        version = store.workspace(study_id).joinpath("results.json").stat().st_mtime_ns
    except OSError:
        version = 0
    links = links_version(store, study_id)
    key = (str(store.root), version, study_id, links, tuple(sorted((choice or {}).items())))
    report = _kept(_reports, key)
    if report is None:
        report = compute(store, study_id, choice)
        _keep(_reports, key, report)
    return report


def study_capture(store: Any, study_id: str) -> Any:
    """What the instrument export a study was opened from was read as (``CaptureMeta``), else None.

    ``None`` for a study opened from an RDML file or analysed outside Studio.
    """
    from qpilot.web import intake
    from qpilot.web.results_views import session_of_study

    sid = session_of_study(store, study_id)
    found = intake.load(store, sid) if sid else None
    return found[0] if found is not None else None


def import_rawness(store: Any, study_id: str) -> str | None:
    """The import's raw-ness verdict for a study opened from an instrument export, else None."""
    meta = study_capture(store, study_id)
    if meta is None or not meta.rawness:
        return None
    verdict = meta.rawness.get("study_verdict")
    return str(verdict) if verdict else None


def _report(ctx: AppContext, study_id: str, choice: dict[str, str] | None) -> core_gate.GateReport:
    """The kept report, or run it in a ``gate.run`` job (409 loading while it runs)."""
    links = links_version(ctx.store, study_id)
    key = (*_version(ctx, study_id), study_id, links, tuple(sorted((choice or {}).items())))
    report = _kept(_reports, key)
    if report is not None:
        return report
    if ctx.store.source(study_id) is None:
        raise api_error(409, "no_source", NO_SOURCE)
    failed = ctx.jobs.latest("gate.run", study_id)
    if failed is not None and failed.status == "failed" and failed.error:
        if time.time() - (failed.finished or 0) < FAILED_S:
            raise api_error(
                409, failed.error.get("code", "failed"), failed.error.get("message", "")
            )

    def work(progress: Progress) -> dict[str, Any]:
        start = time.perf_counter()
        progress("Checking every plate's controls against the rule pack", 0.1)
        done = compute(ctx.store, study_id, choice)
        _keep(_reports, key, done)
        return GateLoaded(
            study_id=study_id,
            head=ctx.store.chain_head(study_id),
            n_evaluations=len(done.evals),
            n_consequences=len(done.consequences),
            n_cards=len(done.cards),
            seconds=round(time.perf_counter() - start, 2),
        ).model_dump(mode="json")

    job = ctx.jobs.submit(
        "gate.run",
        work,
        title="Checking the controls on every plate",
        key=study_id,
        typical_s=RUN_S,
    )
    deadline = time.monotonic() + WAIT_S
    while job.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.05)
    if job.status == "done":
        report = _kept(_reports, key)
        if report is not None:
            return report
    if job.status == "failed" and job.error:
        raise api_error(409, job.error.get("code", "failed"), job.error.get("message", ""))
    raise api_error(
        409,
        "loading",
        "The gate is checking every plate's controls and re-running the analysis without the "
        "wells they point at (about six seconds on the demo). It answers as soon as the job is "
        "done.",
        job=JobView(**job.view()).model_dump(mode="json"),
    )


def clear() -> None:
    """Forget every kept report and view (tests; a fresh demo)."""
    with _lock:
        _reports.clear()
        _views.clear()


# ---- words ---------------------------------------------------------------------------------


def _t(fid: str) -> str:
    return "{{" + fid + "}}"


def _names(items: list[str]) -> str:
    shown = items[:MAX_NAMES]
    text = ", ".join(shown)
    return text + (", and more (listed with the option)" if len(items) > MAX_NAMES else "")


def _option_text(
    ev: RuleEval, opt: core_gate.OptionConsequence, facts: dict[str, Fact]
) -> FactText:
    stem = f"{core_gate.eval_id(ev)}_{opt.option}"
    n = len(opt.excluded)
    lead = f"Leaving {'this' if n == 1 else 'these'} {_t(f'f_gate_nexcl_{stem}')} "
    lead += "well out" if n == 1 else "wells out"
    other = core_gate.elsewhere(opt)
    if opt.consequence == "unknown":
        return rv.plain_text(f"Could not be checked: {opt.reason or 'the analysis did not run'}")
    if opt.code == "already_left_out":
        verb = "well is" if n == 1 else "wells are"
        return rv.fact_text(
            f"{'This' if n == 1 else 'These'} {_t(f'f_gate_nexcl_{stem}')} {verb} already left "
            "out of the analysis: a person decided it (the record says who and why).",
            facts,
        )
    if opt.reason:  # answered without a re-run (the wells are not study samples)
        why = opt.reason[:1].lower() + opt.reason[1:]
        return rv.fact_text(f"{lead} changes no call: {why}", facts)
    if opt.n_flipped:
        calls = "call" if opt.n_flipped == 1 else "calls"
        tokens = (
            f"{lead} changes {_t(f'f_gate_nflip_{stem}')} {calls} at the analysis in use: "
            f"{_names(opt.flipped)}."
        )
        if other:
            more = _t(f"f_gate_nelse_{stem}")
            tokens += f" At other settings it changes {more} more: {_names(other)}."
        return rv.fact_text(tokens, facts)
    if other:
        return rv.fact_text(
            f"{lead} changes no call at the analysis in use; at other settings it changes "
            f"{_t(f'f_gate_nelse_{stem}')}: {_names(other)}.",
            facts,
        )
    if opt.consequence == "magnitude":
        return rv.fact_text(
            f"{lead} changes no call, but moves a fold change by up to "
            f"{_t(f'f_gate_dlog2_{stem}')} on the log2 scale, or how often a call holds across "
            "the other analyses.",
            facts,
        )
    return rv.fact_text(f"{lead} changes no call.", facts)


def _scope(ev: RuleEval) -> dict[str, Any]:
    level = next((k for k in ("sample", "unit", "target", "plate") if k in ev.scope), "study")
    return {
        "level": level,
        "plate": ev.scope.get("plate"),
        "target": ev.scope.get("target"),
        "sample": ev.scope.get("sample"),
        "unit": ev.scope.get("unit"),
    }


def _headline(report: core_gate.GateReport, facts: dict[str, Fact]) -> FactText:
    plates = len(report.units)
    gated = sum(1 for s in report.units.values() if s == "gated")
    flips = sum(1 for c in report.consequences if c.consequence == "flip")
    elsewhere_only = sum(
        1
        for c in report.consequences
        if c.consequence != "flip" and any(core_gate.elsewhere(o) for o in c.options)
    )
    left_out = sum(
        1
        for c in report.consequences
        if c.options and all(o.code == "already_left_out" for o in c.options)
    )
    local = {
        "f_gate_nplates_study": plates,
        "f_gate_ngated_study": gated,
        "f_gate_nungated_study": plates - gated,
        "f_gate_nfail_study": report.counts["fail"],
        "f_gate_nwarn_study": report.counts["warn"],
        "f_gate_nflips_study": flips,
        "f_gate_nelsewhere_study": elsewhere_only,
    }
    for fid, value in local.items():
        facts[fid] = Fact(id=fid, value=value, fmt="{}", path=f"gate/headline/{fid[7:-6]}")
    parts = []
    if plates - gated:
        parts.append(
            f"{_t('f_gate_nungated_study')} of {_t('f_gate_nplates_study')} plates are ungated: "
            "no wells there are typed as controls."
        )
    else:
        parts.append(f"All {_t('f_gate_nplates_study')} plates are gated.")
    hits = report.counts["fail"] + report.counts["warn"]
    if not hits:
        parts.append("Every rule that could be checked passes.")
        return rv.fact_text(" ".join(parts), facts)
    fail, warn = report.counts["fail"], report.counts["warn"]
    if fail and warn:
        verb = "rule check fails" if fail == 1 else "rule checks fail"
        parts.append(f"{_t('f_gate_nfail_study')} {verb} and {_t('f_gate_nwarn_study')} warn.")
    elif fail:
        verb = "rule check fails" if fail == 1 else "rule checks fail"
        parts.append(f"{_t('f_gate_nfail_study')} {verb}.")
    else:
        verb = "rule check warns" if warn == 1 else "rule checks warn"
        parts.append(f"{_t('f_gate_nwarn_study')} {verb}.")
    if not report.consequences:
        parts.append(
            "It points at no wells that could be left out."
            if hits == 1
            else "None of them points at wells that could be left out."
        )
    elif flips:
        parts.append(
            f"Leaving out the wells that {_t('f_gate_nflips_study')} of them point at changes a "
            "call: only you decide."
        )
    elif elsewhere_only:
        parts.append(
            "Leaving out the wells they point at changes no call at the analysis in use; "
            f"{_t('f_gate_nelsewhere_study')} of them can change one at other settings, so an "
            "agent would have to ask you."
        )
    elif left_out and left_out == len(report.consequences):
        parts.append(
            "The wells they point at are already left out of the analysis: a person decided it."
        )
    elif left_out:
        facts["f_gate_nleftout_study"] = Fact(
            id="f_gate_nleftout_study", value=left_out, fmt="{}", path="gate/headline/nleftout"
        )
        parts.append(
            "Leaving out the wells they point at changes no call; a person already left out the "
            f"wells of {_t('f_gate_nleftout_study')} of them."
        )
    else:
        parts.append("Leaving out the wells they point at changes no call.")
    return rv.fact_text(" ".join(parts), facts)


def _card_view(
    card: DecisionCard,
    consequence: core_gate.Consequence,
    ev: RuleEval,
    facts: dict[str, Fact],
    option_texts: dict[str, FactText],
    decision: GateDecisionView | None = None,
    requests: list[GateRequestView] | None = None,
    decidable: bool = False,
) -> CardView:
    from qpilot.core.card_kinds import kind_title
    from qpilot.core.decisions import needs_human

    requests = requests or []
    if decision is not None and decision.option in {o.id for o in card.options}:
        card = card.model_copy(
            update={
                "status": "decided",
                "decision": decision.option,
                "reason": decision.reason,
                "decided_by": "human",
            }
        )
    asked = {r.option for r in requests}
    keep = next((o for o in card.options if o.id == card.recommended), None)
    base = {g: r.conclusion for g, r in keep.per_gene.items()} if keep else {}
    options = [
        CardOptionView(
            id=o.id,
            label=o.label,
            recommended=o.id == card.recommended,
            chosen=o.id == card.decision,
            requested=o.id in asked,
            not_recommended=False,
            effects=[
                OptionEffect(
                    gene=g,
                    fc=r.fc,
                    log2fc=r.log2fc,
                    ci=(float(r.ci[0]), float(r.ci[1])),
                    p=r.p,
                    conclusion=r.conclusion,
                    changes_call=g in base and base[g] != r.conclusion,
                )
                for g, r in o.per_gene.items()
            ],
        )
        for o in card.options
    ]
    worst = max(consequence.options, key=lambda o: (o.n_flipped, len(core_gate.elsewhere(o))))
    stem = f"{core_gate.eval_id(ev)}_{worst.option}"
    if worst.n_flipped:
        calls = "call changes" if worst.n_flipped == 1 else "calls change"
        impact = rv.fact_text(
            f"{_t(f'f_gate_nflip_{stem}')} {calls} at the analysis in use when the wells are "
            "left out",
            facts,
        )
        status = (
            "Waiting for a person: leaving the wells out changes a call. Choose an option and "
            "say why."
            if decidable
            else "Waiting for a person: leaving the wells out changes a call. This study was "
            "analysed outside Studio: its wells are left out by opening its file in Studio."
        )
    else:
        impact = rv.fact_text(
            "No call changes at the analysis in use; "
            f"{_t(f'f_gate_nelse_{stem}')} can change at other settings",
            facts,
        )
        status = (
            "Decided automatically: keep every well. At other settings leaving them out changes a "
            "call, so an agent asking for it must ask a person."
        )
    if card.status == "decided" and decision is not None:
        status = f"Decided by a person: {decision.label}. Why: {decision.reason}"
    if requests:
        status = (
            "An agent asks for "
            + "; ".join(_request_words(r) for r in requests)
            + ". Nothing changes until a person approves it or turns it down."
        )
    texts = [option_texts[o.option] for o in consequence.options if o.option in option_texts]
    explanation = rv.fact_text(" ".join([ev.reason, *(_tokens(t) for t in texts)]), facts)
    return CardView(
        card=card,
        title=kind_title(card.kind),
        status_line=status,
        impact=impact,
        explanation=explanation,
        needs_human=needs_human(card),
        genes=list(card.options[0].per_gene) if card.options else [],
        options=options,
        pending=[
            PendingRequest(
                seq=i,
                option=r.option,
                option_label=r.option_label,
                reason=r.reason,
                actor="agent",
                at=r.at,
            )
            for i, r in enumerate(requests, start=1)
        ],
    )


def _request_words(request: GateRequestView) -> str:
    n = len(request.wells)
    wells = "1 well" if n == 1 else f"{n} wells"
    return f"{request.option_label.lower()} ({wells} {'out' if request.left_out else 'back'})"


# ---- what the session's record says about a card -------------------------------------------


def _option_label(option: str | None) -> str:
    from qpilot.qpcr.gate_rules import OPTION_LABELS

    if option == core_gate.KEEP:
        return KEEP_LABEL
    if option is None:
        return "Some of these wells are left out another way"
    return OPTION_LABELS.get(option, option.replace("_", " "))


def _record(
    proposals: list[Any],
    consequence: core_gate.Consequence,
    left_out: frozenset[str],
) -> tuple[GateDecisionView | None, list[GateRequestView]]:
    """A card's latest decision by a person and the agents' requests waiting on it.

    The option in use comes from the analysed design (the wells it leaves out now); who chose
    it and why from the record: the latest click on this card (its proposals decided at the same
    moment with the same reason).
    """
    from qpilot.studio_service import leaves_out

    universe = {w for o in consequence.options for w in o.excluded}
    decided = [
        (i, p) for i, p in enumerate(proposals) if p.status in ("accepted", "edited", "rejected")
    ]
    decision = None
    if decided:
        _, last = max(decided, key=lambda item: (item[1].decided_at or "", item[0]))
        click = [
            p for _, p in decided if p.decided_at == last.decided_at and p.reason == last.reason
        ]
        applied = [p for p in click if p.status != "rejected"]
        if any(leaves_out(p) for p in applied):
            action = "left_out"
        else:
            action = "put_back" if applied else "kept"
        out = sorted(universe & left_out)
        option = core_gate.KEEP if not out else None
        for o in consequence.options:
            if out and sorted(o.excluded) == out:
                option = o.option
        decision = GateDecisionView(
            option=option,
            label=_option_label(option),
            action=action,  # type: ignore[arg-type]
            left_out=out,
            reason=last.reason or "",
            decided_at=last.decided_at or "",
        )
    groups: dict[tuple[str, bool], list[Any]] = {}
    for p in proposals:
        if p.status == "proposed" and p.made_by.kind == "agent":
            option = str((p.consequence or {}).get("gate", {}).get("option") or "")
            groups.setdefault((option, leaves_out(p)), []).append(p)
    requests = [
        GateRequestView(
            option=option,
            option_label=_option_label(option),
            wells=sorted(p.subject for p in ps),
            left_out=excluded,
            reason=(ps[0].reasons or [""])[0],
            agent=ps[0].made_by.agent,
            at=ps[0].created_at,
        )
        for (option, excluded), ps in groups.items()
    ]
    return decision, requests


class SessionRecord:
    """What a Studio session's inbox says about the gate cards of its analysis."""

    def __init__(self, by_card: dict[str, list[Any]], head: str, can_decide: bool) -> None:
        self.by_card = by_card
        self.head = head
        self.can_decide = can_decide


def _left_out(store: Any, study_id: str) -> frozenset[str]:
    """The wells the study's design leaves out (a person's exclusions), from its workspace."""
    try:
        design = store.design(study_id)
    except Exception:  # an unreadable design leaves nothing out of what is shown
        return frozenset()
    return frozenset(design.excluded_wells) if design is not None else frozenset()


def _tokens(text: FactText) -> str:
    """A FactText back to its tokens (cited numbers as ``{{id}}``)."""
    return "".join(_t(s.fact) if s.fact else s.text for s in text.segments)


def _pack(pack: RulePack) -> GatePack:
    return GatePack(
        name=pack.pack,
        version=pack.version,
        hash=pack.hash,
        label=" ".join(pack.label.split()),
        rules=[
            GateRuleInfo(
                rule_id=r.id,
                title=r.name,
                statement=" ".join(r.statement.split()),
                sources=[
                    GateSource(
                        key=s,
                        citation=" ".join(pack.sources[s].citation.split()),
                        url=pack.sources[s].url,
                    )
                    for s in r.sources
                ],
                informational=not r.consequence_scope,
            )
            for r in pack.rules
            if r.enabled
        ],
    )


def build_view(
    report: core_gate.GateReport,
    pack: RulePack,
    study_id: str,
    session: str | None,
    head: str,
    analysis: str,
    record: SessionRecord | None = None,
    left_out: frozenset[str] = frozenset(),
    links: dict[str, Any] | None = None,
    exports: dict[str, Any] | None = None,
) -> GateView:
    """The page's view of one gate report (words, facts in sentences, cards as Results shows).

    ``record`` (a Studio session's) adds what a person chose on each card and the agents'
    requests waiting on it; ``left_out`` are the wells the analysed design leaves out;
    ``links`` the run files a person linked to its plates (plate -> ``RunLink``), ``exports``
    the run files the instrument export holds for them (plate -> ``ExportRun``).
    """
    from qpilot.qpcr.gate_rules import OPTION_LABELS

    facts = dict(report.facts)
    headline = _headline(report, facts)
    titles = {r.id: r.name for r in pack.rules}
    evals = {ev.key: ev for ev in report.evals}
    tested = {c.eval_key for c in report.consequences}
    evaluations = [
        GateEvaluation(
            id=core_gate.eval_id(ev),
            rule_id=ev.rule_id,
            title=titles.get(ev.rule_id, ev.rule_id),
            **_scope(ev),
            verdict=ev.verdict,
            outcome=ev.outcome,
            code=ev.code,
            reason=rv.fact_text(ev.reason, facts),
            flagged=list(ev.flagged),
            consequence=core_gate.eval_id(ev) if ev.key in tested else None,
        )
        for ev in report.evals
    ]
    consequences, cards = [], []
    by_card = {c.id: c for c in report.cards}
    for c in report.consequences:
        ev = evals[c.eval_key]
        texts = {o.option: _option_text(ev, o, facts) for o in c.options}
        scope = _scope(ev)
        scope.pop("level")
        decision_id = CARD_PREFIX + core_gate.eval_id(ev)
        decision, requests = (
            _record(record.by_card.get(decision_id, []), c, left_out)
            if record is not None
            else (None, [])
        )
        decidable = bool(
            record is not None
            and record.can_decide
            and (
                c.card_id
                or requests
                or (decision is not None and decision.option != core_gate.KEEP)
            )
        )
        consequences.append(
            GateConsequence(
                id=core_gate.eval_id(ev),
                rule_id=c.rule_id,
                title=titles.get(c.rule_id, c.rule_id),
                **scope,
                verdict=c.verdict,
                consequence=c.consequence,
                triage=c.triage,
                triage_text=(
                    ELSEWHERE_TEXT if c.card_id and c.triage != "human" else TRIAGE_TEXT[c.triage]
                ),
                rescue_option=c.rescue_option,
                options=[
                    GateOption(
                        id=o.option,
                        label=OPTION_LABELS.get(o.option, o.option.replace("_", " ")),
                        excluded=list(o.excluded),
                        consequence=o.consequence,
                        n_flipped=o.n_flipped,
                        flipped=list(o.flipped),
                        n_flipped_elsewhere=len(core_gate.elsewhere(o)),
                        flipped_elsewhere=core_gate.elsewhere(o),
                        max_delta_log2fc=float(o.max_delta_log2fc),
                        text=texts[o.option],
                        code=o.code if o.code in OPTION_CODES else "",
                        left_out=[w for w in o.excluded if w in left_out],
                    )
                    for o in c.options
                ],
                card_id=c.card_id,
                decision_id=decision_id,
                can_decide=decidable,
                decision=decision,
                requests=requests,
            )
        )
        if c.card_id and c.card_id in by_card:
            card = _card_view(
                by_card[c.card_id], c, ev, facts, texts, decision, requests, decidable
            )
            cards.append(card)
    cards.sort(key=lambda v: v.card.rank)
    plates = []
    for plate, status in report.units.items():
        mine = [ev.verdict for ev in report.evals if ev.scope.get("plate") == plate]
        counts = {v: mine.count(v) for v in VERDICTS}
        worst = next((v for v in WORST if counts[v]), "not_applicable")
        plates.append(GatePlate(plate=plate, status=status, counts=counts, worst=worst))
    n_gated = sum(1 for p in plates if p.status == "gated")
    runs = _runs(report, links or {}, exports or {})
    return GateView(
        study_id=study_id,
        session=session,
        head=head,
        pack=_pack(pack),
        headline=headline,
        analysis="planned" if analysis == "planned" else "your_choices",
        exclude_in="curves" if session else "none",
        how_to_apply=APPLY_SESSION if session else APPLY_STUDY,
        can_decide=bool(record is not None and record.can_decide),
        inbox_head=record.head if record is not None else None,
        decide_note=DECIDE_NOTE if record is not None and record.can_decide else "",
        plates=plates,
        n_gated=n_gated,
        n_ungated=len(plates) - n_gated,
        counts=dict(report.counts),
        triage=dict(report.triage),
        evaluations=evaluations,
        consequences=consequences,
        cards=cards,
        runs=runs,
        run_note=RUN_NOTE if runs else "",
    )


def _runs(
    report: core_gate.GateReport, links: dict[str, Any], exports: dict[str, Any]
) -> list[GateRunFile]:
    """Per plate, the run file G-INSTR read (none when the pack has no G-INSTR)."""
    from qpilot.web.routers.instruments import _without_identity

    found = {
        ev.scope["plate"]: ev
        for ev in report.evals
        if ev.check == "instrument_run" and "plate" in ev.scope
    }
    out = []
    for plate in report.units:
        ev = found.get(plate)
        if ev is None:
            continue
        source = RUN_SOURCE.get(str(ev.evidence.get("source") or ""), "none")
        link = links.get(plate) if source == "linked" else None
        export = exports.get(plate) if source == "export" else None
        problem = ev.code == "linked_file_unreadable"
        name = link.name if link is not None else None
        if export is not None:
            name = _without_identity(export.name, export.context)[:200]
        out.append(
            GateRunFile(
                plate=plate,
                source=source,  # type: ignore[arg-type]
                kind=(str(ev.evidence["source_kind"]) if ev.evidence.get("source_kind") else None),
                name=name,
                linked_at=link.at if link is not None else None,
                problem=str(ev.evidence.get("problem") or "") if problem else "",  # type: ignore
                verdict=ev.verdict,  # type: ignore[arg-type]
                evaluation=core_gate.eval_id(ev),
            )
        )
    return out


# ---- the route -----------------------------------------------------------------------------


def _session_record(ctx: AppContext, sid: str, study_id: str) -> SessionRecord:
    """The session's gate decisions and requests; a person decides only the analysis in use."""
    from qpilot.web.views import analysed_study

    head = ctx.studio.head(sid)
    by_card = ctx.studio.gate_record(sid)
    return SessionRecord(by_card, head, analysed_study(ctx.studio, sid) == study_id)


@router.get("/studies/{study_id}/gate", response_model=GateView)
def get_gate(study_id: str, ctx: Ctx) -> GateView:
    """The controls on every plate, by rule, and whether leaving their wells out changes a call."""
    from qpilot.qpcr.gate_rules import resolve_pack

    sid = _visible(ctx, study_id)
    head = ctx.store.chain_head(study_id)
    inbox = ctx.studio.head(sid) if sid else None
    vkey = (*_version(ctx, study_id), study_id, head, inbox, links_version(ctx.store, study_id))
    view = _kept(_views, vkey)
    if view is not None:
        return view
    choice = _choice(ctx, study_id)
    report = _report(ctx, study_id, choice)
    view = build_view(
        report,
        resolve_pack(),
        study_id,
        sid,
        head,
        "planned" if choice is None else "your_choices",
        record=_session_record(ctx, sid, study_id) if sid else None,
        left_out=_left_out(ctx.store, study_id),
        links=study_links(ctx.store, study_id),
        exports=study_exports(ctx.store, study_id),
    )
    _keep(_views, vkey, view)
    return view


def gate_choice(
    report: core_gate.GateReport,
    pack: RulePack,
    study_id: str,
    card_id: str,
    option: str,
) -> Any:
    """The :class:`~qpilot.studio_service.GateChoice` of one option of one gate card.

    Built from the engine's report, never from a request: the wells, the card's other wells and
    whether the option changes a call at the analysis in use. ``None`` when the report has no
    consequence test with this id; ``ValueError`` for an option the card does not have.
    """
    from qpilot.studio_service import GateChoice

    found = next(
        (
            (c, ev)
            for c in report.consequences
            for ev in report.evals
            if ev.key == c.eval_key and CARD_PREFIX + core_gate.eval_id(ev) == card_id
        ),
        None,
    )
    if found is None:
        return None
    consequence, ev = found
    by_option = {o.option: o for o in consequence.options}
    if option != core_gate.KEEP and option not in by_option:
        raise ValueError(option)
    universe = sorted({w for o in consequence.options for w in o.excluded})
    chosen = by_option.get(option)
    matters = (
        any(o.n_flipped for o in consequence.options) if chosen is None else chosen.n_flipped > 0
    )
    title = next((r.name for r in pack.rules if r.id == ev.rule_id), ev.rule_id)
    return GateChoice(
        study_id=study_id,
        card_id=card_id,
        rule_id=ev.rule_id,
        verdict=ev.verdict,
        where=f"{title}: {_where(ev)}",
        option=option,
        label=_option_label(option),
        wells=tuple(chosen.excluded) if chosen is not None else (),
        universe=tuple(universe),
        matters=matters,
        pack=f"{pack.pack} {pack.version}",
    )


def _where(ev: RuleEval) -> str:
    keys = ("plate", "unit", "target", "sample")
    parts = [f"{k} {ev.scope[k]}" for k in keys if k in ev.scope]
    return ", ".join(parts) or "the study"


DONE_WORDS = {
    "left_out": "Left out {n} {wells}: the study is being analysed again without {them}.",
    "put_back": "Put {n} {wells} back: the study is being analysed again with {them}.",
    "kept": "Kept every well: recorded with your reason; the analysis is as it was.",
}


@router.post("/studies/{study_id}/gate/cards/{card_id}/decide", response_model=GateDecided)
def decide_gate_card(study_id: str, card_id: str, body: GateDecide, ctx: Ctx) -> GateDecided:
    """A person chooses an option of a gate card, with a reason (a Studio session only).

    Leaving wells out (or putting them back) becomes curve exclusions accepted by the person in
    one write to the session's record, and the study is analysed again (the ``analyse`` job);
    keeping every well is recorded. Blind like every result; ``studio`` (409) for a study
    analysed outside Studio, ``stale`` (409) when the analysis or the record changed since the
    view, ``loading`` (409) while the gate is still being checked.
    """
    from qpilot.qpcr.gate_rules import resolve_pack
    from qpilot.web.routers.studio import HUMAN, call, changed, ensure_analysis
    from qpilot.web.views import analysed_study

    sid = _visible(ctx, study_id)
    if sid is None:
        raise api_error(409, "studio", OUTSIDE_STUDIO)
    reason = body.reason.strip()
    if not reason:
        raise api_error(422, "bad_request", "Say why (the reason is kept in the record).")
    if not card_id.startswith(CARD_PREFIX):
        raise api_error(404, "not_found", "There is no control check with this id.")
    head = ctx.store.chain_head(study_id)
    if (body.expected_head is not None and body.expected_head != head) or analysed_study(
        ctx.studio, sid
    ) != study_id:
        raise api_error(409, "stale", STALE_GATE, head=head)
    pack = resolve_pack()
    report = _report(ctx, study_id, _choice(ctx, study_id))
    try:
        choice = gate_choice(report, pack, study_id, card_id, body.option)
    except ValueError:
        raise api_error(422, "bad_request", "This card has no such option.") from None
    if choice is None:
        raise api_error(404, "not_found", "There is no control check with this id.")
    record = _session_record(ctx, sid, study_id)
    view = build_view(report, pack, study_id, sid, head, "", record, _left_out(ctx.store, study_id))
    shown = next(c for c in view.consequences if c.decision_id == card_id)
    if not shown.can_decide:
        raise api_error(409, "studio", NOT_DECIDABLE)
    outcome = call(
        ctx.studio.decide_gate, sid, choice, HUMAN, reason, expected_head=body.expected_inbox
    )
    if outcome.status == "stale":
        raise api_error(409, "stale", STALE_GATE, head=outcome.head)
    if outcome.status not in ("left_out", "put_back", "kept"):
        raise api_error(403, "refused", f"Not done: {outcome.reason or 'refused'}.")
    changed(ctx, sid)
    job = ensure_analysis(ctx, sid)
    ctx.bus.publish({"type": "study.changed", "key": sid, "source": "page"})
    ctx.bus.publish({"type": "study.changed", "key": study_id, "source": "page"})
    n = len(outcome.left_out) or len(outcome.put_back)
    message = DONE_WORDS[outcome.status].format(
        n=n, wells="well" if n == 1 else "wells", them="it" if n == 1 else "them"
    )
    if outcome.not_put_back:
        message += (
            f" {len(outcome.not_put_back)} more were left out in a Prism round trip and stay "
            "left out."
        )
    return GateDecided(
        status=outcome.status,  # type: ignore[arg-type]
        message=message,
        study_id=study_id,
        left_out=outcome.left_out,
        put_back=outcome.put_back,
        inbox_head=outcome.head,
        job=job,
    )


# ---- run files a person links to a plate (G-INSTR) ------------------------------------------


def _plates(ctx: AppContext, study_id: str) -> list[str]:
    """The study's plates, as the gate reads them (409 while a first gate is loading).

    The plates do not depend on the run files linked or the analysis in use, so any report
    kept for this results version answers; a link made while the gate is read again with the
    previous one does not wait for it.
    """
    version = _version(ctx, study_id)
    with _lock:
        for key, report in reversed(_reports.items()):
            if key[:3] == (*version, study_id):
                return list(report.units)
    return list(_report(ctx, study_id, _choice(ctx, study_id)).units)


def _changed(ctx: AppContext, study_id: str, sid: str | None) -> None:
    ctx.bus.publish({"type": "study.changed", "key": study_id, "source": "page"})
    if sid:
        ctx.bus.publish({"type": "study.changed", "key": sid, "source": "page"})


@router.post("/studies/{study_id}/gate/run-files", response_model=GateRunLinked)
async def link_gate_run_file(
    study_id: str,
    ctx: Ctx,
    plate: Annotated[str | None, Form(max_length=200)] = None,
    run: Annotated[UploadFile | None, File(description=RUN_FILE_HELP)] = None,
) -> GateRunLinked:
    """A person links the run file the instrument wrote to one plate (G-INSTR reads it).

    The file is kept by content and read (what it says about the run; no serial number comes
    back); the link is kept for every analysis of the study's input file, with ``by: human``
    and the time. Blind like every result; ``bad_file`` (422) for a file qPilot cannot read or
    an RDML file; ``not_found`` (404) for a plate the study does not have.
    """
    from datetime import UTC, datetime

    from qpilot.core.store import sha256_file
    from qpilot.qpcr import run_links
    from qpilot.web import views
    from qpilot.web.routers.instruments import _keep_run, _read_run, _without_identity

    sid = _visible(ctx, study_id)  # blind first: a refused body says nothing either way
    if not plate or run is None:
        raise api_error(422, "bad_request", "Choose a plate and the run file to link to it.")
    if plate not in _plates(ctx, study_id):
        raise api_error(404, "not_found", NOT_A_PLATE)
    path = await _keep_run(ctx, run)
    context = _read_run(path)
    if context.source_kind == "rdml":
        raise api_error(422, "bad_file", RDML_RUN_FILE)
    name = _without_identity(views.display_name(path) or path.name, context)
    entry = run_links.RunLink(
        plate=plate,
        file=path.name,
        sha256=sha256_file(path),
        name=name[:200],
        kind=str(context.source_kind),
        at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    try:
        run_links.link(ctx.store.root, input_sha(ctx.store, study_id), entry)
    except run_links.RunLinkError as err:
        raise api_error(422, "bad_request", str(err)) from err
    _changed(ctx, study_id, sid)
    return GateRunLinked(
        plate=plate,
        linked=True,
        name=entry.name,
        kind=entry.kind,
        message=(
            "Linked: G-INSTR now reads this run file for the plate, in every analysis of this "
            "file. The controls are checked again."
        ),
    )


@router.post("/studies/{study_id}/gate/run-files/unlink", response_model=GateRunLinked)
def unlink_gate_run_file(study_id: str, body: GateRunUnlink, ctx: Ctx) -> GateRunLinked:
    """A person removes a plate's linked run file (G-INSTR reads the plate's own one again)."""
    from qpilot.qpcr import run_links

    sid = _visible(ctx, study_id)
    gone = run_links.unlink(ctx.store.root, input_sha(ctx.store, study_id), body.plate)
    if gone is None:
        raise api_error(404, "not_found", "No run file is linked to this plate.")
    _changed(ctx, study_id, sid)
    own = (
        "this plate's run file in the instrument export"
        if body.plate in study_exports(ctx.store, study_id)
        else "the study's own file for this plate"
    )
    return GateRunLinked(
        plate=body.plate,
        linked=False,
        name=gone.name,
        kind=gone.kind,
        message=f"Unlinked: G-INSTR reads {own} again.",
    )
