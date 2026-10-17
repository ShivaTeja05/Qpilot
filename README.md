# qPilot Decision Simulator

Does your qPCR conclusion survive every defensible analysis, and what does it depend on?

The simulator reruns one study under every combination of analysis choices a careful lab could make. For each gene it reports:

- whether the call holds across those analyses;
- which choices or samples change it;
- what to check first.

On top of that it adds:

- known-answer tests on a second lab's dilution series;
- planted faults in real data;
- no-difference tests.

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
.venv/bin/qsim validate                                 # known-answer test (Untergasser)
.venv/bin/qsim app --open                               # results screen on http://127.0.0.1:8765
.venv/bin/pytest -q
```

## Results screen

`qsim app` serves one page in plain lab language from `127.0.0.1` only. It loads no web assets and runs offline. It needs no extra packages: it uses Python's standard library.

It reads `results/explain.json`, `genes.csv`, `issues.json` and `summary.json`, and calls the engine live:

1. **Verdict counts.** Each verdict has its own shape and colour, so colour is never the only cue: ■ check data first, ▲ fragile, ◆ depends on your choices, ◐ holds with caveats, ● solid, ○ no change called. Click a count to filter the gene list.
2. **Gene list.** Each gene's fold change, call and verdict, with the results that need attention first.
3. **Gene card.** It covers:
   - the result and why it got its verdict;
   - "same answer in N of 100 reasonable analyses";
   - which choices change it, with the new fold change and call;
   - what it leans on: fewest samples to change it, single samples, distance from the 2× line;
   - what to do;
   - a link to the evidence page, which shows the gene's records in the engine files.
4. **What-if.** A dropdown for every decision, grouped as your planned analysis, reasonable alternatives and common shortcuts. `qsim.compare.whatif` recomputes all genes on every change.
5. **Ask.** `qsim.ask.Asker`: the local model (Ollama `qwen2.5:7b`, if running) only reads the question. The engine's checked templates write the answer. The panel shows:
   - who read the question;
   - which engine tool answered;
   - every value the engine supplied.
6. **What to check first.** The top of the investigation queue.

The page types no numbers. Every figure comes from those files or a live engine call. `tests/test_app.py` checks this:
- it traces the card numbers back to `explain.json`;
- it matches the what-if results against the engine;
- it checks that the page markup contains no typed digits;
- it scans every screen for statistics jargon.

Options:
- `--no-model`: keyword routing only;
- `--port`;
- `--results <dir>`.

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

### Known answers: Untergasser dilution series

LightCycler 480, three mixes, triplicates, 188 comparisons.

| Efficiency choice | Median error vs true ratio |
|---|---|
| Standard curve | 7.7 % |
| LinRegPCR mean | 7.9 % |
| Assume 100 % | 11.4 % |
| Each well's own | 89 % |

- **Disagreement among analyses flags wrong answers.** When the defensible analyses disagree most (top quarter of spread), the standard answer is off by 31.5 % against 5.9 % otherwise (Spearman 0.50). Within each input level the correlation is 0.40–0.52 (p < 0.02), except at the lowest step, 0.7 → 0.2 ng (0.26, not significant).
- **Coverage fails the 90 % bar.** The truth falls inside the range of defensible analyses in 40 % of cases, and inside the baseline 95 % CI in 73 %. The truth is nominal ng; digital-PCR truth is the next step.
- **Replicate errors are caught and fixed.** A 3-cycle error in one replicate is caught every time by the half-cycle rule, and dropping it reduces the error from 90 % to 1.4 %. The rule also flags 7 % of clean triplicates.

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

These come from the review, in priority order:

1. Use digital-PCR truth and all three instruments for the known-answer test.
2. Run a no-difference test on Ruijter's 380-replicate plate.
3. Make the CIs cover the truth, using delta-method efficiency uncertainty with a run effect.
4. Have an outside qPCR scientist sign off every tier.
5. Add Cq method and baseline choices, a Cq-only import, paired tests and ANOVA.
6. Score the detectors on real faults (competimer, inhibitor series) with a Poisson-aware replicate rule.
7. Build PlateSim, a generative plate model fitted on Untergasser LC480 and tested on held-out instruments, and a design planner from it.

## Data and licence

- Vermeulen et al. 2009 / Ruijter et al. 2013 (CC BY 4.0), fetched SHA-256-pinned by qPilot.
- Untergasser, van der Hoff and Benes, via the RDML consortium (MIT), in `data/untergasser/`.
- Code: Apache-2.0.
