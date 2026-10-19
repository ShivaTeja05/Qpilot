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
(G-NAC), ``nrt_gdna`` (G-NRT), ``pos_window`` (G-POS), ``std_curve`` (G-STD) and
``replicate_spread`` (G-REP). Rules label; they never drop a well. What leaving wells out would
do is the consequence test (:func:`run_gate`).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from qpilot.core.facts import FactRegistry
from qpilot.core.rules import (
    NOT_APPLICABLE,
    Check,
    Finding,
    Rule,
    RuleEval,
    RulePack,
    evaluate_pack,
    load_pack,
    pack_from_json,
)
from qpilot.schemas import Fact

CONTROL_TYPES = frozenset({"ntc", "nac", "ntp", "nrt", "pos", "std"})
ANALYSED = "unkn"
PACKS_DIR_CANDIDATES = (
    Path(__file__).resolve().parents[1] / "_packs",  # wheel (force-included)
    Path(__file__).resolve().parents[2] / "packs",  # source checkout
)
DEFAULT_PACK = "research-default"


# ---------- context ----------


@dataclass
class GateContext:
    """What the evaluators read. ``facts`` collects every number they show."""

    table: pd.DataFrame
    quantities: Mapping[tuple[str, str], float] = field(default_factory=dict)
    rawness: str | None = None
    confirmed_no_controls: frozenset[str] = frozenset()
    facts: FactRegistry = field(default_factory=FactRegistry)
    _std_fits: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        t = self.table
        self.table = t.assign(
            key=t["run_id"] + "/" + t["well"],
            amplified=t["amplification"].astype(bool) & t["cq"].notna(),
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
        if not detected.empty:
            gap = cq_ntc - float(detected["cq"].min())
            facts.append(ctx.fact(rule, scope, "gap", gap, "{:.2f}"))
            evidence["gap_to_lowest_unknown"] = gap
        if tainted.empty:
            yield Finding(
                scope=scope,
                outcome="amplified_clear",
                reason=(
                    f"{{{{{n_amp}}}}} of {{{{{n_ntc}}}}} no-template wells amplified, the "
                    f"earliest at Cq {{{{{f_cq}}}}}; every study sample amplified at least "
                    f"{{{{{f_k}}}}} cycles earlier."
                ),
                facts=facts,
                evidence=evidence,
            )
            continue
        fraction = float(np.max(eff ** -(cq_ntc - tainted["cq"].to_numpy(dtype=float))))
        f_n = ctx.fact(rule, scope, "ntainted", int(len(tainted)))
        f_frac = ctx.fact(rule, scope, "contamfrac", fraction * 100, "{:.1f}", "%")
        evidence.update(n_tainted=int(len(tainted)), max_contaminant_fraction=fraction)
        yield Finding(
            scope=scope,
            outcome="tainted",
            reason=(
                f"{{{{{n_amp}}}}} of {{{{{n_ntc}}}}} no-template wells amplified, the earliest at "
                f"Cq {{{{{f_cq}}}}}. {{{{{f_n}}}}} study wells amplified less than {{{{{f_k}}}}} "
                f"cycles before it, so their positive call and quantity are in doubt (MIQE 2.0). "
                f"If the control's signal were template, it could be up to {{{{{f_frac}}}}} of "
                "theirs. Without melt data the control's product is unclassified (contamination "
                "or primer-dimer) and is treated as possible contamination."
            ),
            facts=[*facts, f_n, f_frac],
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
        pooled = not any(s in by_sample for s in nrt["sample"])
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
            f_s = ctx.fact(rule, scope, "gdna", share * 100, "{:.1f}", "%")
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
        if pos["amplified"].any():
            facts.append(ctx.fact(rule, scope, "cqpos", float(pos["cq"].min()), "{:.2f}"))
        yield Finding(
            scope=scope,
            outcome=NOT_APPLICABLE,
            code="pos_unmapped",
            reason="The positive control is not mapped to a control and a Cq window yet.",
            facts=facts,
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
            "e": ctx.fact(rule, scope, "estd", pct, "{:.1f}", "%"),
            "lo": ctx.fact(rule, scope, "estdlo", (fit["e_low"] - 1) * 100, "{:.1f}", "%"),
            "hi": ctx.fact(rule, scope, "estdhi", (fit["e_high"] - 1) * 100, "{:.1f}", "%"),
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
            f_w = ctx.fact(rule, scope, "ewells", fit["eff_wells"], "{:.3f}")
            f_g = ctx.fact(rule, scope, "egap", gap, "{:.3f}")
            facts += [f_w, f_g]
            evidence.update(eff_per_well_mean=fit["eff_wells"], eff_gap=gap)
            sentences.append(
                f"The same wells' own mean efficiency is {{{{{f_w}}}}} (amplification factor; "
                "the gap is evidence, not a failure)."
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
        yield Finding(
            scope=scope, outcome=outcome, reason=" ".join(sentences), facts=facts, evidence=evidence
        )


# ---------- G-REP ----------

_Q95 = {2: 2.772, 3: 3.314, 4: 3.633, 5: 3.858, 6: 4.030}


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
            f_s = ctx.fact(rule, scope, "share", flagged_groups / evaluated * 100, "{:.0f}", "%")
            yield Finding(
                scope=scope,
                outcome="many_outside",
                reason=(
                    f"{{{{{f_s}}}}} of replicate groups here are outside their expected range: a "
                    "systematic workflow problem is more likely than single bad wells."
                ),
                facts=[f_s],
            )


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
    )
}

OPTION_LABELS = {
    "exclude_flagged": "Leave out the wells this rule flags",
    "exclude_target_plate": "Leave out this target's study wells on this plate",
    "exclude_sample_target": "Leave out this sample for this target",
    "drop_outlier_well": "Leave out the replicate farthest from the others",
    "drop_sample": "Leave out this sample's replicate wells",
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
