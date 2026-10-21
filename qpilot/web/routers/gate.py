"""Run Gate route: what the controls on each plate say, and whether any of it changes a call.

``GET /studies/{id}/gate`` evaluates the shipped rule pack (``research-default``) on the
study's wells (:func:`qpilot.qpcr.gate_rules.run_gate`) and, for every rule that warns or fails
and points at wells, re-runs the study's whole analysis grid without them (the consequence
test, :mod:`qpilot.core.gate`). It answers every evaluation with its reason in words (each number
a cited fact), every consequence with what each option would change, and the ``gate.rule``
Decision Cards in the shape the Results cards use.

Rules label; nothing is applied. A gate card has no grid dimension, so deciding it is not wired
here: the view says what leaving the wells out would change, and for a Studio session points to
the Curves section, where wells are excluded (and the study is analysed again).

Like every result, a study analysed from a Studio session answers ``403 blind`` until its design
and curves are confirmed (the results routes' rule). The first gate of a study re-reads its wells
and re-runs the grid once per option (about six seconds on the demo): it runs as a ``gate.run``
job, and a request that finds it still running answers ``409 loading`` with the job to follow.
The answer is kept per store, results version and decision chain head; the consequences are
measured at the analysis in use (each Decision Card's applied option, the planned one
elsewhere), so a decision that moves it measures them again. GETs never write.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter

from qpilot.core import gate as core_gate
from qpilot.core.rules import VERDICTS, RuleEval, RulePack
from qpilot.schemas import DecisionCard, Fact
from qpilot.web import results_views as rv
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import CardOptionView, CardView, FactText, JobView, OptionEffect
from qpilot.web.contract_gate import (
    GateConsequence,
    GateEvaluation,
    GateLoaded,
    GateOption,
    GatePack,
    GatePlate,
    GateRuleInfo,
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
APPLY_SESSION = (
    "Rules label; nothing here changes your analysis. To leave wells out, exclude them in "
    "Curves: the study is analysed again and the record says who decided and why."
)
APPLY_STUDY = (
    "Rules label; nothing here changes your analysis. This study was analysed outside Studio: "
    "open its file in Studio to leave wells out, or follow a call down to its wells in Trace."
)


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
    result = ctx.store.get(study_id)
    grid = rv.load_grid(ctx.store, result)
    if grid is None or grid.planned is None:
        return None
    cards = ctx.store.cards(study_id)
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
    file. ``rawness`` is not known here yet (the import's verdict is wired later).

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
    return run_gate(curves, settings, quantities=quantities, rawness=None, model=model, cell=cell)


def _report(ctx: AppContext, study_id: str, choice: dict[str, str] | None) -> core_gate.GateReport:
    """The kept report, or run it in a ``gate.run`` job (409 loading while it runs)."""
    key = (*_version(ctx, study_id), study_id, tuple(sorted((choice or {}).items())))
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
    level = next((k for k in ("sample", "target", "plate") if k in ev.scope), "study")
    return {
        "level": level,
        "plate": ev.scope.get("plate"),
        "target": ev.scope.get("target"),
        "sample": ev.scope.get("sample"),
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
    else:
        parts.append("Leaving out the wells they point at changes no call.")
    return rv.fact_text(" ".join(parts), facts)


def _card_view(
    card: DecisionCard,
    consequence: core_gate.Consequence,
    ev: RuleEval,
    facts: dict[str, Fact],
    option_texts: dict[str, FactText],
) -> CardView:
    from qpilot.core.card_kinds import kind_title
    from qpilot.core.decisions import needs_human

    keep = next((o for o in card.options if o.id == card.recommended), None)
    base = {g: r.conclusion for g, r in keep.per_gene.items()} if keep else {}
    options = [
        CardOptionView(
            id=o.id,
            label=o.label,
            recommended=o.id == card.recommended,
            chosen=o.id == card.decision,
            requested=False,
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
            "Waiting for a person: leaving the wells out changes a call. Keep them, or exclude "
            "them where wells are excluded (Curves in Studio)."
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
        pending=[],
    )


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
) -> GateView:
    """The page's view of one gate report (words, facts in sentences, cards as Results shows)."""
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
        consequences.append(
            GateConsequence(
                id=core_gate.eval_id(ev),
                rule_id=c.rule_id,
                title=titles.get(c.rule_id, c.rule_id),
                **scope,
                verdict=c.verdict,
                consequence=c.consequence,
                triage=c.triage,
                triage_text=TRIAGE_TEXT[c.triage],
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
                    )
                    for o in c.options
                ],
                card_id=c.card_id,
            )
        )
        if c.card_id and c.card_id in by_card:
            cards.append(_card_view(by_card[c.card_id], c, ev, facts, texts))
    cards.sort(key=lambda v: v.card.rank)
    plates = []
    for plate, status in report.units.items():
        mine = [ev.verdict for ev in report.evals if ev.scope.get("plate") == plate]
        counts = {v: mine.count(v) for v in VERDICTS}
        worst = next((v for v in WORST if counts[v]), "not_applicable")
        plates.append(GatePlate(plate=plate, status=status, counts=counts, worst=worst))
    n_gated = sum(1 for p in plates if p.status == "gated")
    return GateView(
        study_id=study_id,
        session=session,
        head=head,
        pack=_pack(pack),
        headline=headline,
        analysis="planned" if analysis == "planned" else "your_choices",
        exclude_in="curves" if session else "none",
        how_to_apply=APPLY_SESSION if session else APPLY_STUDY,
        plates=plates,
        n_gated=n_gated,
        n_ungated=len(plates) - n_gated,
        counts=dict(report.counts),
        triage=dict(report.triage),
        evaluations=evaluations,
        consequences=consequences,
        cards=cards,
    )


# ---- the route -----------------------------------------------------------------------------


@router.get("/studies/{study_id}/gate", response_model=GateView)
def get_gate(study_id: str, ctx: Ctx) -> GateView:
    """The controls on every plate, by rule, and whether leaving their wells out changes a call."""
    from qpilot.qpcr.gate_rules import resolve_pack

    sid = _visible(ctx, study_id)
    head = ctx.store.chain_head(study_id)
    vkey = (*_version(ctx, study_id), study_id, head)
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
    )
    _keep(_views, vkey, view)
    return view
