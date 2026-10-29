"""A study whose purpose is to quantify samples: no groups compared, each sample's quantity.

Many qPCR runs compare nothing: a viral load, wastewater surveillance, the copy number of a
construct, a sequencing library. A person says so on the Design page (``design.purpose``
quantify, :attr:`~qpilot.schemas_studio.StudyDesign.purpose`); the study then needs standards
with quantities instead of a comparison and reference genes, and its result is every sample's
quantity from the standard curve (:func:`qpilot.qpcr.absolute.quantify`), with its 95 %
prediction interval, the LOD and the LOQ.

**What is reported for a sample** (one assay of one biological unit) is its **class**, in this
order: *not detected* (no well detected), *no curve* (detected, but no standard curve to read it
from), *below the LOD*, *below the LOQ* (detected, the number is not precise), *below the
lowest standard* (extrapolated), *above the top standard* (extrapolated), *quantified*; and,
for a class that reports a number (quantified, above the top or below the lowest standard), the
quantity. Another analysis **changes what is reported** for the sample when its class differs,
or when the number moves by more than :data:`QUANTITY_FOLD` (2-fold, a lab-editable default,
the same line as the relative engine's 2-fold rule).

**The choices tested** (the robustness idea of the relative engine, applied to quantities):

* ``amp_call``: which wells count as detected: LinRegPCR's own call or a Cq cut-off (40, 38 or
  35 cycles), the options of the design (:data:`qpilot.qpcr.amp_call.STUDIO_AMP_CALLS`), the
  person's call rule first. It decides which standards are on the curve, the LOD, and each
  sample's detected wells;
* ``loq_cv``: how precise a quantity must be to be reported (the LOQ's CV line): 35 % (Forootan
  et al. 2017; the default) or 25 % (a stricter line some labs use).

Every combination is quantified (the grid, ``grid.csv``: one row per analysis and sample). Each
choice is a Decision Card: it waits for a person when another option changes what is reported
for at least one sample at the planned other settings, and is decided automatically otherwise
(the escalation rule of :mod:`qpilot.core.decisions`, applied in code at every decision through
the card's ``impact``). A person's decision on a card is the analysis the Quantities view and
the exports use (:func:`analysis_in_use`).

The relative engine's outputs are empty here (no contrasts, robustness, grades or geNorm), so
every reader of a study can tell a quantification study by :func:`is_quantify_result`.

Deterministic: no model, no network; the same file and design give byte-identical output.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from qpilot.core.card_kinds import requires_human
from qpilot.core.decisions import effective_level, rank_cards
from qpilot.qpcr import absolute as ab
from qpilot.schemas import CardOption, DecisionCard, DesignSummary, Fact, GenormResult, StudyResult

PURPOSE = "quantify"
PURPOSE_WORDS = "quantify samples (no groups compared)"
QUANTITY_FOLD = 2.0  # lab-editable default: a reported number moving by more is a change
LOQ_OPTIONS: tuple[str, ...] = ("0.35", "0.25")  # grid text; the first is the default (35 %)
DIMENSIONS = ("amp_call", "loq_cv")
IDX = "_idx"
MAX_LISTED = 60  # changed samples listed per option on a card
AMP_KIND = "quantity.amp_call"
LOQ_KIND = "quantity.loq_cv"
CARD_IDS = {"amp_call": "card_quantity_amp_call", "loq_cv": "card_quantity_loq_cv"}
KINDS = {"amp_call": AMP_KIND, "loq_cv": LOQ_KIND}
TEMPLATES = {"amp_call": "quantity_amp_v1", "loq_cv": "quantity_loq_v1"}
NOTE = "quantify samples: no groups compared"
AUTO = (
    "Decided automatically: no option on this card changes what is reported for any sample "
    "(its class, or its number by more than 2-fold)."
)
AUTO_ELSEWHERE = (
    "Decided automatically: at the planned settings no option on this card changes what is "
    "reported for any sample. At other settings it can, so an agent must ask a person to "
    "change it."
)

#: Classes, from the least to the most reportable (the page and the exports keep this order).
CLASSES: tuple[str, ...] = (
    "not_detected",
    "no_curve",
    "below_lod",
    "below_loq",
    "below_lowest",
    "above_top",
    "quantified",
)
CLASS_WORDS: dict[str, str] = {
    "not_detected": "not detected",
    "no_curve": "detected, but no standard curve to read it from",
    "below_lod": "below the limit of detection",
    "below_loq": "detected, below the limit of quantification",
    "below_lowest": "below the lowest standard (extrapolated)",
    "above_top": "above the top standard (extrapolated)",
    "quantified": "quantified",
}
#: Classes whose number is reported as such (a change of more than 2-fold is a change).
NUMBERED = frozenset({"quantified", "above_top", "below_lowest"})
LOQ_LABELS = {
    "0.35": "CV at most 35 % (Forootan et al. 2017; the default)",
    "0.25": "CV at most 25 % (stricter)",
}
LOQ_IDS = {"0.35": "loq_cv_35", "0.25": "loq_cv_25"}


class QuantifyError(ValueError):
    """A quantification study that cannot be analysed (the message says why, in words)."""


def is_quantify(design: Any) -> bool:
    """True for a design whose purpose is to quantify samples."""
    return design is not None and getattr(design, "purpose", None) == PURPOSE


def is_quantify_result(result: StudyResult) -> bool:
    """True for a stored quantification study (its ``f_purpose`` fact says so)."""
    fact = result.facts.get("f_purpose")
    return fact is not None and fact.value == PURPOSE


def item_key(target: str, unit: str) -> str:
    """One sample result's id: ``"<assay> · <unit>"`` (names never hold a middle dot)."""
    return f"{target} · {unit}"


