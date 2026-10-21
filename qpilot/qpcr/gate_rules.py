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
and the instrument, the lines of :mod:`qpilot.qpcr.gate_instr`, read from the study's own file
or from a run file a person linked to the plate). Rules label; they never drop a well. What
leaving wells out would do is the consequence test (:func:`run_gate`).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
from qpilot.qpcr.gate_instr import DEFAULT_HOLD_LIMIT_C
from qpilot.qpcr.gate_rt import RT_RANGE_LIMIT
from qpilot.qpcr.instrument_context import RunContext
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


@dataclass(frozen=True)
class RunFile:
    """What one plate's run file says (G-INSTR), and where qPilot read it.

    ``linked`` is True for a run file a person linked to the plate (an ``.eds`` or an export
    the instrument wrote), False for the study's own file (RDML: the instrument and the run date
    at most). ``study_date`` is the plate's run date in the study's own file, when known, so a
    linked file whose run date differs is said. A linked file that cannot be read has no
    ``context`` and says why (``problem``: ``missing``, ``changed`` or ``unreadable``).
    """

    context: RunContext | None
    linked: bool = False
    study_date: str | None = None
    problem: str = ""


@dataclass
class GateContext:
    """What the evaluators read. ``facts`` collects every number they show.

    ``design`` is the confirmed design (its ``rt_replicate`` labels, for G-RT); ``runs`` maps a
    plate to its :class:`RunFile` (for G-INSTR), ``None`` when no run context was given.
    """

    table: pd.DataFrame
    quantities: Mapping[tuple[str, str], float] = field(default_factory=dict)
    rawness: str | None = None
    confirmed_no_controls: frozenset[str] = frozenset()
    design: Any = None
    runs: Mapping[str, RunFile] | None = None
    facts: FactRegistry = field(default_factory=FactRegistry)
    _std_fits: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        t = self.table
        self.table = t.assign(
            key=t["run_id"] + "/" + t["well"],
            amplified=t["amplification"].eq(True) & t["cq"].notna(),
        )

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
    for plate, target, rows in ctx.plate_targets():
        if plate in untyped:
            continue
        scope = {"plate": plate, "target": target}
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
        if tainted.empty:
            earliest = (
                f" (the earliest {{{{{f_gap}}}}} cycles before it)" if f_gap is not None else ""
            )
            yield Finding(
                scope=scope,
                outcome="amplified_clear",
                reason=(
                    f"{{{{{n_amp}}}}} of {{{{{n_ntc}}}}} no-template wells amplified, the "
                    f"earliest at Cq {{{{{f_cq}}}}}; every study sample amplified at least "
                    f"{{{{{f_k}}}}} cycles earlier{earliest}."
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
        yield Finding(
            scope=scope,
            outcome="tainted",
            reason=(
                f"{{{{{n_amp}}}}} of {{{{{n_ntc}}}}} no-template wells amplified, the earliest at "
                f"Cq {{{{{f_cq}}}}}. {{{{{f_n}}}}} {wells} amplified less than {{{{{f_k}}}}} "
                f"cycles before it, so {its} positive call and quantity are in doubt (MIQE 2.0). "
                f"{share} Without melt data the control's product is unclassified (contamination "
                "or primer-dimer) and is treated as possible contamination."
            ),
            facts=[*facts, f_n, *shown],
            evidence=evidence,
            flagged=sorted(tainted["key"]),
            options={"exclude_flagged": sorted(tainted["key"])},
        )


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
        sentences.append(
            "In relative quantification this does not taint study samples; it marks the curve as "
            "an efficiency source."
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
            median = float(np.median(cqs))
            far = amp.iloc[int(np.argmax(np.abs(cqs - median)))]["key"]
            options = {"drop_outlier_well": [far], "drop_sample": sorted(g["key"])}
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
                flagged=[far] if outside else [],
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


def instrument_run(rule: Rule, ctx: GateContext) -> Iterator[Finding]:
    """What each plate's run file says about the run and the instrument (G-INSTR).

    The lines are :func:`qpilot.qpcr.gate_instr.g_instr`'s, worded by
    :mod:`qpilot.explain.instrument_text`; each number they cite is registered again as this
    rule's fact (serials and instrument names never are: G-INSTR leaves them out). The verdict
    is the worst line's under the pack's severity; a warning or a failure points at the run's
    study wells, and the consequence test leaves them out.
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
    source = (
        "From the run file a person linked to this plate:"
        if found.linked
        else "From the study's file:"
    )
    evidence: dict[str, Any] = {
        "source": "linked run file" if found.linked else "study file",
        "source_kind": run.source_kind,
        "run_state": run.run.get("state"),
        "cycles": ",".join(str(c) for c in cycles),
    }
    if worst is None:
        codes = {line.code for line in lines}
        which = "The run file a person linked to this plate" if found.linked else "The study's file"
        said = [f"{which} {t[9:]}" if t.startswith("The file ") else t for t in sentences]
        hint = [] if found.linked else [RDML_SAYS_LITTLE]
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
        reason=" ".join([source, *sentences]),
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


def with_linked(
    own: Mapping[str, RunFile],
    linked: Mapping[str, RunContext],
    problems: Mapping[str, str] | None = None,
) -> dict[str, RunFile]:
    """The study's own run files, with the run files a person linked in their plates' place.

    ``problems`` names the plates whose linked file cannot be read (``missing``, ``changed``,
    ``unreadable``): G-INSTR says so for them instead of reading the study's own file.
    """
    out = dict(own)
    for plate, context in linked.items():
        mine = own.get(plate)
        day = mine.context.run.get("date") if mine is not None and mine.context else None
        out[plate] = RunFile(context=context, linked=True, study_date=str(day) if day else None)
    for plate, problem in (problems or {}).items():
        out[plate] = RunFile(context=None, linked=True, problem=str(problem))
    return out


# ---------- registry ----------

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
    """Every rule of ``pack`` on ``ctx``: pack order, then plate/target order."""
    return evaluate_pack(pack, CHECKS, ctx)


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
            :func:`stored_runs`), with any a person linked (:func:`with_linked`); ``None``
            when none was read (G-INSTR is then not applicable on every plate).

    Returns:
        The report; deterministic for the same inputs.
    """
    from qpilot.qpcr.designs import DesignError, design_curves
    from qpilot.qpcr.study import NGuardError, StudySettings, build_model

    settings = settings or StudySettings()
    rule_pack = resolve_pack(pack)
    table = design_curves(curves, settings.design) if settings.design is not None else curves
    ctx = GateContext(
        table=table,
        quantities=dict(quantities or {}),
        rawness=rawness,
        confirmed_no_controls=frozenset(confirmed_no_controls),
        design=settings.design,
        runs=runs,
    )
    evals = evaluate(rule_pack, ctx)
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

    G-INSTR reads the file's own runs (:func:`file_runs`: the instrument and the run date).
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
    )
