"""Run Review: one page per run, for the person who reviews someone else's work.

The page composes parts that already exist; it adds no maths:

* the headline genes with their call, fold change, confidence level and how often the
  conclusion holds across the robustness grid (all from the stored results);
* the Evidence Ledger (:mod:`qpilot.qpcr.evidence`): what the data can show and what nobody
  recorded;
* what to repeat and why, and the Run Gate per plate, when it is given the study's repeat plan
  (:mod:`qpilot.qpcr.repeat`, which reads the Run Gate, the wells a person left out and Trace):
  the most consequential items, each with its first reason, and the plates a rule warns or
  fails on; without the plan the page says where to see them;
* the sign-offs a person recorded (decision-log entries of kind ``review``, outcome
  ``accept``, ``repeat`` or ``discuss``). This module only renders the entries it is given;
  writing one is the store's job (``StudyStore.append_review``, actor ``human`` only).

What to change next run does not exist yet: it is listed as not available, never filled in.

The page never judges the run: it does not say a run passed, failed or is fit for anything.
Every number on it is a ``{{fact_id}}`` token checked by :func:`qpilot.core.validator.validate`
before it is rendered (:func:`render_text`, :func:`render_html`); names and comments are
HTML-escaped. Deterministic; no model call and no network.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

from qpilot.core.facts import slug
from qpilot.core.validator import render_tokens
from qpilot.explain.evidence_text import (
    GATE_ELSEWHERE,
    NO_HEADLINE,
    NO_SIGNOFF,
    NOT_AVAILABLE,
    PURPOSE,
    REPEAT_ELSEWHERE,
    STATUS_WORDS,
    comparison_lines,
    gate_plate_lines,
    headline_lines,
    item_line,
    ledger_missing,
    ledger_summary,
    render_facts,
    repeat_lines,
    runreview_text,
    signoff_lines,
    study_line,
)
from qpilot.explain.templates import to_html
from qpilot.qpcr.designs import HEADLINE_GENES
from qpilot.qpcr.evidence import (
    CONSEQUENCES,
    ITEM_TITLES,
    ITEMS,
    LEDGER_VERSION,
    EvidenceError,
    EvidenceLedger,
    evidence_store,
)
from qpilot.qpcr.repeat import CONSEQUENCE_WORDS, SOURCE_WORDS, RepeatPlan
from qpilot.schemas import Conclusion, Fact, StudyResult

REVIEW_VERSION = 1
OUTCOMES: tuple[str, ...] = ("accept", "repeat", "discuss")
CALL_WORDS: dict[str, str] = {"up": "called up", "down": "called down", "none": "not called"}
STUDY_FACTS = ("f_n_plates", "f_n_samples", "f_n_reactions", "f_n_cells")
DISCLAIMER = "For research use only. Not for clinical or diagnostic use."
FOOTER = "Every number on this page is a fact from the study's outputs; hover over it to see which."
MIQE_NOTE = (
    "MIQE item numbers follow the article's table as abbreviated in qPilot's research notes; "
    "they are still to be checked against the article. Absent items never change a conclusion "
    "or a confidence grade."
)
SIGNOFF_NOTE = (
    "A person records a sign-off in the study's decision log; this page only shows the "
    "sign-offs recorded there."
)
EVIDENCE_FILE = "evidence.json"  # the store artifact the ledger is kept in, once written
REPEAT_SHOWN = 15  # repeat items the page lists (the rest are counted)


class RunReviewError(ValueError):
    """A sign-off entry that is not a review entry, or a page that fails the validator."""


class HeadlineGene(BaseModel):
    """One headline gene as the page shows it, with the fact ids behind each number."""

    gene: str
    conclusion: Conclusion
    fc: float
    level: str | None = None
    holds: float | None = None
    facts: list[str]


class SignOff(BaseModel):
    """A recorded review decision, as the page shows it."""

    seq: int
    outcome: Literal["accept", "repeat", "discuss"]
    reviewer: str
    comment: str = ""
    at: str = ""
    hash: str = ""
    facts: list[str]


class Unavailable(BaseModel):
    """A part of the full Run Review that is not built yet."""

    id: str
    title: str
    reason: str


class RunReview(BaseModel):
    """The thin Run Review of one study: headline, Evidence Ledger, sign-offs, gaps.

    ``facts`` holds every fact the page cites (the study facts it uses, the ledger's facts
    and the ``f_rr_*`` facts of the headline and sign-offs).
    """

    version: int = REVIEW_VERSION
    study_id: str
    input_sha256: str
    ledger: EvidenceLedger | None = None
    ledger_note: str = ""
    headline: list[HeadlineGene]
    reviews: list[SignOff]
    not_available: list[Unavailable]
    repeat: RepeatPlan | None = None
    facts: dict[str, Fact]

    def tokens(self) -> str:
        """The whole page as token text (``runreview_v1``), one line per point."""
        return runreview_text(self.facts)


# ---------- building ----------


def _entry_data(entry: Any) -> dict[str, Any]:
    if isinstance(entry, BaseModel):
        return entry.model_dump(mode="json")
    if isinstance(entry, Mapping):
        return dict(entry)
    raise RunReviewError(f"a sign-off must be a mapping or a model, not {type(entry).__name__}")


def _sign_off(entry: Any) -> SignOff:
    """A decision-log entry of kind ``review`` as a :class:`SignOff`; anything else is refused."""
    data = _entry_data(entry)
    if data.get("kind") != "review":
        raise RunReviewError("only decision-log entries of kind 'review' are sign-offs")
    outcome = data.get("outcome") or data.get("option")
    if outcome not in OUTCOMES:
        raise RunReviewError(f"a review outcome is one of {', '.join(OUTCOMES)}, not {outcome!r}")
    reviewer = str(data.get("reviewer") or "").strip()
    if not reviewer:
        raise RunReviewError("a review entry names its reviewer")
    seq = data.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise RunReviewError("a review entry has a decision-log sequence number")
    return SignOff(
        seq=seq,
        outcome=outcome,
        reviewer=reviewer,
        comment=" ".join(str(data.get("reason") or data.get("comment") or "").split()),
        at=str(data.get("at") or ""),
        hash=str(data.get("hash") or ""),
        facts=[],
    )


def build_review(
    result: StudyResult,
    *,
    headline: Sequence[str] = HEADLINE_GENES,
    ledger: EvidenceLedger | None = None,
    ledger_note: str = "",
    reviews: Iterable[Any] = (),
    repeat: RepeatPlan | None = None,
) -> RunReview:
    """The Run Review of a study from its stored results (pure; nothing is read or written).

    Args:
        result: The study's stored results (``StudyStore.get``).
        headline: The headline genes, in order; genes the study does not have are left out.
        ledger: The study's Evidence Ledger, or ``None`` when it is not available.
        ledger_note: Why the ledger is not available (shown on the page).
        reviews: Decision-log entries of kind ``review`` (mappings or models with ``seq``,
            ``outcome`` (or ``option``), ``reviewer``, ``reason``, ``at``, ``hash``).
        repeat: The study's repeat plan (:func:`qpilot.qpcr.repeat.build_plan`), for what to
            repeat and why and the Run Gate per plate; ``None``: the page says where to see them.

    Raises:
        RunReviewError: An entry is not a review entry, two share a sequence number, or the
            ledger belongs to another study.
    """
    facts: dict[str, Fact] = {}

    def add(
        fid: str, value: float | int | str, fmt: str = "{}", path: str = "", unit: str = ""
    ) -> str:
        facts[fid] = Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path)
        return fid

    def copy(fid: str) -> str | None:
        if fid not in result.facts:
            return None
        facts[fid] = result.facts[fid]
        return fid

    add("f_rr_study_id", result.study_id, path="review.study_id")
    for fid in STUDY_FACTS:
        copy(fid)
    genes = [gene for gene in dict.fromkeys(headline) if gene in result.contrasts]
    shown = []
    for i, gene in enumerate(genes, start=1):
        s, robust, graded = slug(gene), result.robustness.get(gene), result.confidence.get(gene)
        conclusion = robust.conclusion if robust is not None else result.contrasts[gene].conclusion
        call = CALL_WORDS[conclusion]
        ids = [
            add(f"f_rr_headline_{i}_gene", gene, path=f"review.headline[{i - 1}].gene"),
            add(f"f_rr_headline_{i}_call", call, path=f"robustness.{gene}.conclusion"),
        ]
        ids += [f for f in (copy(f"f_fc_{s}_recommended"), copy(f"f_level_{s}"),
                            copy(f"f_holds_{s}")) if f]  # fmt: skip
        shown.append(
            HeadlineGene(
                gene=gene,
                conclusion=conclusion,
                fc=result.contrasts[gene].fc,
                level=graded.level if graded is not None else None,
                holds=robust.holds if robust is not None else None,
                facts=ids,
            )
        )
    _comparison_facts(result, genes, add)
    if ledger is not None:
        if ledger.study_id is not None and ledger.study_id != result.study_id:
            raise RunReviewError("the Evidence Ledger belongs to another study")
        facts.update(ledger.facts)
    elif ledger_note:
        add("f_rr_ledger_note", ledger_note, path="review.ledger_note")
    if repeat is not None:
        if repeat.study_id != result.study_id:
            raise RunReviewError("the repeat plan belongs to another study")
        _repeat_facts(repeat, add)
    signoffs = sorted((_sign_off(entry) for entry in reviews), key=lambda o: o.seq)
    seqs = [o.seq for o in signoffs]
    if len(set(seqs)) != len(seqs):
        raise RunReviewError("two review entries share a decision-log sequence number")
    for k, signoff in enumerate(signoffs):
        p, path = f"f_rr_review_{signoff.seq}", f"review.reviews[{k}]"
        ids = [
            add(f"{p}_seq", signoff.seq, path=f"{path}.seq"),
            add(f"{p}_reviewer", signoff.reviewer, path=f"{path}.reviewer"),
            add(f"{p}_outcome", signoff.outcome, path=f"{path}.outcome"),
        ]
        if signoff.at:
            ids.append(add(f"{p}_at", signoff.at, path=f"{path}.at"))
        if signoff.comment:
            ids.append(add(f"{p}_comment", signoff.comment, path=f"{path}.comment"))
        signoffs[k] = signoff.model_copy(update={"facts": ids})
    return RunReview(
        study_id=result.study_id,
        input_sha256=result.input_sha256,
        ledger=ledger,
        ledger_note="" if ledger is not None else ledger_note,
        headline=shown,
        reviews=signoffs,
        not_available=[Unavailable(id=i, title=t, reason=r) for i, t, r in NOT_AVAILABLE],
        repeat=repeat,
        facts=dict(sorted(facts.items())),
    )


def _comparison_facts(result: StudyResult, genes: Sequence[str], add: Any) -> None:
    """``f_rr_cmp<i>_*``: each comparison of a study with several, and its headline genes.

    Nothing for a study with one comparison. Values are read from ``StudyResult.comparisons``
    (the stored outcomes, at the planned analysis), the p is the one each call used.
    """
    from qpilot.qpcr.contrast import CORRECTED, CORRECTION_WORDS

    found = result.comparisons
    if found is None or len(found.comparisons) < 2:
        return
    corrected = found.correction in CORRECTED
    if corrected:
        words = CORRECTION_WORDS[found.correction]
        add("f_rr_cmp_correction", words, path="comparisons.correction")
    for i, o in enumerate(found.comparisons, start=1):
        p, root = f"f_rr_cmp{i}", f"comparisons.{o.id}"
        add(f"{p}_label", o.label, path=f"{root}.label")
        if o.primary:
            add(f"{p}_first", "first", path=f"{root}.primary")
        if corrected:
            add(f"{p}_corrected", "corrected", path="comparisons.correction")
        for j, gene in enumerate((g for g in genes if g in o.contrasts), start=1):
            g, c = f"{p}_gene{j}", o.contrasts[gene]
            add(f"{g}_name", gene, path=f"{root}.contrasts.{gene}.target")
            add(f"{g}_call", CALL_WORDS[c.conclusion], path=f"{root}.contrasts.{gene}.conclusion")
            if math.isfinite(c.fc):
                add(f"{g}_fc", float(c.fc), "{:.2g}", f"{root}.contrasts.{gene}.fc", "×")
            p_used = o.p_adjusted.get(gene)
            if p_used is not None and math.isfinite(p_used):
                add(f"{g}_p", float(p_used), "{:.2g}", f"{root}.p_adjusted.{gene}")
            robust = o.robustness.get(gene)
            if robust is not None:
                add(f"{g}_holds", float(robust.holds), "{:.0%}", f"{root}.robustness.{gene}.holds")


def _repeat_facts(plan: RepeatPlan, add: Any) -> None:
    """The repeat plan's facts: counts, the shown items (names are string facts) and the gate."""
    add("f_rr_repeat_n_items", len(plan.items), "{:,}", "repeat.items@len")
    add("f_rr_repeat_n_changes_call", plan.counts.get("changes_call", 0), "{:,}", "repeat.counts")
    if plan.wells:
        add("f_rr_repeat_n_wells", plan.n_wells, "{:,}", "repeat.n_wells")
        add("f_rr_repeat_n_plates", plan.n_plates, "{:,}", "repeat.n_plates")
        if plan.calibrator:
            add("f_rr_repeat_calibrator", plan.calibrator, path="repeat.calibrator")
    for i, item in enumerate(plan.items[:REPEAT_SHOWN], start=1):
        p, path = f"f_rr_repeat_{i}", f"repeat.items[{i - 1}]"
        add(f"{p}_sample", item.sample, path=f"{path}.sample")
        add(f"{p}_target", item.target or "every gene", path=f"{path}.target")
        add(f"{p}_consequence", CONSEQUENCE_WORDS[item.consequence], path=f"{path}.consequence")
        if item.changed_calls:
            add(f"{p}_calls", ", ".join(item.changed_calls), path=f"{path}.changed_calls")
        first = item.reasons[0] if item.reasons else None
        why = f"{SOURCE_WORDS.get(first.source, first.source)}: {first.words}" if first else ""
        if len(item.reasons) > 1:
            why += f" (and {len(item.reasons) - 1} more reason(s))"
        add(f"{p}_why", why, path=f"{path}.reasons")
    if len(plan.items) > REPEAT_SHOWN:
        add("f_rr_repeat_n_more", len(plan.items) - REPEAT_SHOWN, "{:,}", "repeat.items@len")
    if not plan.gate_lines:
        return
    flagged = [line for line in plan.gate_lines if line.worst in ("fail", "warn")]
    add("f_rr_gate_n_plates", len(plan.gate_lines), "{:,}", "repeat.gate_lines@len")
    add("f_rr_gate_n_flagged", len(flagged), "{:,}", "repeat.gate_lines")
    for k, line in enumerate(flagged, start=1):
        p, path = f"f_rr_gate_{k}", f"repeat.gate_lines[{k - 1}]"
        add(f"{p}_plate", line.plate, path=f"{path}.plate")
        add(f"{p}_worst", "fails" if line.worst == "fail" else "warns", path=f"{path}.worst")
        add(f"{p}_n_fail", line.counts.get("fail", 0), "{:,}", f"{path}.counts.fail")
        add(f"{p}_n_warn", line.counts.get("warn", 0), "{:,}", f"{path}.counts.warn")


