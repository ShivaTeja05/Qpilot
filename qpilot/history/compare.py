"""Compare two analyses of the same input file: which conclusions differ, and why.

Two studies of one file differ by their confirmed design (a Prism round trip that excludes a
value, say) and by the choices in force at each chain head. Each side's conclusions are its own
chain replayed to its head (:mod:`qpilot.history.replay`). When the later analysis' grid holds
the earlier analysis' choices, the difference is split in two, exactly, by reading that grid
cell: *by the design* (same choices, the other design) and *by the choices* (the later design,
the other choices).
"""

from __future__ import annotations

import json
from typing import Any

from qpilot.core.store import StudyStore
from qpilot.history.replay import (
    Analysis,
    Chain,
    HistoryError,
    _cell_genes,
    _planned_genes,
    _plural,
    change_sentence,
    choice_changes,
    choices_in_force,
    counts_of,
    gene_changes,
    load_chain,
)
from qpilot.schemas_studio import StudyDesign
from qpilot.web import results_views as rv
from qpilot.web.contract_history import CompareSide, DesignChange, HistoryCompare, HistoryGene

FIELD_TITLE = {
    "design_id": "Design preset",
    "experiment_id": "Experiment analysed",
    "mode": "How the groups are made",
    "marker_split": "Groups split by a marker gene",
    "comparison": "The comparison",
    "samples": "Samples",
    "targets": "Targets",
    "reference_candidates": "Candidate control genes",
    "headline": "Headline genes",
    "well_roles": "Well roles",
    "well_calls": "Curve calls a person resolved",
    "excluded_wells": "Wells left out",
    "amp_calls": "Amplification rules offered",
    "note": "Note",
}
MAX_TEXT = 200


def design_of(chain: Chain) -> StudyDesign | None:
    """The design a study was analysed with (the demo preset for a legacy workspace)."""
    design = chain.store.design(chain.study_id)
    if design is not None:
        return design
    if chain.store.workspace(chain.study_id).name == chain.result.input_sha256:
        from qpilot.qpcr.designs import vermeulen_design

        return vermeulen_design()
    return None


