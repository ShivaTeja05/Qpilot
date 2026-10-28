"""Views of a study's comparisons: one comparison at a time, or all of them side by side.

A study with a comparison plan stores every comparison in ``StudyResult.comparisons`` and every
comparison's grid in ``grid_comparisons.csv`` (the same analyses as ``grid.csv``). The Results
section shows one comparison at a time by swapping that comparison's contrasts, robustness and
grades into the study's result (:func:`shown_result`) and its rows of the grid into the grid
(:func:`comparison_grid`); everything else (the Decision Cards, the options a person chose) is
the study's, so the analysis in use is the same for every comparison. A study with one
comparison has no plan: :func:`comparisons_view` shows its one comparison with the engine's
Benjamini-Hochberg q-values over its genes.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from qpilot.core.store import StudyStore
from qpilot.qpcr.contrast import CORRECTION_WORDS, TEST_WORDS, ConclusionRule, bh
from qpilot.schemas import ComparisonOutcome, DecisionCard, Fact, StudyResult
from qpilot.web.contract_compare import (
    ComparisonCell,
    ComparisonGeneRow,
    ComparisonInfo,
    ComparisonNote,
    ComparisonsView,
)

GRID_FILE = "grid_comparisons.csv"
MAX_FRAMES = 2


class UnknownComparison(LookupError):
    """The study has no comparison with this id (the message says which it has)."""


def outcome_of(result: StudyResult, comparison: str | None) -> ComparisonOutcome | None:
    """The stored outcome of ``comparison`` (``None``: the study's own, primary, numbers).

    Raises:
        UnknownComparison: An id the study does not have.
    """
    if not comparison:
        return None
    found = result.comparisons
    if found is None:
        raise UnknownComparison("This study has one comparison; there is nothing to choose.")
    for outcome in found.comparisons:
        if outcome.id == comparison:
            return outcome
    known = ", ".join(o.id for o in found.comparisons)
    raise UnknownComparison(f"This study has no comparison {comparison!r} (it has: {known}).")


def shown_result(result: StudyResult, outcome: ComparisonOutcome | None) -> StudyResult:
    """The study's result as one comparison shows it (the primary: the result itself).

    The contrasts, robustness and grades are the comparison's; the groups (their names and
    sizes) are its two. Everything else is the study's.
    """
    if outcome is None or outcome.primary:
        return result
    facts = dict(result.facts)
    for fid, value, path in (
        ("f_group_a", outcome.group_a, "design.comparison.group_a"),
        ("f_group_b", outcome.group_b, "design.comparison.group_b"),
    ):
        facts[fid] = Fact(id=fid, value=value, path=path)
    design = result.design.model_copy(
        update={
            "n_hi": outcome.n_a,
            "n_lo": outcome.n_b,
            "group_var": f"{outcome.group_a} vs {outcome.group_b}",
        }
    )
    return result.model_copy(
        update={
            "contrasts": outcome.contrasts,
            "robustness": outcome.robustness,
            "confidence": outcome.confidence,
            "facts": facts,
            "design": design,
        }
    )


def extra_columns(
    result: StudyResult, outcome: ComparisonOutcome | None
) -> dict[str, tuple[float | None, float | None]]:
    """Gene -> ``(corrected p, q-value)`` for the gene table of the comparison shown.

    The corrected p is ``None`` for a study with one comparison (its call uses p); the q-value
    is the engine's (stored for a plan, else :func:`qpilot.qpcr.contrast.bh` over the genes).
    """
    if result.comparisons is not None:
        if outcome is None:
            outcome = result.comparisons.comparisons[0]
        return {g: (outcome.p_adjusted.get(g), outcome.q_value.get(g)) for g in outcome.contrasts}
    genes = list(result.contrasts)
    q = bh(np.array([result.contrasts[g].p for g in genes], dtype=float))
    return {g: (None, _finite(v)) for g, v in zip(genes, q, strict=True)}


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


# ---- the comparisons' grid -------------------------------------------------------------------

_lock = threading.Lock()
_frames: OrderedDict[tuple[str, int], pd.DataFrame] = OrderedDict()


def _frame(store: StudyStore, study_id: str) -> pd.DataFrame | None:
    path = store.workspace(study_id) / GRID_FILE
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = (str(path), mtime)
    with _lock:
        cached = _frames.get(key)
        if cached is not None:
            return cached
    frame = pd.read_csv(path)
    with _lock:
        _frames[key] = frame
        while len(_frames) > MAX_FRAMES:
            _frames.popitem(last=False)
    return frame


def comparison_grid(store: StudyStore, study_id: str, comparison: str, primary):  # noqa: ANN001,ANN201
    """The grid of one comparison, with the primary grid's options and planned analysis.

    ``primary`` is the study's :class:`qpilot.web.results_views.Grid`; the comparison's grid
    has the same analyses, so the planned one and the cards' options are the primary's.
    ``None`` when there is no primary grid or no grid of the comparisons.
    """
    from qpilot.web.results_views import Grid

    if primary is None:
        return None
    frame = _frame(store, study_id)
    if frame is None:
        return None
    rows = frame[frame["comparison"] == comparison].drop(columns=["comparison"])
    return Grid(
        frame=rows.reset_index(drop=True),
        dimensions=primary.dimensions,
        options=primary.options,
        planned=primary.planned,
    )


def at_choices_in(primary, grid, cards: Sequence[DecisionCard]) -> pd.DataFrame | None:  # noqa: ANN001
    """One comparison's rows at the options in use now, when they are not the planned ones.

    The options in use are read from the primary grid (the cards' consequences are the
    primary comparison's); the rows are the comparison's own.
    """
    from qpilot.web.results_views import card_options, current_cell

    if primary is None or primary.planned is None or grid is None:
        return None
    choice = current_cell(primary, cards, card_options(primary, cards))
    return None if choice == primary.planned else grid.cell(choice)


# ---- all comparisons side by side ------------------------------------------------------------

CORRECTION_NOTE = {
    "holm": "Each gene is compared {n} times, so its p-values are corrected with Holm's method "
    "across those {n} comparisons: a gene is called only when its corrected p is below {alpha:g} "
    "and the change is at least {fold:g}-fold. Each 95 % interval is for its comparison alone.",
    "none": "No correction for comparing each gene {n} times was chosen: each call uses its own "
    "p-value, so with {n} comparisons per gene some calls are expected by chance alone.",
}
PAIRED_NOTE = (
    "Paired by {pair_by}: each comparison tests the differences within each {pair_by} (a paired "
    "t-test on log2 relative quantity), so n is the number of complete pairs."
)
Q_NOTE = (
    "q (false discovery rate) is the share of false findings expected among the genes with that "
    "q or lower in one comparison (Benjamini-Hochberg across its genes). It is shown, never used "
    "for a call."
)
PRIMARY_ONLY_NOTE = (
    "The Decision Cards, Trace, the robustness audit and the Run Review describe the first "
    "comparison ({label}); a choice you make on a card applies to every comparison. The gene "
    "table and the robustness map follow the comparison you pick."
)
OMNIBUS_NOTE = (
    "“Any difference” asks whether a gene differs anywhere among {groups}: Welch's one-way "
    "ANOVA (unequal variances) at the planned analysis. It is for orientation only; the calls "
    "are the comparisons'."
)
NOT_MEASURED_NOTE = (
    "Some biological units were not measured for every gene; each is left out of only the genes "
    "it lacks."
)


def comparisons_view(store: StudyStore, study_id: str) -> ComparisonsView:
    """Every comparison of the study side by side (one for a study without a plan)."""
    from qpilot.web.results_views import headline_genes, load_grid

    result = store.get(study_id)
    cards = store.cards(study_id)
    headline = set(headline_genes(result, cards, store))
    rule = ConclusionRule(**result.conclusion_rule)
    found = result.comparisons
    outcomes = list(found.comparisons) if found is not None else [_single(result)]
    primary_grid = load_grid(store, result)
    at: dict[str, pd.DataFrame | None] = {}
    for outcome in outcomes:
        grid = (
            primary_grid
            if outcome.primary
            else comparison_grid(store, study_id, outcome.id, primary_grid)
        )
        at[outcome.id] = at_choices_in(primary_grid, grid, cards)
    genes = list(dict.fromkeys(g for o in outcomes for g in (*o.contrasts, *o.not_tested)))
    rows = []
    for gene in genes:
        cells = [_cell(o, gene, at.get(o.id)) for o in outcomes]
        called = sum(1 for c in cells if c is not None and c.conclusion != "none")
        omnibus = found.omnibus.get(gene) if found is not None else None
        rows.append(
            ComparisonGeneRow(
                gene=gene,
                headline=gene in headline,
                cells=cells,
                n_called=called,
                omnibus_p=omnibus.p if omnibus is not None else None,
            )
        )
    test = found.test if found is not None else "welch"
    correction = found.correction if found is not None else "none"
    notes = []
    if found is not None:
        n = len(outcomes)
        if n > 1:
            text = CORRECTION_NOTE[correction].format(
                n=n, alpha=rule.alpha, fold=2**rule.min_log2fc
            )
            notes.append(ComparisonNote(kind="correction", text=text))
        if found.pair_by is not None:
            notes.append(
                ComparisonNote(kind="paired", text=PAIRED_NOTE.format(pair_by=found.pair_by))
            )
        notes.append(
            ComparisonNote(
                kind="primary_only", text=PRIMARY_ONLY_NOTE.format(label=outcomes[0].label)
            )
        )
    notes.append(ComparisonNote(kind="q_value", text=Q_NOTE))
    if found is not None and found.omnibus_groups:
        groups = ", ".join(found.omnibus_groups[:-1]) + " and " + found.omnibus_groups[-1]
        notes.append(ComparisonNote(kind="omnibus", text=OMNIBUS_NOTE.format(groups=groups)))
    missing = _not_measured(result.facts)
    if missing:
        notes.append(ComparisonNote(kind="not_measured", text=NOT_MEASURED_NOTE))
    return ComparisonsView(
        study_id=study_id,
        several=found is not None,
        test=test,
        test_words=TEST_WORDS[test],
        correction=correction,
        correction_words=CORRECTION_WORDS[correction],
        pattern=found.pattern if found is not None else "chosen",
        control=found.control if found is not None else None,
        pair_by=found.pair_by if found is not None else None,
        rule_text=_rule_text(rule, correction if len(outcomes) > 1 else "none"),
        comparisons=[_info(o) for o in outcomes],
        genes=rows,
        notes=notes,
        not_measured=missing,
        omnibus_groups=list(found.omnibus_groups) if found is not None else [],
    )


def tabs(result: StudyResult) -> list[dict]:
    """The comparison picker's entries (empty for a study with one comparison)."""
    if result.comparisons is None:
        return []
    out = []
    for o in result.comparisons.comparisons:
        calls = [c.conclusion for c in o.contrasts.values()]
        out.append(
            {
                "id": o.id,
                "label": o.label,
                "primary": o.primary,
                "n_up": calls.count("up"),
                "n_down": calls.count("down"),
            }
        )
    return out


def rule_words(result: StudyResult, rule: ConclusionRule) -> str:
    """The calling rule of a study in words (the corrected p when several comparisons use it)."""
    found = result.comparisons
    several = found is not None and len(found.comparisons) > 1
    return _rule_text(rule, found.correction if several else "none")  # type: ignore[union-attr]


def _rule_text(rule: ConclusionRule, correction: str) -> str:
    fold = f"{2**rule.min_log2fc:g}"
    if correction == "holm":
        return (
            f"up or down only if the corrected p < {rule.alpha:g} and the change is at least "
            f"{fold}-fold; otherwise no call"
        )
    return rule.describe()


def _single(result: StudyResult) -> ComparisonOutcome:
    """The study's one comparison as an outcome (q-values: the engine's BH over its genes)."""
    facts = result.facts
    a = str(facts["f_group_a"].value) if "f_group_a" in facts else None
    b = str(facts["f_group_b"].value) if "f_group_b" in facts else None
    if a is None or b is None:
        marker = result.design.group_var.removesuffix("_high") or result.design.group_var
        a, b = f"{marker}-high", "rest"
    genes = list(result.contrasts)
    q = bh(np.array([result.contrasts[g].p for g in genes], dtype=float))
    return ComparisonOutcome(
        id="primary",
        group_a=a,
        group_b=b,
        label=f"{a} vs {b}",
        primary=True,
        n_a=result.design.n_hi,
        n_b=result.design.n_lo,
        contrasts=result.contrasts,
        p_adjusted={g: result.contrasts[g].p for g in genes},
        q_value={g: float(v) for g, v in zip(genes, q, strict=True)},
        robustness=result.robustness,
        confidence=result.confidence,
    )


def _info(outcome: ComparisonOutcome) -> ComparisonInfo:
    calls = [c.conclusion for c in outcome.contrasts.values()]
    return ComparisonInfo(
        id=outcome.id,
        label=outcome.label,
        group_a=outcome.group_a,
        group_b=outcome.group_b,
        primary=outcome.primary,
        n_a=outcome.n_a,
        n_b=outcome.n_b,
        n_pairs=outcome.n_pairs,
        n_up=calls.count("up"),
        n_down=calls.count("down"),
        n_tested=len(outcome.contrasts),
        not_tested=dict(outcome.not_tested),
    )


def _cell(outcome: ComparisonOutcome, gene: str, at: pd.DataFrame | None) -> ComparisonCell | None:
    contrast = outcome.contrasts.get(gene)
    if contrast is None:
        return None
    robust = outcome.robustness.get(gene)
    grade = outcome.confidence.get(gene)
    yours = None
    if at is not None and gene in at.index:
        call = str(at.loc[gene, "conclusion"])
        yours = call if call in ("up", "down", "none") else None
    return ComparisonCell(
        conclusion=contrast.conclusion,
        fc=contrast.fc,
        log2fc=contrast.log2fc,
        ci=(float(contrast.ci[0]), float(contrast.ci[1])),
        p=contrast.p,
        p_adjusted=float(outcome.p_adjusted.get(gene, contrast.p)),
        q=float(outcome.q_value.get(gene, math.nan)),
        n_a=contrast.n_hi,
        n_b=contrast.n_lo,
        holds=robust.holds if robust else None,
        level=grade.level if grade else None,
        at_your_choices=yours,  # type: ignore[arg-type]
    )


def _not_measured(facts: Mapping[str, Fact]) -> dict[str, str]:
    """Gene -> the units it was not measured in, from the ``f_not_measured_*`` facts."""
    out = {}
    for fid, fact in facts.items():
        if fid.startswith("f_not_measured_") and fact.path.startswith("not_measured."):
            out[fact.path[len("not_measured.") :]] = str(fact.value)
    return dict(sorted(out.items()))
