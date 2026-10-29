"""The Quantities view: a stored study's standard curves and every unknown's quantity.

Built from the study's own input file and confirmed design, as the analysis was: the per-well
table (the curve cache), the design's well roles and exclusions
(:func:`qpilot.qpcr.designs.design_curves`), its primary amplification rule and well calls, the
standards' quantities (a person's on the Design page over the file's declared ones), the
biological units, and the reaction input when a person gave it. :func:`qpilot.qpcr.absolute.
quantify` does every number. One study's quantification is kept in memory (by study id and
input file), so the chart and the table cost one computation.

Units carry their group only for a groups design (a person's groups), and only after the blind
stages are confirmed (the routes check that first, as Results does).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from qpilot.qpcr import absolute as ab
from qpilot.qpcr.absolute_study import QuantitiesUnavailable, for_study
from qpilot.web.contract_absolute import (
    AssayQuantities,
    AssaySummary,
    BandPoint,
    CurveDetail,
    CurveSummary,
    FlagView,
    LevelView,
    LimitView,
    NotQuantified,
    QuantitiesSettings,
    QuantitiesView,
    ReactionView,
    StandardPointView,
    UnitQuantity,
    UnknownWellView,
)

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

NO_STANDARDS = (
    "This study has no standards with a known quantity. Absolute quantities need a dilution "
    "series of known quantity on the plate: type its wells as standards and give the top "
    "quantity and the dilution step on the Design page."
)
NO_FILE = "the study's input file is not known or has changed"


# ---- views -------------------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _limit(limit: ab.Limit) -> LimitView:
    return LimitView(
        quantity=_num(limit.quantity),
        method=limit.method,  # type: ignore[arg-type]
        words=limit.words,
        at_most=limit.at_most,
    )


def _settings(result: ab.Absolute) -> QuantitiesSettings:
    s = result.settings
    return QuantitiesSettings(
        lod_rate=s.lod_rate, loq_cv=s.loq_cv, min_levels=s.min_levels, prediction_level=ab.PI_LEVEL
    )


def _reaction(result: ab.Absolute) -> ReactionView | None:
    r = result.reaction
    if r is None:
        return None
    return ReactionView(template_ul=r.template_ul, input_ng=r.input_ng, unit=r.unit)


def _summary(curve: ab.StandardCurve, n_unknowns: int) -> dict[str, Any]:
    fit = curve.fit
    out: dict[str, Any] = {
        "id": curve.id,
        "target": curve.target,
        "scope": curve.scope,
        "runs": list(curve.runs),
        "fitted": fit is not None,
        "problem": curve.problem,
        "lod": _limit(curve.lod),
        "lod_model": _limit(curve.lod_model) if curve.lod_model is not None else None,
        "loq": _limit(curve.loq),
        "quantity_source": curve.quantity_source,
        "warnings": list(curve.warnings),
        "n_levels": len({p.quantity for p in curve.points if p.detected}),
        "top": _num(curve.top),
        "lowest": _num(curve.lowest),
        "n_unknowns": n_unknowns,
    }
    if fit is not None:
        low, high = fit.efficiency_ci
        out.update(
            slope=fit.slope,
            intercept=fit.intercept,
            r2=_num(fit.r2),
            efficiency=_num(fit.efficiency),
            efficiency_low=_num(low),
            efficiency_high=_num(high),
            s_yx=_num(fit.s_yx),
            n_wells=fit.n,
        )
    return out


def _readers(result: ab.Absolute) -> dict[str, int]:
    counts: dict[str, int] = {}
    for u in result.unknowns:
        for cid in u.curves:
            counts[cid] = counts.get(cid, 0) + 1
    return counts


def computed(store: StudyStore, study_id: str) -> Any:
    """The study's quantification (cached by study and input file).

    Raises:
        QuantitiesUnavailable: The input file is unknown or changed.
    """
    result = store.get(study_id)
    path = store.source(study_id)
    if path is None or not Path(path).is_file():
        raise QuantitiesUnavailable(NO_FILE)
    design = store.design(study_id)
    return for_study(study_id, result.input_sha256, Path(path), design, in_use(store, study_id))


def in_use(store: StudyStore, study_id: str) -> dict[str, str] | None:
    """A quantification study's analysis in use (its cards' decisions); ``None`` otherwise."""
    from qpilot.qpcr.quantify_study import analysis_in_use, is_quantify

    design = store.design(study_id)
    if not is_quantify(design):
        return None
    return analysis_in_use(design, store.cards(study_id))


def quantities_view(
    store: StudyStore, study_id: str, *, can_set_reaction: bool = False
) -> QuantitiesView:
    """Every assay with standards: its curves' numbers and how many units it quantified."""
    from qpilot.qpcr.absolute import METHOD_CARD_PATH, REFERENCES
    from qpilot.qpcr.quantify_study import CLASS_WORDS, CLASSES, class_of

    found = computed(store, study_id)
    result = found.result
    readers = _readers(result)
    assays = []
    for target in sorted({c.target for c in result.curves}):
        curves, units = result.for_target(target)
        by_class: dict[str, int] = {}
        for u in units:
            by_class[class_of(u)] = by_class.get(class_of(u), 0) + 1
        assays.append(
            AssaySummary(
                target=target,
                curves=[CurveSummary(**_summary(c, readers.get(c.id, 0))) for c in curves],
                n_units=len(units),
                n_quantified=sum(1 for u in units if u.log10_quantity is not None),
                n_flagged=sum(1 for u in units if u.flags),
                by_class={k: by_class[k] for k in CLASSES if k in by_class},
            )
        )
    not_quantified = [
        NotQuantified(target=t, reason=r) for t, r in sorted(result.not_quantified.items())
    ]
    available = bool(assays)
    quantify = in_use(store, study_id) is not None
    return QuantitiesView(
        study_id=study_id,
        available=available,
        why="" if available or not_quantified else NO_STANDARDS,
        unit=result.unit,
        settings=_settings(result),
        reaction=_reaction(result),
        can_set_reaction=can_set_reaction,
        assays=assays,
        not_quantified=not_quantified,
        groups_shown=found.groups is not None,
        notes=list(found.notes),
        method_card=METHOD_CARD_PATH,
        references=list(REFERENCES),
        purpose="quantify" if quantify else "compare",
        analysis=_analysis_words(store, study_id) if quantify else [],
        classes=[FlagView(id=k, words=CLASS_WORDS[k]) for k in CLASSES],
    )


