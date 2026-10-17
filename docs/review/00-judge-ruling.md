# Judge's ruling: the qPilot Decision Simulator

## 1. Verdict

The skeptic wins on framing and on evidence standards. What exists is a thorough, reproducible sensitivity analysis plus data-perturbation tests, not a simulator. Its one test against known answers (Untergasser, current file) fails the team's own bar: the truth falls inside the range of defensible analyses in only 40.4% of comparisons against a target of at least 90%, and the baseline 95% CI covers it only 73.4% of the time.

The advocate wins on substance, for three reasons:
- Changing only the reference genes still changes 31 genes' calls on the Vermeulen data, and 92% of 3 vs 3 calls in the strict option space.
- Calls that hold across analyses are wrong 4.5% of the time; the rest are wrong 28% of the time.
- No shipping tool, Clarida included, computes whether a conclusion survives the other defensible analyses.

The pitch becomes convincing only after three things happen: the option tiers are cleaned up, the tool passes known-answer and no-difference tests using dPCR as the truth, and a generative plate model is added. Until then, call it a robustness audit, not a simulator.

## 2. Scorecard

| Dimension | Score | Justification |
|---|---|---|
| How serious the problem is | **7** | Normalising to one reference gene gives errors up to 3.0-fold in 25% of cases and 6.4-fold in 10% ([Vandesompele 2002](https://pmc.ncbi.nlm.nih.gov/articles/PMC126239)). But Hampton's 42% figure comes from microarray data, the 93.2% figure is one worst-case simulation row, and RNA quality and reverse transcription cause most of the variation. |
| How well it solves the problem today | **5** | It runs every combination (30,132 analyses in 18 s) and measures exactly which samples and wells each call depends on. But nothing yet links it to the truth: range coverage is 40%, CI coverage 73%, the agreement share adds nothing once p and distance to the 2-fold line are known (AUROC 0.755 → 0.756), and there is no threshold or baseline decision. |
| After the recommended changes | **8** | Validated against dPCR, tested on no-difference data, with cleaned-up tiers, a plate generator and a design planner, it would answer both "is my call right?" and "what should I change?". |
| How convincing it is to an experienced qPCR scientist today | **4** | Output is CLI and CSV in statistics jargon. Groups are defined from the competitor's own data. The headline includes artefacts (Mann-Whitney at n=3, multiple-testing correction over 58 genes), and the fault benchmark is circular. |
| Novelty versus existing tools, Clarida included | **6** | Varying choices together, measuring sample and well influence, and locking decisions in advance are new in qPCR tools. Trying every reference subset ([Chervoneva 2010](https://pmc.ncbi.nlm.nih.gov/articles/PMC2889935/)) and publishing scenario tables ([de Ronde 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5393188/)) are not. |

## 3. Is it a simulator?

**The definition experts accept.** ADEMP ([Morris 2019](https://doi.org/10.1002/sim.8086)) requires a data-generating mechanism with a known true value, the methods under test, and performance measures. qPCR people also expect a mechanism, meaning molecules producing curves.

**What qualifies today:**
- **Planted faults.** These are real plates with faults of known size, which meets the definition. The caveat is that `benchmark.py _shift` edits Cq and N0, not fluorescence, so the planted faults skip curve analysis entirely.
- **Untergasser dilutions.** The ratios are known. Note that `validate.py` uses the nominal ng amounts as truth.
- **3 vs 3 and 6 vs 6 subsampling.** This is checked against the call on all 366 tumours. That call is a reference answer, not the truth.

**What does not qualify:** the Vermeulen sweep of 30,132 analyses. It has no data-generating mechanism and no truth.

**Wording to use publicly:** "**qPilot Robustness Audit**: checks whether your qPCR conclusion survives every defensible analysis setting, and which samples and wells it depends on; validated on known-answer dilution data and planted artefacts."
- "What-if" is fine for general audiences.
- Keep the word "simulator" for PlateSim once its calibration passes.
- With experts, never say multiverse, flip or fault injection. Say "the call changes" and "planted artefacts".

## 4. Who won each contested point

**Evidence note: both sides quoted out-of-date numbers.** The files in `results/` were regenerated at 23:28 today. Quote only these:
- 30,132 analyses, now including standard-curve efficiency.
- Per-well efficiency demoted to common practice.
- **45 of 58** genes change call within defensible options.
- The max-T permutation test finds **58 of 58** genes associated.
- Untergasser: truth inside the defensible range **40.4%** of the time.
- Untergasser: spread-versus-error Spearman correlation **0.504** (p=2e-13).

| Point | Winner | Why |
|---|---|---|
| "It's not a simulator" | Skeptic | By the advocate's own ADEMP definition, the headline sweep has no mechanism and no truth. |
| Built-in artefacts at 3 vs 3 | Skeptic on the headline, advocate on substance | Exact Mann-Whitney at 3 vs 3 has a minimum p of 0.1, and multiple-testing changes scale with the 58-gene panel. Even so, changing only the reference genes still changes 92% of 3 vs 3 calls in the strict option space. |
| Which options are defensible | Skeptic | The 26 "defensible" reference subsets include unscreened pairs, and the tool's own detector says HMBS/UBC and HMBS/HPRT1 differ between groups. `decisions.py` still lists Mann-Whitney and dropping wells below 10 copies as defensible. |
| Groups defined from the data (MYCN cut) | Skeptic | Changing the cut changes the question being answered, not the analysis, and it carries 54% of variance. With the cut fixed, reference genes alone still change 13 of 40 calls. |
| "Fragile means wrong" | Split | Fragile calls are wrong 6.2× and 3.4× as often as robust ones, and requiring 95% agreement cuts false calls on no-difference splits from 2.5% to 0.17%. But the agreement share adds no predictive value beyond p and distance to the 2-fold line. |
| Untergasser coverage | Skeptic | Coverage is 40.4% against a 90% bar. The spread–error correlation now reads 0.50, which looks good for the advocate, but it is probably driven by input amount: spread and error both grow at 0.2 ng. It is unproven until rerun separately for each input level. |
| Fault benchmark is circular | Skeptic | The no-template-control score is guaranteed by construction, and the reference-shift fault and its detector use the same group mask. 40 of the 46 trials that changed a call were reference shifts, and the 85% detection rate (39/46) has a Wilson 95% CI of 72–92%. The false-alarm rate is unmeasured. |
| "Interactions" | Skeptic | The largest pairwise interaction is 1.55% of variance (flagged × refs). These are small additive effects crossing the 2-fold line together. |
| Severity citations | Skeptic | The 42% figure is from 986 microarray studies ([PMC7473940](https://pmc.ncbi.nlm.nih.gov/articles/PMC7473940)). The 93.2% figure is one row: 5 vs 5, correlation 0.9 ([PMC12666847](https://pmc.ncbi.nlm.nih.gov/articles/PMC12666847/)). |
| Novelty | Split | Chervoneva 2010 already searched every reference subset. Reporting per study whether the conclusion survives, together with influence analysis, is new. |
| "Clarida could copy it" | Skeptic on the code, advocate on the moat | It is 3,734 lines under Apache-2.0. Only independence and published validation are defensible. |
| "No live preview" is a gap in Clarida | Skeptic | It is a deliberate anti-p-hacking principle. Attacking it invites the reply that qPilot offers 30,000 ways to reach the answer you want. |

## 5. Clarida versus qPilot

**What Clarida really does:**
- A five-stage workflow: Define, Design, Execute, Analyze, Report.
- 74 locked, versioned settings. "Compare with…" compares setting values, not results ([settings sets](https://clarida.bio/resources/methods/settings-sets)).
- No live recomputation, by design ([methods](https://clarida.bio/resources/methods/exploration-and-stored-analyses)).
- Since release 2026.9, reads native instrument files and calls Cq by threshold, SDM or LinRegPCR ([changelog](https://clarida.bio/changelog/2026-9)).
- Eight statistical tests, a MIQE score, and a free geNorm tool with on/off checkboxes per sample and gene ([genorm](https://clarida.bio/tools/genorm)).
- An MCP server is on its planned list.
- The closest it comes to simulation is a blog post ([Ruijter & van den Hoff](https://clarida.bio/blog/why-use-the-real-pcr-efficiency)) and a mock card on its homepage ("excluding 4 of 378 flagged wells does not change significance"). The mock card shows the conclusion their own users want verified.

**What qPilot does differently:**
- It computes whether the call survives the alternatives, not just which settings were chosen.
- It measures exactly how much a call depends on single samples and wells.
- It tells you which decisions to lock in advance.
- It is local-first and open source, and its MCP server is already built.

**What to copy:**
- Clarida's settings vocabulary: Cq method, baseline, aggregation, efficiency mode.
- One frozen primary analysis, with the robustness report attached to it.
- Conclusion cards in plain words with Accept/Edit buttons.
- A MIQE checklist score.
- A free, no-account tool: "Does my call survive?"
- Paired tests and ANOVA.

**Answer to "Clarida could add this":** "Yes, and they should. But a vendor grading its own pipeline is not an audit. qPilot is the independent, open check that runs on any RDML file, including Clarida's export, offline, with its validation results published. Our moat is validated evidence and independence, not code."

Be honest internally: if Clarida ships this with the credibility of MIQE's authors, a pure feature race is lost. Aim at core facilities, journals and regulated labs, or at partnering.

## 6. Why nobody has built this yet

1. **Data access.** Instruments export one Cq per well, and few papers share raw curves ([HEROIC 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10158759)). MIQE 2.0 only began asking vendors to allow raw-data export in 2025 ([Bustin 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/)).
2. **The field's benchmark suggested analysis was solved.** [Ruijter 2013](https://pubmed.ncbi.nlm.nih.gov/22975077/) varied only curve analysis, on this same dataset, and found results robust. It held reference genes and grouping fixed, and those two carry 27% and 54% of fold-change variance here.
3. **The method lives in another field.** Multiverse analysis comes from psychology ([Steegen 2016](https://doi.org/10.1177/1745691616658637), [Simonsohn 2020](https://www.doi.org/10.1038/s41562-020-0912-z)). In qPCR, sensitivity checks appear only as one-off papers: de Ronde's scenarios A–E, Hastings' seven efficiency methods, and [Auto-qPCR's](https://pmc.ncbi.nlm.nih.gov/articles/PMC8556264/) sweep of the SD cut-off.
4. **Incentives.** Vendors sell one trusted answer, and Clarida treats recomputation as a p-hacking risk.
5. **Compute was never the barrier.** The full sweep takes 18 s on a laptop.

Caveat: a failed search is not proof that no such tool exists.

## 7. Theoretical simulators to adopt (ranked)

**1. PlateSim, a generator of whole plates with a known true answer.**

| Layer | Design |
|---|---|
| Biology | log2 expression = μ_g + β_g·group + λ_g·f_s + ε. β is known; reference genes have β = 0 unless the reference-shift fault is planted. |
| Loading | N0 ~ Poisson(c·V·(1+δ)), with δ ~ N(0, 1–5%) as the pipetting error ([Gilson/ISO 8655](https://www.gilson.com/pub/media/docs/Pipette_Specs_Chart_LT380069-12.pdf)). |
| Kinetics | While N < 10⁴: N_{n+1} = N_n + Binomial(N_n, p_n), with p_n = Emax·K/(K+N_n) ([Jagers & Klebaner 2003](https://research.chalmers.se/en/publication/77540)). Above that: deterministic, with efficiency falling as E_n = Emax(1−F_n/Fmax) ([Rutledge 2008](https://pmc.ncbi.nlm.nih.gov/articles/PMC2397388)). Primer loss to side reactions each cycle. |
| Optics | Fluorescence = a·N + a linear baseline (slope N(0.7, 0.2), intercept N(200, 70)) + noise N(0, 1.75), using [Lievens 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3506646/) parameters. |
| Plate | Row, column and edge effects as free Emax shifts, since published effect sizes are unverified. |

- Write the output as RDML so it runs through the real engine.
- Fit at most 6 hyperparameters on Untergasser AMC LC480 data.
- Hold out QuantStudio, StepOne and the Ruijter ds_94_4, ds_380 and competimer sets for testing.
- Reimplement the published equations; do not vendor the GPL code.

**2. Efficiency-uncertainty propagation** ([Bilgrau 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4827196/), delta method). This is the direct fix for the 73% CI coverage.

**3. Design planner from nested variance components** (Tichopad 2009, Kitchen 2010), run through PlateSim. It reports, for each design, P(correct call) and P(the call holds across analyses).

**4. Sobol and Morris sensitivity indices** via [SALib](https://github.com/SALib/SALib) (MIT licence), replacing the ad hoc variance shares.

**5. Multitype competing-template branching** ([arXiv 2603.29549](https://arxiv.org/html/2603.29549v1)), later, for genomic-DNA and primer-dimer faults.

**Not as the core:** AmpSim and pcrsim (curve shapes fitted to data rather than modelled from mechanism, and GPL-licensed), Cobbs 2012 (too heavy), and the term "digital twin".

## 8. Changes ranked by impact on convincing experts

"Night" means it can be done in one night.

1. **Clean up the option tiers (night).**
   - Build:
     - A reference subset counts as defensible only if geNorm M < 0.5 (< 1.0 for mixed tissue), V < 0.15, and the group-difference detector does not flag it.
     - Disable Mann-Whitney whenever its minimum achievable p exceeds α.
     - Make BH the baseline, and label multiple-testing results with the panel size.
     - Report the cut separately, as a question-definition choice.
     - Demote "drop wells below 10 copies" to common practice.
   - Data: Vermeulen.
   - Pass: publish the gene count that survives, whatever it is.
2. **Validate against dPCR truth, by input level (night).**
   - Why: the dPCR table in `data/untergasser` puts nominal adjacent ratios within 0.16 log2 of dPCR from 20 ng to 0.7 ng. At the 0.7→0.2 ng step, one assay reads 1.32× against a nominal 3.5×. Nominal-ng truth therefore cannot tell assay-mean efficiency (7.9% error) from standard curve (7.7%) or assume-100% (11.4%).
   - Build: use dPCR ratios as truth, report 0.2 ng separately, include dPCR's Poisson CI in the coverage test, and use all three instruments.
   - Pass:
     - The preferred efficiency option has median |bias| ≤ 0.15 log2 on at least 2 instruments.
     - The spread–error correlation stays ≥ 0.3 within each input level. If not, drop "spread is a warning".
3. **No-difference test on ds_380 (night).** 1,000 splits at 3 vs 3 and at 6 vs 6. Pass: at most 1% of analysis cells make a call, and none is labelled solid. Note that the true amount is 150,000 copies, not the published 15,000.
4. **Make the CI cover the truth (night).** Use the delta method with a run effect. Pass: baseline 95% CI coverage ≥ 90%, up from 73.4%.
5. **Outside qPCR scientist signs off every option's tier, with a citation for each (this week).**
6. **Add the missing decisions (late-Cq cut-off in one night; the rest in 2 days).**
   - Build: late-Cq cut-off at 35/38/40, Cq method, baseline method, global-mean normalisation ([Mestdagh 2009](https://genomebiology.biomedcentral.com/articles/10.1186/gb-2009-10-6-r64)), and ΔΔCq order of operations.
   - Why: Untergasser Cq ranges from 11.6 to 24.9 while TD0 stays near 25.
   - Pass: efficiency-corrected ratios from curve-based methods stay within 0.15 log2 under every threshold choice.
7. **Show that fragility predicts error, beyond the obvious predictors (2–3 days; needs a Cq-only import).**
   - Data: ds_94_4 subsamples (check the labels, which were reversed in the original) and MAQC C vs D.
   - Pass: AUROC ≥ 0.70, and the agreement share adds at least 0.03 AUROC over p plus distance to the 2-fold line.
   - Also move the 200-draw subsampling runs from the scratchpad into the repo.
8. **Score detectors on real faults, with detectors frozen first (2 days).**
   - Data: competimer, lievens2/3, testdat, and the Untergasser no-template controls.
   - Replace the 0.5-cycle replicate rule, which flags 7% of clean triplicates, with a Poisson-aware rule (39% versus 7% rejected in [Ruijter 2017](https://www.econferences.de/?p=3963)).
   - Pass: sensitivity ≥ 80% and false alarms ≤ 2% of clean wells.
9. **Expert-facing report plus a local-model Ask (night).**
   - Report: one page in MIQE units (ΔCq and log2 fold change with CI, a de Ronde-style scenario table, geNorm M and V plots, curves with threshold and baseline drawn on).
   - Ask: run qwen2.5:7b through Ollama's OpenAI-compatible endpoint, behind the existing validator.
   - Pass, on 50 scripted questions: zero numbers the engine did not produce, correct tool chosen at least 90% of the time, and it works with the network off.
10. **Lock first (night).** Write the primary-analysis hash into the Analysis Record before the sweep runs.
11. **PlateSim (1 week).** It ranks this low only because real known-answer data persuades experts more than synthetic data.
12. **Paired t-test, ANOVA and mixed models (2–3 days).**

## 9. Validation plan on datasets with known answers

| Step | Data | Pass | Fail means |
|---|---|---|---|
| V0 Reproduction | Vermeulen standards, the RDML-Tools tables | Relative difference ≤ 1e-6 | Stop |
| V1 Bias for each decision | Untergasser with dPCR truth; competimer | Preferred efficiency median \|bias\| ≤ 0.15 log2 on 2 or more instruments. Assume-100% bias rises with competitor % (ρ ≥ 0.8). Curve-based options stay within ±0.25 log2 up to 30% competitor | The option ranking is unsupported |
| V2 Coverage | Untergasser dPCR; ds_94_4 subsamples | The CI with truth uncertainty contains the truth at least 90% of the time | Intervals are overconfident |
| V3 Fragility predicts error | ds_94_4, MAQC C vs D at 4 vs 4 | AUROC ≥ 0.70 with lower bound > 0.55, and the agreement share adds value over p plus margin | Drop "fragile" as a predictor and sell the lock advisor instead |
| V4 No-difference data | ds_380; Untergasser same-template ratios | At most 1% of cells make a call, none is solid, and median \|log2\| ≤ 0.15 | False positives |
| V5 Real faults | competimer ≥ 20%, lievens2/3, testdat FX.3/FX.4 | Sensitivity ≥ 80%, false alarms ≤ 2% | 85% is optimistic |
| V6 Invariance | RDML shifted_baseline, matrix_gaps | \|Δ\| < 1e-9; gap wells flagged | Engine bug |
| V7 PlateSim realism | Held-out instruments | KS p > 0.05 on Cq SD versus input, non-detect fraction at ≤ 10 copies, efficiency spread, plateau CV | Don't call it a simulator |

This plan tests measurement and analysis. It cannot validate a biological inference.

## 10. The 12 hardest questions, with answers

1. **"This is a sensitivity analysis, not a simulator."** Agreed, and we call it a robustness audit. The parts that simulate are the planted artefacts with known sizes and the dilution data with known ratios. PlateSim, the generative plate model, is next and will be checked against held-out instruments before we use the word.
2. **"You built a p-hacking machine."** The reverse. The primary analysis is locked and hashed before the sweep runs, and any switch needs a Decision Card that stays in the record. We report the distribution across analyses and never let you pick a branch.
3. **"At 3 vs 3 you've just rediscovered low power."** Partly. We removed Mann-Whitney and the multiple-testing options from that headline. Even so, changing only the reference genes changes 92% of 3 vs 3 calls and 80% of 6 vs 6 calls, because every fold change shifts by up to 1.58×. That is a normalisation problem, not a power problem.
4. **"Your groups come from MYCN measured in the same panel."** True, and the cut is now reported separately as a choice about the question. With the cut fixed, reference genes still change 13 of 40 calls. The headline moves to designed contrasts: Untergasser, then MAQC.
5. **"Does 'fragile' mean 'wrong'?"** Robust calls were wrong 4.5% of the time against 28% for fragile ones, and the filter cut false calls on no-difference splits from 2.5% to 0.17%. But agreement adds nothing beyond p and distance to the 2-fold line, so we sell "what to lock, and why", not a new predictor.
6. **"Your own known-answer test fails."** Yes: 40% range coverage and 73% CI coverage. Part of the reason is that our truth was the nominal ng, and dPCR shows nominal ratios are off by up to 0.16 log2, with the 0.2 ng step unreliable. We are rerunning with dPCR truth and propagated efficiency uncertainty against a 90% bar, and will publish the result either way.
7. **"Your detectors were written for your faults."** Correct, and the no-template-control score is guaranteed by construction. The honest figure is 39 of 46 (95% CI 72–92%), mostly reference shifts. Frozen detectors will be scored on real faults (competimer, inhibitor series), with a false-alarm limit of 2%.
8. **"geNorm solved this in 2002."** geNorm ranks how stable each gene is. It does not tell you whether your conclusion survives the reference sets geNorm would accept, or which tumour it depends on. Twenty-four years later, reference-gene choice is still the leading failure, and Chervoneva 2010 searched every subset but shipped no per-study check.
9. **"Most variance comes from RNA and reverse transcription."** True, and no re-analysis tool can see it, Clarida included. We audit what can be audited, and PlateSim's design planner will use nested variance components to recommend replicates at each level.
10. **"Clarida reads raw curves now and will add this."** It should. An analysis vendor auditing itself isn't independent. qPilot runs on any RDML, including Clarida's export, offline under Apache-2.0, with published validation. If raw curves aren't available, a Cq-only import keeps most of the reference-gene and statistics checks.
11. **"No wet-lab scientist on the team; why trust you?"** Don't trust us, check us. Every number traces to a curve and a hash, the baseline matches the qPilot engine to 1e-12, the validation results are public, and an outside qPCR scientist will sign off every option's tier. Recruiting a wet-lab advisor is this week's priority.
12. **"Why 2-fold? Your own permutation test finds 58 of 58 genes associated."** Exactly. Significance is robust, and what changes is the claim papers actually publish ("over 2-fold"). We lead with log2 fold change and its interval, report the 2-fold claim as one readout, and let users set their own threshold.

Files checked: `/Users/gaddamshivateja/Wheel-hack/qpilot-simulator/results/validation_untergasser.json`, `results/summary.json`, `results/REPORT.md`, `src/qsim/validate.py` (truth = nominal ng), `src/qsim/decisions.py`, `data/untergasser/large_DNA_dilutions_res_dpcr_probe.tsv`.