def class_of(estimate: ab.UnknownEstimate) -> str:
    """The class of one sample result (see the module docstring)."""
    flags = set(estimate.flags)
    if estimate.n_detected == 0:
        return "not_detected"
    if estimate.log10_quantity is None:
        return "no_curve"
    for name in ("below_lod", "below_loq"):
        if name in flags:
            return name
    if "below_lowest" in flags:
        return "below_lowest"
    if "above_top" in flags:
        return "above_top"
    return "quantified"


@dataclass(frozen=True)
class Reported:
    """What is reported for one sample result under one analysis."""

    cls: str
    log10_q: float | None

    def changes(self, other: Reported, fold: float = QUANTITY_FOLD) -> bool:
        """True when ``other`` reports something else (the class, or the number > ``fold``)."""
        if self.cls != other.cls:
            return True
        if self.cls not in NUMBERED or self.log10_q is None or other.log10_q is None:
            return False
        return abs(self.log10_q - other.log10_q) > math.log10(fold) + 1e-12


def reported(absolute: ab.Absolute) -> dict[str, Reported]:
    """Every sample result of one quantification, by :func:`item_key`."""
    return {
        item_key(u.target, u.unit): Reported(class_of(u), u.log10_quantity)
        for u in absolute.unknowns
    }


# ---------------------------------------------------------------------------------------------
# What a quantification design needs (blind: names, types and quantities, never a Cq)
# ---------------------------------------------------------------------------------------------

NO_STANDARDS = (
    "no standards yet: a quantification needs a dilution series of known quantity on the "
    "plate; mark the standards on Samples (type Standard)"
)
NO_QUANTITIES = (
    "no standards with a quantity yet: give the standards their quantities on Samples (the "
    "highest quantity and the dilution step); a standard curve needs at least {n} levels"
)
LEVEL_NUMBERS = (
    "the standards are named {names}, which number the levels, not quantities: give them "
    "their quantities on Samples (the highest quantity and the dilution step)"
)


