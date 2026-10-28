"""What to repeat and why: the reactions to re-run, ranked by consequence, and their plate.

The Run Review's repeat plan. It adds no maths: it gathers what other parts measured, at the
analysis in use, and says per sample x gene why it is worth re-running and what it does to the
conclusions:

* **the Run Gate's warnings and failures** (:mod:`qpilot.core.gate`): the study wells a rule
  points at (a no-template control that came up near the samples, replicates that disagree, a
  failed control, a run file that reports a problem) and what leaving them out does to the calls
  (the gate's consequence test);
* **the wells a person left out** of the analysis (the design's excluded wells), with the reason
  the person gave in a Studio session and whether leaving them out changed a call when they
  decided;
* **samples in no comparison** (Trace's S7: an empty reference or marker well), with what
  bringing one back would do (its one empty reference read from the sample's other references);
* **no amplification where one was expected**: a study well with no quantity although the gene
  amplified in at least :data:`EXPECTED_SHARE` of the other compared samples (an unsourced,
  lab-editable default: below it, not amplifying may be the biology), and technical replicates
  that did not amplify while the others did;
* **Trace's places to look** for every compared gene (S1-S6), with what each option there does.

Each item is one sample x gene (a whole sample for a tube place or a sample set aside) with
every reason in plain words, its consequence and the calls it changes. Items are ranked by
consequence: it changes a call > it moves a fold change beyond its confidence interval > the
sample has no value there (repeating it adds the sample back) > not known > it changes no call,
then by the number of calls changed. The repeat plate
(:func:`qpilot.qpcr.layout.make_repeat_layout`) runs every repeated sample with all its
reference genes, and per assay the inter-run calibrator (a compared sample of the original run
that nothing points at), the no-RT and no-template controls, and a positive control where the
original run had one. It is written as the planner's instrument-agnostic CSV.

The plan never decides and never judges the run: re-running is a person's call; it lists what
the checks point at and what each does to the conclusions. Deterministic; no model call and no
network. Every number in its words comes from the engines it reads.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from qpilot.qpcr import layout as plates
from qpilot.qpcr import trace as trace_engine

if TYPE_CHECKING:
    from qpilot.core.gate import GateReport
    from qpilot.core.rules import RulePack
    from qpilot.qpcr.trace import TraceContext

#: A gene is expected to amplify in a sample when it amplified in at least this share of the
#: other compared samples (unsourced, lab-editable default).
EXPECTED_SHARE = 0.9
#: Places per gene read from Trace (its most a page shows).
TRACE_TOP = 20
MIN_REPLICATES = 2
#: The option that says what a place itself does to the calls: a reference well read as the
#: sample's other references expect it, a target well's value left out, the tube set aside.
OWN_OPTION: dict[str, str] = {
    "reference_well": "read_from_other_refs",
    "target_well": "set_aside_value",
    "sample": "set_aside",
}
WELL_LABEL = re.compile(r"^([A-Z]{1,2})(\d{1,3})$")

Consequence = Literal["changes_call", "beyond_ci", "no_value", "unknown", "changes_nothing"]
CONSEQUENCES: tuple[str, ...] = (
    "changes_call",
    "beyond_ci",
    "no_value",
    "unknown",
    "changes_nothing",
)
CONSEQUENCE_WORDS: dict[str, str] = {
    "changes_call": "changes a call",
    "beyond_ci": "moves a fold change beyond its confidence interval",
    "no_value": "the sample has no value there: repeating it adds the sample back",
    "unknown": "what it does to the calls is not known",
    "changes_nothing": "changes no call",
}
GATE_CLASS: dict[str, str] = {
    "flip": "changes_call",
    "magnitude": "beyond_ci",
    "none": "changes_nothing",
    "unknown": "unknown",
}
VERDICT_WORDS = {"fail": "fails", "warn": "warns"}
SOURCES: tuple[str, ...] = ("run_gate", "set_aside", "no_comparison", "no_amplification", "trace")
SOURCE_WORDS: dict[str, str] = {
    "run_gate": "Run Gate",
    "set_aside": "Left out by a person",
    "no_comparison": "In no comparison",
    "no_amplification": "No amplification",
    "trace": "Trace",
}


class RepeatError(ValueError):
    """The plan cannot be built (the message says why, in words)."""


class RepeatReason(BaseModel):
    """One reason to re-run a reaction (or a reason that needs no repeat), in plain words."""

    source: str = Field(description="run_gate, set_aside, no_comparison, no_amplification, trace.")
    code: str = Field(description="The rule id (G-NTC-1), the check (S1) or the kind of reason.")
    words: str
    what_to_check: str = ""


class RepeatItem(BaseModel):
    """One sample x gene to re-run (``target`` None: the whole sample), with why and what for."""

    rank: int = 0
    sample: str
    target: str | None
    scope: Literal["reaction", "sample"]
    group: str = ""
    plates: list[str]
    wells: list[str]
    reasons: list[RepeatReason]
    consequence: Consequence
    consequence_words: str
    changed_calls: list[str]
    repeat: list[str] = Field(description="Genes it re-runs (the refs are added on the plate).")
    on_plate: bool = Field(default=False, description="Its reactions are on the repeat plate.")


class RepeatPlateWell(BaseModel):
    """One well of the repeat plate, as the planner's CSV writes it."""

    plate: int
    well: str
    sample: str
    group: str
    target: str
    type: str


