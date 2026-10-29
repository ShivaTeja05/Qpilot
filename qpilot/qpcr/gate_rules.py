"""Run Gate's qPCR evaluators: what the controls on each plate say, per rule of a pack.

The qPCR side of ``core/rules.py`` and ``core/gate.py``. Each function below is the evaluator of
one ``check`` named in ``packs/research-default.yaml``; thresholds come from the pack's
``params`` (sources in the pack and in ``agent-bus/contracts/scientist-spec-gate.md``), never
from this module. Every number an evaluation shows is registered as a fact (``f_gate_*``) and
its ``reason`` cites them as ``{{fact_id}}`` tokens.

Inputs are the per-well table from :func:`qpilot.qpcr.curves.analyse_study` (with the confirmed
design's re-typing applied, :func:`qpilot.qpcr.designs.design_curves`), whose ``sample_type`` is
already resolved per target (RDML 1.3 ``sampleTargetType``; absent = ``unkn``), plus the
standards' declared quantities. A well "amplified" when LinRegPCR says so and gives it a Cq
(the engine's primary call, never the vendor's "Undetermined").

Checks in this module: ``typed_controls`` (G-TYPED), ``ntc_gap`` (G-NTC-1), ``nac_amplified``
(G-NAC), ``nrt_gdna`` (G-NRT), ``pos_window`` (G-POS), ``std_curve`` (G-STD),
``replicate_spread`` (G-REP), and two gate lines of origin/main read as rules of the pack:
``rt_replicate_spread`` (G-RT: the Cq range between reverse-transcription replicates of one
biological unit, from the design's ``rt_replicate`` labels; ranges as :mod:`qpilot.qpcr.gate_rt`
computes them) and ``instrument_run`` (G-INSTR: what each plate's run file says about the run
and the instrument, the lines of :mod:`qpilot.qpcr.gate_instr`, read from a run file a person
linked to the plate, else the plate's run file in the instrument export the study was opened
from, else the study's own file), and ``melt_products`` (G-MELT: whether each amplified study
well melts as one product at its assay's melting temperature, and what melted in each
no-template control, from the file's melt curves as :mod:`qpilot.qpcr.melt` reads them; G-NTC-1
grades a control's amplification with that class), and ``ipc_inhibition`` (G-IPC: in multiplex
wells, an internal positive control that comes up much later than in the no-template wells, a
sign of inhibition; :mod:`qpilot.qpcr.multiplex`). Every rule works per target, so the curves of a
multiplex well are judged one dye at a time; an internal positive control is meant to amplify in
the no-template wells, so G-NTC-1 does not judge it. Rules label; they never drop a well. What
leaving wells out would do is the consequence test (:func:`run_gate`); in a multiplex well it
leaves out every curve of the well together (one reaction).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats

from qpilot.core import gate as core_gate
from qpilot.core.facts import FactRegistry
from qpilot.core.rules import (
    NOT_APPLICABLE,
    Check,
    Finding,
    Rule,
    RuleEval,
    RulePack,
    Severity,
    evaluate_pack,
    load_pack,
    pack_from_json,
)
from qpilot.core.validator import TOKEN
from qpilot.qpcr import multiplex as mx
from qpilot.qpcr.gate_instr import DEFAULT_HOLD_LIMIT_C
from qpilot.qpcr.gate_rt import RT_RANGE_LIMIT
from qpilot.qpcr.instrument_context import RunContext
from qpilot.qpcr.melt import (
    JUDGED,
    NO_TEMPLATE,
    NTC_FLAGS,
    STUDY_FLAGS,
    AssayMelt,
    MeltData,
    MeltParams,
    WellCall,
    judge,
)
from qpilot.qpcr.quant import EXCLUDED
from qpilot.schemas import Fact

CONTROL_TYPES = frozenset({"ntc", "nac", "ntp", "nrt", "pos", "std"})
ANALYSED = "unkn"
PACKS_DIR_CANDIDATES = (
    Path(__file__).resolve().parents[1] / "_packs",  # wheel (force-included)
    Path(__file__).resolve().parents[2] / "packs",  # source checkout
)
DEFAULT_PACK = "research-default"
#: An option whose wells the analysis already leaves out (a person decided it).
ALREADY_LEFT_OUT = "These wells are already left out of the analysis."


# ---------- context ----------


#: Where a plate's run file comes from (G-INSTR), in the order one takes another's place.
RunSource = Literal["study_file", "export", "linked"]


@dataclass(frozen=True)
class RunFile:
    """What one plate's run file says (G-INSTR), and where qPilot read it.

    ``source`` is ``linked`` for a run file a person linked to the plate (an ``.eds`` or an
    export the instrument wrote), ``export`` for the plate's own run file in the instrument
    export a Studio session was opened from (a QuantStudio results export, CFX run information:
    :mod:`qpilot.qpcr.export_runs`), ``study_file`` for the study's own file (RDML: the
    instrument and the run date at most). ``study_date`` is the plate's run date in the file a
    linked one takes the place of, when known, so a linked file whose run date differs is said.
    A linked file that cannot be read has no ``context`` and says why (``problem``:
    ``missing``, ``changed`` or ``unreadable``).
    """

    context: RunContext | None
    source: RunSource = "study_file"
    study_date: str | None = None
    problem: str = ""

    @property
    def linked(self) -> bool:
        """Whether a person linked this run file to the plate."""
        return self.source == "linked"


@dataclass
class GateContext:
    """What the evaluators read. ``facts`` collects every number they show.

    ``design`` is the confirmed design (its ``rt_replicate`` labels, for G-RT); ``runs`` maps a
    plate to its :class:`RunFile` (for G-INSTR), ``None`` when no run context was given; ``melt``
    is the study file's melt curves (for G-MELT, and G-NTC-1's class of a control's product),
    ``None`` when none were read, judged with ``melt_params`` (the pack's G-MELT thresholds).
    """

    table: pd.DataFrame
    quantities: Mapping[tuple[str, str], float] = field(default_factory=dict)
    rawness: str | None = None
    confirmed_no_controls: frozenset[str] = frozenset()
    design: Any = None
    runs: Mapping[str, RunFile] | None = None
    melt: MeltData | None = None
    melt_params: MeltParams = field(default_factory=MeltParams)
    internal: pd.DataFrame | None = None
    facts: FactRegistry = field(default_factory=FactRegistry)
    _std_fits: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    _melt: dict[tuple[str, str], AssayMelt] | None = None
    _multiplex: frozenset[str] | None = None

    def __post_init__(self) -> None:
        self.table = _keyed(self.table)
        if self.internal is not None:
            self.internal = _keyed(self.internal)

    def multiplex_keys(self) -> frozenset[str]:
        """The keys of the wells that hold more than one target's curve (computed once)."""
        if self._multiplex is None:
            self._multiplex = mx.multiplex_keys(self.table)
        return self._multiplex

    def control_rows(self) -> pd.DataFrame:
        """The internal positive controls' curves (G-IPC), with the wells' other curves.

        ``internal`` holds them when the design leaves the control out of the analysis
        (``run_gate`` keeps its curves for this rule); otherwise they are in ``table``.
        """
        if self.internal is None:
            return self.table
        others = self.table[~self.table["target"].isin(set(self.internal["target"]))]
        return pd.concat([others, self.internal], ignore_index=True)

    def internal_controls(self) -> list[str]:
        """The targets that are internal positive controls (:func:`multiplex.internal_controls`)."""
        return mx.internal_controls(self.control_rows())

    def plates(self) -> list[str]:
        """Plate ids in table order."""
        return list(dict.fromkeys(self.table["run_id"]))

    def typed(self, plate: str) -> bool:
        """True when the plate has at least one control-typed well."""
        rows = self.table[self.table["run_id"] == plate]
        return bool(rows["sample_type"].isin(CONTROL_TYPES).any())

    def plate_targets(self) -> Iterator[tuple[str, str, pd.DataFrame]]:
        """(plate, target, rows) in table order."""
        for (plate, target), rows in self.table.groupby(["run_id", "target"], sort=False):
            yield str(plate), str(target), rows

    def melt_assays(self) -> dict[tuple[str, str], AssayMelt]:
        """(plate, target) -> its melt calls (:func:`qpilot.qpcr.melt.judge`), computed once."""
        if self._melt is None:
            found = judge(self.table, self.melt, self.melt_params) if self.melt else []
            self._melt = {(a.run_id, a.target): a for a in found}
        return self._melt

    def quantity(self, sample: str, target: str) -> float | None:
        """A standard's declared quantity for this target (or for every target)."""
        value = self.quantities.get((sample, target), self.quantities.get((sample, "")))
        return float(value) if value is not None and value > 0 else None

    def fact(
        self,
        rule: Rule,
        scope: Mapping[str, str],
        name: str,
        value: float | int | str,
        fmt: str = "{}",
        unit: str = "",
    ) -> str:
        """Register one evidence number for (rule, scope) and return its fact id."""
        digest = hashlib.sha256(
            "|".join([rule.id, *(f"{k}={scope[k]}" for k in sorted(scope))]).encode()
        ).hexdigest()[:10]
        fid = f"f_gate_{name}_{digest}"
        if isinstance(value, float):
            value = round(value, 6)
        path = "gate/" + "/".join([rule.id, *(f"{k}={scope[k]}" for k in sorted(scope)), name])
        self.facts.add(Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path))
        return fid


def _keyed(t: pd.DataFrame) -> pd.DataFrame:
    """The table with each row's well key and the engine's amplification call."""
    return t.assign(
        key=t["run_id"] + "/" + t["well"],
        amplified=t["amplification"].eq(True) & t["cq"].notna(),
    )


def _na(scope: dict[str, str], code: str, reason: str) -> Finding:
    return Finding(scope=scope, outcome=NOT_APPLICABLE, code=code, reason=reason)


def _untyped(ctx: GateContext, rule: Rule) -> tuple[list[Finding], set[str]]:
    """One ``not_applicable: untyped_plate`` per untyped plate, and those plates."""
    plates = {p for p in ctx.plates() if not ctx.typed(p)}
    findings = [
        _na({"plate": p}, "untyped_plate", "No wells on this plate are typed as controls.")
        for p in ctx.plates()
        if p in plates
    ]
    return findings, plates


def _param(rule: Rule, name: str, default: float) -> float:
    value = rule.params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"rule {rule.id}: parameter {name} must be a number")
    return float(value)


# ---------- G-TYPED ----------