def standards_needed(design: Any, facts: Any) -> str | None:
    """Why the design cannot quantify yet (standards, their quantities), or ``None``.

    Blind-safe: reads the wells' declared types, the design's roles and quantities and the
    file's declared quantities, never a Cq. An assay is ready when its standards have at
    least :data:`qpilot.qpcr.absolute.MIN_LEVELS` distinct quantities.
    """
    from qpilot.qpcr.designs import design_curves

    table = design_curves(facts.wells, design)
    if design.experiment_id is not None and "experiment_id" in table.columns:
        table = table[table["experiment_id"] == design.experiment_id]
    std = table[table["sample_type"] == "std"]
    if std.empty:
        return NO_STANDARDS
    declared = {
        (sample, target): (float(value), str(unit or ""))
        for sample, entries in facts.sample_quantities.items()
        for value, unit, target in entries
    }
    quantities = {s: d.quantity for s, d in design.samples.items() if d.quantity}
    q, source, unit = ab.standard_quantities(std, quantities, declared)
    std = std.assign(abs_q=q, abs_source=source, abs_unit=unit)
    labelled = ab._level_labels(std)
    best = 0
    for target, rows in std.groupby(std["target"].astype(str)):
        if target in labelled:
            continue
        best = max(best, int(rows["abs_q"][rows["abs_q"] > 0].nunique()))
    if best >= ab.MIN_LEVELS:
        return None
    if labelled and best == 0:
        return LEVEL_NUMBERS.format(names=sorted(labelled.values())[0])
    return NO_QUANTITIES.format(n=ab.MIN_LEVELS)


# ---------------------------------------------------------------------------------------------
# Inputs and the analysis at one cell
# ---------------------------------------------------------------------------------------------


@dataclass
class Inputs:
    """What every analysis of the study shares: the per-well table and the design's inputs."""

    table: pd.DataFrame
    quantities: dict[str, float]
    declared: dict[tuple[str, str], tuple[float, str]]
    units: dict[str, str] | None
    calls: dict[str, bool] | None
    reaction: ab.ReactionInputs | None
    amp_calls: tuple[str, ...]
    _done: dict[tuple[str, str], ab.Absolute] = field(default_factory=dict)

    def at(self, amp_call: str, loq_cv: str) -> ab.Absolute:
        """The quantification under one rule and one LOQ line (computed once)."""
        key = (amp_call, loq_cv)
        if key not in self._done:
            self._done[key] = ab.quantify(
                self.table,
                quantities=self.quantities,
                declared=self.declared,
                units=self.units,
                rule_id=amp_call,
                calls=self.calls,
                reaction=self.reaction,
                settings=ab.AbsoluteSettings(loq_cv=float(loq_cv)),
            )
        return self._done[key]

    def without(self, keys: Sequence[str]) -> Inputs:
        """The same inputs with the wells ``run_id/well`` in ``keys`` left out."""
        from qpilot.qpcr.quant import EXCLUDED

        table = self.table.copy()
        hit = (table["run_id"].astype(str) + "/" + table["well"].astype(str)).isin(set(keys))
        before = table[EXCLUDED].astype(bool).to_numpy() if EXCLUDED in table.columns else False
        table[EXCLUDED] = hit.to_numpy() | before
        return Inputs(
            table,
            self.quantities,
            self.declared,
            self.units,
            self.calls,
            self.reaction,
            self.amp_calls,
        )


def inputs_for(path: str | Path, curves: pd.DataFrame, design: Any) -> Inputs:
    """The shared inputs of a quantification design on its file's per-well table."""
    from qpilot.qpcr.absolute_study import declared_quantities
    from qpilot.qpcr.designs import design_curves, design_units

    given = design.reaction_input
    reaction = ab.ReactionInputs(given.template_ul, given.input_ng, given.unit) if given else None
    return Inputs(
        table=design_curves(curves, design),
        quantities={s: d.quantity for s, d in design.samples.items() if d.quantity},
        declared=declared_quantities(path),
        units=design_units(design) or None,
        calls=dict(design.well_calls) or None,
        reaction=reaction,
        amp_calls=tuple(design.amp_calls),
    )