class GatePlateLine(BaseModel):
    """What the Run Gate says about one plate: verdict counts and the rules that warn or fail."""

    plate: str
    worst: str = Field(description="fail, warn, pass or not_applicable (the worst verdict).")
    counts: dict[str, int]
    findings: list[RepeatReason]


class RepeatPlan(BaseModel):
    """What to repeat and why, ranked; the repeat plate; what was looked at and needs no repeat."""

    study_id: str
    items: list[RepeatItem]
    not_repeated: list[RepeatReason]
    gate_lines: list[GatePlateLine] = Field(description="The Run Gate per plate (none unread).")
    calibrator: str | None = None
    replicates: int
    plate_size: int
    n_samples: int
    n_reactions: int = Field(description="Sample x assay pairs on the repeat plates (refs too).")
    n_wells: int
    n_plates: int
    wells: list[RepeatPlateWell]
    notes: list[str]
    warnings: list[str]
    counts: dict[str, int] = Field(description="Items by consequence.")

    def csv(self) -> str:
        """The repeat plate as the planner's CSV (plate, well, sample, group, target, type)."""
        rows = [
            plates.Well(w.plate, w.well, w.sample, w.group, w.target, w.type, 1) for w in self.wells
        ]
        return plates.layout_csv(_Wells(rows))  # type: ignore[arg-type]


class LeftOut(BaseModel):
    """A well a person left out of the analysis, as the session's record says (when it does)."""

    well: str
    reason: str = ""
    by: str = Field(default="", description="Trace, Run Gate, Curves, a Prism round trip, …")
    matters: bool | None = None
    option: str | None = None
    place_target: str | None = Field(default=None, description="Trace: the place's own gene.")


class _Wells:
    def __init__(self, rows: list[plates.Well]) -> None:
        self._rows = rows

    def wells(self) -> list[plates.Well]:
        return self._rows


class _Item:
    def __init__(self, unit: str, target: str | None, scope: str) -> None:
        self.unit, self.target, self.scope = unit, target, scope
        self.wells: set[str] = set()
        self.reasons: list[RepeatReason] = []
        self.cons: str = "changes_nothing"
        self.changed: set[str] = set()
        self.repeat: set[str] = set()

    def add(
        self,
        wells: Iterable[str],
        reason: RepeatReason,
        consequence: str,
        changed: Iterable[str],
        repeat: Iterable[str],
    ) -> None:
        self.wells.update(wells)
        if not any(
            (r.source, r.code, r.words) == (reason.source, reason.code, reason.words)
            for r in self.reasons
        ):
            self.reasons.append(reason)
        if CONSEQUENCES.index(consequence) < CONSEQUENCES.index(self.cons):
            self.cons = consequence
        self.changed.update(changed)
        self.repeat.update(repeat)