def _stored_ledger(store: Any, study_id: str) -> EvidenceLedger | None:
    """The ledger the store kept for this study, when the store can hold artifacts."""
    getter = getattr(store, "get_artifact", None)
    if getter is None:
        return None
    data = getter(study_id, EVIDENCE_FILE)
    if not data:
        return None
    ledger = EvidenceLedger.model_validate(data)
    return ledger if ledger.version == LEDGER_VERSION else None


def run_review(
    store: Any,
    study_id: str,
    *,
    reviews: Iterable[Any] = (),
    ledger: EvidenceLedger | None = None,
    repeat: RepeatPlan | None = None,
) -> RunReview:
    """The Run Review of a stored study (read-only).

    Args:
        store: A :class:`~qpilot.core.store.StudyStore`.
        study_id: The study id (or a unique prefix).
        reviews: The study's review sign-offs (``StudyStore.reviews`` once it exists); only
            these are shown, and nothing is written.
        ledger: The Evidence Ledger to show. By default the one the store kept
            (``evidence.json``), else one rebuilt from the input file; when neither is
            possible the page says the ledger is not available and why.
        repeat: The study's repeat plan (:func:`repeat_plan_store` builds it);
            ``None``: the page says where to see what to repeat and the Run Gate per plate.

    Raises:
        StudyNotFound: No such study.
        RunReviewError: An entry in ``reviews`` is not a review entry.
    """
    result = store.get(study_id)
    design = store.design(study_id)
    headline = tuple(design.headline) if design is not None else HEADLINE_GENES
    note = ""
    if ledger is None:
        ledger = _stored_ledger(store, study_id)
    if ledger is None:
        try:
            ledger = evidence_store(store, study_id)
        except EvidenceError as err:
            note = str(err)
    return build_review(result, headline=headline, ledger=ledger, ledger_note=note,
                        reviews=reviews, repeat=repeat)  # fmt: skip


