"""Live engine views behind the results screen's charts and lab panels.

Everything here is computed by the engine while the page is open, or read from the run's files:

* every reasonable analysis of one gene (the same 144 cells the run's verdicts use);
* one choice at a time: each option of each decision with every other choice as planned;
* each sample's normalised value under any set of choices, with its plate, well and Cq;
* the assay's lab parameters (Cq spread, late and missing Cq, efficiency, flagged wells);
* the study views (map of all genes, which choices matter, reference stability, validation).

Numbers are returned with their formatting done here, so the page never types one.
"""

from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from qsim.decisions import PLAIN
from qsim.engine import CALL_NAMES
from qsim.issues import HEADLINE
from qsim.report import _defensible

# the pipeline in lab order; each stage names the decisions the simulator varies there
STAGES = (
    (
        "Curves to quantities",
        "Each well's curve gives a Cq and an amplification efficiency.",
        ("efficiency",),
    ),
    (
        "Which wells count",
        "Wells that were flagged, amplified very late or never amplified.",
        ("flagged", "late_cq", "nondetect"),
    ),
    ("Normalise", "Each sample is divided by the average of its reference genes.", ("refs",)),
    ("Define the groups", "Samples are split into the high group and the rest.", ("cut",)),
    ("Compare the groups", "A two-group test gives a p-value for each gene.", ("test",)),
    (
        "Many genes at once",
        "The p-values may be corrected for testing many genes.",
        ("multiplicity",),
    ),
)


def _fold(fold: float) -> str:
    return f"{fold:.2f}× higher" if fold >= 1 else f"{1 / fold:.2f}× lower"


def _pct(share: float) -> int:
    return int(round(100 * float(share)))