class _Plan:
    def __init__(self, ctx: TraceContext) -> None:
        self.ctx = ctx
        self.items: dict[tuple[str, str | None], _Item] = {}
        self.not_repeated: list[RepeatReason] = []

    def add(
        self,
        unit: str,
        target: str | None,
        *,
        wells: Iterable[str],
        reason: RepeatReason,
        consequence: str,
        changed: Iterable[str] = (),
        repeat: Iterable[str] = (),
        scope: str = "reaction",
    ) -> None:
        key = (unit, target)
        item = self.items.get(key)
        if item is None:
            item = self.items[key] = _Item(unit, target, scope)
        item.add(wells, reason, consequence, changed, repeat)


# ---- reading the parts ---------------------------------------------------------------------


def _study(ctx: TraceContext, keys: Iterable[str]) -> list[str]:
    """The study wells among ``keys`` (wells of samples, not controls or standards)."""
    w = ctx.wells
    return sorted(k for k in set(keys) if k in w.index and str(w.at[k, "sample_type"]) == "unkn")


def _cells(ctx: TraceContext, keys: Iterable[str]) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for k in keys:
        out.setdefault((str(ctx.wells.at[k, "unit"]), str(ctx.wells.at[k, "target"])), []).append(k)
    return out


def _gate(plan: _Plan, gate: GateReport, pack: RulePack | None) -> list[GatePlateLine]:
    from qpilot.core.validator import render_tokens

    names = {r.id: r.name for r in pack.rules} if pack is not None else {}
    consequences = {c.eval_key: c for c in gate.consequences}
    lines: dict[str, GatePlateLine] = {
        unit: GatePlateLine(plate=unit, worst="not_applicable", counts={}, findings=[])
        for unit in gate.units
    }
    order = ("fail", "warn", "pass", "not_applicable")
    for ev in gate.evals:
        plate = ev.scope.get("plate")
        line = lines.get(plate) if plate else None
        if line is not None:
            line.counts[ev.verdict] = line.counts.get(ev.verdict, 0) + 1
            if ev.verdict in order and order.index(ev.verdict) < order.index(line.worst):
                line.worst = ev.verdict
        if ev.verdict not in VERDICT_WORDS:
            continue
        try:
            detail = render_tokens(ev.reason, gate.facts)
        except (KeyError, ValueError):
            detail = ""
        where = ", ".join(
            f"{k} {ev.scope[k]}" for k in ("plate", "target", "sample", "unit") if k in ev.scope
        )
        name = names.get(ev.rule_id, ev.rule_id)
        words = f"{ev.rule_id} ({name}) {VERDICT_WORDS[ev.verdict]} on {where or 'the study'}"
        words += f": {detail}" if detail else "."
        reason = RepeatReason(source="run_gate", code=ev.rule_id, words=words)
        if line is not None:
            line.findings.append(reason)
        study = _study(plan.ctx, ev.flagged) or _study(
            plan.ctx, (k for ks in ev.options.values() for k in ks)
        )
        if not study:
            plan.not_repeated.append(
                reason.model_copy(
                    update={
                        "words": words.rstrip(".") + ". It points at no study well, so no "
                        "sample's value rests on it."
                    }
                )
            )
            continue
        found = consequences.get(ev.key)
        group_cls = GATE_CLASS.get(found.consequence, "unknown") if found else "unknown"
        flipped = sorted({g for o in found.options for g in o.flipped}) if found else []
        if flipped:  # what the gate's own consequence test measured, for all its wells at once
            reason = reason.model_copy(
                update={
                    "words": reason.words.rstrip(".")
                    + f". Leaving every well it points at out changes the call of "
                    f"{', '.join(flipped)}."
                }
            )
        for (unit, target), keys in sorted(_cells(plan.ctx, study).items()):
            own = trace_engine.cell_effect(plan.ctx, unit, target)
            if own is None:  # a gene the comparison does not read as a value: the gate's own
                cls, changed = group_cls, flipped
            else:
                changed = sorted(str(g) for g in own.get("changed_calls") or ())
                cls = "changes_call" if changed else str(own.get("class") or "changes_nothing")
            plan.add(
                unit,
                target,
                wells=keys,
                reason=reason,
                consequence=cls if cls in CONSEQUENCES else "unknown",
                changed=changed,
                repeat=[target],
            )
    return [lines[u] for u in sorted(lines)]