def repeat_plan_store(
    store: Any, study_id: str, *, include: Literal["consequential", "all"] = "consequential"
) -> RepeatPlan:
    """The repeat plan of a stored study at the analysis in use (read-only).

    Reads what the page reads: Trace's context and the Run Gate at each Decision Card's applied
    option (the gate is computed here: about half a minute on the demo the first time), and, for
    a study of a Studio session, the session's record of the wells a person left out.

    Raises:
        StudyNotFound: No such study.
        qpilot.qpcr.trace.TraceError: The input file is missing or changed, or the re-analysis
            does not reproduce the stored results.
        qpilot.qpcr.repeat.RepeatError: The repeat plate cannot be laid out.
    """
    from qpilot.qpcr import trace as trace_engine
    from qpilot.qpcr.gate_rules import resolve_pack
    from qpilot.qpcr.repeat import build_plan, left_out_from_inbox
    from qpilot.web.results_views import session_of_study
    from qpilot.web.routers.gate import analysis_choice, report_for

    study_id = store.get(study_id).study_id
    ctx = trace_engine._store_context(store, study_id, analysis_choice(store, study_id))
    gate = report_for(store, study_id)
    sid = session_of_study(store, study_id)
    left = left_out_from_inbox(store.proposals(sid).accepted(), ctx) if sid else {}
    return build_plan(study_id, ctx, gate=gate, pack=resolve_pack(), left_out=left, include=include)


