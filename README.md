# qPilot Decision Simulator

Does your qPCR conclusion survive every defensible analysis, and what does it depend on?

The simulator reruns one study under every combination of analysis choices a careful lab could make. For each gene it reports:

- whether the call holds across those analyses;
- which choices or samples change it;
- what to check first.

On top of that it adds:

- known-answer tests against digital PCR, on four qPCR machines;
- planted faults in real data;
- no-difference tests, including a plate of 380 identical wells.

It is built on [qPilot](https://github.com/ShivaTeja05/Qpilot)'s validated engine (LinRegPCR from raw curves, geNorm, the conclusion rule) and reproduces qPilot exactly at the baseline. Research use only.

**What to call it.** An independent review ([docs/review](docs/review/00-judge-ruling.md)) ruled that the exhaustive sweep is a robustness audit. The parts that simulate in the strict sense (a known true answer and a data-generating mechanism) are the planted faults, the known-answer dilutions and the small-experiment draws. A generative plate model (PlateSim) is the next step before using "simulator" with experts.

**No training, no labelled data.** The engine is deterministic statistics. An optional local model (Ollama `qwen2.5:7b`) only words the answers, and qPilot's validator rejects any number the engine did not produce.

## Quick start

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/qsim demo                                     # raw curve -> verdict, narrated
.venv/bin/qsim run                                      # every analysis + tests -> results/
.venv/bin/qsim ask "Does NM23A depend on the reference genes?"
.venv/bin/qsim whatif --set refs=HMBS --set late_cq=cq35
.venv/bin/qsim validate                                 # dPCR known answers + null plate
.venv/bin/qsim external                                 # new public data: held-out plates, low copy, inhibition
.venv/bin/pytest -q
```

## The choices it varies

| Choice | Options | How the tier is set |
|---|---|---|
| Efficiency | LinRegPCR assay mean · plate standard curve · each well's own · assume 100 % | Per-well and 100 % are common practice. Per-well was demoted after an 89 % median error against known dilution ratios. |
| Flagged wells | keep · drop efficiency outliers · also drop < 10 copies | The last is common practice. |
| Late Cq | keep · Cq > 35 not detected · Cq > 38 not detected | Both cut-offs defensible ([de Ronde 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5393188/)). |
| Non-detects | drop · lowest detected · Cq 40 | Cq 40 is common practice ([McCall 2014](https://pmc.ncbi.nlm.nih.gov/articles/PMC4133581)). |
| Reference genes | all 31 subsets | Rule-based from the study itself; see below. |
| Test | Welch · Student · Mann–Whitney | Mann–Whitney is removed when it cannot reach p < 0.05 at the group sizes. |
| Group cut-off | top 10 / 15 / 20 % | A question choice: it changes the claim, so it is reported separately. |
| Multiple testing | none · BH · Holm | A question choice, reported separately. |

The reference-gene rule:

- A single gene is common practice.
- A set containing a gene the group-difference check implicates (here HMBS and UBC) is common practice.
- If two or more candidates are geNorm-stable (M < 1.0), only sets of stable genes are defensible.
- Otherwise, only sets of three or more unimplicated genes are defensible.

Every option, tier and the baseline are hashed into `results/lock.json` before any alternative is computed.

## Results

### Neuroblastoma benchmark

Vermeulen/Ruijter RDML: 64 plates, 366 tumours, 58 genes. Details are in [`results/REPORT.md`](results/REPORT.md).

**All options:**
- 90,396 analyses in 55 s on one core.
- 55 of 58 genes change call somewhere.
- 21 genes flip only when two or more choices change together.

**Strict defensible view:** 144 analyses.
- 14 genes change call.
- 31 of 40 calls hold in at least 95 % of analyses.
- The late-Cq cut-off is the most influential defensible choice (48 % of fold-change variance).
- Verdicts: 23 solid, 7 hold with caveats (they lean on 5 or fewer tumours), 3 depend on your choices, 5 fragile, 2 check data first.

**What to lock in advance:** locking late-Cq, reference genes and cut-off protects all four headline calls.

**What calls lean on:**
- Removing one tumour flips 4 genes.
- 148 of 1,745 single reference-well removals flip a gene.

**Joint test:** a permutation max-T test across 48 defensible analyses finds 56 of 58 genes associated with the group. So the 2-fold threshold and the analysis choices make calls fragile, not significance.

### Known answers: digital-PCR truth on four machines

The data are the Untergasser dilution series. The truth is the QX200 dPCR ratio of the same tubes. The instrument comparison uses the pipetted ratio, because dPCR never measured its tubes.

That gives 197 comparisons on 5 plates and 4 machines: two LightCycler 480s, a QuantStudio 6 Flex and a StepOne. Details and caveats are in [docs/review/30-validation-round-2.md](docs/review/30-validation-round-2.md).

| Test (bar set by the review) | Result |
|---|---|
| Baseline efficiency: median \|error\| ≤ 0.15 log2 on ≥ 2 machines | **Pass by the letter.** LC480 AMC 0.12 (dPCR truth) and StepOne 0.09 (pipetted truth, 4 cases). Fails on LC480 DKFZ 0.22 (dPCR) and QuantStudio 0.21 (pipetted). |
| Spread across analyses warns of error: Spearman ≥ 0.3 within each input level | **Pass**, 0.33–0.68. Among assays that pass the dilution QC it is 0.02–0.55, so mostly it flags broken assays. |
| Baseline 95 % interval contains the truth ≥ 90 % | **Fail: 83 %.** This is with efficiency uncertainty and a run effect propagated into the interval. The replicate-only interval covers 66 %. Calibrating the efficiency on held-out dPCR plates gives 88 %, still a fail. Adding a between-plate term estimated without truth gives 92 %, with intervals 63 % wider (±1.33-fold); Poisson sampling alone explains 87 % (`docs/review/31-research-closing-the-coverage-gap.md`). |

| Efficiency choice | Median \|error\| vs dPCR (log2) |
|---|---|
| Standard curve | 0.10 |
| LinRegPCR mean (baseline) | 0.13 |
| Assume 100 % | 0.17 |
| Each well's own | 1.04 |

- **Two steps have no dPCR answer.** At 0.2 ng the two dPCR assays disagree 2.5-fold, and the 10^5 standard saturates the droplets. Both are reported separately.
- **The interval misses because of a bias, not too little variance.** At the widest steps the assay-mean efficiency runs about 1.6 % per cycle low, so the baseline reads 0.11 log2 low.
- **The standard curve beat the baseline on one LightCycler and lost on the other.** Tiers are unchanged until the outside review.

Round 1, with nominal ng as truth (AMC LightCycler 480, 188 comparisons), stays in `results/validation_untergasser.json`:
- The truth falls inside the baseline 95 % CI in 73 % of cases, and inside the propagated interval in 81 %.
- It falls inside the range of defensible analyses in 40 %.
- **Replicate errors are caught and fixed.** A 3-cycle error in one replicate is always caught by the half-cycle rule, and dropping it cuts the error from 90 % to 1.4 %. The rule also flags 7 % of clean triplicates.

### No difference: one template on one plate

The data are Ruijter's ds_380: 380 wells of 150,000 copies on one CFX384, converted to RDML for qPilot's LinRegPCR. The test drew 1,000 random 3 vs 3 and 6 vs 6 splits.

- **Defensible analyses never made a call.** No call passed the robust filter, and the median \|log2 fold change\| was 0.07 at 3 vs 3 and 0.06 at 6 vs 6.
- **Across all analyses, 1.33 % and 1.01 % of cells made a call.** That is just above the 1 % bar. Every one came from per-well efficiency (3–4 % of its cells), which is already common practice.
- **This is an easy null.** At 150,000 copies the Cq SD is 0.19 cycles. There are no reference genes, so normalisation is not tested.

### New public data, scored with nothing refitted

These tests were planned before scoring (`docs/review/32-external-data-tests.md`); every interval component is fixed from the results above.

| Test | Result |
|---|---|
| 3 new Untergasser plates of the same tubes (2 on a QuantStudio), 120 cases | **Pass.** The interval with the between-plate term covers 100 %, and the round-2 interval covers 97.5 %. Only 4 distinct truths stand behind these cases. |
| A constant added to every curve (RDML technical file) | **Pass.** Nothing changes; the largest difference is 0.00008 log2. |
| Ruijter ds_94_4, triplicates at 15–15,000 copies against nominal 10-fold steps | **Fail: 85 %.** The plate reads 0.26–0.39 log2 short of 10-fold per decade, which is either efficiency error or dilution error. |
| ds_94_4 no-difference at 15 and 150 copies | **Defensible analyses never call.** Per-well efficiency makes almost every call (3–5 % of its cells). |
| Ruijter competimer (efficiency lowered on purpose) | The assay-mean baseline is biased by up to −10.6 log2. Per-well efficiency is less biased only at ≥ 30 % competitor; it is as bad or worse at 5–10 % and on clean wells. The efficiency detectors also flag clean wells (17–83 %). |

### Small experiments drawn from real data

100 draws per size.

| Group size | False calls, no true difference: one analysis | After requiring the call to hold in ≥ 95 % of analyses |
|---|---|---|
| 3 vs 3 | 2.5 % | 0 % |
| 6 vs 6 | 2.8 % | 0.24 % |

With a real difference, the filter does not make small-study calls agree better with the full 366-tumour answer (robust 25 % vs not robust 22 % disagreement). The audit removes false calls caused by analysis choices; it does not fix small-sample noise.

### Planted faults

220 trials.
- 39 of 46 faults that changed a call were detected (85 %, 95 % CI 72–92 %).
- Most of those were reference-gene shifts.
- Single bad wells without replicates and sample swaps were not detected; none of them changed a call.

## Limits and next steps

These come from the review and from validation round 2, in priority order:

1. Make the coverage claim robust. A between-plate term estimated without truth lifts coverage to 92 % (±1.33-fold intervals), but it rests mostly on one pair from the instrument comparison, which mixes instrument disagreement with one plate's separate dilution; Poisson sampling, with nothing fitted, explains 87 % (`docs/review/31-research-closing-the-coverage-gap.md`). More instruments measuring shared tubes would pin the between-plate term down. Quote 92 % with the term and 83 % without, never a nominal 95 %.
2. Have an outside qPCR scientist sign off every tier, including the result that the standard curve beat the baseline against dPCR on one machine.
3. Run low-copy no-difference and fragility tests on ds_94_4 and MAQC.
4. Add Cq method and baseline choices, a Cq-only import, paired tests and ANOVA.
5. Score the detectors on real faults (competimer, inhibitor series) with a Poisson-aware replicate rule.
6. Build PlateSim, a generative plate model fitted on Untergasser LC480 and tested on held-out instruments, and a design planner from it.

## Data and licence

- Vermeulen et al. 2009 / Ruijter et al. 2013 (CC BY 4.0), fetched SHA-256-pinned by qPilot.
- Untergasser, van der Hoff and Benes, via the RDML consortium (MIT), in `data/untergasser/`.
- Ruijter et al. 2013 ds_380, ds_94_4 and competimer, via the `ruijter` R package (CC BY 4.0), in `data/ruijter/`.
- RDML consortium technical files (MIT), in `data/technical/`.
- Code: Apache-2.0.
