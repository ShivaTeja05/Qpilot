"""Build one study's report (:class:`~qpilot.report.model.ReportView`), cached per study state.

The report depends only on the study's files, its audit and the session's proposal chain; a
report built once is kept until one of them changes (:func:`qpilot.report.inputs.fingerprint`).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import UTC, datetime

from qpilot.core.store import StudyStore
from qpilot.io.datasets import VERMEULEN_SHA256
from qpilot.qpcr.confidence_checks import HOLDS_MIN
from qpilot.report import methods as methods_mod
from qpilot.report.context import Ctx
from qpilot.report.inputs import fingerprint, gather
from qpilot.report.miqe import miqe
from qpilot.report.model import (
    KeyNumber,
    ReportAudit,
    ReportDecision,
    ReportGene,
    ReportHeader,
    ReportView,
)
from qpilot.report.review import _label, _verdicts, limitations, review
from qpilot.report.text import Q, tok

MAX_CACHED = 6
_lock = threading.Lock()
_cache: OrderedDict[tuple, ReportView] = OrderedDict()


def report(store: StudyStore, study_id: str, session: str | None = None) -> ReportView:
    """The study's report (from the cache while nothing it reads has changed)."""
    key = (str(store.root), session, *fingerprint(store, study_id))
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    view = build(store, study_id, session)
    with _lock:
        _cache[key] = view
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
    return view


def build(store: StudyStore, study_id: str, session: str | None = None) -> ReportView:
    """Build the report afresh.

    Raises:
        StudyNotFound: No analysed study with this id.
        ProseError: A sentence would show a number that is not a fact (a bug, never output).
    """
    c = Ctx(gather(store, study_id, session))
    methods = methods_mod.methods(c)
    checklist = miqe(c)
    reviewer = review(c)
    limits = limitations(c)
    summary = _summary(c)
    keys = _key_numbers(c)
    from qpilot.qpcr.contrast import ConclusionRule

    rule = ConclusionRule(**c.result.conclusion_rule).describe()
    return ReportView(
        header=_header(c),
        summary=summary,
        key_numbers=keys,
        methods=methods,
        miqe=checklist,
        review=reviewer,
        limitations=limits,
        genes=_genes(c),
        decisions=_decisions(c),
        audit=_audit(c),
        rule=rule,
        facts=c.facts.cited_facts(),
    )


def _header(c: Ctx) -> ReportHeader:
    from qpilot.app_state import design_line

    r = c.result
    source = c.inputs.source
    return ReportHeader(
        study_id=c.inputs.study_id,
        session=c.inputs.session,
        title=design_line(r),
        source_name=source.name if source is not None else None,
        demo=r.input_sha256 == VERMEULEN_SHA256,
        input_sha256=r.input_sha256,
        chain_head=c.inputs.head,
        n_decisions=len(c.inputs.entries),
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        versions={k: str(v) for k, v in c.inputs.versions.items()},
    )


def _summary(c: Ctx):  # noqa: ANN202 - ReportText
    r = c.result
    a, b = c.group_names
    plates = c.count("n_plates", r.n_plates, "results.json:/n_plates")
    parts: list = []
    if c.has("f_n_samples", "f_n_reactions"):
        parts.append(
            f"{plates} plates, {tok('f_n_samples')} samples and {tok('f_n_reactions')} reactions. "
        )
    if c.has("f_n_genes", "f_n_hi", "f_n_lo"):
        parts += [
            f"{tok('f_n_genes')} genes compared between ",
            Q(a),
            f" ({tok('f_n_hi')} units) and ",
            Q(b),
            f" ({tok('f_n_lo')}). ",
        ]
    parts.append(
        f"At the planned analysis {c.call_count('up')} genes are up, {c.call_count('down')} down "
        f"and {c.call_count('none')} have no call"
    )
    if c.has("f_n_hold_lt_80", "f_n_cells"):
        holds = tok(
            c.facts.derive(
                "holds_min", HOLDS_MIN, "qpilot.qpcr.confidence_checks:/HOLDS_MIN", fmt="{:.0%}"
            )
        )
        parts.append(
            f"; {tok('f_n_hold_lt_80')} keep their call in fewer than {holds} of the "
            f"{tok('f_n_cells')} analyses qPilot checks"
        )
    parts.append(".")
    counts = c.inputs.audit.manifest.get("verdict_counts") if c.inputs.audit else None
    if isinstance(counts, dict) and "solid" in counts and "fragile" in counts:
        solid = c.audit_num("verdict_solid", "audit_manifest.json", "verdict_counts", "solid")
        fragile = c.audit_num("verdict_fragile", "audit_manifest.json", "verdict_counts", "fragile")
        parts.append(f" The audit finds {solid} genes solid and {fragile} fragile.")
    return c.t(*parts)


