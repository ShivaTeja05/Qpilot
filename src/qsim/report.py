"""Run everything on one study and write the results folder plus a plain-language REPORT.md."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd
import qpilot
import scipy

from qsim import __version__, explore, inference, influence
from qsim.attribution import Factorial
from qsim.benchmark import run_benchmark
from qsim.data import BENCHMARK_NAME, Study, load_study
from qsim.decisions import Space
from qsim.engine import Engine, Grid
from qsim.issues import HEADLINE, build_queue, queue_frame
from qsim.study_space import space_for
from qsim.troubleshoot import run_detectors
from qsim.verdict import ORDER, RULES, explain, verdicts


def _defensible(space: Space) -> dict[str, list[int]]:
    base = space.baseline_index()
    return {
        d.id: (
            [i for i, o in enumerate(d.options) if o.tier != "common_practice"]
            if d.role == "analysis"
            else [base[k]]  # a question choice (the cut-off) is reported separately
        )
        for k, d in enumerate(space.decisions)
    }


def _grid_hash(grid: Grid) -> str:
    h = hashlib.sha256()
    for a in (grid.index, grid.log2fc, grid.p, grid.call):
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()[:16]


def explorer_check(engine: Engine, truth: Factorial) -> list[dict]:
    """How much of the exhaustive truth each cheaper strategy recovers."""
    space = engine.space
    flipping = set(np.array(engine.items)[truth.fragility() > 0])
    base_call = truth.base_call
    out = []
    plans = [
        ("rings <= 1", explore.rings(space, 1), {}),
        ("rings <= 2", explore.rings(space, 2), {}),
        ("covering array t=2", explore.covering_array(space, 2, seed=1), {"seed": 1}),
        ("covering array t=3", explore.covering_array(space, 3, seed=1), {"seed": 1}),
        ("Morris, 20 trajectories", np.concatenate(explore.morris(space, 20, seed=1)), {"seed": 1}),
        ("random, 500 cells", explore.random_cells(space, 500, seed=1), {"seed": 1}),
    ]
    for name, cells, seeds in plans:
        cells = np.unique(cells, axis=0)
        g = engine.run(cells)
        found = set(np.array(engine.items)[(g.call != base_call[None, :]).any(axis=0)])
        out.append(
            {
                "strategy": name,
                "runs": int(len(cells)),
                "share_of_space": len(cells) / truth.n_cells,
                "genes_with_a_flip_found": len(found & flipping),
                "genes_with_a_flip_total": len(flipping),
                "pairwise_coverage": explore.coverage(space, cells, 2),
                **seeds,
            }
        )
    return out


def run_all(
    rdml: str | None = None,
    out: str | Path = "results",
    permutations: int = 999,
    bench_trials: int = 20,
    seed: int = 2026,
    design_draws: int = 100,
    explorer: bool = True,
    source: str | None = None,
) -> dict:
    """Run every analysis of one RDML file and write the results folder.

    ``explorer`` runs the cheaper-search check; ``source`` names the file on the results screen
    (default: the file name, or the benchmark's name when no file is given).
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    study: Study = load_study(rdml)
    space, space_info = space_for(study)
    engine = Engine(study, space)
    timings["load_s"] = time.perf_counter() - t0

    # lock the prespecified analysis and the tier rules before any alternative is computed
    lock = {
        "input_sha256": study.input_sha256,
        "baseline": space.baseline,
        "tiers": {d.id: {o.id: o.tier for o in d.options} for d in space.decisions},
        "roles": {d.id: d.role for d in space.decisions},
        "rule": {"alpha": engine.rule.alpha, "min_log2fc": engine.rule.min_log2fc},
        "qsim_version": __version__,
    }
    lock_hash = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
    (out / "lock.json").write_text(json.dumps({**lock, "sha256": lock_hash}, indent=1))
    t = time.perf_counter()
    grid = engine.run(explore.full(space))
    timings["full_grid_s"] = time.perf_counter() - t
    led = explore.ledger(space, grid.index, "full")
    grid.to_frame().to_parquet(out / "grid.parquet", index=False)

    allf = Factorial(grid)
    defn = Factorial(grid, _defensible(space))
    genes = (
        allf.gene_table()
        .add_prefix("all_")
        .join(
            defn.gene_table()[
                ["holds", "fragility", "flipped_by_one", "interaction_only"]
            ].add_prefix("defensible_")
        )
    )

    t = time.perf_counter()
    base = influence.Baseline(engine)
    loo = influence.leave_one_out(engine, base)
    refw = influence.reference_wells(engine, base)
    marg = influence.margins(engine, base).set_index("gene")
    called = [g for g, c in zip(engine.items, base.call, strict=True) if c != 0]
    dk = pd.DataFrame([influence.drop_k(engine, g, 5, base) for g in called]).set_index("gene")
    timings["influence_s"] = time.perf_counter() - t

    t = time.perf_counter()
    joint, joint_meta = inference.joint_test(engine, permutations=permutations, seed=seed)
    timings["joint_test_s"] = time.perf_counter() - t

    t = time.perf_counter()
    observations, ident = run_detectors(study)
    queue = build_queue(engine, observations, allf)
    timings["troubleshoot_s"] = time.perf_counter() - t

    loo_flips = loo[loo["flips"]]
    genes = genes.join(marg[["fold_margin_log2", "fold_margin_in_se", "p_margin_decades"]])
    genes["samples_whose_removal_flips"] = loo_flips.groupby("gene")["sample"].nunique()
    genes["drop_k_to_flip"] = dk["k"]
    genes = genes.join(
        joint.set_index("gene")[
            ["p_global", "q_global_bh", "share_forks_significant_same_direction"]
        ]
    )
    genes["samples_whose_removal_flips"] = (
        genes["samples_whose_removal_flips"].fillna(0).astype(int)
    )
    genes.index.name = "gene"
    genes.to_csv(out / "genes.csv")

    decisions = pd.DataFrame(
        {
            "flip_rate_all": allf.flip_rate().mean(),
            "flip_rate_defensible": defn.flip_rate().mean(),
            "genes_flipped_alone": allf.single_flips().sum(),
            "variance_share_all": allf.main_effect_share().mean(),
            "variance_share_defensible": defn.main_effect_share().mean(),
        }
    )
    decisions.index.name = "decision"
    decisions.to_csv(out / "decisions.csv")
    interactions = allf.interaction_share().mean().sort_values(ascending=False)

    check = []
    if explorer:
        t = time.perf_counter()
        check = explorer_check(engine, allf)
        timings["explorer_check_s"] = time.perf_counter() - t

    bench_summary = None
    bench_pooled = None
    if bench_trials > 0:
        t = time.perf_counter()
        bench_summary, bench_detail = run_benchmark(study, trials=bench_trials, seed=seed)
        timings["benchmark_s"] = time.perf_counter() - t
        bench_summary.to_csv(out / "benchmark.csv")
        bench_detail.drop(columns=["truth"]).to_csv(out / "benchmark_trials.csv", index=False)
        changed = bench_detail[bench_detail["calls_changed"] > 0]
        unchanged = bench_detail[bench_detail["calls_changed"] == 0]
        bench_pooled = {
            "trials": int(len(bench_detail)),
            "trials_changing_a_call": int(len(changed)),
            "detected_when_a_call_changed": int(changed["detected"].sum()),
            "trials_changing_nothing": int(len(unchanged)),
            "detected_when_nothing_changed": int(unchanged["detected"].sum()),
            "mean_other_new_findings": round(
                float(bench_detail["new_findings_elsewhere"].mean()), 2
            ),
        }

    issue_dicts = [i.__dict__ for i in queue]
    genes["verdict"] = verdicts(genes, issue_dicts)
    genes.to_csv(out / "genes.csv")
    explained = explain(engine, defn, genes, genes["verdict"])
    (out / "explain.json").write_text(json.dumps(explained, indent=1, default=_json_default))
    verdict_counts = {v: int((genes["verdict"] == v).sum()) for v in ORDER}
    t = time.perf_counter()
    from qsim import designs

    design_result = (
        designs.run(study, space, draws=design_draws, seed=seed) if design_draws else None
    )
    if design_result:
        (out / "designs.json").write_text(json.dumps(design_result, indent=1))
    timings["designs_s"] = time.perf_counter() - t
    question = {
        d: int(v)
        for d, v in allf.single_flips().sum().items()
        if space.decision(d).role == "question"
    }
    qf = queue_frame(queue)
    qf.to_csv(out / "issues.csv", index=False)
    (out / "issues.json").write_text(json.dumps([i.__dict__ for i in queue], indent=1, default=str))
    loo_flips.to_csv(out / "one_sample_flips.csv", index=False)
    refw.sort_values(["genes_flipped", "max_abs_d_in_se"], ascending=False).head(50).to_csv(
        out / "reference_wells_top50.csv", index=False
    )

    base_counts = pd.Series([c for c in genes["all_baseline_call"]]).value_counts().to_dict()
    called_mask = genes["all_baseline_call"] != "none"
    summary = {
        "qsim_version": __version__,
        "qpilot_version": qpilot.__version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "machine": platform.platform(),
        "input_sha256": study.input_sha256,
        "source": {
            "name": source or (Path(rdml).name if rdml else BENCHMARK_NAME),
            "rdml": str(Path(rdml).resolve()) if rdml else None,
        },
        "grid_hash": _grid_hash(grid),
        "seed": seed,
        "study": {
            "samples": len(study.samples),
            "genes_compared": len(study.items),
            "references": list(study.primary_refs),
            "plates": int(study.curves["run_id"].nunique()),
        },
        "space": {
            "decisions": {
                d.id: d.ids if d.id != "refs" else f"{len(d.options)} subsets"
                for d in space.decisions
            },
            "levels": space.levels,
            "baseline": space.baseline,
        },
        "ledger": {**led.as_dict(), "notes": list(space.notes)},
        "space_rules": space_info,
        "baseline_calls": base_counts,
        "multiverse": {
            "all": _multiverse_summary(allf, called_mask.values),
            "defensible": _multiverse_summary(defn, called_mask.values),
        },
        "headline": {
            g: {
                "call": genes.loc[g, "all_baseline_call"],
                "fold": round(float(genes.loc[g, "all_baseline_fold"]), 3),
                "holds_all": round(float(genes.loc[g, "all_holds"]), 4),
                "holds_defensible": round(float(genes.loc[g, "defensible_holds"]), 4),
                "fragility_defensible": int(genes.loc[g, "defensible_fragility"]),
                "minimal_flip_sets_defensible": defn.minimal_flip_sets(g),
            }
            for g in HEADLINE
            if g in genes.index
        },
        "lock_advisor": {
            "headline_all": allf.lock_advisor(list(HEADLINE)),
            "called_all": allf.lock_advisor(list(genes.index[called_mask])),
            "called_defensible": defn.lock_advisor(list(genes.index[called_mask])),
        },
        "decisions": decisions.round(4).to_dict(orient="index"),
        "top_interactions": interactions.head(5).round(4).to_dict(),
        "influence": {
            "genes_flipped_by_one_sample": int(loo_flips["gene"].nunique()),
            "samples_that_flip_a_gene": int(loo_flips["sample"].nunique()),
            "reference_well_removals": int(len(refw)),
            "reference_well_removals_that_flip": int((refw["genes_flipped"] > 0).sum()),
            "max_genes_flipped_by_one_reference_well": int(refw["genes_flipped"].max()),
            "called_genes": int(called_mask.sum()),
            "called_within_1_se_of_fold_line": int(
                (genes.loc[called_mask, "fold_margin_in_se"] < 1).sum()
            ),
            "called_overturned_by_le_5_samples": int(
                genes.loc[called_mask, "drop_k_to_flip"].notna().sum()
            ),
        },
        "joint_test": {
            **joint_meta,
            "genes_q_lt_0.05": int((joint["q_global_bh"] < 0.05).sum()),
            "genes_significant_in_ge_95pct_forks": int(
                (joint["share_forks_significant_same_direction"] >= 0.95).sum()
            ),
            "called_genes_significant_in_ge_95pct_forks": int(
                (genes.loc[called_mask, "share_forks_significant_same_direction"] >= 0.95).sum()
            ),
        },
        "troubleshooting": {
            "observations": {
                k: int(v)
                for k, v in pd.Series([o.kind for o in observations]).value_counts().items()
            },
            "issues": len(queue),
            "issues_by_impact": qf["impact"].value_counts().to_dict(),
            "identifiability": ident,
            "top_issues": qf.head(10).drop(columns=["action", "status"]).to_dict(orient="records"),
        },
        "explorer_check": check,
        "lock_sha256": lock_hash,
        "question_choices_flip_alone": question,
        "designs": design_result,
        "verdicts": {
            "counts": verdict_counts,
            "rules": RULES,
            "by_gene": genes["verdict"].to_dict(),
        },
        "benchmark_pooled": bench_pooled,
        "benchmark": None
        if bench_summary is None
        else bench_summary.reset_index().round(3).to_dict(orient="records"),
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=_json_default))
    (out / "REPORT.md").write_text(render_report(summary))
    return summary


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def _multiverse_summary(f: Factorial, called: np.ndarray) -> dict:
    t = f.gene_table()
    return {
        "cells": f.n_cells,
        "genes_that_flip_somewhere": int((t["fragility"] > 0).sum()),
        "fragility_counts": {
            str(k): int(v) for k, v in t["fragility"].value_counts().sort_index().items()
        },
        "interaction_only_genes": int(t["interaction_only"].sum()),
        "called_genes_holding_ge_95pct": int((t.loc[called, "holds"] >= 0.95).sum()),
        "called_genes_holding_lt_80pct": int((t.loc[called, "holds"] < 0.80).sum()),
    }


