# qPilot Decision Simulator

Which analysis choices, and which samples, change a qPCR conclusion?

The simulator reruns one qPCR study under every reasonable combination of analysis choices. For each call it reports:
- which choices flip it, alone or together;
- which tumours and wells it leans on;
- whether the effect survives joint testing across all analyses;
- what a scientist should check first.

It is built on [qPilot](https://github.com/ShivaTeja05/Qpilot)'s validated engine (LinRegPCR curve analysis, geNorm, the conclusion rule) and reproduces qPilot's results exactly at the baseline. Research use only.

**No training, no model, no labelled data.** Everything is deterministic statistics on the instrument data. Datasets are used only to test the simulator. The fault-injection benchmark makes its own labelled cases by planting known problems in real data.

## Results on the public neuroblastoma benchmark

The data is the Vermeulen/Ruijter RDML: 64 plates × 384 wells, 366 tumours, 58 genes compared between MYCN-high tumours and the rest. Full numbers are in [`results/REPORT.md`](results/REPORT.md).

| Question | Answer |
|---|---|
| How many analyses? | 7 decisions → **22,599 analyses, all run**, in 14 s on one laptop core |
| Does a single analysis hide sensitivity? | Within the defensible options, **46 of 58 genes** change call somewhere. Only 20 of 40 called genes hold in ≥ 95 % of analyses; 9 hold in < 80 % |
| Do choices interact ("X and Y")? | **19 genes** flip only when two or more choices change together, never with one |
| Which choices matter? | Group cut-off and reference genes explain **52 % and 27 %** of fold-change variance. The statistical test and multiple-testing correction explain ~0 % here |
| What should be locked in advance? | Locking **reference genes + cut-off** protects all four headline calls. Adding efficiency + flagged-well handling protects every call |
| What do calls lean on? | Removing one tumour flips 4 genes. 148 of 1,745 single reference-well removals flip a gene. 15 of 40 calls can be overturned by removing ≤ 5 tumours |
| Is the effect itself robust? | Permutation max-T test across 936 analyses per gene: **57 of 58 genes** are associated with the group. The fragility comes from the 2-fold threshold and the group definition, not from significance |
| Does cheaper search work when exhaustive is impossible? | A 98-run pairwise covering array (0.4 % of the space) finds 47 of the 54 genes that ever flip. A 500-cell random sample finds 51 |
| Does troubleshooting catch what matters? | Of **46 planted faults that changed a call, 39 were detected (85 %)**. Contaminated controls were caught 100 % of the time and reference genes shifted with the group 85 % |
| Where is it blind? | Single bad wells under ~5 cycles and sample swaps go undetected. With one well per tumour per gene, they look like biology. None of those planted faults changed a call |

## Quick start

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/qsim options                                        # decisions and options (* = baseline)
.venv/bin/qsim whatif --set refs=HMBS --set nondetect=cap_min # any "what if we chose X and Y"
.venv/bin/qsim run                                            # everything; writes results/
.venv/bin/pytest -q
```

The demo RDML is downloaded once, SHA-256-pinned, by qPilot. `--rdml path/to/file.rdml` runs your own study.

What-if output, per gene:
- the baseline and new call and fold change;
- the move in baseline standard errors;
- the change in CI width;
- the margin to the 2-fold line and to the p threshold;
- an impact class: `changes_conclusion` / `biases` / `widens_uncertainty` / `no_demonstrated_effect`.

## How it works

| Part | Module | Method |
|---|---|---|
| Decisions | `decisions.py` | Efficiency model, flagged wells, non-detects, reference set (31), cut-off, test, multiplicity. Each option is tiered prespecified / defensible / common practice, and each decision is tagged E/N/U (Del Giudice & Gangestad 2021) |
| Engine | `engine.py` | Cells run in stage order, so a sweep walks the prefix tree once. Efficiency models are exact rearrangements of LinRegPCR output (`log2 N0 = log2 Nq − Cq·log2 E`) |
| Exploration | `explore.py` | Exhaustive, rings around the baseline (anchored decomposition), greedy covering arrays (NIST SP 800-142), Morris trajectories, a random stratum, and a coverage ledger |
| Attribution | `attribution.py` | Exact over the full factorial: holds, flip rate per decision, fragility, minimal flip sets, main-effect and interaction variance shares, and a lock advisor (minimal hitting set) |
| Influence | `influence.py` | Exact closed-form leave-one-out, single reference-well removal (one well feeds every gene of its sample), greedy drop-k-to-flip, margins |
| Inference | `inference.py` | Permutation max-T across analyses per gene, the PIMA idea (Girardi et al. 2024), with BH across genes. Groups are re-drawn inside each permutation |
| Troubleshooting | `troubleshoot.py` | Detectors (below) and a check of what the plate layout can separate |
| Queue | `issues.py` | Each finding gets a remedy scenario and a computed consequence. Issues are ranked by a lexicographic key: invalidates > changes a headline call > changes a call > move in SE > outputs affected |
| Benchmark | `benchmark.py` | Faults planted at random sites in real data; scores detection, other new findings, and whether the fault changed a call |

The troubleshooting detectors:
- no-template control within 5 cycles (MIQE 2.0);
- well residuals from a two-way and low-rank co-expression model;
- group-adjusted row, column and edge tests;
- assay efficiency;
- reference genes that differ between groups;
- sample outliers.

## Validation (tests)

- **Baseline:** reproduces qPilot's `study_from_curves` to 1e-12, with every call identical.
- **qPilot's 186-analysis grid:** reproduced cell for cell inside the simulator's space.
- **Closed-form leave-one-out and reference-well updates:** equal full recomputation.
- **Supporting maths:** BH/Holm, Mann–Whitney against SciPy, covering arrays reaching full pairwise coverage, the joint test using the engine's statistics, and determinism.

## Limits

- **The benchmark data has limits.** It has one gene per plate, every tumour in the same well on every plate, and no technical replicates. Replicate-level faults and sample swaps need a dataset with replicates. A position effect shared by all plates cannot be separated from the tumour itself.
- **"Holds in X %" weights every option equally.** That is an assumption, reported alongside the defensible-only view.
- **The groups are defined from MYCN expression, not clinical labels.**
- **Benchmark faults are planted at the quantity level, not in raw fluorescence.**

## Data and licence

The demo data is from Vermeulen et al. 2009 and Ruijter et al. 2013 (CC BY 4.0), via the RDML consortium's pinned copy. The code is Apache-2.0.