def dimensions(inputs: Inputs) -> dict[str, tuple[str, ...]]:
    """The choices tested: every amplification rule of the design, the two LOQ lines."""
    return {"amp_call": tuple(inputs.amp_calls), "loq_cv": LOQ_OPTIONS}


def primary(dims: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """The analysis as planned: the first option of each choice."""
    return {d: str(options[0]) for d, options in dims.items()}


def analysis_in_use(design: Any, cards: Sequence[DecisionCard]) -> dict[str, str]:
    """The analysis in use: each quantity card's applied option, the planned one elsewhere."""
    amp_calls = tuple(design.amp_calls) if design is not None else ("linregpcr",)
    choice = {"amp_call": amp_calls[0], "loq_cv": LOQ_OPTIONS[0]}
    for card in cards:
        if card.kind not in (AMP_KIND, LOQ_KIND) or not card.decision:
            continue
        if card.kind == AMP_KIND and card.decision in amp_calls:
            choice["amp_call"] = card.decision
        elif card.kind == LOQ_KIND:
            value = next((v for v, cid in LOQ_IDS.items() if cid == card.decision), None)
            if value is not None:
                choice["loq_cv"] = value
    return choice


# ---------------------------------------------------------------------------------------------
# The grid and each choice's impact
# ---------------------------------------------------------------------------------------------


def _cells(dims: Mapping[str, Sequence[str]]) -> list[dict[str, str]]:
    names = list(dims)
    return [dict(zip(names, combo, strict=True)) for combo in itertools.product(*dims.values())]


def run_grid(inputs: Inputs, dims: Mapping[str, Sequence[str]]) -> pd.DataFrame:
    """One row per analysis (cell) and sample result: the class and the quantity."""
    rows = []
    for cell in _cells(dims):
        found = inputs.at(cell["amp_call"], cell["loq_cv"])
        index = {d: list(dims[d]).index(cell[d]) for d in dims}
        for u in sorted(found.unknowns, key=lambda e: (e.target, e.unit)):
            row: dict[str, Any] = {}
            for d in dims:
                row[d + IDX] = index[d]
                row[d] = cell[d]
            row.update(
                item=item_key(u.target, u.unit),
                target=u.target,
                unit=u.unit,
                **{"class": class_of(u)},
                log10_quantity=u.log10_quantity,
                log10_low=u.log10_low,
                log10_high=u.log10_high,
                n_detected=u.n_detected,
                n_wells=u.n_wells,
            )
            rows.append(row)
    columns = [c for d in dims for c in (d + IDX, d)]
    columns += ["item", "target", "unit", "class", "log10_quantity", "log10_low", "log10_high"]
    columns += ["n_detected", "n_wells"]
    return pd.DataFrame(rows, columns=columns)


@dataclass(frozen=True)
class Change:
    """One sample result another option reports differently."""

    item: str
    target: str
    unit: str
    before: Reported
    after: Reported


def changes(
    base: Mapping[str, Reported],
    other: Mapping[str, Reported],
    names: Mapping[str, tuple[str, str]],
) -> list[Change]:
    """Every sample result ``other`` reports differently from ``base`` (sorted by item)."""
    out = []
    missing = Reported("not_detected", None)
    for item in sorted(set(base) | set(other)):
        a, b = base.get(item, missing), other.get(item, missing)
        if a.changes(b):
            target, unit = names.get(item, (item, ""))
            out.append(Change(item, target, unit, a, b))
    return out


def _names(inputs: Inputs, dims: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for cell in _cells(dims):
        for u in inputs.at(cell["amp_call"], cell["loq_cv"]).unknowns:
            out.setdefault(item_key(u.target, u.unit), (u.target, u.unit))
    return out


def _max_delta(base: Mapping[str, Reported], other: Mapping[str, Reported]) -> float:
    """The largest change of a reported number, in log2 (both analyses give one)."""
    deltas = [0.0]
    for item, a in base.items():
        b = other.get(item)
        if b is None or a.log10_q is None or b.log10_q is None:
            continue
        deltas.append(abs(a.log10_q - b.log10_q) / math.log10(2))
    return max(deltas)


def impact(
    inputs: Inputs, dims: Mapping[str, Sequence[str]], dim: str, base_cell: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, list[Change]]]:
    """What changing ``dim`` alone does, at ``base_cell`` and at every other setting.

    Returns the card's ``impact`` (``flips``: another option changes what is reported for a
    sample at the planned other settings; ``flips_anywhere``: at some setting of the other
    choices; ``n_genes_flipped`` and ``n_genes_flipped_anywhere`` count sample results, the
    core's field names) and each option's changes at ``base_cell``.
    """
    names = _names(inputs, dims)
    at_base = reported(inputs.at(base_cell["amp_call"], base_cell["loq_cv"]))
    per_option: dict[str, list[Change]] = {}
    flipped: set[str] = set()
    deltas = [0.0]
    for option in dims[dim]:
        cell = {**base_cell, dim: option}
        found = reported(inputs.at(cell["amp_call"], cell["loq_cv"]))
        listed = changes(at_base, found, names)
        per_option[option] = listed
        flipped |= {c.item for c in listed}
        deltas.append(_max_delta(at_base, found))
    anywhere: set[str] = set()
    others = {d: v for d, v in dims.items() if d != dim}
    for rest in _cells(others) if others else [{}]:
        seen = [reported(inputs.at(*_ordered({**rest, dim: option}))) for option in dims[dim]]
        for one in seen[1:]:
            anywhere |= {c.item for c in changes(seen[0], one, names)}
    anywhere |= flipped
    return (
        {
            "flips": bool(flipped),
            "n_genes_flipped": len(flipped),
            "max_delta_log2fc": max(deltas),
            "flips_anywhere": bool(anywhere),
            "n_genes_flipped_anywhere": len(anywhere),
            "items": "samples",
        },
        per_option,
    )


def _ordered(cell: Mapping[str, str]) -> tuple[str, str]:
    return cell["amp_call"], cell["loq_cv"]


# ---------------------------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------------------------


def option_id(dim: str, value: str) -> str:
    """A card option's id: the rule id (``amp_call``), ``loq_cv_35`` / ``loq_cv_25``."""
    return value if dim == "amp_call" else LOQ_IDS.get(value, f"loq_cv_{value}")


def option_label(dim: str, value: str) -> str:
    """A card option in words."""
    if dim == "amp_call":
        from qpilot.qpcr.amp_call import get_rule

        return get_rule(value).label
    return LOQ_LABELS.get(value, f"CV at most {float(value) * 100:g} %")


def _change_record(change: Change) -> dict[str, Any]:
    def q(r: Reported) -> float | None:
        return None if r.log10_q is None else float(10**r.log10_q)

    return {
        "item": change.item,
        "target": change.target,
        "unit": change.unit,
        "class_from": change.before.cls,
        "class_to": change.after.cls,
        "quantity_from": q(change.before),
        "quantity_to": q(change.after),
    }


def build_card(
    inputs: Inputs,
    dims: Mapping[str, Sequence[str]],
    dim: str,
    autonomy: str = "suggest",
) -> DecisionCard:
    """One quantity card: its options, what each changes, and the escalation rule's status."""
    base = primary(dims)
    found, per_option = impact(inputs, dims, dim, base)
    options = [
        CardOption(id=option_id(dim, v), label=option_label(dim, v), per_gene={}) for v in dims[dim]
    ]
    evidence: dict[str, Any] = {
        "dimension": dim,
        "fold": QUANTITY_FOLD,
        "per_option": {
            option_id(dim, v): {
                "n_changed": len(listed),
                "changed": [_change_record(c) for c in listed[:MAX_LISTED]],
            }
            for v, listed in per_option.items()
        },
    }
    if dim == "amp_call":
        evidence["not_recommended"] = [o for o in dims[dim] if o == "cq_le_35"]
    kind = KINDS[dim]
    human_kind = requires_human(kind)
    card = DecisionCard(
        id=CARD_IDS[dim],
        kind=kind,
        rank=0,
        impact=found,
        evidence=evidence,
        options=options,
        recommended=option_id(dim, base[dim]),
        rationale_template=TEMPLATES[dim],
        facts=[f"f_qn_changed_{dim}", "f_qn_items", "f_qn_fold"],
        autonomy=autonomy,  # type: ignore[arg-type]
        effective_autonomy=effective_level(autonomy, found, human_kind),  # type: ignore[arg-type]
    )
    if not found["flips"] and not human_kind:
        card = card.model_copy(
            update={
                "status": "auto_decided",
                "decision": card.recommended,
                "reason": AUTO_ELSEWHERE if found["flips_anywhere"] else AUTO,
                "decided_by": "system",
            }
        )
    return card


# ---------------------------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------------------------


def _facts(
    planned: ab.Absolute,
    cards: Sequence[DecisionCard],
    dims: Mapping[str, Sequence[str]],
) -> dict[str, Fact]:
    from qpilot.qpcr.amp_call import get_rule

    counts = {c: 0 for c in CLASSES}
    for u in planned.unknowns:
        counts[class_of(u)] += 1
    out: dict[str, Fact] = {}

    def add(fid: str, value: Any, fmt: str = "{}", unit: str = "", path: str = "") -> None:
        out[fid] = Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path)

    add("f_purpose", PURPOSE)
    add("f_qn_items", len(planned.unknowns), path="quantities:/unknowns")
    add("f_qn_units", len({u.unit for u in planned.unknowns}), path="quantities:/unknowns")
    add("f_qn_assays", len({c.target for c in planned.curves if c.fit is not None}))
    add("f_qn_curves", sum(1 for c in planned.curves if c.fit is not None))
    for name in CLASSES:
        add(f"f_qn_{name}", counts[name], path=f"quantities:/unknowns?class={name}")
    add("f_qn_fold", QUANTITY_FOLD, fmt="{:g}-fold")
    add("f_qn_loq_cv", float(dims["loq_cv"][0]) * 100, fmt="{:g} %")
    add("f_amp_primary", get_rule(dims["amp_call"][0]).label)
    add("f_n_rules", len(dims["amp_call"]))
    for card in cards:
        dim = card.evidence.get("dimension")
        if dim in dims:
            add(f"f_qn_changed_{dim}", int(card.impact["n_genes_flipped"]), path=f"cards/{card.id}")
            add(
                f"f_qn_changed_anywhere_{dim}",
                int(card.impact["n_genes_flipped_anywhere"]),
                path=f"cards/{card.id}",
            )
    return dict(sorted(out.items()))