# ---------- rendering ----------


def _checked(review: RunReview, key: str, tokens: str) -> str:
    """Token text that passed the validator (``RunReviewError`` otherwise)."""
    try:
        render_facts(key, tokens, review.facts)
    except ValueError as err:
        raise RunReviewError(str(err)) from err
    return tokens


def _ledger_rows(review: RunReview) -> list[tuple[str, str, str, str]]:
    """(item title, status words, consequence tokens, MIQE token) per ledger item."""
    if review.ledger is None:
        return []
    rows = []
    for item in ITEMS:
        status = review.facts.get(f"f_ev_{item}_status")
        code = review.facts.get(f"f_ev_{item}_code")
        if status is None or code is None:
            continue
        rows.append(
            (
                ITEM_TITLES[item],
                STATUS_WORDS[str(status.value)],
                CONSEQUENCES[str(code.value)],
                "{{f_ev_" + item + "_miqe}}",
            )
        )
    return rows


def _ledger_head(review: RunReview) -> str:
    """The ledger's summary line, or why there is no ledger (token text)."""
    summary = ledger_summary(review.facts) if review.ledger is not None else None
    return summary or ledger_missing(review.facts)


def render_text(review: RunReview) -> str:
    """The Run Review as plain text: headings, then one line per point.

    Raises:
        RunReviewError: Some text on the page fails the validator.
    """
    facts = review.facts

    def show(tokens: str) -> str:
        return render_tokens(_checked(review, "runreview_v1", tokens), facts)

    out = ["Run Review", "", show(study_line(facts)), show(PURPOSE), "", "Headline"]
    out += [f"- {show(line)}" for line in headline_lines(facts) or [NO_HEADLINE]]
    if lines := comparison_lines(facts):
        out += ["", "Comparisons"]
        out += [f"- {show(line)}" for line in lines]
    out += ["", "Evidence Ledger", show(_ledger_head(review))]
    if review.ledger is not None:
        out += [f"- {show(line)}" for item in ITEMS if (line := item_line(facts, item))]
    out += ["", "What to repeat and why"]
    lines = repeat_lines(facts)
    out += [f"- {show(line)}" for line in lines] if lines else [show(REPEAT_ELSEWHERE)]
    out += ["", "Run Gate per plate"]
    lines = gate_plate_lines(facts)
    out += [f"- {show(line)}" for line in lines] if lines else [show(GATE_ELSEWHERE)]
    out += ["", "Sign-off"]
    out += [f"- {show(line)}" for line in signoff_lines(facts) or [NO_SIGNOFF]]
    out += ["", "Not available yet"]
    out += [f"- {show(f'{part.title}: {part.reason}')}" for part in review.not_available]
    out += ["", show(DISCLAIMER)]
    return "\n".join(out) + "\n"