def _set_aside(plan: _Plan, left_out: Mapping[str, LeftOut]) -> None:
    w = plan.ctx.wells
    out = w[(w["sample_type"] == "unkn") & w["person_excluded"]]
    whole: dict[str, list[str]] = {}
    for key in sorted(out.index):
        rec = left_out.get(key) or LeftOut(well=key, by="the design")
        if rec.option == "set_aside":
            whole.setdefault(str(out.at[key, "unit"]), []).append(key)
            continue
        unit, target = str(out.at[key, "unit"]), str(out.at[key, "target"])
        plan.add(
            unit,
            target,
            wells=[key],
            reason=_left_out_reason(rec, "it"),
            consequence=_matters(rec),
            repeat=[target],
        )
    for unit, keys in whole.items():
        rec = next(left_out[k] for k in keys)
        target = rec.place_target
        plan.add(
            unit,
            None,
            wells=keys,
            reason=_left_out_reason(rec, "the whole sample"),
            consequence=_matters(rec),
            repeat=[target] if target else [],
            scope="sample",
        )


def _left_out_reason(rec: LeftOut, what: str) -> RepeatReason:
    by = f" from {rec.by}" if rec.by and rec.by != "the design" else ""
    words = f"A person left {what} out of the analysis{by}"
    words += f": “{rec.reason}”." if rec.reason else " (the design leaves it out)."
    return RepeatReason(source="set_aside", code="left_out", words=words)


def _matters(rec: LeftOut) -> str:
    return (
        "unknown" if rec.matters is None else "changes_call" if rec.matters else "changes_nothing"
    )


def _absent(plan: _Plan) -> None:
    ctx = plan.ctx
    for entry in ctx.absent:
        unit = str(entry["sample"])
        reasons = [r for r in entry.get("reasons") or () if not r.get("left_out")]
        if not reasons:
            continue
        effect = trace_engine.restore_effect(ctx, unit)
        cls = str(effect["class"]) if effect else "no_value"
        changed = [str(g) for g in (effect or {}).get("changed_calls") or ()]
        for r in reasons:
            target = r.get("target")
            if not target:
                continue
            keys = [f"{r['plate']}/{r['well']}"] if r.get("plate") and r.get("well") else []
            if r.get("reason") == "not_measured_for_every_gene":
                words = f"Sample {unit} is in no comparison: it was not measured for {target}."
            else:
                what = "reference" if r.get("reason") == "empty_reference_well" else "marker"
                where = f" (plate {r['plate']}, well {r['well']})" if keys else ""
                words = (
                    f"Sample {unit} is in no comparison: its {target} {what} well{where} has no "
                    "value"
                )
                codes = r.get("note_codes") or ()
                words += (
                    ": LinRegPCR found no amplification." if "no_amplification" in codes else "."
                )
            if effect is not None:
                words += " Read from the sample's other reference wells, bringing it back " + (
                    f"changes the call of {', '.join(changed)}." if changed else "changes no call."
                )
            plan.add(
                unit,
                str(target),
                wells=keys,
                reason=RepeatReason(source="no_comparison", code="S7", words=words),
                consequence=cls,
                changed=changed,
                repeat=[str(target)],
            )


def _no_amplification(plan: _Plan) -> None:
    ctx = plan.ctx
    w = ctx.wells
    used = {ctx.units[i] for i in np.flatnonzero(ctx.used)}
    study = w[(w["sample_type"] == "unkn") & ~w["person_excluded"] & w["unit"].isin(used)]
    study = study[study["target"].isin(set(ctx.items))]
    empty = study[study["n0"].isna()]
    if empty.empty:
        return
    capped = (ctx.cell or {}).get("undetermined") == "cap"
    ok = study["n0"].notna().rename("ok")
    cells = ok.groupby([study["target"], study["unit"]]).agg(["sum", "size"])
    detected = (cells["sum"] > 0).groupby(level=0).sum()
    n_units = cells["sum"].groupby(level=0).size()
    keys_of: dict[tuple[str, str], list[str]] = {}
    for key, target, unit in zip(empty.index, empty["target"], empty["unit"], strict=True):
        keys_of.setdefault((str(target), str(unit)), []).append(str(key))
    for (target, unit), keys in sorted(keys_of.items()):
        n_ok, n_wells = (int(x) for x in cells.loc[(target, unit)])
        n_other = int(n_units[target]) - 1
        if n_other < 1:
            continue
        if n_ok == 0:
            others = int(detected[target])
            if others / n_other < EXPECTED_SHARE:
                continue  # the gene often does not amplify: that may be the biology
            words = (
                f"No amplification in {target} for sample {unit}, while it amplified in {others} "
                f"of the {n_other} other compared samples"
            )
            words += (
                ": its value is set to the lowest one seen (capped)."
                if capped
                else ": the sample is missing from this gene's comparison."
            )
            cons = "unknown" if capped else "no_value"
        else:
            words = (
                f"{len(keys)} of sample {unit}'s {n_wells} {target} replicate wells did not "
                "amplify while the others did."
            )
            cons = "unknown"
        plan.add(
            unit,
            target,
            wells=sorted(keys),
            reason=RepeatReason(source="no_amplification", code="no_amplification", words=words),
            consequence=cons,
            repeat=[target],
        )