def quantify_study(
    path: str | Path,
    curves: pd.DataFrame,
    input_sha256: str,
    settings: Any,
) -> tuple[StudyResult, list[DecisionCard], pd.DataFrame]:
    """The quantification study of a design whose purpose is to quantify samples.

    Raises:
        QuantifyError: No standard curve could be fitted (the reason, in words).
    """
    from qpilot.qpcr.designs import study_key

    design = settings.design
    if not is_quantify(design):
        raise QuantifyError("this design compares groups; it is not a quantification design")
    inputs = inputs_for(path, curves, design)
    dims = dimensions(inputs)
    planned = inputs.at(*_ordered(primary(dims)))
    if not any(c.fit is not None for c in planned.curves):
        why = "; ".join(f"{t}: {w}" for t, w in sorted(planned.not_quantified.items()))
        raise QuantifyError(
            "no standard curve could be fitted, so nothing can be quantified"
            + (f" ({why})" if why else "")
        )
    grid = run_grid(inputs, dims)
    cards = rank_cards([build_card(inputs, dims, d, settings.autonomy) for d in dims])
    table = inputs.table
    study = table[table["sample_type"] == "unkn"]
    efficiency = (
        curves.dropna(subset=["eff_target"]).groupby("target")["eff_target"].median()
        if "eff_target" in curves.columns
        else pd.Series(dtype=float)
    )
    result = StudyResult(
        study_id=study_key(input_sha256, design)[:12],
        input_sha256=input_sha256,
        n_plates=int(curves["run_id"].nunique()),
        n_reactions=len(curves),
        n_samples=len({u.unit for u in planned.unknowns}) or int(study["sample"].nunique()),
        design=DesignSummary(
            group_var=PURPOSE_WORDS,
            cut=0.0,
            n_hi=0,
            n_lo=0,
            note=NOTE,
            refs_primary=(),
        ),
        genorm=GenormResult(M_initial={}, order=[], V={}, recommended=()),
        contrasts={},
        robustness={},
        efficiency={str(k): float(v) for k, v in efficiency.sort_index().items()},
        facts=_facts(planned, cards, dims),
    )
    return result, cards, grid