class LabViews:
    """Mixed into :class:`qsim.app.Screen`; needs ``engine``, ``space``, ``explain``, ``summary``."""

    _reasonable_cache = None
    _single_cache: dict | None = None

    # ---- cached engine sweeps -------------------------------------------------------------
    def reasonable(self):
        """The reasonable analyses (planned question, no shortcuts), evaluated live once."""
        with self._engine_lock:
            if self._reasonable_cache is None:
                allowed = _defensible(self.space)
                cells = list(itertools.product(*[allowed[n] for n in self.space.names]))
                runs = [self.engine.evaluate(c) for c in cells]
                self._reasonable_cache = (
                    cells,
                    np.array([r["log2fc"] for r in runs]),
                    np.array([r["call"] for r in runs]),
                )
        return self._reasonable_cache

    def _single(self, decision: str, option: str):
        with self._engine_lock:
            if self._single_cache is None:
                self._single_cache = {}
            key = (decision, option)
            if key not in self._single_cache:
                r = self.engine.evaluate(self.space.to_index({decision: option}))
                self._single_cache[key] = (r["log2fc"].copy(), r["call"].copy())
        return self._single_cache[key]

    def _base(self):
        return self._single(self.space.names[0], self.space.baseline[self.space.names[0]])

    def _scale(self) -> dict:
        return {"line_log2": self.engine.rule.min_log2fc, "line": f"{self.line:g}×"}

    # ---- gene charts ----------------------------------------------------------------------
    def gene_analyses(self, gene: str) -> dict:
        cells, lfc, call = self.reasonable()
        i = self.engine.items.index(gene)
        base = self.space.baseline_index()
        base_call = self._base()[1][i]
        rows = []
        for k, cell in enumerate(cells):
            changed = [
                self.space.decisions[j].options[o].label for j, o in enumerate(cell) if o != base[j]
            ]
            rows.append(
                {
                    "log2": float(lfc[k, i]),
                    "fold": _fold(2 ** float(lfc[k, i])),
                    "call": self.call_words(CALL_NAMES[int(call[k, i])]),
                    "same": bool(call[k, i] == base_call),
                    "choices": changed,
                    "planned": not changed,
                }
            )
        same = sum(r["same"] for r in rows)
        return {
            "gene": gene,
            "rows": rows,
            "n": len(rows),
            "n_same": same,
            "n_other": len(rows) - same,
            "base_call": self.call_words(CALL_NAMES[int(base_call)]),
            **self._scale(),
        }

    def gene_effects(self, gene: str) -> dict:
        i = self.engine.items.index(gene)
        base_log2, base_call = self._base()
        out = []
        for d in self.space.decisions:
            opts = []
            for o in d.options:
                lfc, call = self._single(d.id, o.id)
                opts.append(
                    {
                        "label": o.label,
                        "tier": o.tier,
                        "log2": float(lfc[i]),
                        "fold": _fold(2 ** float(lfc[i])),
                        "call": self.call_words(CALL_NAMES[int(call[i])]),
                        "changes_call": bool(call[i] != base_call[i]),
                        "planned": o.id == self.space.baseline[d.id],
                    }
                )
            out.append(
                {
                    "id": d.id,
                    "name": PLAIN[d.id][0].upper() + PLAIN[d.id][1:],
                    "options": opts,
                    "n_change": sum(o["changes_call"] for o in opts),
                }
            )
        return {
            "gene": gene,
            "planned_log2": float(base_log2[i]),
            "planned": _fold(2 ** float(base_log2[i])),
            "decisions": out,
            **self._scale(),
        }

    def gene_samples(self, gene: str, changes: dict[str, str] | None = None) -> dict:
        changes = {d: o for d, o in (changes or {}).items() if self.space.baseline.get(d) != o}
        cell = self.space.to_index(changes)
        e, s = self.engine, self.engine.study
        v, ids = e.values_of(cell), e.ids_of(cell)
        with self._engine_lock:
            matrix = e.matrix(v["efficiency"], v["flagged"], v["nondetect"], late=v.get("late_cq"))
            rel, valid = e.relative(matrix, ids["refs"])
        i = e.items.index(gene)
        col = s.genes.index(gene)
        high, rest = s.group_masks(v["cut"])
        x, ok = rel[:, i], valid[:, i]
        rest_mean = float(np.mean(x[ok & rest]))
        high_mean = float(np.mean(x[ok & high]))
        late = min(o.value for o in self.space.decision("late_cq").options if o.value is not None)
        singles = {r["sample"] for r in self._singles(gene)}
        points = []
        for k in np.flatnonzero(ok & (high | rest)):
            cq = s.cq[k, col]
            points.append(
                {
                    "x": float(x[k] - rest_mean),
                    "group": "high" if high[k] else "rest",
                    "sample": s.samples[k],
                    "plate": str(s.run[k, col]),
                    "well": str(s.well[k, col]),
                    "cq": None if np.isnan(cq) else f"{cq:.1f}",
                    "late": bool(not np.isnan(cq) and cq > late),
                    "nondetect": bool(np.isnan(cq)),
                    "flagged": bool(s.flag_eff[k, col] or s.flag_low[k, col]),
                    "carries": s.samples[k] in singles,
                    "value": _fold(2 ** float(x[k] - rest_mean)),
                }
            )
        labels = [
            self.space.decision(d).options[self.space.decision(d).index(o)].label
            for d, o in changes.items()
        ]
        return {
            "gene": gene,
            "points": points,
            "groups": {
                "high": {
                    "label": f"{self.group} ({self._cut_label(v['cut'])})",
                    "n": int((ok & high).sum()),
                    "missing": int((~ok & high).sum()),
                    "mean": high_mean - rest_mean,
                },
                "rest": {
                    "label": "the rest",
                    "n": int((ok & rest).sum()),
                    "missing": int((~ok & rest).sum()),
                    "mean": 0.0,
                },
            },
            "fold": _fold(2 ** (high_mean - rest_mean)),
            "fold_log2": high_mean - rest_mean,
            "late_cut": f"{late:g}",
            "changes": labels,
            **self._scale(),
        }

    def _cut_label(self, value) -> str:
        return next(o.label for o in self.space.decision("cut").options if o.value == value)

    def lab_parameters(self, gene: str) -> dict:
        s = self.engine.study
        col = s.genes.index(gene)
        e = self.explain[gene]
        cq = s.cq[:, col]
        found = cq[~np.isnan(cq)]
        lates = [o.value for o in self.space.decision("late_cq").options if o.value is not None]
        eff = np.nanmedian(s.eff_assay[:, col])
        std = s.eff_std[:, col]
        high, rest = s.group_masks(dict(self.engine.values_of(self.space.baseline_index()))["cut"])
        refs = self.space.decision("refs")
        planned_refs = refs.options[refs.index(self.space.baseline["refs"])]
        m_values = self.summary["space_rules"]["geNorm_M"]
        implicated = set(self.summary["space_rules"]["implicated_genes"])
        rows = [
            ("Samples in each group", f"{int(high.sum())} {self.group} · {int(rest.sum())} rest"),
            ("Plates for this assay", f"{len(set(s.run[:, col]))}"),
            (
                "Cq, median (lowest to highest)",
                f"{np.median(found):.1f} ({found.min():.1f} to {found.max():.1f})"
                if found.size
                else "no Cq",
            ),
        ]
        for cut in lates:
            rows.append((f"Wells with Cq above {cut:g}", f"{int((found > cut).sum())}"))
        rows += [
            ("Wells that never amplified", f"{int(np.isnan(cq).sum())}"),
            ("Efficiency, LinRegPCR assay mean", f"{eff:.2f} ({_pct(eff - 1)} % per cycle)"),
            (
                "Efficiency, plate standard curve",
                f"{np.nanmedian(std):.2f} ({_pct(np.nanmedian(std) - 1)} % per cycle)"
                if np.isfinite(std).any()
                else "no standard curve on this plate",
            ),
            ("Wells flagged for efficiency", f"{int(s.flag_eff[:, col].sum())}"),
            ("Wells flagged as very low copy number", f"{int(s.flag_low[:, col].sum())}"),
            ("p-value, planned analysis", f"{e['p']:.2g}"),
        ]
        references = [
            {
                "gene": g,
                "m": f"{m_values[g]:.2f}" if g in m_values else "",
                "differs": g in implicated or g.split("(")[0] in implicated,
            }
            for g in planned_refs.value
        ]
        return {
            "gene": gene,
            "rows": [{"label": a, "value": b} for a, b in rows],
            "references": references,
            "refs_label": planned_refs.label,
            "stable_below": f"{self.summary['space_rules']['stable_below_M']:g}",
        }

    # ---- study views ------------------------------------------------------------------------
    def study_view(self) -> dict:
        decisions = pd.read_csv(self.dir / "decisions.csv").set_index("decision")
        rules = self.summary["space_rules"]
        implicated = set(rules["implicated_genes"])
        lock = self.summary.get("lock_advisor", {})
        infl = self.summary.get("influence", {})
        return {
            "map": [
                {
                    "gene": g,
                    "log2": e["log2fc"],
                    "fold": e["fold_words"],
                    "holds": _pct(e["holds_defensible"]),
                    "verdict": e["verdict"],
                    "headline": g in HEADLINE,
                }
                for g, e in self.explain.items()
            ],
            "choices": [
                {
                    "id": d,
                    "name": PLAIN[d][0].upper() + PLAIN[d][1:],
                    "alone": int(decisions.loc[d, "genes_flipped_alone"]),
                    "spread": _pct(decisions.loc[d, "variance_share_defensible"]),
                    "question": self.space.decision(d).role == "question",
                }
                for d in self.space.names
                if d in decisions.index
            ],
            "references": [
                {
                    "gene": g,
                    "m": f"{m:.2f}",
                    "differs": g in implicated or g.split("(")[0] in implicated,
                }
                for g, m in sorted(rules["geNorm_M"].items(), key=lambda kv: kv[1])
            ],
            "stable_below": f"{rules['stable_below_M']:g}",
            "reference_note": "; ".join(rules.get("notes", [])),
            "lock_headline": [PLAIN[d] for d in lock.get("headline_all", [])],
            "lock_called": [PLAIN[d] for d in lock.get("called_defensible", [])],
            "influence": {
                "one_sample_genes": infl.get("genes_flipped_by_one_sample"),
                "ref_removals": f"{infl.get('reference_well_removals', 0):,}",
                "ref_removals_flip": infl.get("reference_well_removals_that_flip"),
            },
            **self._scale(),
        }

    def how_view(self) -> dict:
        ledger = self.summary["ledger"]
        decisions = pd.read_csv(self.dir / "decisions.csv").set_index("decision")
        stages = []
        for title, text, ids in STAGES:
            items = []
            for d in ids:
                dec = self.space.decision(d)
                tiers = [o.tier for o in dec.options]
                items.append(
                    {
                        "name": PLAIN[d][0].upper() + PLAIN[d][1:],
                        "question": dec.question,
                        "planned": dec.options[dec.index(self.space.baseline[d])].label,
                        "n_options": len(dec.options),
                        "n_reasonable": tiers.count("defensible"),
                        "n_shortcut": tiers.count("common_practice"),
                        "alone": int(decisions.loc[d, "genes_flipped_alone"])
                        if d in decisions.index
                        else None,
                        "changes_question": dec.role == "question",
                        "options": [{"label": o.label, "tier": o.tier} for o in dec.options[:8]],
                        "more": max(0, len(dec.options) - 8),
                    }
                )
            stages.append({"title": title, "text": text, "decisions": items})
        out = {
            "stages": stages,
            "call_rule": (
                f"A change is called when it is at least {self.line:g}× and the p-value is below "
                f"{self.alpha:g}."
            ),
            "total": f"{ledger['total_cells']:,}",
            "reasonable": len(self.reasonable()[0]),
            "seconds": f"{self.summary.get('timings_s', {}).get('full_grid_s', 0):.0f}",
            "rules": self.verdict_rules(),
        }
        bench = self.summary.get("benchmark_pooled")
        if bench:
            out["faults"] = {
                "trials": bench["trials"],
                "changed": bench["trials_changing_a_call"],
                "caught": bench["detected_when_a_call_changed"],
            }
        designs = self.summary.get("designs", {}).get("sizes", {})
        out["small"] = [
            {
                "size": size,
                "single": f"{100 * v['no_difference']['false_call_rate_single_analysis']:.1f}",
                "filtered": f"{100 * v['no_difference']['false_call_rate_after_robust_filter']:.1f}",
            }
            for size, v in designs.items()
        ]
        val = self.dir / "validation_untergasser.json"
        if val.exists():
            v = json.loads(val.read_text())
            eff = self.space.decision("efficiency")
            labels = {o.id: o.label for o in eff.options}
            out["known"] = {
                "dataset": v["dataset"],
                "cases": v["cases"],
                "efficiency": [
                    {
                        "label": labels.get(k, k),
                        "error": r["median_abs_error_pct"],
                        "error_text": f"{r['median_abs_error_pct']:g} %",
                        "planned": k == self.space.baseline["efficiency"],
                    }
                    for k, r in sorted(
                        v["by_choice"]["efficiency"].items(),
                        key=lambda kv: kv[1]["median_abs_error_pct"],
                    )
                ],
                "spread_warns": {
                    "top": f"{v['warning']['baseline_median_abs_error_pct_when_spread_in_top_quarter']:g}",
                    "other": f"{v['warning']['baseline_median_abs_error_pct_otherwise']:g}",
                },
                "inside_range": _pct(v["coverage"]["truth_inside_range_of_defensible_analyses"]),
                "inside_ci": _pct(v["coverage"]["truth_inside_baseline_95ci"]),
            }
        return out