def _trace(plan: _Plan) -> set[str]:
    ctx = plan.ctx
    flagged: set[str] = set()
    results = {}
    for gene in ctx.items:
        try:
            results[gene] = trace_engine.trace_gene(ctx, gene, top=TRACE_TOP)
        except trace_engine.TraceError:  # a gene Trace cannot follow adds no place
            continue
    for _, result in sorted(results.items()):
        for place in result.places:
            if not place.checks:
                continue
            flagged.add(place.sample)
            # what the place itself does: the well read as expected (a reference read from the
            # sample's other references), the target value left out, or the tube set aside
            own = place.options.get(OWN_OPTION.get(place.role, "set_aside")) or {}
            changed = sorted(str(g) for g in own.get("changed_calls") or ())
            cls = str(own.get("class") or "changes_nothing")
            if changed:
                cls = "changes_call"
            elif cls not in CONSEQUENCES:
                cls = "unknown"
            keys = trace_engine.place_wells(ctx, place)
            for code in place.checks:
                words = trace_engine.CHECKS.get(code)
                if words is None:
                    continue
                at = f"plate {place.plate}, well {place.well}" if place.well else "the tube"
                reason = RepeatReason(
                    source="trace",
                    code=code,
                    words=(
                        f"Trace ({at}): looks like {words['looks_like']}; consistent with "
                        f"{words['consistent_with']}."
                    ),
                    what_to_check=words["what_to_check"],
                )
                if place.role == "sample" or place.target is None:
                    plan.add(
                        place.sample,
                        None,
                        wells=keys,
                        reason=reason,
                        consequence=cls,
                        changed=changed,
                        repeat=changed,
                        scope="sample",
                    )
                else:
                    plan.add(
                        place.sample,
                        place.target,
                        wells=keys,
                        reason=reason,
                        consequence=cls,
                        changed=changed,
                        repeat=[place.target],
                    )
    return flagged


# ---- the plan ------------------------------------------------------------------------------


def _group(ctx: TraceContext, unit: str) -> str:
    i = ctx.unit_row.get(unit)
    if i is None:
        return ""
    if ctx.in_hi[i]:
        return ctx.labels[0]
    if ctx.in_lo[i]:
        return ctx.labels[1]
    return ""


def study_replicates(ctx: TraceContext) -> int:
    """Technical replicates per sample and gene in the study (the median over its cells)."""
    w = ctx.wells
    study = w[w["sample_type"] == "unkn"]
    if study.empty:
        return 1
    return max(1, int(np.median(study.groupby(["unit", "target"]).size().to_numpy())))


def study_plate_size(ctx: TraceContext) -> int:
    """96, or 384 when a well of the study lies outside A1-H12."""
    for label in set(ctx.wells["well"].astype(str)):
        found = WELL_LABEL.match(label)
        if found is None:
            continue
        row, col = found.group(1), int(found.group(2))
        if len(row) > 1 or row > "H" or col > 12:
            return 384
    return 96