# ---------------------------------------------------------------------------------------------
# Run Gate: does leaving a control's wells out change what is reported?
# ---------------------------------------------------------------------------------------------


def gate_items(absolute: ab.Absolute) -> dict[str, Reported]:
    """The sample results the consequence test compares (:func:`reported`)."""
    return reported(absolute)


def gate_compare(
    option: str,
    excluded: Sequence[str],
    base: Mapping[str, Reported],
    variant: Mapping[str, Reported],
    magnitude_log2: float,
) -> Any:
    """Run Gate's consequence of leaving ``excluded`` out, for a quantification study.

    ``flip``: some sample's reported result changes (its class, or its number by more than
    2-fold); ``magnitude``: no such change, but a number moves by more than ``magnitude_log2``
    (the rule pack's line); ``none`` otherwise. Each sample result is an item of the report.
    """
    from qpilot.core import gate as core_gate

    names = {item: tuple(item.split(" · ", 1)) for item in set(base) | set(variant)}
    listed = changes(base, variant, names)  # type: ignore[arg-type]
    changed = []
    flipped = [c.item for c in listed]
    for item in sorted(set(base) | set(variant)):
        a = base.get(item, Reported("not_detected", None))
        b = variant.get(item, Reported("not_detected", None))
        if a == b:
            continue
        changed.append(
            core_gate.ItemChange(
                item=item,
                call_keep=a.cls,
                call_option=b.cls,
                log2fc_keep=None if a.log10_q is None else a.log10_q / math.log10(2),
                log2fc_option=None if b.log10_q is None else b.log10_q / math.log10(2),
                agreement_keep=1.0,
                agreement_option=1.0,
            )
        )
    delta = _max_delta(base, variant)
    if flipped:
        cls = "flip"
    elif delta > magnitude_log2:
        cls = "magnitude"
    else:
        cls = "none"
    return core_gate.OptionConsequence(
        option=option,
        excluded=sorted(set(excluded)),
        consequence=cls,  # type: ignore[arg-type]
        n_flipped=len(flipped),
        flipped=flipped,
        n_flipped_anywhere=len(flipped),
        flipped_anywhere=flipped,
        max_delta_log2fc=delta,
        changed=changed,
    )


def gate_baseline(items: Mapping[str, Reported]) -> Any:
    """Run Gate's baseline (the analysis as it stands) for a quantification study."""
    from qpilot.core import gate as core_gate

    keys = sorted(items)
    return core_gate.Baseline(
        items=keys,
        calls={k: items[k].cls for k in keys},
        log2fc={
            k: (math.nan if items[k].log10_q is None else items[k].log10_q / math.log10(2))
            for k in keys
        },
        agreement=dict.fromkeys(keys, 1.0),
        results={},
        dimensions={},
        cells=None,
    )