def _analysis_words(store: StudyStore, study_id: str) -> list[str]:
    """A quantification study's analysis in use, in words (the cards' options)."""
    from qpilot.qpcr import quantify_study as qs

    design = store.design(study_id)
    cards = store.cards(study_id)
    now = qs.analysis_in_use(design, cards)
    planned = qs.analysis_in_use(design, [])
    loq = f"{float(now['loq_cv']) * 100:g} %"
    out = [
        f"Wells count as detected by {qs.option_label('amp_call', now['amp_call'])}.",
        f"The limit of quantification asks for a read-back CV of at most {loq}.",
    ]
    if now != planned:
        out.append("A person chose these on the cards; the analysis as planned is listed there.")
    return out


def assay_view(store: StudyStore, study_id: str, target: str) -> AssayQuantities:
    """One assay's curves in full and every unit's quantity.

    Raises:
        KeyError: The study has no standard curve for this assay.
    """
    from qpilot.qpcr.quantify_study import CLASS_WORDS, class_of

    found = computed(store, study_id)
    result = found.result
    curves, units = result.for_target(target)
    if not curves:
        raise KeyError(target)
    readers = _readers(result)
    details = []
    for c in curves:
        details.append(
            CurveDetail(
                **_summary(c, readers.get(c.id, 0)),
                points=[
                    StandardPointView(
                        run_id=p.run_id,
                        well=p.well,
                        sample=p.sample,
                        quantity=p.quantity,
                        cq=_num(p.cq),
                        detected=p.detected,
                        residual=_num(p.residual),
                        back_quantity=_num(p.back_quantity),
                        note=p.note,
                    )
                    for p in c.points
                ],
                levels=[
                    LevelView(
                        quantity=lv.quantity,
                        n_wells=lv.n_wells,
                        n_detected=lv.n_detected,
                        rate=_num(lv.rate),
                        mean_cq=_num(lv.mean_cq),
                        sd_cq=_num(lv.sd_cq),
                        back_quantity=_num(lv.back_quantity),
                        cv=_num(lv.cv),
                    )
                    for lv in c.levels
                ],
                band=[
                    BandPoint(log10_quantity=a, cq=b, low=lo, high=hi) for a, b, lo, hi in c.band()
                ],
            )
        )
    groups = found.groups or {}
    rows = [
        UnitQuantity(
            unit=u.unit,
            group=groups.get(u.unit) if found.groups is not None else None,
            samples=list(u.samples),
            curves=list(u.curves),
            n_wells=u.n_wells,
            n_detected=u.n_detected,
            mean_cq=_num(u.mean_cq),
            quantity=_num(u.quantity),
            low=_num(u.low),
            high=_num(u.high),
            per_ul=_num(u.per_ul),
            per_ng=_num(u.per_ng),
            flags=[FlagView(id=f, words=ab.FLAG_WORDS.get(f, f)) for f in u.flags],
            reported=class_of(u),
            reported_words=CLASS_WORDS[class_of(u)],
            wells=[
                UnknownWellView(
                    run_id=w.run_id,
                    well=w.well,
                    sample=w.sample,
                    cq=_num(w.cq),
                    detected=w.detected,
                    curve=w.curve,
                    quantity=_num(w.quantity),
                    note=w.note,
                )
                for w in u.wells
            ],
        )
        for u in units
    ]
    return AssayQuantities(
        study_id=study_id,
        target=target,
        unit=result.unit,
        settings=_settings(result),
        reaction=_reaction(result),
        curves=details,
        units=rows,
    )