def _key_numbers(c: Ctx) -> list[KeyNumber]:
    r = c.result
    out = [
        KeyNumber(
            label="plates", fact=c.facts.derive("n_plates", r.n_plates, "results.json:/n_plates")
        )
    ]
    for label, fid in (
        ("samples", "f_n_samples"),
        ("reactions", "f_n_reactions"),
        ("genes compared", "f_n_genes"),
        ("analyses qPilot checks", "f_n_cells"),
    ):
        if c.has(fid):
            out.append(KeyNumber(label=label, fact=fid))
    a = c.inputs.audit
    if a is not None and isinstance(a.manifest.get("analyses"), int):
        fid = c.facts.derive(
            "audit_analyses",
            a.manifest["analyses"],
            "audit:audit_manifest.json:/analyses",
            fmt="{:,}",
        )
        out.append(KeyNumber(label="analyses in the audit", fact=fid))
    for k in out:
        if k.fact not in c.facts.cited:
            c.facts.cited.append(k.fact)
    return out


def _genes(c: Ctx) -> list[ReportGene]:
    verdicts = _verdicts(c)
    headline = c.headline
    order = headline + sorted(g for g in c.result.contrasts if g not in headline)
    rows = []
    for gene in order:
        con = c.result.contrasts[gene]
        rob = c.result.robustness.get(gene)
        grade = c.result.confidence.get(gene)
        verdict = verdicts.get(gene)
        rows.append(
            ReportGene(
                gene=gene,
                headline=gene in headline,
                conclusion=con.conclusion,
                fc=con.fc,
                ci_lo=float(con.ci[0]),
                ci_hi=float(con.ci[1]),
                p=con.p,
                n_hi=con.n_hi,
                n_lo=con.n_lo,
                holds=rob.holds if rob else None,
                n_cells=rob.n_cells if rob else 0,
                level=grade.level if grade else None,
                flips_by=sorted(
                    d for d, v in (rob.impact if rob else {}).items() if v.get("flips")
                ),
                verdict=verdict,
                verdict_label=_label(c, verdict) if verdict else None,
            )
        )
    return rows


def _decisions(c: Ctx) -> list[ReportDecision]:
    from qpilot.web.results_views import REVIEW_TITLE, REVIEW_WORDS

    cards = {card.id: card for card in [*c.inputs.cards, *c.inputs.traced]}
    out = []
    for e in c.inputs.entries:
        card = cards.get(e.card_id)
        review = e.kind == "review"  # a person's sign-off of the run: no card
        out.append(
            ReportDecision(
                seq=e.seq,
                card_id=e.card_id,
                card_title=REVIEW_TITLE if review else c.card_title(card) if card else e.card_id,
                option=e.option,
                option_label=(
                    REVIEW_WORDS.get(e.option, e.option)
                    if review
                    else c.option_label(card, e.option)
                    if card
                    else e.option
                ),
                actor=e.actor,
                status=e.status,
                at=e.at,
                reason=e.reason,
                hash=e.hash,
                can_flip=bool(card and card.impact.get("flips")),
            )
        )
    for card in c.open_cards:
        out.append(
            ReportDecision(
                seq=None,
                card_id=card.id,
                card_title=c.card_title(card),
                option=card.recommended,
                option_label=c.option_label(card, card.recommended),
                actor=None,
                status="open" if card.status == "open" else "waiting for a person",
                at=None,
                reason=None,
                hash=None,
                can_flip=bool(card.impact.get("flips")),
            )
        )
    return out


def _audit(c: Ctx) -> ReportAudit:
    a = c.inputs.audit
    if a is None:
        return ReportAudit(status="none")
    counts = a.manifest.get("verdict_counts") or {}
    reasonable = ((a.summary.get("multiverse") or {}).get("defensible") or {}).get("cells")
    return ReportAudit(
        status="ready",
        current=c.audit_current,
        chain_head=a.manifest.get("chain_head"),
        analyses=a.manifest.get("analyses"),
        reasonable=reasonable if isinstance(reasonable, int) else None,
        verdict_counts={str(k): int(v) for k, v in counts.items()},
        verdict_labels={str(k): _label(c, str(k)) for k in counts},
        reproduces=(a.manifest.get("reproduces_qpilot") or {}).get("ok"),
    )
