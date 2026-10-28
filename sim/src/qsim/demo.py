"""``qsim demo``: a narrated walk from one raw amplification curve to a verdict on one gene.

Every number printed is computed live from the input file; nothing is typed in.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import numpy as np
import pandas as pd
from qpilot.io import rdml_io

from qsim import explore, inference, influence
from qsim.attribution import Factorial
from qsim.compare import whatif
from qsim.data import demo_rdml, load_study, sha256
from qsim.engine import CALL_NAMES, Engine
from qsim.issues import build_queue
from qsim.study_space import space_for
from qsim.troubleshoot import run_detectors

BARS = "▁▂▃▄▅▆▇█"
WIDTH = 96


def _h(step: int, title: str) -> None:
    print("\n" + "─" * WIDTH)
    print(f" STEP {step}  {title}")
    print("─" * WIDTH)


def _spark(values: np.ndarray) -> str:
    lo, hi = np.nanmin(values), np.nanmax(values)
    idx = ((values - lo) / (hi - lo) * (len(BARS) - 1)).round().astype(int)
    return "".join(BARS[i] for i in idx)


def _fold(log2fc: float) -> str:
    f = 2**log2fc
    return f"{f:.2f}× higher" if f >= 1 else f"{1 / f:.2f}× lower"


def run_demo(
    rdml: str | None = None, gene: str = "NM23A", well: str = "A1", pause: float = 0.0
) -> None:
    path = Path(rdml) if rdml else demo_rdml()

    _h(1, "INPUT: the instrument's raw file (RDML)")
    t = time.perf_counter()
    doc = rdml_io.load(path)
    runs = rdml_io.runs(doc, "biomarker_set")
    study = load_study(path)
    c = study.curves
    print(
        f" file      {path.name}  ({path.stat().st_size / 1e6:.1f} MB, SHA-256 {sha256(path)[:16]}…)"
    )
    print(f" contents  {len(runs)} plates × 384 wells = {len(c):,} amplification curves")
    types = c["sample_type"].value_counts().to_dict()
    print(
        f"           {types.get('unkn', 0):,} tumour wells, {types.get('std', 0)} dilution standards, {types.get('ntc', 0)} no-template controls"
    )
    print(
        f"           {len(study.samples)} tumours, {len(study.items)} genes to compare, {len(study.candidates)} reference genes"
    )
    run = next(r for r in runs if r["id"].startswith(gene))
    table = pd.read_csv(io.StringIO(run.export_table("amp")), sep="\t")
    row = table[table["Well"] == well].iloc[0]
    cycles = [col for col in table.columns if col.isdigit()]
    fluor = row[cycles].to_numpy(dtype=float)
    print(
        f"\n one well, exactly as the instrument wrote it: plate {run['id']}, well {well}, tumour {row['Sample']}"
    )
    print(f" fluorescence, cycles 1-{len(cycles)}:  {_spark(fluor)}")
    shown = ", ".join(f"{v:.2f}" for v in fluor[[0, 9, 14, 19, 24, 29, 39, len(fluor) - 1]])
    print(f" values at cycles 1, 10, 15, 20, 25, 30, 40, {len(fluor)}: {shown}")
    print(f" ({time.perf_counter() - t:.1f} s to read and check the file)")

    _h(2, "ENGINE, per well: qPilot's validated LinRegPCR curve analysis")
    g = study.genes.index(gene)
    i = study.samples.index(str(row["Sample"]))
    print(" baseline-corrected, fitted in the log-linear phase of the curve above:")
    print(
        f"   efficiency of this well      {study.eff_well[i, g]:.3f}   (2.0 = perfect doubling per cycle)"
    )
    print(f"   mean efficiency of the assay {study.eff_assay[i, g]:.3f}   (used by default)")
    print(f"   Cq                           {study.cq[i, g]:.2f}")
    print(f"   starting quantity N0         {2 ** study.log2_n0[i, g]:.3g}")
    refs = ", ".join(
        f"{r.split('(')[0]} {2 ** study.log2_n0[i, study.genes.index(r)]:.3g}"
        for r in study.primary_refs
    )
    print(f" the same tumour's 5 reference genes (the 'ruler' it is divided by): {refs}")

    space = space_for(study)[0]
    engine = Engine(study, space)
    _h(3, f"ONE ANALYSIS: what a scientist normally gets for {gene}")
    hi, lo = study.group_masks(0.15)
    base = engine.evaluate(space.baseline_index())
    k = engine.items.index(gene)
    print(f" groups    {hi.sum()} MYCN-high tumours (top 15 %) vs {lo.sum()} others")
    print(" choices   " + " · ".join(f"{k}={v}" for k, v in space.baseline.items()))
    print(
        f" result    {gene} is {_fold(base['log2fc'][k])} in MYCN-high "
        f"(95 % CI {2 ** base['lo'][k]:.2f}–{2 ** base['hi'][k]:.2f}), p = {base['p'][k]:.1e}"
    )
    print(
        f" call      {CALL_NAMES[int(base['call'][k])].upper()}  (rule: p < 0.05 and at least 2-fold)"
    )
    print(" ...but every line of 'choices' was a decision someone made.")

    _h(4, "THE DECISION SPACE: every reasonable way to analyse the same plates")
    for d in space.decisions:
        tiers = pd.Series([o.tier for o in d.options]).value_counts().to_dict()
        print(f" {d.id:13s} {len(d.options):2d} options  {d.question}  {tiers}")
    total = int(np.prod(space.levels))
    print(f" {' × '.join(map(str, space.levels))} = {total:,} analyses")

    _h(5, f"RUN ALL {total:,} ANALYSES")
    t = time.perf_counter()
    grid = engine.run(explore.full(space))
    print(
        f" done in {time.perf_counter() - t:.1f} s on one laptop core ({total * len(engine.items):,} gene results)"
    )
    f = Factorial(grid)
    table = f.gene_table()
    print(
        f" genes whose call flips in at least one analysis: {int((table['fragility'] > 0).sum())} of {len(table)}"
    )
    print(
        f" genes that flip only when two or more choices change together: {int(table['interaction_only'].sum())}"
    )

    _h(6, f"OUTPUT for {gene}: does the call survive the other analyses?")
    gt = table.loc[gene]
    print(f" holds in {gt['holds']:.0%} of the {total:,} analyses")
    rates = f.flip_rate().loc[gene].sort_values(ascending=False)
    print(
        " share of settings of the other choices in which this choice can flip it: "
        + ", ".join(f"{d} {r:.0%}" for d, r in rates.items() if r > 0)
    )
    sets = f.minimal_flip_sets(gene)
    print(" smallest sets of decisions that flip it: " + "; ".join(" + ".join(s) for s in sets[:5]))
    for changes in (
        {"cut": "top20"},
        {"refs": "HMBS"},
        {"cut": "top10"},
        {"test": "mann_whitney", "multiplicity": "bh"},
    ):
        r = whatif(engine, changes).set_index("gene").loc[gene]
        print(
            f"   what if {changes}: {r['base_call']} → {r['call']}, fold {r['base_fold']:.2f} → {r['fold']:.2f}, "
            f"moves {r['d_in_se']:+.1f} SE  [{r['impact']}]"
        )
    pair_gene = next(
        (x for x in table.index[table["interaction_only"] & (table["baseline_call"] != "none")]),
        None,
    )
    if pair_gene:
        pair = f.minimal_flip_sets(pair_gene)[0]
        cell = _first_flip(f, space, pair_gene, pair)
        changes = {d: space.to_assignment(cell)[d] for d in pair}
        r = whatif(engine, changes).set_index("gene").loc[pair_gene]
        single = [
            whatif(engine, {d: v}).set_index("gene").loc[pair_gene, "call"]
            for d, v in changes.items()
        ]
        print(
            f"\n an 'X and Y' case, {pair_gene}: {', '.join(f'{d}={v}' for d, v in changes.items())}"
        )
        print(f"   each alone: {single} (no change); together: {r['base_call']} → {r['call']}")
    print(
        f"\n lock these choices in advance and no headline call can flip: {f.lock_advisor(['ODC1', 'BIRC5', 'NTRK1', 'NM23A'])}"
    )

    _h(7, f"WHAT {gene} LEANS ON (baseline analysis)")
    b = influence.Baseline(engine)
    m = influence.margins(engine, b).set_index("gene").loc[gene]
    print(
        f" margin to the 2-fold line: {m['fold_margin_log2']:+.2f} log2 ({m['fold_margin_in_se']:+.1f} SE); "
        f"to p = 0.05: {m['p_margin_decades']:.1f} decades"
    )
    dk = influence.drop_k(engine, gene, 5, b)
    if dk["k"]:
        print(
            f" removing {dk['k']} tumour(s) ({', '.join(dk['samples'])}) turns the call into '{dk['flips_to']}'"
        )
    rw = (
        influence.reference_wells(engine, b)
        .sort_values(["genes_flipped", "max_abs_d_in_se"], ascending=False)
        .iloc[0]
    )
    print(
        f" most influential single reference well: tumour {rw['sample']}, {rw['reference']} well {rw['well']} "
        f"→ removing it flips {rw['genes_flipped']} genes ({rw['flipped']})"
    )
    jt, meta = inference.joint_test(engine, permutations=199, seed=2026)
    j = jt.set_index("gene").loc[gene]
    print(
        f" joint test over {meta['forks']} defensible analyses: global p = {j['p_global']:.3f}; "
        f"significant (family-wise) in {j['share_forks_significant_same_direction']:.0%} of them"
    )

    _h(8, "TROUBLESHOOTING: what to inspect first")
    obs, ident = run_detectors(study)
    queue = build_queue(engine, obs, f)
    print(f" {len(obs)} observations → {len(queue)} issues, ranked by consequence (all kept)")
    for n, x in enumerate(queue[:6], 1):
        where = x.loci.get("wells", [])[:1] or [x.loci.get("decision") or x.loci.get("gene", "")]
        print(f" {n}. [{x.impact}] {x.title}  ({where[0]}); calls changed: {len(x.changed_calls)}")
        print(f"    → {x.action}")
    print(f" layout note: {ident['notes'][0][: WIDTH - 15]}…")

    _h(9, "ASK IN PLAIN WORDS (local model; every number checked against the engine)")
    from qsim.ask import Asker

    results = Path("results")
    if (results / "explain.json").exists():
        asker = Asker(results, rdml=rdml)
        who = asker.client.model or "templates only"
        for q in (
            "Does NM23A depend on the reference genes?",
            "What if we used only HMBS and capped the non-detects?",
        ):
            ans = asker.answer(q)
            print(f" Q: {q}")
            print(f" A: {ans.text}")
            print(f"    [{ans.tool}; written by {ans.written_by}; model: {who}]")
    else:
        print(" run `qsim run` once to enable Ask")
    vfile = results / "validation_untergasser.json"
    if vfile.exists():
        import json

        v = json.loads(vfile.read_text(encoding="utf-8"))
        eff = v["by_choice"]["efficiency"]
        print(
            "\n known-answer check on a different lab's dilution series (Untergasser, LightCycler 480):"
        )
        print(
            f"   error vs truth: standard curve {eff['std_curve']['median_abs_error_pct']} %, LinRegPCR mean "
            f"{eff['assay_mean']['median_abs_error_pct']} %, assume 100 % {eff['assume_100']['median_abs_error_pct']} %, "
            f"each well's own {eff['per_well']['median_abs_error_pct']} %"
        )
        w = v["warning"]
        print(
            f"   when analyses disagree most, the standard answer is off by {w['baseline_median_abs_error_pct_when_spread_in_top_quarter']} % "
            f"(vs {w['baseline_median_abs_error_pct_otherwise']} % otherwise)"
        )

    _h(10, "OUTPUT FILES (qsim run)")
    print(" results/REPORT.md        plain-language report, every number from the engine")
    print(" results/genes.csv        per gene: call, holds, fragility, margins, drop-k, joint test")
    print(" results/issues.csv/json  the ranked investigation queue with evidence and actions")
    print(" results/grid.parquet     every analysis × gene result, for any further question")
    print(
        " results/summary.json     versions, input hash, grid hash, seeds (byte-identical reruns)"
    )


def _first_flip(f: Factorial, space, gene: str, decisions: tuple[str, ...]) -> tuple[int, ...]:
    g = f.grid.items.index(gene)
    base = space.baseline_index()
    pos = [space.names.index(d) for d in decisions]
    for row, cell in enumerate(f.grid.index):
        changed = [k for k, (a, b) in enumerate(zip(cell, base, strict=True)) if a != b]
        if sorted(changed) == sorted(pos) and f.grid.call[row, g] != f.base_call[g]:
            return tuple(int(x) for x in cell)
    raise ValueError("no flipping cell")