# ---- a person records what one reaction held ---------------------------------------------------

REACTION_KIND = "choice.reaction_input"
REACTION_REASON = "set by a person on the Results page (Quantities), with the reason recorded"


def record_reaction(
    studio: Any,
    sid: str,
    payload: Mapping[str, Any],
    reason: str,
    *,
    expected_head: str | None = None,
) -> Any:
    """Make and accept, in one act of the person, the ``choice.reaction_input`` proposal.

    The payload is checked as the design will apply it (:func:`qpilot.qpcr.designs.
    reaction_input`); a value equal to the design's own is not written again (``unchanged``).

    Raises:
        ValueError: The payload is not a reaction input, or the reason is missing.
    """
    from qpilot.core.proposals import ProposalError
    from qpilot.qpcr.designs import DesignError, reaction_input
    from qpilot.schemas_studio import Evidence, MadeBy, Proposal
    from qpilot.studio_design import _inbox_with_checks

    try:
        wanted = reaction_input(payload)
    except DesignError as err:
        raise ValueError(str(err)) from err
    clean = {
        "template_ul": (wanted or {}).get("template_ul"),
        "input_ng": (wanted or {}).get("input_ng"),
        "unit": (wanted or {}).get("unit"),
    }
    assembly = studio.assemble(sid)
    current = assembly.design.reaction_input if assembly.design is not None else None
    if (current.model_dump() if current is not None else None) == wanted:
        return Recorded("unchanged", studio.head(sid), "")
    proposal = Proposal(
        study_id=sid,
        kind=REACTION_KIND,
        subject="reaction",
        payload=clean,
        evidence=[Evidence(kind="rule", ref="reaction input", note="set by a person")],
        level="High",
        reasons=[REACTION_REASON],
        made_by=MadeBy(kind="person"),
    )
    inbox = _inbox_with_checks(studio, sid, {})
    try:
        (outcome,) = inbox.decide_together(
            [(proposal, "accept")], [], "human", reason, proposer="human",
            expected_head=expected_head,
        )  # fmt: skip
    except ProposalError as err:
        raise ValueError(str(err)) from err
    return Recorded(str(outcome.status), str(outcome.head), str(outcome.reason or ""))


@dataclasses.dataclass(frozen=True)
class Recorded:
    """What recording did: ``accepted``, ``unchanged``, ``stale`` or ``refused``."""

    status: str
    head: str
    reason: str