def _source_title(s: dict) -> str:
    name = (s.get("source") or {}).get("name")
    return "the public neuroblastoma benchmark" if name in (None, BENCHMARK_NAME) else name


def render_report(s: dict) -> str:
    m_all, m_def = s["multiverse"]["all"], s["multiverse"]["defensible"]
    inf, jt = s["influence"], s["joint_test"]
    lines = [
        f"# qPilot Decision Simulator: results on {_source_title(s)}",
        "",
        f"Input SHA-256 `{s['input_sha256'][:16]}…`, grid hash `{s['grid_hash']}`, seed {s['seed']}. "
        f"qsim {s['qsim_version']}, qPilot {s['qpilot_version']}, Python {s['python']}, NumPy {s['numpy']}, SciPy {s['scipy']}.",
        "",
        f"Study: {s['study']['samples']} tumours, {s['study']['genes_compared']} genes compared (MYCN-high vs rest), "
        f"{s['study']['plates']} plates. Baseline calls: {s['baseline_calls']}.",
        "",
        "## Decision space",
        "",
        f"{len(s['space']['levels'])} decisions with levels {s['space']['levels']}: "
        f"{s['ledger']['total_cells']:,} analyses, **all evaluated** ({s['ledger']['exploration']}). "
        f"Full sweep: {s['timings_s']['full_grid_s']} s on one core.",
        "",
        "| | all options | defensible options only |",
        "|---|---|---|",
        f"| analyses | {m_all['cells']:,} | {m_def['cells']:,} |",
        f"| genes whose call flips somewhere | {m_all['genes_that_flip_somewhere']} | {m_def['genes_that_flip_somewhere']} |",
        f"| fragility (fewest choices to flip): count of genes | {m_all['fragility_counts']} | {m_def['fragility_counts']} |",
        f"| genes that flip only through two or more choices together | {m_all['interaction_only_genes']} | {m_def['interaction_only_genes']} |",
        f"| called genes holding in ≥ 95 % of analyses | {m_all['called_genes_holding_ge_95pct']} of {inf['called_genes']} | {m_def['called_genes_holding_ge_95pct']} of {inf['called_genes']} |",
        f"| called genes holding in < 80 % | {m_all['called_genes_holding_lt_80pct']} | {m_def['called_genes_holding_lt_80pct']} |",
        "",
        "Fragility 0 means no analysis in the space changes the call.",
        "",
        "### Which decisions matter",
        "",
        "| decision | genes flipped by this choice alone | flip rate (all / defensible) | share of fold-change variance (all / defensible) |",
        "|---|---|---|---|",
    ]
    for d, v in s["decisions"].items():
        lines.append(
            f"| {d} | {int(v['genes_flipped_alone'])} | {v['flip_rate_all']:.3f} / {v['flip_rate_defensible']:.3f} | {v['variance_share_all']:.3f} / {v['variance_share_defensible']:.3f} |"
        )
    lines += [
        "",
        f"Largest pairwise interactions (share of variance): {s['top_interactions']}.",
        "",
        f"**Pre-registration advisor.** Locking {s['lock_advisor']['headline_all']} protects every headline call. "
        f"Locking {s['lock_advisor']['called_all']} protects every called gene; the remaining choices cannot flip any call.",
        "",
        "### Headline genes",
        "",
        "| gene | call | fold | holds (all) | holds (defensible) | fewest choices to flip (defensible) | minimal flip sets (defensible) |",
        "|---|---|---|---|---|---|---|",
    ]
    for g, v in s["headline"].items():
        sets = "; ".join(" + ".join(x) for x in v["minimal_flip_sets_defensible"]) or "none"
        lines.append(
            f"| {g} | {v['call']} | {v['fold']} | {v['holds_all']:.3f} | {v['holds_defensible']:.3f} | {v['fragility_defensible'] or '–'} | {sets} |"
        )
    lines += [
        "",
        f"**Locked before the sweep:** baseline, tiers and rule, SHA-256 `{s['lock_sha256'][:16]}…` (results/lock.json).",
        "",
        f"**Question choices, reported separately** (they change the claim, not the analysis): calls changed by each alone {s['question_choices_flip_alone']}.",
        "",
        "## Verdicts in plain words",
        "",
        "Rules: solid = same call in >= 95 % of defensible analyses, no 5 or fewer samples overturn it, significant in >= 95 %; "
        "fragile = < 80 %, or <= 2 samples overturn it, or within 0.1 log2 of the fold line; check data first = a data finding changes it.",
        "",
        " · ".join(f"{k}: {v}" for k, v in s["verdicts"]["counts"].items()),
        "",
        "## What the calls lean on (baseline analysis)",
        "",
        f"* {inf['genes_flipped_by_one_sample']} genes flip when one tumour is removed; {inf['samples_that_flip_a_gene']} different tumours can do it.",
        f"* {inf['reference_well_removals_that_flip']} of {inf['reference_well_removals']} single reference-well removals flip at least one gene; the worst flips {inf['max_genes_flipped_by_one_reference_well']}.",
        f"* {inf['called_within_1_se_of_fold_line']} of {inf['called_genes']} called genes sit within one SE of the 2-fold line; {inf['called_overturned_by_le_5_samples']} can be overturned by removing at most 5 tumours (greedy, an upper bound).",
        "",
        "## Joint inference across analyses",
        "",
        f"Permutation max-T over {jt['forks']} defensible Welch analyses per gene ({jt['permutations']} permutations, seed {jt['seed']}): "
        f"{jt['genes_q_lt_0.05']} genes are associated with the MYCN-high group (BH q < 0.05). "
        f"{jt['genes_significant_in_ge_95pct_forks']} genes are significant, same direction, in at least 95 % of analyses with family-wise control; "
        f"of the called genes, {jt['called_genes_significant_in_ge_95pct_forks']}. Significance is robust; the 2-fold threshold and the group definition are what make calls fragile.",
        "",
        "## Troubleshooting",
        "",
        f"Observations: {s['troubleshooting']['observations']}. Issues in the queue: {s['troubleshooting']['issues']} ({s['troubleshooting']['issues_by_impact']}).",
        "",
        "Identifiability: " + "; ".join(s["troubleshooting"]["identifiability"]["notes"]) + ".",
        "",
        "| rank | issue | impact | headline changed | calls changed | max move (SE) |",
        "|---|---|---|---|---|---|",
    ]
    for r in s["troubleshooting"]["top_issues"]:
        lines.append(
            f"| {r['rank']} | {r['title']} | {r['impact']} | {r['headline_changed'] or '–'} | {r['calls_changed']} | {r['max_abs_d_in_se']} |"
        )
    if s["explorer_check"]:
        lines += [
            "",
            "## Can cheaper search find the same flips?",
            "",
            "| strategy | runs | share of space | genes with a flip found | pairwise coverage |",
            "|---|---|---|---|---|",
        ]
    for r in s["explorer_check"]:
        lines.append(
            f"| {r['strategy']} | {r['runs']} | {r['share_of_space']:.3%} | {r['genes_with_a_flip_found']} / {r['genes_with_a_flip_total']} | {r['pairwise_coverage']:.3f} |"
        )
    if s["benchmark"]:
        lines += [
            "",
            "## Fault-injection benchmark",
            "",
            f"Of {s['benchmark_pooled']['trials_changing_a_call']} planted faults that changed at least one call, "
            f"{s['benchmark_pooled']['detected_when_a_call_changed']} were detected. Of {s['benchmark_pooled']['trials_changing_nothing']} that changed nothing, "
            f"{s['benchmark_pooled']['detected_when_nothing_changed']} were detected. Mean other new findings per trial: {s['benchmark_pooled']['mean_other_new_findings']} "
            "(these include knock-on effects of the fault, so they are an upper bound on false alarms).",
            "",
            "| fault | size (cycles) | trials | detected | new findings elsewhere (mean) | trials where a call changed | detected when a call changed |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in s["benchmark"]:
            dc = r.get("detection_rate_when_a_call_changed")
            dc = "–" if dc is None or (isinstance(dc, float) and np.isnan(dc)) else f"{dc:.0%}"
            lines.append(
                f"| {r['fault']} | {r['size_cycles']} | {r['trials']} | {r['detection_rate']:.0%} | {r['mean_new_findings_elsewhere']:.2f} | {r['share_trials_changing_a_call']:.0%} | {dc} |"
            )
    if s.get("designs"):
        lines += [
            "",
            "## Typical bench experiments drawn from the real data",
            "",
            f"{s['designs']['draws']} random draws per size; defensible analyses = {s['designs']['defensible_cells']} (question choices fixed); robust = same call in >= 95 %.",
            "",
            "| n per group | false calls, single analysis (no true difference) | false calls after robust filter | real difference: calls passing filter | disagree with full study: robust / not robust |",
            "|---|---|---|---|---|",
        ]
        for n, r in s["designs"]["sizes"].items():
            nd, rd = r["no_difference"], r["real_difference"]
            lines.append(
                f"| {n} | {nd['false_call_rate_single_analysis']:.2%} | {nd['false_call_rate_after_robust_filter']:.2%} | {rd['share_robust']} | {rd['disagree_with_full_study_if_robust']} / {rd['disagree_with_full_study_if_not_robust']} |"
            )
        lines += [
            "",
            "The filter removes analysis-induced false calls; it does not fix small-sample noise (robust and non-robust real calls disagree with the full study about equally).",
        ]
    lines += ["", f"Timings (s): {s['timings_s']}.", ""]
    return "\n".join(lines)