def typed_controls(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """Are there typed controls on each plate? (G-TYPED; scientist spec section 2)."""
    for plate in ctx.plates():
        scope = {"plate": plate}
        rows = ctx.table[ctx.table["run_id"] == plate]
        controls = rows[rows["sample_type"].isin(CONTROL_TYPES)]
        if len(controls):
            fid = ctx.fact(rule, scope, "ncontrol", int(len(controls)))
            yield Finding(
                scope=scope,
                outcome="typed",
                reason=f"{{{{{fid}}}}} wells on this plate are typed as controls.",
                facts=[fid],
                evidence={"n_control_wells": int(len(controls))},
            )
        elif plate in ctx.confirmed_no_controls:
            yield Finding(
                scope=scope,
                outcome="no_controls_confirmed",
                reason="A person confirmed this plate has no control wells; it is ungated.",
            )
        else:
            yield Finding(
                scope=scope,
                outcome="untyped",
                reason="This plate is ungated: no wells are typed as controls. Type the controls "
                "once and the gate can check them.",
            )


# ---------- G-NTC-1 ----------


def ntc_gap(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """NTC/NTP amplification relative to the unknowns (G-NTC-1, MIQE 2.0's 5-cycle rule)."""
    k = _param(rule, "k_cycles", 5.0)
    findings, untyped = _untyped(ctx, rule)
    yield from findings
    controls = set(ctx.internal_controls())
    for plate, target, rows in ctx.plate_targets():
        if plate in untyped:
            continue
        scope = {"plate": plate, "target": target}
        if target in controls:
            yield _na(scope, "internal_control", INTERNAL_CONTROL_NTC)
            continue
        ntc = rows[rows["sample_type"].isin(("ntc", "ntp"))]
        unkn = rows[rows["sample_type"] == ANALYSED]
        if ntc.empty:
            yield _na(scope, "no_ntc_typed", "No no-template control for this target here.")
            continue
        if unkn.empty:
            yield _na(scope, "no_unknowns", "No study samples for this target on this plate.")
            continue
        amp = ntc[ntc["amplified"]]
        n_ntc = ctx.fact(rule, scope, "nntc", int(len(ntc)))
        n_amp = ctx.fact(rule, scope, "nntcamp", int(len(amp)))
        evidence: dict[str, Any] = {"n_ntc": int(len(ntc)), "n_ntc_amplified": int(len(amp))}
        if amp.empty:
            yield Finding(
                scope=scope,
                outcome="clean",
                reason=f"None of the {{{{{n_ntc}}}}} no-template wells amplified.",
                facts=[n_ntc, n_amp],
                evidence=evidence,
            )
            continue
        cq_ntc = float(amp["cq"].min())
        detected = unkn[unkn["amplified"]]
        tainted = detected[cq_ntc - detected["cq"] < k]
        eff = (
            float(rows["eff_target"].dropna().median()) if rows["eff_target"].notna().any() else 2.0
        )
        f_cq = ctx.fact(rule, scope, "cqntc", cq_ntc, "{:.2f}")
        f_k = ctx.fact(rule, scope, "k", k, "{:g}")
        facts = [n_ntc, n_amp, f_cq, f_k]
        evidence.update(cq_ntc=cq_ntc, k_cycles=k, efficiency=eff, chemistry_class="unclassified")
        f_gap = None
        if not detected.empty:
            gap = cq_ntc - float(detected["cq"].min())
            f_gap = ctx.fact(rule, scope, "gap", gap, "{:.2f}")
            facts.append(f_gap)
            evidence["gap_to_lowest_unknown"] = gap
        melt_class = ntc_melt_class(ctx, plate, target, list(amp["key"]))
        if melt_class is not None:
            evidence["chemistry_class"] = melt_class
        if tainted.empty:
            earliest = (
                f" (the earliest {{{{{f_gap}}}}} cycles before it)" if f_gap is not None else ""
            )
            classed = f" {MELT_CLASS_SAID[melt_class]}" if melt_class is not None else ""
            yield Finding(
                scope=scope,
                outcome="amplified_clear",
                reason=(
                    f"{{{{{n_amp}}}}} of {{{{{n_ntc}}}}} no-template wells amplified, the "
                    f"earliest at Cq {{{{{f_cq}}}}}; every study sample amplified at least "
                    f"{{{{{f_k}}}}} cycles earlier{earliest}.{classed}"
                ),
                facts=facts,
                evidence=evidence,
            )
            continue
        gaps = cq_ntc - tainted["cq"].to_numpy(dtype=float)
        # A share of a well's signal is at most all of it: a well that amplified no earlier than
        # the control could owe all of its signal to what the control shows.
        fraction = min(1.0, float(np.max(eff**-gaps)))
        late = int(np.sum(gaps <= 0))
        f_n = ctx.fact(rule, scope, "ntainted", int(len(tainted)))
        evidence.update(
            n_tainted=int(len(tainted)), n_not_earlier=late, max_contaminant_fraction=fraction
        )
        wells, its = ("study well", "its") if len(tainted) == 1 else ("study wells", "their")
        if late:
            f_late = ctx.fact(rule, scope, "nlate", late)
            share = (
                f"{{{{{f_late}}}}} of them amplified no earlier than the control: their whole "
                "signal could be what the control shows."
            )
            shown = [f_late]
        else:
            f_frac = ctx.fact(rule, scope, "contamfrac", fraction, "{:.1%}")
            share = (
                f"If the control's signal were template, it could be up to {{{{{f_frac}}}}} of "
                "theirs."
            )
            shown = [f_frac]
        product = (
            MELT_CLASS_TAINTED[melt_class]
            if melt_class is not None
            else "Without melt data the control's product is unclassified (contamination or "
            "primer-dimer) and is treated as possible contamination."
        )
        yield Finding(
            scope=scope,
            outcome="tainted_dimer" if melt_class == "dimer_candidate" else "tainted",
            reason=(
                f"{{{{{n_amp}}}}} of {{{{{n_ntc}}}}} no-template wells amplified, the earliest at "
                f"Cq {{{{{f_cq}}}}}. {{{{{f_n}}}}} {wells} amplified less than {{{{{f_k}}}}} "
                f"cycles before it, so {its} positive call and quantity are in doubt (MIQE 2.0). "
                f"{share} {product}"
            ),
            facts=[*facts, f_n, *shown],
            evidence=evidence,
            flagged=sorted(tainted["key"]),
            options={"exclude_flagged": sorted(tainted["key"])},
        )


#: Why G-NTC-1 does not judge an internal positive control.
INTERNAL_CONTROL_NTC = (
    "This target is the internal positive control: it is added to every well, the no-template "
    "controls too, and is meant to amplify there (G-IPC reads it)."
)


#: How G-NTC-1 says G-MELT's class of the product in the no-template wells that amplified.
MELT_CLASS_SAID = {
    "dimer_candidate": "Their melt curves peak below this assay's product only (G-MELT): "
    "primer-dimers are more likely than template.",
    "contamination_candidate": "A no-template well that amplified melts at this assay's product "
    "temperature (G-MELT): a contamination candidate.",
    "other_product": "A no-template well that amplified melts above this assay's product "
    "(G-MELT): another product.",
    "unclassified": "Their melt curves do not classify every one of them (G-MELT).",
}
MELT_CLASS_TAINTED = {
    "dimer_candidate": "Their melt curves peak below this assay's product only (G-MELT): "
    "primer-dimers are more likely than template, so this is a warning rather than a failure; a "
    "primer-dimer can still add signal to late study wells.",
    "contamination_candidate": "A no-template well that amplified melts at this assay's product "
    "temperature (G-MELT), so the control's product is treated as contamination.",
    "other_product": "A no-template well that amplified melts above this assay's product "
    "(G-MELT): another product, treated as possible contamination.",
    "unclassified": "The melt curves do not classify every no-template well that amplified "
    "(G-MELT), so the control's product is treated as possible contamination.",
}


def ntc_melt_class(ctx: GateContext, plate: str, target: str, keys: list[str]) -> str | None:
    """G-MELT's class of the product in these no-template wells (scientist spec, G-NTC-1).

    ``None`` when the plate has no melt curve at all (G-NTC-1 then says so as before);
    ``dimer_candidate`` when every one of them peaks below the product only;
    ``contamination_candidate`` when one peaks at the product's temperature; ``other_product``
    when one peaks above it (and none at it); ``unclassified`` otherwise (a well without a
    readable melt curve, no peak, or no known product temperature), treated as contamination.
    """
    if ctx.melt is None or plate not in ctx.melt.plates_with_melt():
        return None
    assay = ctx.melt_assays().get((plate, target))
    if assay is None:
        return "unclassified"
    status = {w.key: w.status for w in assay.wells}
    found = [status.get(k, "no_melt") for k in keys]
    if not found:
        return "unclassified"
    if "product" in found:
        return "contamination_candidate"
    if "other_product" in found:
        return "other_product"
    if all(s == "dimer" for s in found):
        return "dimer_candidate"
    return "unclassified"


# ---------- G-NAC ----------


def nac_amplified(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """Amplification in a no-amplification control (G-NAC)."""
    findings, untyped = _untyped(ctx, rule)
    yield from findings
    for plate, target, rows in ctx.plate_targets():
        if plate in untyped:
            continue
        scope = {"plate": plate, "target": target}
        nac = rows[rows["sample_type"] == "nac"]
        if nac.empty:
            yield _na(scope, "no_nac_typed", "No no-amplification control for this target here.")
            continue
        amp = nac[nac["amplified"]]
        n_nac = ctx.fact(rule, scope, "nnac", int(len(nac)))
        n_amp = ctx.fact(rule, scope, "nnacamp", int(len(amp)))
        if amp.empty:
            yield Finding(
                scope=scope,
                outcome="clean",
                reason=f"None of the {{{{{n_nac}}}}} no-amplification wells amplified.",
                facts=[n_nac, n_amp],
            )
            continue
        unkn = rows[rows["sample_type"] == ANALYSED]
        yield Finding(
            scope=scope,
            outcome="amplified",
            reason=(
                f"{{{{{n_amp}}}}} of {{{{{n_nac}}}}} no-amplification wells gave signal: the "
                "signal for this target here may not depend on amplification (by analogy with "
                "run-validity practice)."
            ),
            facts=[n_nac, n_amp],
            flagged=sorted(amp["key"]),
            options={"exclude_target_plate": sorted(unkn["key"])},
        )


# ---------- G-NRT ----------


def nrt_gdna(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """Genomic-DNA share estimated from the no-RT control (G-NRT, ValidPrime grade cut-offs)."""
    cut_a = _param(rule, "grade_a_max", 0.03)
    cut_b = _param(rule, "grade_b_max", 0.25)
    cut_c = _param(rule, "grade_c_max", 0.60)
    findings, untyped = _untyped(ctx, rule)
    yield from findings
    for plate, target, rows in ctx.plate_targets():
        if plate in untyped:
            continue
        nrt = rows[rows["sample_type"] == "nrt"]
        unkn = rows[(rows["sample_type"] == ANALYSED) & rows["amplified"]]
        if nrt.empty:
            yield _na({"plate": plate, "target": target}, "no_nrt_typed", "No no-RT control here.")
            continue
        eff = (
            float(rows["eff_target"].dropna().median()) if rows["eff_target"].notna().any() else 2.0
        )
        by_sample = {s: g for s, g in unkn.groupby("sample")}
        studied = set(rows.loc[rows["sample_type"] == ANALYSED, "sample"])
        pooled = not any(s in studied for s in nrt["sample"])
        pairs = (
            [(s, nrt, g) for s, g in by_sample.items()]
            if pooled
            else [(s, g, by_sample.get(s)) for s, g in nrt.groupby("sample")]
        )
        for sample, nrt_rows, rt_rows in pairs:
            scope = {"plate": plate, "target": target, "sample": str(sample)}
            if rt_rows is None or rt_rows.empty:
                yield _na(scope, "no_rt_wells", "This no-RT control has no RT(+) sample wells.")
                continue
            cq_rt = float(rt_rows["cq"].mean())
            amp = nrt_rows[nrt_rows["amplified"]]
            f_rt = ctx.fact(rule, scope, "cqrt", cq_rt, "{:.2f}")
            label = "pooled no-RT control" if pooled else "no-RT control"
            if amp.empty:
                yield Finding(
                    scope=scope,
                    outcome="grade_a",
                    reason=f"The {label} did not amplify: grade A (no correction needed).",
                    facts=[f_rt],
                    evidence={"pooled": pooled, "cq_rt": cq_rt, "nrt_amplified": False},
                )
                continue
            delta = float(amp["cq"].min()) - cq_rt
            share = eff**-delta
            grade = (
                "a" if share < cut_a else "b" if share < cut_b else "c" if share < cut_c else "f"
            )
            f_d = ctx.fact(rule, scope, "dcqnrt", delta, "{:.2f}")
            f_s = ctx.fact(rule, scope, "gdna", share, "{:.1%}")
            keys = sorted(rt_rows["key"])
            yield Finding(
                scope=scope,
                outcome=f"grade_{grade}",
                reason=(
                    f"The {label} amplified {{{{{f_d}}}}} cycles after the sample (Cq "
                    f"{{{{{f_rt}}}}}): genomic DNA could be about {{{{{f_s}}}}} of its signal, "
                    f"grade {grade.upper()} (ValidPrime cut-offs applied to a no-RT estimate, a "
                    "qPilot adaptation)."
                ),
                facts=[f_rt, f_d, f_s],
                evidence={"pooled": pooled, "cq_rt": cq_rt, "delta_cq": delta, "gdna_share": share},
                flagged=keys if grade != "a" else [],
                options={"exclude_sample_target": keys},
            )


# ---------- G-POS ----------


def pos_window(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """Positive control window (G-POS): needs a lab-mapped control and window; none in v0."""
    findings, untyped = _untyped(ctx, rule)
    yield from findings
    for plate, target, rows in ctx.plate_targets():
        if plate in untyped:
            continue
        scope = {"plate": plate, "target": target}
        pos = rows[rows["sample_type"] == "pos"]
        if pos.empty:
            yield _na(scope, "no_pos_typed", "No positive control for this target here.")
            continue
        facts = []
        reason = "The positive control is not mapped to a control and a Cq window yet."
        if pos["amplified"].any():
            earliest = float(pos.loc[pos["amplified"], "cq"].min())
            f_pos = ctx.fact(rule, scope, "cqpos", earliest, "{:.2f}")
            facts.append(f_pos)
            reason += f" It amplified at Cq {{{{{f_pos}}}}}."
        yield Finding(
            scope=scope, outcome=NOT_APPLICABLE, code="pos_unmapped", reason=reason, facts=facts
        )


# ---------- G-STD ----------


def std_fit(ctx: GateContext, plate: str, target: str, rows: pd.DataFrame) -> dict[str, Any]:
    """OLS of Cq on log10(quantity) over the amplified standard wells (cached per plate x target).

    Keys: ``n_std`` (typed wells), ``n_quantified``, ``n_amplified``, ``levels``,
    ``reps_min``, ``slope``, ``intercept``, ``r2``, ``efficiency``, ``e_low``, ``e_high``,
    ``span_log10``, ``eff_wells`` (mean LinRegPCR per-well E of the same wells), ``missing``
    (quantities of levels with no amplified well).
    """
    key = (plate, target)
    if key in ctx._std_fits:
        return ctx._std_fits[key]
    std = rows[rows["sample_type"] == "std"].copy()
    std["qty"] = [ctx.quantity(s, target) for s in std["sample"]]
    quantified = std[std["qty"].notna()]
    amp = quantified[quantified["amplified"]]
    out: dict[str, Any] = {
        "n_std": int(len(std)),
        "n_quantified": int(len(quantified)),
        "n_amplified": int(len(amp)),
        "levels": int(amp["qty"].nunique()),
    }
    all_levels = set(quantified["qty"])
    out["missing"] = sorted(all_levels - set(amp["qty"]))
    if out["levels"] >= 2 and len(amp) >= 3:
        x = np.log10(amp["qty"].to_numpy(dtype=float))
        y = amp["cq"].to_numpy(dtype=float)
        fit = stats.linregress(x, y)
        n = len(x)
        t = float(stats.t.ppf(0.975, n - 2)) if n > 2 else float("nan")
        slopes = (fit.slope - t * fit.stderr, fit.slope + t * fit.stderr)
        efficiency = 10 ** (-1 / fit.slope) if fit.slope < 0 else float("nan")
        bounds = sorted(10 ** (-1 / s) if s < 0 else float("nan") for s in slopes)
        out.update(
            slope=float(fit.slope),
            intercept=float(fit.intercept),
            r2=float(fit.rvalue**2),
            efficiency=float(efficiency),
            e_low=float(bounds[0]),
            e_high=float(bounds[1]),
            span_log10=float(x.max() - x.min()),
            reps_min=int(amp.groupby("qty").size().min()),
            eff_wells=float(amp["eff_indiv"].mean()) if amp["eff_indiv"].notna().any() else None,
        )
    ctx._std_fits[key] = out
    return out


def std_curve(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """Standard curve acceptance (G-STD): efficiency window, R², levels, replicates."""
    e_min = _param(rule, "efficiency_min_pct", 90.0)
    e_max = _param(rule, "efficiency_max_pct", 110.0)
    r2_min = _param(rule, "r2_min", 0.980)
    min_levels = _param(rule, "min_levels", 3)
    min_reps = _param(rule, "min_replicates", 3)
    findings, untyped = _untyped(ctx, rule)
    yield from findings
    for plate, target, rows in ctx.plate_targets():
        if plate in untyped:
            continue
        scope = {"plate": plate, "target": target}
        if not (rows["sample_type"] == "std").any():
            yield _na(scope, "no_std_typed", "No standards for this target here.")
            continue
        fit = std_fit(ctx, plate, target, rows)
        if fit["n_quantified"] == 0:
            yield _na(scope, "no_quantity", "The standards carry no declared quantity.")
            continue
        if fit["levels"] < min_levels or "slope" not in fit:
            f_lv = ctx.fact(rule, scope, "nlevels", fit["levels"])
            yield Finding(
                scope=scope,
                outcome=NOT_APPLICABLE,
                code="too_few_levels",
                reason=f"Only {{{{{f_lv}}}}} standard levels amplified; a curve needs more.",
                facts=[f_lv],
            )
            continue
        pct = (fit["efficiency"] - 1) * 100
        f = {
            "e": ctx.fact(rule, scope, "estd", fit["efficiency"] - 1, "{:.1%}"),
            "lo": ctx.fact(rule, scope, "estdlo", fit["e_low"] - 1, "{:.1%}"),
            "hi": ctx.fact(rule, scope, "estdhi", fit["e_high"] - 1, "{:.1%}"),
            "r2": ctx.fact(rule, scope, "r2", fit["r2"], "{:.3f}"),
            "slope": ctx.fact(rule, scope, "slope", fit["slope"], "{:.3f}"),
            "lv": ctx.fact(rule, scope, "nlevels", fit["levels"]),
            "rep": ctx.fact(rule, scope, "repmin", fit["reps_min"]),
            "span": ctx.fact(rule, scope, "span", fit["span_log10"], "{:.1f}"),
        }
        out_e = not (e_min <= pct <= e_max)
        low_r2 = fit["r2"] < r2_min
        few = fit["reps_min"] < min_reps
        outcome = (
            "efficiency_out" if out_e else "r2_low" if low_r2 else "few_replicates" if few else "ok"
        )
        evidence: dict[str, Any] = {
            k: fit[k] for k in ("slope", "intercept", "r2", "efficiency", "e_low", "e_high")
        }
        evidence.update(
            levels=fit["levels"],
            reps_min=fit["reps_min"],
            span_log10=fit["span_log10"],
            n_wells=fit["n_amplified"],
            n_std_not_amplified=fit["n_quantified"] - fit["n_amplified"],
            efficiency_out=out_e,
            r2_low=low_r2,
            few_replicates=few,
        )
        sentences = [
            f"Standard curve over {{{{{f['lv']}}}}} levels: efficiency {{{{{f['e']}}}}} (95 % "
            f"confidence interval {{{{{f['lo']}}}}} to {{{{{f['hi']}}}}}), R² {{{{{f['r2']}}}}}, "
            f"slope {{{{{f['slope']}}}}}."
        ]
        facts = list(f.values())
        if fit["eff_wells"] is not None and ctx.rawness in (None, "raw"):
            gap = fit["efficiency"] - fit["eff_wells"]
            f_w = ctx.fact(rule, scope, "ewells", fit["eff_wells"] - 1, "{:.1%}")
            facts.append(f_w)
            evidence.update(eff_per_well_mean=fit["eff_wells"], eff_gap=gap)
            sentences.append(
                f"The same wells' own mean efficiency (LinRegPCR, per curve) is {{{{{f_w}}}}}; "
                "the difference is evidence, not a failure."
            )
        if fit["span_log10"] < 4:
            sentences.append(
                f"The standards span {{{{{f['span']}}}}} orders of magnitude (MIQE 2.0 asks for "
                "four to five)."
            )
        if out_e:
            sentences.append("The efficiency is outside the pack's window.")
        if low_r2:
            sentences.append("R² is below the pack's minimum.")
        if few:
            sentences.append(
                f"The fewest replicates at one level is {{{{{f['rep']}}}}} (MIQE 2.0: ideally "
                "three or more per dilution step)."
            )
        if is_quantify(ctx.design):
            sentences.append(
                "This study quantifies samples: every quantity of this assay on this plate is "
                "read from this curve, so a curve that fails a check weakens all of them (the "
                "Quantities view names what MIQE would question)."
            )
        else:
            sentences.append(
                "In relative quantification this does not taint study samples; it marks the "
                "curve as an efficiency source."
            )
        reason = " ".join(sentences)
        yield Finding(
            scope=scope,
            outcome=outcome,
            reason=reason,
            facts=[fid for fid in facts if "{{" + fid + "}}" in reason],
            evidence=evidence,
        )


# ---------- G-REP ----------

# scipy.stats.studentized_range.ppf(0.95, n, inf) to six decimals (the spec rounds to three; the
# oracle uses scipy's values, and 2.772 vs 2.7718 moves a duplicate's tolerance by 7e-5 cycles).
_Q95 = {2: 2.771808, 3: 3.314493, 4: 3.63316, 5: 3.857656, 6: 4.030092}


def range_quantile(n: int) -> float:
    """Upper 5 % point of the range of ``n`` iid standard normals (studentized range, df = inf)."""
    if n in _Q95:
        return _Q95[n]
    return float(stats.studentized_range.ppf(0.95, n, np.inf))


#: Two Cq deviations this close (cycles) are a tie: no one well is farther than the other.
TIE_CYCLES = 1e-6


def outlier_well(keys: Sequence[str], cqs: np.ndarray) -> str | None:
    """The replicate farthest from the replicates' median, or ``None`` when that is a tie.

    With duplicates the two wells are always equally far from their median, and with three wells
    spread symmetrically (20.0, 20.5, 21.0) the two outer ones are: the spread is then not one
    well's, and proposing the first in well order would be arbitrary (science review J10).
    """
    dev = np.abs(np.asarray(cqs, dtype=float) - float(np.median(cqs)))
    farthest = np.flatnonzero(dev >= dev.max() - TIE_CYCLES)
    return str(keys[int(farthest[0])]) if len(farthest) == 1 else None


def replicate_spread(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """Technical-replicate Cq range against a Poisson + pipetting tolerance (G-REP)."""
    c = _param(rule, "pipetting_cv", 0.15)
    low_copy_floor = _param(rule, "low_copy_tolerance_cycles", 2.0)
    cq_known = _param(rule, "copies_unknown_max_cq", 30.0)
    cq_stochastic = _param(rule, "stochastic_min_cq", 35.0)
    share_max = _param(rule, "plate_share_max", 0.10)
    # Not a control rule: replicates of study samples are checked on untyped plates too.
    for plate, target, rows in ctx.plate_targets():
        kinds = rows[rows["sample_type"].isin((ANALYSED, "pos", "std"))]
        groups = [(s, g) for s, g in kinds.groupby("sample", sort=False) if len(g) >= 2]
        if not groups:
            yield _na(
                {"plate": plate, "target": target},
                "no_replicates",
                "No sample has two or more wells for this target here.",
            )
            continue
        eff = (
            float(rows["eff_target"].dropna().median()) if rows["eff_target"].notna().any() else 2.0
        )
        fit = std_fit(ctx, plate, target, rows)
        flagged_groups = 0
        evaluated = 0
        for sample, g in groups:
            scope = {"plate": plate, "target": target, "sample": str(sample)}
            amp = g[g["amplified"]]
            if len(amp) < 2:
                yield _na(scope, "too_few_amplified", "Fewer than two of its wells amplified.")
                continue
            cqs = amp["cq"].to_numpy(dtype=float)
            mean_cq = float(cqs.mean())
            spread = float(cqs.max() - cqs.min())
            copies = None
            if fit.get("levels", 0) >= 3 and "slope" in fit and fit["slope"] < 0:
                copies = 10 ** ((mean_cq - fit["intercept"]) / fit["slope"])
            flags = []
            if copies is not None and copies > 0:
                inv_n = 1 / copies
                if copies < 10:
                    flags.append("approx_low_copy")
            elif mean_cq <= cq_known:
                inv_n = 0.0
                flags.append("copies_unknown")
            elif mean_cq <= cq_stochastic:
                inv_n = 0.0
                flags.append("copies_unknown_low_copy_possible")
            else:
                yield _na(
                    scope,
                    "stochastic_range",
                    "Its wells amplified so late that copy numbers are unknown and the spread "
                    "is dominated by sampling.",
                )
                continue
            sigma = math.sqrt(c**2 + inv_n) / math.log(eff)
            tol = range_quantile(len(amp)) * sigma
            if "copies_unknown_low_copy_possible" in flags:
                tol = max(tol, low_copy_floor)
            evaluated += 1
            outside = spread > tol
            flagged_groups += int(outside)
            f_r = ctx.fact(rule, scope, "range", spread, "{:.2f}")
            f_t = ctx.fact(rule, scope, "tol", tol, "{:.2f}")
            f_n = ctx.fact(rule, scope, "nrep", int(len(amp)))
            undetermined = int(len(g) - len(amp))
            facts = [f_r, f_t, f_n]
            reason = (
                f"The {{{{{f_n}}}}} replicate wells span {{{{{f_r}}}}} cycles; the expected range "
                f"for this copy number is up to {{{{{f_t}}}}} cycles."
            )
            if undetermined:
                f_u = ctx.fact(rule, scope, "nundet", undetermined)
                facts.append(f_u)
                reason += f" {{{{{f_u}}}}} more replicate wells did not amplify."
            far = outlier_well(amp["key"].tolist(), cqs)
            options = {"drop_sample": sorted(g["key"])}
            if far is not None:
                options = {"drop_outlier_well": [far], **options}
            elif outside:  # science review J10: a tie is not one well's spread
                reason += (
                    " The spread is not one well's: the wells farthest from the others' median "
                    "are equally far from it, so no single well is proposed to leave out."
                )
            yield Finding(
                scope=scope,
                outcome="outside" if outside else "within",
                reason=reason,
                facts=facts,
                evidence={
                    "range": spread,
                    "tolerance": tol,
                    "mean_cq": mean_cq,
                    "copies": copies,
                    "n_replicates": int(len(amp)),
                    "n_undetermined": undetermined,
                    "flags": ",".join(flags),
                    "notes": ";".join(sorted({n for n in amp["note"] if n})),
                },
                flagged=([far] if far is not None else sorted(amp["key"])) if outside else [],
                options=options if outside else {},
            )
        if evaluated and flagged_groups / evaluated > share_max:
            scope = {"plate": plate, "target": target}
            f_s = ctx.fact(rule, scope, "share", flagged_groups / evaluated, "{:.0%}")
            yield Finding(
                scope=scope,
                outcome="many_outside",
                reason=(
                    f"{{{{{f_s}}}}} of replicate groups here are outside their expected range: a "
                    "systematic workflow problem is more likely than single bad wells."
                ),
                facts=[f_s],
            )


# ---------- G-RT ----------

RT_OUTCOMES: dict[str, Severity] = {"rt_within_limit": "pass", "rt_over_limit": "warn"}


def rt_replicate_spread(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """RT-replicate Cq range per biological unit and target (G-RT; ranges of ``qpcr.gate_rt``).

    Every study well of an RT-labelled sample counts, including wells a person left out, so the
    check stays where the decision was made (its option then says the wells are already left
    out); the Evidence Ledger's G-RT line counts only the wells in use.
    """
    from qpilot.qpcr.gate_rt import rt_labels, rt_means, rt_ranges, rt_replicate_wells

    limit = _param(rule, "limit_cycles", RT_RANGE_LIMIT)
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError(f"rule {rule.id}: limit_cycles must be a positive number of cycles")
    if not rt_labels(ctx.design):
        yield _na(
            {},
            "rt_not_annotated",
            "No reverse-transcription replicates are annotated in the design, so the spread of "
            "reverse transcription is not measured. Samples of one biological unit that were "
            "reverse-transcribed separately from the same RNA are marked in the sample sheet's "
            "rt_replicate column.",
        )
        return
    wells = rt_replicate_wells(ctx.table, ctx.design, include_excluded=True)
    ranges = rt_ranges(wells)
    if ranges.empty:
        yield _na(
            {},
            "rt_not_measurable",
            "Reverse-transcription replicates are annotated, but no biological unit has two of "
            "them with study wells for one target.",
        )
        return
    means = rt_means(wells)
    cycles = "cycle" if limit == 1 else "cycles"
    for row in ranges.itertuples(index=False):
        unit, target = str(row.unit), str(row.target)
        scope = {"unit": unit, "target": target}
        mine = wells[(wells["unit"] == unit) & (wells["target"] == target)]
        keys = sorted(mine["key"])
        if not math.isfinite(row.range):
            yield _na(
                scope,
                "too_few_measured",
                "Fewer than two of this unit's reverse-transcription replicates have a Cq for "
                "this target.",
            )
            continue
        f_n = ctx.fact(rule, scope, "nrt", int(row.n_measured))
        f_r = ctx.fact(rule, scope, "rtrange", float(row.range), "{:.2f}")
        f_l = ctx.fact(rule, scope, "rtlimit", limit, "{:g}")
        over = bool(row.range >= limit)
        reason = (
            f"The {{{{{f_n}}}}} reverse-transcription replicates of this unit span "
            f"{{{{{f_r}}}}} cycles for this target (each the mean Cq of its wells); the limit is "
            f"{{{{{f_l}}}}} {cycles}."
        )
        if over:
            reason += (
                " At or above the limit, reverse transcription differed between them more than "
                "the criterion allows; whether it matters is the consequence test's answer."
            )
        options = {"exclude_unit_target": keys}
        farthest = ""
        if row.n_measured >= 3:
            rts = means.loc[(unit, target)].dropna()
            gap = (rts - float(rts.median())).abs()
            farthest = str(gap.sort_values(ascending=False, kind="stable").index[0])
            options["drop_rt_replicate"] = sorted(mine.loc[mine["rt"] == farthest, "key"])
        yield Finding(
            scope=scope,
            outcome="rt_over_limit" if over else "rt_within_limit",
            reason=reason,
            facts=[f_n, f_r, f_l],
            evidence={
                "range": float(row.range),
                "limit_cycles": limit,
                "n_rt": int(row.n_rt),
                "n_measured": int(row.n_measured),
                "cq_min": float(row.cq_min),
                "cq_max": float(row.cq_max),
                "farthest_rt": farthest,
            },
            flagged=keys if over else [],
            options=options if over else {},
        )


# ---------- G-INSTR ----------

#: G-INSTR's codes that give a verdict. Its information lines are warnings here (an expired
#: calibration is a fact to weigh, so the consequence test prices it); "calibration date not in
#: the file" and "nothing to check" give none.
INSTR_OUTCOMES: dict[str, Severity] = {
    "run_complete": "pass",
    "run_not_complete": "warn",
    "interrupted": "warn",
    "aborted_in_log": "warn",
    "power_event": "warn",
    "no_interruptions": "pass",
    "calibration_expired": "warn",
    "calibrations_in_date": "pass",
    "hold_off_setpoint": "warn",
    "hold_on_setpoint": "pass",
}
_SEVERITY_RANK = {"pass": 0, "warn": 1, "fail": 2}
LINK_PROBLEMS = {
    "missing": "The run file a person linked to this plate is no longer where qPilot kept it: "
    "link it again to check the run.",
    "changed": "The run file a person linked to this plate has changed since it was linked, so "
    "it is not read: link it again to check the run.",
    "unreadable": "The run file a person linked to this plate cannot be read any more: link it "
    "again to check the run.",
}
RDML_SAYS_LITTLE = (
    "RDML has no field for the run state, pauses or calibrations: link the run file the "
    "instrument wrote for this plate (an .eds file or a QuantStudio or CFX export) to check them."
)
#: Per run file source: the evidence's ``source``, the reason's lead, and the file in a sentence.
RUN_SOURCES: dict[str, tuple[str, str, str]] = {
    "linked": (
        "linked run file",
        "From the run file a person linked to this plate:",
        "The run file a person linked to this plate",
    ),
    "export": (
        "export run file",
        "From this plate's run file in the instrument export:",
        "This plate's run file in the instrument export",
    ),
    "study_file": ("study file", "From the study's file:", "The study's file"),
}


def instrument_run(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """What each plate's run file says about the run and the instrument (G-INSTR).

    The lines are :func:`qpilot.qpcr.gate_instr.g_instr`'s, worded by
    :mod:`qpilot.explain.instrument_text`; each number they cite is registered again as this
    rule's fact (serials and instrument names never are: G-INSTR leaves them out). The verdict
    is the worst line's under the pack's severity; a warning or a failure points at the run's
    study wells, and the consequence test leaves them out. The reason says which file it read.
    """
    hold = _param(rule, "hold_limit_c", DEFAULT_HOLD_LIMIT_C)
    for plate in ctx.plates():
        found = (ctx.runs or {}).get(plate)
        if found is None:
            yield _na(
                {"plate": plate},
                "no_run_file",
                "qPilot has no run context for this plate. " + RDML_SAYS_LITTLE,
            )
            continue
        if found.context is None:
            problem = found.problem if found.problem in LINK_PROBLEMS else "unreadable"
            yield Finding(
                scope={"plate": plate},
                outcome=NOT_APPLICABLE,
                code="linked_file_unreadable",
                reason=LINK_PROBLEMS[problem],
                evidence={"source": "linked run file", "problem": problem},
            )
            continue
        yield _run_finding(rule, ctx, plate, found, hold)


def _run_finding(rule: Rule, ctx: GateContext, plate: str, found: RunFile, hold: float) -> Finding:
    """One plate's G-INSTR finding from its run file's lines."""
    from qpilot.explain.instrument_text import line_tokens
    from qpilot.qpcr.gate_instr import g_instr

    scope = {"plate": plate}
    run = found.context
    assert run is not None  # instrument_run says the plates without one
    prefix = run.fact_id("")
    cited: dict[str, str] = {}

    def cite(fid: str, facts: Mapping[str, Fact]) -> str:
        if fid not in cited:
            fact = facts[fid]
            name = re.sub(r"[^a-z0-9_]+", "_", fid.removeprefix(prefix).lower()).strip("_")
            value = fact.value
            if isinstance(value, bool) or not isinstance(value, int | float | str):
                value = str(value)
            cited[fid] = ctx.fact(
                rule, scope, f"instr_{name or 'value'}", value, fact.fmt, fact.unit
            )
        return cited[fid]

    lines = g_instr(run, hold_limit_c=hold)
    sentences: list[str] = []
    worst: tuple[int, str] | None = None
    cycles: list[int] = []
    for line in lines:
        try:
            tokens = line_tokens(line)
            sentences.append(
                TOKEN.sub(lambda m, f=line.facts: "{{" + cite(m.group(1), f) + "}}", tokens)
            )
        except KeyError:  # a line without wording or a fact: said by its status alone
            sentences.append(f"A {line.status} line the wording does not cover.")
        cycles += [c for c in line.cycles if c not in cycles]
        if line.code in INSTR_OUTCOMES:
            rank = _SEVERITY_RANK[rule.verdict_for(line.code, INSTR_OUTCOMES)]
            if worst is None or rank > worst[0]:
                worst = (rank, line.code)
    day = run.run.get("date")
    if found.linked and found.study_date and day and str(day) != str(found.study_date):
        f_a = ctx.fact(rule, scope, "instr_linked_date", str(day))
        f_b = ctx.fact(rule, scope, "instr_study_date", str(found.study_date))
        cited.update({"linked date": f_a, "study date": f_b})
        sentences.append(
            f"The linked file's run date ({{{{{f_a}}}}}) is not this plate's date in the "
            f"study's file ({{{{{f_b}}}}}): check that it is this plate's run file."
        )
    source, lead, which = RUN_SOURCES[found.source]
    evidence: dict[str, Any] = {
        "source": source,
        "source_kind": run.source_kind,
        "run_state": run.run.get("state"),
        "cycles": ",".join(str(c) for c in cycles),
    }
    if worst is None:
        codes = {line.code for line in lines}
        said = [f"{which} {t[9:]}" if t.startswith("The file ") else t for t in sentences]
        hint = [RDML_SAYS_LITTLE] if found.source == "study_file" else []
        return Finding(
            scope=scope,
            outcome=NOT_APPLICABLE,
            code="nothing_in_file" if "nothing_in_file" in codes else "nothing_to_check",
            reason=" ".join([*said, *hint]),
            facts=list(cited.values()),
            evidence=evidence,
        )
    verdict = rule.verdict_for(worst[1], INSTR_OUTCOMES)
    study = ctx.table[(ctx.table["run_id"] == plate) & (ctx.table["sample_type"] == ANALYSED)]
    keys = sorted(study["key"])
    return Finding(
        scope=scope,
        outcome=worst[1],
        reason=" ".join([lead, *sentences]),
        facts=list(cited.values()),
        evidence=evidence,
        flagged=keys if verdict in ("warn", "fail") else [],
        options={"exclude_run": keys},
    )


def file_runs(rdml_path: str | Path) -> dict[str, RunFile]:
    """Each run of an RDML file as the study's own :class:`RunFile` (``{}`` when unreadable)."""
    from qpilot.qpcr.instrument_context import InstrumentFileError, run_contexts_from_rdml

    try:
        contexts = run_contexts_from_rdml(rdml_path)
    except (InstrumentFileError, OSError, ValueError):
        return {}
    return {c.run_id: RunFile(context=c) for c in contexts if c.run_id}


def stored_runs(data: Any) -> dict[str, RunFile] | None:
    """The study's own run files from a stored ``run_context.json`` (``None`` if unusable).

    The file holds each run's :meth:`RunContext.model_view` (no serial, alias or local fact).
    """
    from pydantic import ValidationError

    views = data.get("runs") if isinstance(data, Mapping) else None
    if not isinstance(views, list):
        return None
    out: dict[str, RunFile] = {}
    for view in views:
        try:
            context = RunContext.model_validate(view)
        except ValidationError:
            return None
        if context.run_id:
            out[context.run_id] = RunFile(context=context)
    return out


def with_export(
    own: Mapping[str, RunFile], exported: Mapping[str, RunContext]
) -> dict[str, RunFile]:
    """The study's own run files, with each plate's run file in the instrument export in its place.

    ``exported`` is what :func:`qpilot.qpcr.export_runs.export_runs` read (plate -> context);
    a run file a person links goes on top of both (:func:`with_linked`).
    """
    out = dict(own)
    for plate, context in exported.items():
        out[plate] = RunFile(context=context, source="export")
    return out


def with_linked(
    own: Mapping[str, RunFile],
    linked: Mapping[str, RunContext],
    problems: Mapping[str, str] | None = None,
) -> dict[str, RunFile]:
    """The plates' run files (``own``), with the run files a person linked in their place.

    ``problems`` names the plates whose linked file cannot be read (``missing``, ``changed``,
    ``unreadable``): G-INSTR says so for them instead of reading the file in ``own``.
    """
    out = dict(own)
    for plate, context in linked.items():
        mine = own.get(plate)
        day = mine.context.run.get("date") if mine is not None and mine.context else None
        out[plate] = RunFile(context=context, source="linked", study_date=str(day) if day else None)
    for plate, problem in (problems or {}).items():
        out[plate] = RunFile(context=None, source="linked", problem=str(problem))
    return out


# ---------- G-MELT ----------

#: G-MELT's outcomes and their verdicts (scientist spec, G-MELT; the pack may remap them).
MELT_OUTCOMES: dict[str, Severity] = {
    "one_product": "pass",
    "extra_peak": "warn",
    "tm_off": "fail",
    "no_peak": "fail",
    "ntc_clean": "pass",
    "ntc_dimer": "pass",
    "ntc_other_product": "warn",
    "ntc_product": "warn",
}
NO_MELT_STUDY = (
    "This study's file has no melt curves, so the products' melting temperatures are not "
    "checked. For SYBR Green or another DNA-binding dye, export the melt curves with the "
    "amplification (CFX: Melt Curve RFU Results; QuantStudio: Melt Curve Raw Data) and open "
    "them together."
)
NO_MELT_PLATE = (
    "This plate has no melt curves, so its products' melting temperatures are not checked."
)
NO_MELT_TARGET = "No well of this target on this plate has a melt curve."
PROBE_CHEMISTRY = (
    "The file names a probe chemistry for this target: a melt curve does not show its product."
)
MIQE_MELT = (
    "A single peak at the expected temperature does not guarantee that it is the intended "
    "amplicon (MIQE 2.0)."
)
#: A study group's outcome is its worst well's status, in this order.
STUDY_ORDER = ("tm_off", "no_peak", "extra_peak")
#: A no-template group's outcome is its worst well's class, in this order.
NTC_ORDER = ("product", "other_product", "dimer")
NTC_OUTCOME = {
    "product": "ntc_product",
    "other_product": "ntc_other_product",
    "dimer": "ntc_dimer",
    "no_product": "ntc_clean",
}
#: Wells a G-MELT reason names one by one before it counts the rest.
MELT_WELLS_SAID = 6
DEG = " °C"


class _Said:
    """The facts of one G-MELT finding, registered as its reason cites them."""

    def __init__(self, rule: Rule, ctx: GateContext, scope: Mapping[str, str]) -> None:
        self.rule, self.ctx, self.scope = rule, ctx, dict(scope)
        self.facts: list[str] = []

    def __call__(self, name: str, value: float | int | str, fmt: str = "{}", unit: str = "") -> str:
        fid = self.ctx.fact(self.rule, self.scope, name, value, fmt, unit)
        if fid not in self.facts:
            self.facts.append(fid)
        return "{{" + fid + "}}"

    def tm(self, name: str, value: float) -> str:
        return self(name, float(value), "{:.1f}", DEG)

    def delta(self, name: str, value: float) -> str:
        return self(name, abs(float(value)), "{:.1f}", DEG)


def _expected_said(assay: AssayMelt, say: _Said) -> str:
    """Where this assay's product is expected to melt, in words (a clause, lower case)."""
    p = assay.params
    if assay.expected_tm is None:
        return (
            "the product's melting temperature on this plate is not known (fewer than "
            f"{say('minwells', p.min_wells)} study wells melted and the file declares none), so "
            "only extra peaks are checked"
        )
    exp = say.tm("exptm", assay.expected_tm)
    tol = say.tm("tol", p.tm_tolerance_c)
    if assay.expected_source == "file":
        return f"the file declares this target's product to melt at {exp} (the rule allows ±{tol})"
    n_ref = say("nref", len(assay.reference))
    return (
        f"this assay's product melts at {exp} on this plate (the median of {n_ref} study wells; "
        f"the rule allows ±{tol})"
    )


def _amplified_said(w: WellCall, say: _Said, i: int) -> str:
    if w.amplified and w.cq is not None:
        return f" (it amplified at Cq {say(f'cq{i}', float(w.cq), '{:.1f}')})"
    return " (it gave no Cq: the product may have formed late)"


def _study_flag(w: WellCall, i: int, say: _Said) -> str:
    """One flagged study well in words."""
    well = say(f"well{i}", w.well)
    main = w.main
    if w.status == "no_peak" or main is None:
        cq = f" (Cq {say(f'cq{i}', float(w.cq), '{:.1f}')})" if w.cq is not None else ""
        return (
            f"Well {well} amplified{cq} but its melt curve shows no peak above this plate's "
            "noise: no product melted at the expected temperature."
        )
    tm = say.tm(f"tm{i}", main.tm)
    if w.status == "tm_off" and w.offset is not None:
        side = "below" if w.offset < 0 else "above"
        return (
            f"Well {well}'s main peak is at {tm}, {say.delta(f'off{i}', w.offset)} {side} it: "
            "no product at the expected temperature; it may be another product."
        )
    shares = dict(zip(w.peaks, w.shares, strict=True))
    parts = [
        f"{say.tm(f'xtm{i}_{j}', pk.tm)} ({say(f'xshare{i}_{j}', shares[pk], '{:.0%}')} of its "
        "peak height)"
        for j, pk in enumerate(w.extra)
    ]
    more = "a second peak" if len(parts) == 1 else f"{say(f'nextra{i}', len(parts))} more peaks"
    return f"Well {well} shows {more} beside its product at {tm}: at {' and at '.join(parts)}."


def _study_finding(
    rule: Rule,
    ctx: GateContext,
    scope: dict[str, str],
    assay: AssayMelt,
    usable: list[WellCall],
) -> Finding:
    """One study sample's amplified wells on one plate, for one target."""
    say = _Said(rule, ctx, scope)
    expected = _expected_said(assay, say)
    flagged = [w for w in usable if w.status in STUDY_FLAGS]
    worst = next((s for s in STUDY_ORDER if any(w.status == s for w in usable)), "one_product")
    n = len(usable)
    sentences: list[str] = []
    if not flagged:
        tms = [w.main.tm for w in usable if w.main is not None]
        lo, hi = min(tms), max(tms)
        if n == 1:
            lead = f"Its amplified well melts as one product at {say.tm('tm', lo)}"
        elif round(lo, 1) == round(hi, 1):
            lead = (
                f"Its {say('n', n)} amplified wells each melt as one product at {say.tm('tm', lo)}"
            )
        else:
            lead = (
                f"Its {say('n', n)} amplified wells each melt as one product, at "
                f"{say.tm('tmlo', lo)} to {say.tm('tmhi', hi)}"
            )
        sentences += [f"{lead}; {expected}.", MIQE_MELT]
    else:
        ok = n - len(flagged)
        if ok:
            sentences.append(
                f"{say('nok', ok)} of its {say('n', n)} amplified wells melt as one product; "
                f"{expected}."
            )
        else:
            sentences.append(f"{expected[0].upper()}{expected[1:]}.")
        sentences += [_study_flag(w, i, say) for i, w in enumerate(flagged[:MELT_WELLS_SAID])]
        if len(flagged) > MELT_WELLS_SAID:
            rest = say("nrest", len(flagged) - MELT_WELLS_SAID)
            sentences.append(f"{rest} more of its wells are flagged the same way.")
        if any(w.status == "extra_peak" for w in flagged):
            sentences.append(
                "Part of the signal of a well with an extra peak is not the product, so its Cq "
                "may not measure the target alone; a peak below the product is usually a "
                "primer-dimer."
            )
        if any(w.status in ("tm_off", "no_peak") for w in flagged):
            sentences.append(
                "A well without a product at the expected temperature may have amplified "
                "something else."
            )
    keys = sorted(w.key for w in flagged)
    return Finding(
        scope=scope,
        outcome=worst,
        reason=" ".join(sentences),
        facts=say.facts,
        evidence={
            "expected_tm": assay.expected_tm,
            "expected_source": assay.expected_source or "",
            "tolerance_c": assay.params.tm_tolerance_c,
            "n_wells": n,
            "n_flagged": len(flagged),
            "calls": ",".join(f"{w.well}:{w.status}" for w in usable),
        },
        flagged=keys,
        options={"exclude_flagged": keys} if keys else {},
    )


def _ntc_finding(
    rule: Rule,
    ctx: GateContext,
    scope: dict[str, str],
    assay: AssayMelt,
    usable: list[WellCall],
) -> Finding:
    """One no-template sample's wells on one plate, for one target: what melted in them."""
    say = _Said(rule, ctx, scope)
    found = [w for w in usable if w.status in NTC_ORDER]
    if not found and any(w.status == "unclassified" for w in usable):
        p = assay.params
        return Finding(
            scope=scope,
            outcome=NOT_APPLICABLE,
            code="no_expected_tm",
            reason=(
                "A no-template well's melt curve shows a peak, but this assay's product "
                "temperature on this plate is not known (fewer than "
                f"{say('minwells', p.min_wells)} study wells melted and the file declares "
                "none), so the peak cannot be classified."
            ),
            facts=say.facts,
        )
    worst = next((s for s in NTC_ORDER if any(w.status == s for w in usable)), "no_product")
    sentences: list[str] = []
    if not found:
        if len(usable) == 1:
            sentences.append("This no-template well's melt curve shows no peak: nothing melted.")
        else:
            sentences.append(
                f"None of its {say('n', len(usable))} no-template wells shows a melt peak: "
                "nothing melted in them."
            )
    else:
        exp = say.tm("exptm", assay.expected_tm or 0.0)
        tol = say.tm("tol", assay.params.tm_tolerance_c)
        for i, w in enumerate(found[:MELT_WELLS_SAID]):
            well = say(f"well{i}", w.well)
            amp = _amplified_said(w, say, i)
            if w.status == "product":
                at = next(
                    (
                        pk
                        for pk in (w.main, *w.extra)
                        if pk is not None
                        and assay.expected_tm is not None
                        and abs(pk.tm - assay.expected_tm) <= assay.params.tm_tolerance_c
                    ),
                    w.main,
                )
                sentences.append(
                    f"Well {well} shows a peak at {say.tm(f'tm{i}', at.tm if at else 0.0)}, "
                    f"within ±{tol} of this assay's product ({exp}): template may have reached "
                    f"it, a contamination candidate{amp}."
                )
                continue
            main = w.main
            assert main is not None and w.offset is not None
            tm, off = say.tm(f"tm{i}", main.tm), say.delta(f"off{i}", w.offset)
            if w.status == "other_product" and w.offset < 0:
                # below the product but closer than a primer-dimer melts (science review J5)
                gap = say.tm("dimergap", assay.params.dimer_min_below_c)
                sentences.append(
                    f"Well {well} melts at {tm}, {off} below this assay's product ({exp}), "
                    f"closer than the {gap} a primer-dimer is expected to melt below it: a "
                    f"shorter product or a variant amplicon may have formed in it{amp}."
                )
            elif w.status == "other_product":
                sentences.append(
                    f"Well {well} melts at {tm}, {off} above this assay's product ({exp}): "
                    f"another product formed in it{amp}."
                )
            else:
                sentences.append(
                    f"Well {well} melts at {tm}, {off} below this assay's product ({exp}): a "
                    f"primer-dimer is more likely than template{amp}."
                )
        if len(found) > MELT_WELLS_SAID:
            rest = say("nrest", len(found) - MELT_WELLS_SAID)
            sentences.append(f"{rest} more of its wells show a peak.")
        if worst in ("product", "other_product"):
            sentences.append(
                "Whether that touches the study wells is for the no-template control rule to say "
                "(how many cycles earlier they amplified); leaving a control out changes no "
                "conclusion."
            )
        else:
            sentences.append(
                "A primer-dimer is usually harmless in a no-template control; the no-template "
                "control rule grades the control's amplification as a primer-dimer."
            )
    flagged = sorted(w.key for w in usable if w.status in NTC_FLAGS)
    return Finding(
        scope=scope,
        outcome=NTC_OUTCOME[worst],
        reason=" ".join(sentences),
        facts=say.facts,
        evidence={
            "expected_tm": assay.expected_tm,
            "expected_source": assay.expected_source or "",
            "tolerance_c": assay.params.tm_tolerance_c,
            "n_wells": len(usable),
            "calls": ",".join(f"{w.well}:{w.status}" for w in usable),
        },
        flagged=flagged,
    )


def _unreadable(rule: Rule, ctx: GateContext, scope: dict[str, str], assay: AssayMelt) -> Finding:
    """An assay none of whose melt curves can be read (too few or too far-apart readings)."""
    if assay.coarse and assay.step_c is not None:
        say = _Said(rule, ctx, scope)
        return Finding(
            scope=scope,
            outcome=NOT_APPLICABLE,
            code="coarse_melt",
            reason=(
                f"The melt readings are about {say.tm('step', assay.step_c)} apart: too far "
                "apart to place a melting temperature to within the rule's tolerance."
            ),
            facts=say.facts,
        )
    return _na(scope, "too_few_points", "The melt curves have too few readings to find peaks.")


def melt_products(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """One product at the assay's melting temperature (G-MELT; :mod:`qpilot.qpcr.melt`).

    Per study sample x target x plate, over its amplified wells (unknowns, positives,
    standards): one product at the expected Tm passes; an extra peak warns; a main peak off the
    expected Tm, or no peak, fails; the flagged wells go to the consequence test. Per
    no-template sample: no peak, a primer-dimer candidate, another product or a contamination
    candidate (G-NTC-1 grades the control's amplification with this class); a control is not a
    study sample, so it has no consequence test of its own.
    """
    params = MeltParams.from_rule(rule.params)
    if ctx.melt is None or not ctx.melt.has_melt:
        yield _na({}, "no_melt_data", NO_MELT_STUDY)
        return
    if params != ctx.melt_params:  # this rule's own thresholds (a lab's edited pack)
        ctx.melt_params, ctx._melt = params, None
    assays = ctx.melt_assays()
    with_melt = ctx.melt.plates_with_melt()
    for plate in ctx.plates():
        if plate not in with_melt:
            yield _na({"plate": plate}, "no_melt_data", NO_MELT_PLATE)
            continue
        rows = ctx.table[ctx.table["run_id"] == plate]
        for target in dict.fromkeys(str(t) for t in rows["target"]):
            scope = {"plate": plate, "target": target}
            if ctx.melt.probe(target):
                yield _na(scope, "probe_chemistry", PROBE_CHEMISTRY)
                continue
            assay = assays.get((plate, target))
            if assay is None:
                yield _na(scope, "no_melt_data", NO_MELT_TARGET)
                continue
            if not any(w.melt is not None and not w.melt.problem for w in assay.wells):
                yield _unreadable(rule, ctx, scope, assay)
                continue
            yield from _melt_assay(rule, ctx, scope, assay)


def _melt_assay(
    rule: Rule, ctx: GateContext, scope: dict[str, str], assay: AssayMelt
) -> Iterator[Finding]:
    """The findings of one target on one plate: its study samples, then its controls."""
    studied: dict[str, list[WellCall]] = {}
    controls: dict[str, list[WellCall]] = {}
    for w in assay.wells:
        if w.sample_type in JUDGED:
            studied.setdefault(w.sample, []).append(w)
        elif w.sample_type in NO_TEMPLATE:
            controls.setdefault(w.sample, []).append(w)
    quiet = 0
    for sample, wells in studied.items():
        usable = [w for w in wells if w.amplified and w.melt is not None and not w.melt.problem]
        if usable:
            yield _study_finding(rule, ctx, {**scope, "sample": sample}, assay, usable)
        elif any(w.amplified for w in wells):
            yield _na(
                {**scope, "sample": sample},
                "no_melt_curve",
                "Its amplified wells have no melt curve that can be read.",
            )
        else:
            quiet += 1
    if quiet:
        say = _Said(rule, ctx, scope)
        yield Finding(
            scope=scope,
            outcome=NOT_APPLICABLE,
            code="not_amplified",
            reason=(
                f"{say('nquiet', quiet)} study samples here did not amplify, so their melt curves "
                "are not judged."
                if quiet > 1
                else "One study sample here did not amplify, so its melt curve is not judged."
            ),
            facts=say.facts,
        )
    for sample, wells in controls.items():
        usable = [w for w in wells if w.melt is not None and not w.melt.problem]
        if usable:
            yield _ntc_finding(rule, ctx, {**scope, "sample": sample}, assay, usable)
        else:
            yield _na(
                {**scope, "sample": sample},
                "no_melt_curve",
                "This no-template control has no melt curve that can be read.",
            )


# ---------- registry ----------

# ---------- G-IPC ----------

#: G-IPC's outcomes and their verdicts.
IPC_OUTCOMES = {"ipc_ok": "pass", "ipc_delayed": "warn", "ipc_failed": "warn"}


def ipc_inhibition(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """An internal positive control much later than in the no-template wells (G-IPC).

    Per plate and internal control (:func:`qpilot.qpcr.multiplex.internal_controls`): its
    expected Cq is the median over the no-template wells where it amplified (nothing there to
    compete with it or to inhibit it), else, with fewer than ``min_reference_wells`` of them, the
    median over the plate's study wells. A study well whose control is ``delay_cycles`` or more
    later suggests inhibition; a well where the control did not amplify while no other target of
    the well did either cannot tell a negative from an inhibited reaction. A control that did not
    amplify beside a target that did is not read as inhibition: a strongly amplifying target can
    use up the reaction before the control rises. The consequence test leaves out the flagged
    wells, every curve of each (one reaction).
    """
    delay = _param(rule, "delay_cycles", 3.0)
    min_reference = int(_param(rule, "min_reference_wells", 2))
    table = ctx.control_rows()
    controls = mx.internal_controls(table)
    if not controls:
        yield _na(
            {},
            "no_internal_control",
            "No internal positive control is measured in the same wells as the targets, so "
            "inhibition is not checked this way.",
        )
        return
    for (plate, target), rows in table.groupby(["run_id", "target"], sort=False):
        if target not in controls:
            continue
        scope = {"plate": str(plate), "target": str(target)}
        on_plate = table[table["run_id"] == plate]
        others = mx.partners(on_plate, str(target))
        others = others[~others["target"].isin(controls)]
        partner_amplified = others.groupby("key")["amplified"].any()
        blank = rows[rows["sample_type"].isin(("ntc", "ntp")) & rows["amplified"]]
        study = rows[rows["sample_type"] == ANALYSED]
        if study.empty:
            yield _na(scope, "no_unknowns", "No study samples for this control on this plate.")
            continue
        if len(blank) >= min_reference:
            expected = float(blank["cq"].median())
            basis = "no-template wells where it amplified"
            n_basis = len(blank)
        else:
            seen = study[study["amplified"]]
            if len(seen) < 3:
                yield _na(
                    scope,
                    "too_few_controls",
                    "The control amplified in too few wells here to say what its Cq should be.",
                )
                continue
            expected = float(seen["cq"].median())
            basis = "study wells where it amplified (too few no-template wells had it)"
            n_basis = len(seen)
        amp = study[study["amplified"]]
        late = amp[amp["cq"] - expected >= delay]
        silent = study[~study["amplified"]]
        rescued = silent["key"].map(partner_amplified).fillna(False).astype(bool)
        failed, outcompeted = silent[~rescued], silent[rescued]
        f_n = ctx.fact(rule, scope, "nstudy", int(len(study)))
        f_e = ctx.fact(rule, scope, "expected", expected, "{:.2f}")
        f_b = ctx.fact(rule, scope, "nbasis", int(n_basis))
        f_d = ctx.fact(rule, scope, "delay", delay, "{:g}")
        facts = [f_n, f_e, f_b, f_d]
        evidence: dict[str, Any] = {
            "expected_cq": expected,
            "basis": "no_template" if basis.startswith("no-template") else "study",
            "n_study_wells": int(len(study)),
            "n_delayed": int(len(late)),
            "n_failed": int(len(failed)),
            "n_outcompeted": int(len(outcompeted)),
            "delay_cycles": delay,
        }
        said = (
            f"The control's expected Cq is {{{{{f_e}}}}}, its median over the {{{{{f_b}}}}} "
            f"{basis}."
        )
        extra = ""
        if len(outcompeted):
            f_o = ctx.fact(rule, scope, "noutcompeted", int(len(outcompeted)))
            facts.append(f_o)
            extra = (
                f" In {{{{{f_o}}}}} wells it did not amplify beside a target that did: a strongly "
                "amplifying target can use up the reaction first, which is not inhibition."
            )
        if late.empty and failed.empty:
            yield Finding(
                scope=scope,
                outcome="ipc_ok",
                reason=(
                    f"{said} In every one of the {{{{{f_n}}}}} study wells where it amplified, it "
                    f"came up less than {{{{{f_d}}}}} cycles later than that.{extra}"
                ),
                facts=facts,
                evidence=evidence,
            )
            continue
        parts = []
        if len(late):
            shift = float((late["cq"] - expected).max())
            f_l = ctx.fact(rule, scope, "ndelayed", int(len(late)))
            f_s = ctx.fact(rule, scope, "maxshift", shift, "{:.2f}")
            facts += [f_l, f_s]
            evidence["max_delay"] = shift
            parts.append(
                f"In {{{{{f_l}}}}} of the {{{{{f_n}}}}} study wells it came up {{{{{f_d}}}}} or "
                f"more cycles later (up to {{{{{f_s}}}}}): something in those samples may have "
                "slowed the reaction (inhibition), so the targets measured with it may be "
                "underestimated."
            )
        if len(failed):
            f_f = ctx.fact(rule, scope, "nfailed", int(len(failed)))
            facts.append(f_f)
            parts.append(
                f"In {{{{{f_f}}}}} study wells neither the control nor any target amplified: an "
                "inhibited reaction cannot be told from a negative one there."
            )
        flagged = sorted({*late["key"], *failed["key"]})
        evidence["samples"] = ", ".join(
            dict.fromkeys(str(s) for s in rows.loc[rows["key"].isin(flagged), "sample"])
        )
        yield Finding(
            scope=scope,
            outcome="ipc_delayed" if len(late) else "ipc_failed",
            reason=" ".join([said, *parts]) + extra,
            facts=facts,
            evidence=evidence,
            flagged=flagged,
            options={"exclude_inhibited": flagged},
        )


#: Added to a finding whose options leave out multiplex wells.
MULTIPLEX_OPTION_NOTE = (
    "These wells hold more than one dye (multiplex): leaving a well out leaves out every curve "
    "in it, so each gene keeps the reference measured in the same reaction."
)


def _multiplex_words(ev: RuleEval, ctx: GateContext) -> RuleEval:
    """``ev`` with :data:`MULTIPLEX_OPTION_NOTE` when one of its options leaves out such wells."""
    shared = ctx.multiplex_keys()
    if not shared or not any(shared.intersection(keys) for keys in ev.options.values()):
        return ev
    return ev.model_copy(update={"reason": f"{ev.reason} {MULTIPLEX_OPTION_NOTE}"})


CHECKS: dict[str, Check] = {
    c.name: c
    for c in (
        Check(
            name="typed_controls",
            evaluate=typed_controls,
            outcomes={"typed": "pass", "untyped": "fail", "no_controls_confirmed": "warn"},
        ),
        Check(
            name="ntc_gap",
            evaluate=ntc_gap,
            outcomes={
                "clean": "pass",
                "amplified_clear": "warn",
                "tainted_dimer": "warn",
                "tainted": "fail",
            },
            options=("exclude_flagged",),
        ),
        Check(
            name="nac_amplified",
            evaluate=nac_amplified,
            outcomes={"clean": "pass", "amplified": "fail"},
            options=("exclude_target_plate",),
        ),
        Check(
            name="nrt_gdna",
            evaluate=nrt_gdna,
            outcomes={"grade_a": "pass", "grade_b": "warn", "grade_c": "fail", "grade_f": "fail"},
            options=("exclude_sample_target",),
        ),
        Check(
            name="pos_window", evaluate=pos_window, outcomes={"inside": "pass", "outside": "fail"}
        ),
        Check(
            name="std_curve",
            evaluate=std_curve,
            outcomes={
                "ok": "pass",
                "few_replicates": "warn",
                "efficiency_out": "fail",
                "r2_low": "fail",
            },
        ),
        Check(
            name="replicate_spread",
            evaluate=replicate_spread,
            outcomes={"within": "pass", "outside": "warn", "many_outside": "warn"},
            options=("drop_outlier_well", "drop_sample"),
        ),
        Check(
            name="rt_replicate_spread",
            evaluate=rt_replicate_spread,
            outcomes=RT_OUTCOMES,
            options=("exclude_unit_target", "drop_rt_replicate"),
        ),
        Check(
            name="instrument_run",
            evaluate=instrument_run,
            outcomes=INSTR_OUTCOMES,
            options=("exclude_run",),
        ),
        Check(
            name="melt_products",
            evaluate=melt_products,
            outcomes=MELT_OUTCOMES,
            options=("exclude_flagged",),
        ),
        Check(
            name="ipc_inhibition",
            evaluate=ipc_inhibition,
            outcomes=IPC_OUTCOMES,
            options=("exclude_inhibited",),
        ),
    )
}

OPTION_LABELS = {
    "exclude_flagged": "Leave out the wells this rule flags",
    "exclude_target_plate": "Leave out this target's study wells on this plate",
    "exclude_sample_target": "Leave out this sample for this target",
    "drop_outlier_well": "Leave out the replicate farthest from the others",
    "drop_sample": "Leave out this sample's replicate wells",
    "exclude_unit_target": "Leave out this unit's wells for this target",
    "drop_rt_replicate": "Leave out the reverse-transcription replicate farthest from the others",
    "exclude_run": "Leave out this run's study wells",
    "exclude_inhibited": "Leave out the wells whose internal control suggests inhibition",
}


# ---------- packs ----------


def pack_path(name: str = DEFAULT_PACK) -> Path:
    """The shipped pack file called ``name`` (``packs/<name>.yaml``)."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"not a pack name: {name!r}")
    for directory in PACKS_DIR_CANDIDATES:
        candidate = directory / f"{name}.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no shipped rule pack called {name!r}")


def resolve_pack(pack: RulePack | str | Path | None = None) -> RulePack:
    """A pack object from an object, a shipped name, a ``.yaml`` path or a canonical ``.json``."""
    if isinstance(pack, RulePack):
        return pack
    if pack is None:
        return load_pack(pack_path(DEFAULT_PACK))
    path = Path(pack)
    if path.suffix.lower() in (".yaml", ".yml"):
        return load_pack(path)
    if path.suffix.lower() == ".json":
        return pack_from_json(path.read_text(encoding="utf-8"))
    return load_pack(pack_path(str(pack)))


# ---------- the gate ----------


def evaluate(pack: RulePack, ctx: GateContext) -> list[RuleEval]:
    """Every rule of ``pack`` on ``ctx``: pack order, then plate/target order.

    A finding whose options leave out multiplex wells says that every curve of such a well is
    left out with it (:data:`MULTIPLEX_OPTION_NOTE`).
    """
    return [_multiplex_words(ev, ctx) for ev in evaluate_pack(pack, CHECKS, ctx)]


def plate_status(evals: Collection[RuleEval]) -> dict[str, str]:
    """Plate -> ``gated`` | ``ungated`` from the typed-controls evaluations."""
    out: dict[str, str] = {}
    for ev in evals:
        if ev.check == "typed_controls" and "plate" in ev.scope:
            out[ev.scope["plate"]] = "gated" if ev.outcome == "typed" else "ungated"
    return out


def run_gate(
    curves: pd.DataFrame,
    settings: Any = None,
    pack: RulePack | str | Path | None = None,
    *,
    quantities: Mapping[tuple[str, str], float] | None = None,
    rawness: str | None = None,
    confirmed_no_controls: Collection[str] = (),
    model: Any = None,
    cell: Mapping[str, Any] | None = None,
    runs: Mapping[str, RunFile] | None = None,
    melt: MeltData | None = None,
) -> core_gate.GateReport:
    """Evaluate ``pack`` on a study's wells and run the consequence test on every hit.

    Args:
        curves: The study's per-well table (:func:`qpilot.qpcr.curves.analyse_study`).
        settings: The study's :class:`qpilot.qpcr.study.StudySettings` (default: the demo's).
        pack: A pack, a shipped pack name, or a path (default ``research-default``).
        quantities: ``(sample, target) -> declared quantity`` of the standards (target ``""``
            = every target), e.g. from :func:`study_quantities`.
        rawness: ``capture``'s raw-ness verdict for the input, when known.
        confirmed_no_controls: Plates a person confirmed have no control wells.
        model: The study's :class:`qpilot.qpcr.study.StudyModel` when already built.
        cell: The analysis in use when a person's decisions moved it off the planned one (one
            option per decision-space dimension); every option is then compared at that cell.
        runs: Plate -> its run file (G-INSTR): the study's own (:func:`file_runs`,
            :func:`stored_runs`), the instrument export's (:func:`with_export`), with any a
            person linked on top (:func:`with_linked`); ``None`` when none was read (G-INSTR is
            then not applicable on every plate).
        melt: The study file's melt curves (:func:`qpilot.qpcr.melt.read_melt`) for G-MELT
            and G-NTC-1's class of a control's product; ``None`` or none in the file: G-MELT
            is not applicable and G-NTC-1 says the product is unclassified, as before.

    Returns:
        The report; deterministic for the same inputs.
    """
    from qpilot.qpcr.designs import DesignError, design_curves
    from qpilot.qpcr.study import NGuardError, StudySettings, build_model

    settings = settings or StudySettings()
    rule_pack = resolve_pack(pack)
    table = design_curves(curves, settings.design) if settings.design is not None else curves
    given = dict(quantities or {})
    if is_quantify(settings.design):  # a person's quantities over the file's, as Quantities
        mine = {s: d.quantity for s, d in settings.design.samples.items() if d.quantity}
        given = {k: v for k, v in given.items() if k[0] not in mine}
        given.update({(s, ""): float(q) for s, q in mine.items()})
    ctx = GateContext(
        table=table,
        internal=_left_out_controls(curves, settings.design),
        quantities=given,
        rawness=rawness,
        confirmed_no_controls=frozenset(confirmed_no_controls),
        design=settings.design,
        runs=runs,
        melt=melt,
        melt_params=melt_params(rule_pack),
    )
    evals = evaluate(rule_pack, ctx)
    if is_quantify(settings.design):  # quantify samples: does a sample's reported result change?
        return _quantify_report(rule_pack, ctx, evals, curves, settings, quantities, cell)
    model = model or build_model(curves, settings)
    base = core_gate.baseline(core_gate.at_cell(model.space, cell))
    analysed = set(ctx.table.loc[ctx.table["sample_type"] == ANALYSED, "key"])
    left_out = set()
    if EXCLUDED in ctx.table.columns:
        left_out = set(ctx.table.loc[ctx.table[EXCLUDED].astype(bool), "key"])

    def variant(keys: list[str]) -> Any:
        if left_out.issuperset(keys):
            return core_gate.unchanged("", keys, ALREADY_LEFT_OUT, code="already_left_out")
        if not analysed.intersection(keys):
            return core_gate.unchanged(
                "",
                keys,
                "These wells are not study samples, so no conclusion uses them.",
                code="not_study_samples",
            )
        try:
            return core_gate.at_cell(build_model(curves, settings, extra_excluded=keys).space, cell)
        except (NGuardError, DesignError, ValueError) as err:
            return core_gate.unknown(
                "", keys, f"The analysis cannot be re-run without them: {err}", code="cannot_rerun"
            )

    params = rule_pack.consequence
    done = core_gate.run_consequences(
        evals, base, variant, params.magnitude_log2, params.magnitude_agreement
    )
    headline = [g for g in settings.headline if g in base.items]
    return core_gate.build_report(
        rule_pack.ref(),
        plate_status(evals),
        evals,
        done,
        base,
        ctx.facts.as_dict(),
        OPTION_LABELS,
        headline,
    )


def is_quantify(design: Any) -> bool:
    """A study that quantifies samples (:func:`qpilot.qpcr.quantify_study.is_quantify`)."""
    from qpilot.qpcr.quantify_study import is_quantify as quantify

    return quantify(design)


def _quantify_report(
    rule_pack: RulePack,
    ctx: GateContext,
    evals: list[RuleEval],
    curves: pd.DataFrame,
    settings: Any,
    quantities: Mapping[tuple[str, str], float] | None,
    cell: Mapping[str, Any] | None,
) -> core_gate.GateReport:
    """The consequence test of a study that quantifies samples (no groups compared).

    Every rule runs as for any study. For each flagged set of wells the study is quantified
    again without them, at the analysis in use (``cell``: the amplification rule and the LOQ
    line a person chose on the quantity cards), and each sample result is compared: ``flip``
    when its class or its number (more than 2-fold) changes
    (:func:`qpilot.qpcr.quantify_study.gate_compare`). Standards count as well as study
    samples: leaving a standard out moves the curve, so every quantity read from it.
    """
    from qpilot.qpcr import quantify_study as qs
    from qpilot.qpcr.designs import design_units

    design = settings.design
    given = design.reaction_input
    inputs = qs.Inputs(
        table=ctx.table,
        quantities={s: d.quantity for s, d in design.samples.items() if d.quantity},
        declared={k: (float(v), "") for k, v in (quantities or {}).items()},
        units=design_units(design) or None,
        calls=dict(design.well_calls) or None,
        reaction=qs.ab.ReactionInputs(given.template_ul, given.input_ng, given.unit)
        if given
        else None,
        amp_calls=tuple(design.amp_calls),
    )
    amp = str((cell or {}).get("amp_call") or design.amp_calls[0])
    loq = str((cell or {}).get("loq_cv") or qs.LOQ_OPTIONS[0])
    items = qs.reported(inputs.at(amp, loq))
    base = qs.gate_baseline(items)
    used = set(ctx.table.loc[ctx.table["sample_type"].isin([ANALYSED, "std"]), "key"])
    left_out = set()
    if EXCLUDED in ctx.table.columns:
        left_out = set(ctx.table.loc[ctx.table[EXCLUDED].astype(bool), "key"])
    params = rule_pack.consequence

    def variant(keys: list[str]) -> Any:
        if left_out.issuperset(keys):
            return core_gate.unchanged("", keys, ALREADY_LEFT_OUT, code="already_left_out")
        if not used.intersection(keys):
            return core_gate.unchanged(
                "",
                keys,
                "These wells are neither samples nor standards, so no quantity uses them.",
                code="not_study_samples",
            )
        found = qs.reported(inputs.without(keys).at(amp, loq))
        return qs.gate_compare("", keys, items, found, params.magnitude_log2)

    done = core_gate.run_consequences(
        evals, base, variant, params.magnitude_log2, params.magnitude_agreement
    )
    return core_gate.build_report(
        rule_pack.ref(),
        plate_status(evals),
        evals,
        done,
        base,
        ctx.facts.as_dict(),
        OPTION_LABELS,
        [],
    )


def _left_out_controls(curves: pd.DataFrame, design: Any) -> pd.DataFrame | None:
    """The curves of internal positive controls the design leaves out of the analysis (G-IPC).

    A person may leave an IPC out of the study (role ``ignore``: it is not a gene to compare),
    and the engine then never sees it; G-IPC still reads its curves, typed as the design types
    the wells. ``None`` when the design leaves no such control out.
    """
    from qpilot.qpcr.designs import design_curves

    if design is None:
        return None
    ignored = {
        t
        for t, d in design.targets.items()
        if d.role == "ignore" and mx.is_internal_control_name(t)
    }
    if not ignored:
        return None
    targets = {t: d for t, d in design.targets.items() if t not in ignored}
    kept = design_curves(curves, design.model_copy(update={"targets": targets}))
    rows = kept[kept["target"].isin(ignored)]
    return rows if not rows.empty else None


def melt_params(pack: RulePack) -> MeltParams:
    """The pack's G-MELT thresholds (the defaults when the pack has no enabled G-MELT rule)."""
    for rule in pack.rules:
        if rule.check == "melt_products" and rule.enabled:
            return MeltParams.from_rule(rule.params)
    return MeltParams()


def file_melt(rdml_path: str | Path, experiment_id: str | None = None) -> MeltData | None:
    """The file's melt curves for the gate (``None`` when they cannot be read)."""
    from qpilot.qpcr.melt import MeltError, read_melt

    try:
        return read_melt(rdml_path, experiment_id)
    except (MeltError, OSError, ValueError):
        return None


def study_quantities(rdml_path: str | Path) -> dict[tuple[str, str], float]:
    """Declared quantities of the file's samples: ``(sample, target) -> value``."""
    from qpilot.qpcr.inspect import file_facts

    facts = file_facts(rdml_path)
    out: dict[tuple[str, str], float] = {}
    for sample, entries in facts.sample_quantities.items():
        for value, _unit, target in entries:
            out.setdefault((sample, target), float(value))
    return out


def gate_file(
    rdml_path: str | Path,
    settings: Any = None,
    pack: RulePack | str | Path | None = None,
    *,
    cache_dir: str | Path | None = None,
    rawness: str | None = None,
    confirmed_no_controls: Collection[str] = (),
) -> core_gate.GateReport:
    """:func:`run_gate` on an RDML file with the study's settings (curves from the cache).

    G-INSTR reads the file's own runs (:func:`file_runs`: the instrument and the run date),
    G-MELT the file's melt curves (:func:`file_melt`).
    """
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.study import StudySettings

    settings = settings or StudySettings()
    curves = analyse_study(
        rdml_path, settings.experiment_id, settings.candidates, settings.curves, cache_dir=cache_dir
    )
    quantities = study_quantities(rdml_path) if (curves["sample_type"] == "std").any() else {}
    return run_gate(
        curves,
        settings,
        pack,
        quantities=quantities,
        rawness=rawness,
        confirmed_no_controls=confirmed_no_controls,
        runs=file_runs(rdml_path),
        melt=file_melt(rdml_path, settings.experiment_id),
    )