def _calibrator(ctx: TraceContext, avoid: set[str], targets: Sequence[str]) -> str | None:
    """A compared sample nothing points at with a value for every repeated gene and reference.

    The one whose reference level is closest to the compared samples' median (a typical input),
    then the first by name: a suggestion; any sample of the original run works.
    """
    cols = [ctx.item_col[t] for t in targets if t in ctx.item_col]
    with warnings.catch_warnings():  # a sample with no reference value has no level
        warnings.simplefilter("ignore", RuntimeWarning)
        level = (
            np.nanmean(ctx.ref_values, axis=1) if ctx.ref_values.size else np.zeros(len(ctx.units))
        )
    used = [i for i in np.flatnonzero(ctx.used) if ctx.units[i] not in avoid]
    ok = [
        i
        for i in used
        if not np.isnan(ctx.ref_values[i]).any()
        and (not cols or not np.isnan(ctx.values[i, cols]).any())
    ]
    if not ok:
        return None
    middle = float(np.median(level[np.flatnonzero(ctx.used)]))
    best = min(ok, key=lambda i: (abs(float(level[i]) - middle), ctx.units[i]))
    name = ctx.units[best]
    return name if plates.SAFE_NAME.match(name) else None


def build_plan(
    study_id: str,
    ctx: TraceContext,
    *,
    gate: GateReport | None = None,
    pack: RulePack | None = None,
    left_out: Mapping[str, LeftOut] | None = None,
    replicates: int | None = None,
    plate_size: int | None = None,
    include: Literal["consequential", "all"] = "consequential",
    seed: int = 0,
) -> RepeatPlan:
    """The repeat plan of one study at the analysis ``ctx`` traces (pure; nothing is written).

    Args:
        study_id: The study (named on the plan).
        ctx: Trace's context at the analysis in use (:func:`qpilot.qpcr.trace.build_context`).
        gate: The Run Gate's report at the same analysis (``None``: not read; the plan says so).
        pack: The rule pack the gate ran (for the rules' names).
        left_out: The session's record of the wells a person left out, by ``RUN/WELL``.
        replicates: Replicates on the repeat plate (default: the study's, at least two).
        plate_size: 96 or 384 (default: the study's plates).
        include: Which items go on the repeat plate: ``consequential`` (default: every item
            but those that change no call) or ``all``.
        seed: The repeat plate's random order.

    Raises:
        RepeatError: The repeat plate cannot be laid out.
    """
    plan = _Plan(ctx)
    notes: list[str] = []
    gate_lines = _gate(plan, gate, pack) if gate is not None else []
    if gate is None:
        notes.append("The Run Gate was not read for this plan: its findings are not in it.")
    _set_aside(plan, left_out or {})
    _absent(plan)
    _no_amplification(plan)
    flagged = _trace(plan)
    ranked = sorted(
        plan.items.values(),
        key=lambda it: (CONSEQUENCES.index(it.cons), -len(it.changed), it.unit, it.target or ""),
    )
    items = [
        RepeatItem(
            rank=n,
            sample=it.unit,
            target=it.target,
            scope="sample" if it.scope == "sample" else "reaction",
            group=_group(ctx, it.unit),
            plates=sorted(
                {str(ctx.wells.at[k, "run_id"]) for k in it.wells if k in ctx.wells.index}
            ),
            wells=sorted(it.wells),
            reasons=sorted(it.reasons, key=lambda r: (SOURCES.index(r.source), r.code, r.words)),
            consequence=it.cons,  # type: ignore[arg-type]
            consequence_words=CONSEQUENCE_WORDS[it.cons],
            changed_calls=sorted(it.changed),
            repeat=sorted(t for t in it.repeat if t),
        )
        for n, it in enumerate(ranked, start=1)
    ]
    reps = replicates if replicates is not None else max(MIN_REPLICATES, study_replicates(ctx))
    size = plate_size if plate_size is not None else study_plate_size(ctx)
    plated = [
        i for i in items if i.repeat and (include == "all" or i.consequence != "changes_nothing")
    ]
    for i in plated:
        i.on_plate = True
    reactions = sorted({(i.sample, i.group, t) for i in plated for t in i.repeat})
    samples = {s for s, _, _ in reactions}
    targets = sorted({t for _, _, t in reactions} | set(ctx.refs))
    avoid = samples | flagged | {i.sample for i in items}
    calibrator = _calibrator(ctx, avoid, targets) if reactions else None
    w = ctx.wells
    positive = tuple(sorted(set(w.loc[w["sample_type"] == "pos", "target"].astype(str))))
    cautions: list[str] = []
    wells: list[RepeatPlateWell] = []
    n_plates = n_reactions = 0
    if reactions:
        spec = plates.RepeatSpec(
            reactions=tuple(reactions),
            refs=tuple(ctx.refs),
            calibrator=calibrator or plates.IRC,
            replicates=reps,
            plate_size=size,
            positive=positive,
            seed=seed,
        )
        try:
            built = plates.make_repeat_layout(spec)
        except plates.LayoutError as err:
            raise RepeatError(str(err)) from err
        wells = [
            RepeatPlateWell(
                plate=x.plate,
                well=x.well,
                sample=x.sample,
                group=x.group,
                target=x.target,
                type=x.type,
            )
            for x in built.wells()
        ]
        n_plates = len(built.plates)
        n_reactions = len({(x.sample, x.target) for x in built.wells() if x.type == "unkn"})
        notes += list(built.notes)
        cautions += list(built.warnings)
        if reps > study_replicates(ctx):
            notes.append(
                f"The original run had {study_replicates(ctx)} well(s) per sample and gene; the "
                f"repeat runs {reps}, so a single well that is off can be told from the sample."
            )
        if calibrator:
            notes.append(
                f"Suggested inter-run calibrator: sample {calibrator} (compared in this study, a "
                "value for every repeated gene, nothing points at it); any sample of the original "
                "plates works."
            )
    else:
        notes.append("Nothing points at a reaction to re-run.")
    left = [i for i in items if i.repeat and not i.on_plate]
    if left:
        notes.append(
            f"{len(left)} item(s) change no call: they are listed but not on the plate (put "
            "every item on it to re-run them too)."
        )
    sample_only = [i for i in items if not i.repeat]
    if sample_only:
        notes.append(
            f"{len(sample_only)} item(s) point at a sample's tube, not a well: check the tube "
            "first (input, extraction); the plate carries it only for the calls it changes."
        )
    counts = {c: sum(i.consequence == c for i in items) for c in CONSEQUENCES}
    return RepeatPlan(
        study_id=study_id,
        items=items,
        not_repeated=plan.not_repeated,
        gate_lines=gate_lines,
        calibrator=calibrator,
        replicates=reps,
        plate_size=size,
        n_samples=len(samples),
        n_reactions=n_reactions,
        n_wells=len(wells),
        n_plates=n_plates,
        wells=wells,
        notes=notes,
        warnings=cautions,
        counts=counts,
    )