def _text(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def design_changes(before: StudyDesign | None, after: StudyDesign | None) -> list[DesignChange]:
    """Every field of the confirmed design that differs, as added / removed items or values."""
    if before is None or after is None:
        return []
    a = before.model_dump(mode="json")
    b = after.model_dump(mode="json")
    out = []
    for field in a.keys() | b.keys():
        old, new = a.get(field), b.get(field)
        if old == new:
            continue
        title = FIELD_TITLE.get(field, field.replace("_", " "))
        if isinstance(old, list | tuple) and isinstance(new, list | tuple):
            olds, news = [_text(x) for x in old], [_text(x) for x in new]
            out.append(
                DesignChange(
                    field=field,
                    title=title,
                    added=[x for x in news if x not in olds],
                    removed=[x for x in olds if x not in news],
                )
            )
        elif isinstance(old, dict) and isinstance(new, dict):
            olds = [f"{k} = {_text(v)}" for k, v in sorted(old.items())]
            news = [f"{k} = {_text(v)}" for k, v in sorted(new.items())]
            out.append(
                DesignChange(
                    field=field,
                    title=title,
                    added=[x for x in news if x not in olds],
                    removed=[x for x in olds if x not in news],
                )
            )
        else:
            out.append(
                DesignChange(
                    field=field,
                    title=title,
                    before=None if old is None else _text(old),
                    after=None if new is None else _text(new),
                )
            )
    order = list(FIELD_TITLE)
    return sorted(out, key=lambda c: (order.index(c.field) if c.field in order else 99, c.field))


def _head(chain: Chain) -> Analysis:
    analysis = chain.analysis_at(len(chain.entries))
    if analysis is None:
        raise HistoryError(chain.note or "This analysis cannot be replayed from its grid.")
    return analysis


def _same_choices_elsewhere(
    before: Chain, before_head: Analysis, after: Chain
) -> dict[str, HistoryGene] | None:
    """The later design with the earlier choices: the later grid's cell at those choices.

    None when the later grid does not hold them (other choices offered, say).
    """
    gb, ga = before.grid, after.grid
    if (
        gb is None
        or ga is None
        or ga.planned is None
        or before_head.choice is None
        or set(gb.dimensions) != set(ga.dimensions)
    ):
        return None
    choice = {}
    for dim in ga.dimensions:
        value = gb.options[dim][before_head.choice[dim]]
        if value not in ga.options[dim]:
            return None
        choice[dim] = ga.options[dim].index(value)
    if choice == ga.planned:
        return _planned_genes(after.result)
    return _cell_genes(after.result, ga, choice)


def _current(store: StudyStore, study_id: str) -> bool:
    sid = rv.session_of_study(store, study_id)
    if sid is None:
        return False
    try:
        meta = json.loads((store.find_session(sid) / "studio.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return False
    return meta.get("current_study") == study_id


def _side(chain: Chain, head: Analysis, design: StudyDesign | None) -> CompareSide:
    from qpilot.history.studio import created_at

    return CompareSide(
        study_id=chain.study_id,
        created_at=created_at(chain.store, chain.study_id),
        head=chain.head,
        n_entries=len(chain.entries),
        design_hash=design.design_hash() if design is not None else None,
        counts=counts_of(head.genes.values()),
        choices=choices_in_force(chain.step_cards[-1]),
        current=_current(chain.store, chain.study_id),
    )


def _made(chain: Chain) -> tuple[str, int]:
    """When an analysis was made: its first chain entry's time, then its results file's time.

    The file's time tells apart two analyses made within the same second.
    """
    from qpilot.history.studio import created_at

    try:
        mtime = (chain.store.workspace(chain.study_id) / "results.json").stat().st_mtime_ns
    except OSError:
        mtime = 0
    return created_at(chain.store, chain.study_id) or "", mtime


def compare_studies(store: StudyStore, study_id: str, other_id: str) -> HistoryCompare:
    """Two analyses of the same input file, earlier then later (``HistoryError`` if not)."""
    if other_id == study_id:
        raise HistoryError("Pick another analysis of this file to compare with.")
    this, other = load_chain(store, study_id), load_chain(store, other_id)
    if this.result.input_sha256 != other.result.input_sha256:
        raise HistoryError(
            "These two analyses are of different files, so their conclusions cannot be compared."
        )
    before, after = (other, this) if _made(other) <= _made(this) else (this, other)
    head_b, head_a = _head(before), _head(after)
    design_b, design_a = design_of(before), design_of(after)
    designs = design_changes(design_b, design_a)

    genes = list(after.result.contrasts) + [
        g for g in before.result.contrasts if g not in after.result.contrasts
    ]
    middle = _same_choices_elsewhere(before, head_b, after)
    side_b = _side(before, head_b, design_b)
    side_a = _side(after, head_a, design_a)
    choices = choice_changes(side_b.choices, side_a.choices)
    same_design = (
        design_b is not None
        and design_a is not None
        and design_b.design_hash() == design_a.design_hash()
    )
    causes: dict[str, str] = {}
    by_design = by_choices = 0
    for gene in genes:
        b, a = head_b.genes.get(gene), head_a.genes.get(gene)
        if b is None or a is None:
            continue
        if middle is not None and gene in middle:
            m = middle[gene].conclusion
            by_design += b.conclusion != m
            by_choices += m != a.conclusion
            if b.conclusion != a.conclusion:
                d, c = b.conclusion != m, m != a.conclusion
                causes[gene] = "both" if d and c else "design" if d else "choices"
        elif b.conclusion != a.conclusion:
            causes[gene] = "choices" if same_design else "design" if not choices else "unknown"
    verdicts, labels = rv._verdicts(store, after.study_id)
    headline = rv.headline_genes(after.result, after.cards, store)
    calls, folds, holds, n_moved = gene_changes(
        genes, head_b.genes, head_a.genes, headline, verdicts, labels, causes
    )

    parts = [change_sentence(calls, n_moved)]
    if calls and middle is not None:
        parts.append(
            f"With the same choices the design alone changes {_plural(by_design, 'call')}; "
            f"with the same design the choices alone change {_plural(by_choices, 'call')}."
        )
    if designs:
        parts.append("The design differs in: " + ", ".join(d.title for d in designs) + ".")
    else:
        parts.append("The two designs are the same.")
    if choices:
        parts.append(f"The choices in force differ on {_plural(len(choices), 'card')}.")
    else:
        parts.append("The same choices are in force.")
    return HistoryCompare(
        input_sha256=this.result.input_sha256,
        before=side_b,
        after=side_a,
        design=designs,
        choices=choices,
        calls_changed=calls,
        fold_moves=folds,
        holds_moves=holds,
        n_moved=n_moved,
        genes_only_before=[g for g in before.result.contrasts if g not in after.result.contrasts],
        genes_only_after=[g for g in after.result.contrasts if g not in before.result.contrasts],
        decomposed=middle is not None,
        by_design=by_design,
        by_choices=by_choices,
        summary=" ".join(parts),
    )