_STYLE = """
:root { --bg: #ffffff; --fg: #1d1d1f; --muted: #5f6368; --line: #d9d9de; --chip: #f2f2f5;
        --present: #1e6b3a; --absent: #9a3412; --other: #4b5563; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #16171a; --fg: #ececf1; --muted: #a0a3ab; --line: #34363c; --chip: #23252a;
          --present: #7bd29b; --absent: #f2a36b; --other: #b8bcc6; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.15rem; margin: 28px 0 8px; border-bottom: 1px solid var(--line);
     padding-bottom: 4px; }
p, li { max-width: 72ch; }
.muted { color: var(--muted); font-size: 0.9rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
th, td { text-align: left; vertical-align: top; padding: 6px 8px;
         border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 600; }
.table-wrap { overflow-x: auto; }
.status { display: inline-block; padding: 0 8px; border-radius: 999px; background: var(--chip);
          white-space: nowrap; }
.status-present { color: var(--present); }
.status-absent { color: var(--absent); }
.status-not_applicable, .status-unknown { color: var(--other); }
.fact { font-variant-numeric: tabular-nums; border-bottom: 1px dotted var(--muted); }
"""


def render_html(review: RunReview) -> str:
    """The Run Review as one self-contained HTML page (inline style, no script, no links).

    Every number is a ``<span class="fact" data-fact="f_...">``; all other text, names and
    comments included, is HTML-escaped.

    Raises:
        RunReviewError: Some text on the page fails the validator.
    """
    facts = review.facts

    def show(tokens: str, key: str = "runreview_v1") -> str:
        return to_html(_checked(review, key, tokens), facts)

    body = [
        "<h1>Run Review</h1>",
        f"<p>{show(study_line(facts))}</p>",
        f'<p class="muted">{show(PURPOSE)}</p>',
        "<h2>Headline</h2>",
    ]
    lines = headline_lines(facts)
    items = "".join(f"<li>{show(line)}</li>" for line in lines)
    body.append(f"<ul>{items}</ul>" if lines else f"<p>{show(NO_HEADLINE)}</p>")
    if lines := comparison_lines(facts):
        body.append("<h2>Comparisons</h2>")
        body.append("<ul>" + "".join(f"<li>{show(line)}</li>" for line in lines) + "</ul>")
    body.append("<h2>Evidence Ledger</h2>")
    body.append(f"<p>{show(_ledger_head(review), 'evidence_v1')}</p>")
    rows = _ledger_rows(review)
    if rows:
        head = show("MIQE {{f_ev_miqe_version}} item", "evidence_v1")
        body.append(
            '<div class="table-wrap"><table><thead><tr><th>Item</th><th>Status</th>'
            f"<th>What it means</th><th>{head}</th></tr></thead><tbody>"
        )
        for title, status, consequence, miqe in rows:
            css = next(k for k, v in STATUS_WORDS.items() if v == status)
            body.append(
                f"<tr><td>{show(title)}</td>"
                f'<td><span class="status status-{css}">{show(status)}</span></td>'
                f"<td>{show(consequence, 'evidence_v1')}</td>"
                f"<td>{show(miqe, 'evidence_v1')}</td></tr>"
            )
        body.append("</tbody></table></div>")
        body.append(f'<p class="muted">{show(MIQE_NOTE)}</p>')
    for title, lines, missing in (
        ("What to repeat and why", repeat_lines(facts), REPEAT_ELSEWHERE),
        ("Run Gate per plate", gate_plate_lines(facts), GATE_ELSEWHERE),
    ):
        body.append(f"<h2>{title}</h2>")
        items = "".join(f"<li>{show(line)}</li>" for line in lines)
        body.append(f"<ul>{items}</ul>" if lines else f"<p>{show(missing)}</p>")
    body.append("<h2>Sign-off</h2>")
    lines = signoff_lines(facts)
    items = "".join(f"<li>{show(line)}</li>" for line in lines)
    body.append(f"<ul>{items}</ul>" if lines else f"<p>{show(NO_SIGNOFF)}</p>")
    body.append(f'<p class="muted">{show(SIGNOFF_NOTE)}</p>')
    body.append("<h2>Not available yet</h2><ul>")
    body += [f"<li>{show(f'{part.title}: {part.reason}')}</li>" for part in review.not_available]
    body.append("</ul>")
    footer = f"{DISCLAIMER} {FOOTER}"
    body.append(f'<p class="muted">{show(footer)}</p>')
    return (
        '<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>qPilot Run Review</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n<main>\n"
        + "\n".join(body)
        + "\n</main>\n</body>\n</html>\n"
    )