def left_out_from_inbox(
    accepted: Sequence[Any], ctx: TraceContext | None = None
) -> dict[str, LeftOut]:
    """Per well left out, the person's latest accepted ``curve.exclude_well`` as a record.

    Who proposed it (Trace, the Run Gate or the Curves inbox), the reason, whether it changed a
    call when decided, and for Trace the place's own gene.
    """
    from qpilot.studio_service import EXCLUDE_KIND, gate_card_of, leaves_out, trace_card_of

    latest: dict[str, Any] = {}
    for p in accepted:
        if p.kind == EXCLUDE_KIND:
            latest[p.subject] = p
    out: dict[str, LeftOut] = {}
    for well, p in latest.items():
        if not leaves_out(p):
            continue
        consequence = p.consequence or {}
        trace = consequence.get("trace") if isinstance(consequence.get("trace"), dict) else {}
        by = (
            "Trace"
            if trace_card_of(p)
            else "Controls (the Run Gate)"
            if gate_card_of(p)
            else ("Curves")
        )
        place = trace.get("well") if trace else None
        target = None
        if ctx is not None and isinstance(place, str) and place in ctx.wells.index:
            target = str(ctx.wells.at[place, "target"])
        matters = consequence.get("matters")
        out[well] = LeftOut(
            well=well,
            reason=p.reason or "",
            by=by,
            matters=matters if isinstance(matters, bool) else None,
            option=str(trace.get("option")) if trace and trace.get("option") else None,
            place_target=target,
        )
    return out


__all__: Sequence[str] = (
    "CONSEQUENCES",
    "CONSEQUENCE_WORDS",
    "EXPECTED_SHARE",
    "GatePlateLine",
    "LeftOut",
    "RepeatPlateWell",
    "RepeatError",
    "RepeatItem",
    "RepeatPlan",
    "RepeatReason",
    "build_plan",
    "left_out_from_inbox",
    "study_plate_size",
    "study_replicates",
)
