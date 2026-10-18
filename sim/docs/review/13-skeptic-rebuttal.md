# SKEPTIC: qPilot is a useful sensitivity analysis but not yet a convincing simulator

## What the advocate gets right

- **The engine is real and reproducible.** It runs all 22,599 analyses with none skipped. Every run logs the input SHA-256 and a grid hash, and the baseline matches qPilot to 1e-12.
- **Reference genes are the right target.** Changing them alone flips 31 calls, and the literature agrees this is where results go wrong.
- **The permutation result is honest and important.** It finds 57 of 58 genes associated with the group. The calls are fragile at the 2-fold line, not in their significance.
- **I found no tool that varies analysis choices together and reports which calls change.** One exception is in point 3: all reference subsets have been searched before. Clarida's methods pages describe frozen settings and no comparison of results.
- **Both of the advocate's concessions are correct.** Mann-Whitney at 3 vs 3 has a smallest p of 2/20 = 0.1. Multiple-testing flips grow with panel size.

## Where it fails in front of an experienced qPCR reviewer

**1. The advocate's own definition of "simulator" rules out the headline result.**
- ADEMP needs a data-generating mechanism and a known true value (https://doi.org/10.1002/sim.8086).
- The Vermeulen multiverse has neither: these are real tumours with an unknown truth.
- Only the fault injection (the fault is known) and the Untergasser dilutions (the ratio is known) meet the definition.
- A reviewer trained on MIQE will call it a sensitivity analysis, and they will be right. We should use that word first.

**2. The known-answer test the advocate calls "not yet done" has already been run, and it fails his own pass bar.**
The file is `results/validation_untergasser.json`: 711 wells, 41 assays, 188 comparisons, 7,280 analyses.
- **Truth inside the range of defensible analyses: 64.4%.** The advocate's pass mark is 90% or more.
- **Truth inside the baseline 95% CI: 73.4%.** The intervals the advocate wants to put on every result are too narrow.
- **A wider spread does not mean a wrong answer.** The rank correlation between spread and error is 0.118 (p = 0.106). Median error is 7.5% in the top quarter of spread and 7.9% everywhere else. The core product claim, "fragile means warning", has no support on known-answer data.
- **Bias does pass.** The LinRegPCR assay-mean option has a median error of 7.9% (about 0.11 log2) and a bias of −5.1%.
  - The standard curve, which the Vermeulen grid leaves out, is the least biased option at −0.6%.
- **This dataset cannot test the main claims.** It is a genomic-DNA dilution with no reverse transcription, no reference genes and no groups. It says nothing about the two decisions that carry 79% of fold-change variance: the group cut (52%) and reference genes (27%).
- **The truth used is the pipetted ng.** The dPCR measurements already in `data/untergasser` were not used.
- **The output has a bug.** Two fields come out as NaN (`median_error_pct_mean_of_three` and `median_error_pct_after_drop_outlier`).

**3. The "46/58 within defensible options" headline is out of date and includes options that should not count.**
- **It counts an option our own validation rejected.**
  - The defensible count is 8,424 = 2 × 3 × 2 × 26 × 27, so two efficiency options were counted: assay-mean and per-well.
  - `src/qsim/decisions.py` now demotes per-well efficiency "on evidence", because it had an 89.1% median error on Untergasser.
  - The headline must be rerun.
- **The reference sets are chosen by size, not by stability.** The 26 "defensible" subsets include all 10 pairs, with no check of geNorm M or V on this data.
  - The tool's own detector reports that HMBS/UBC and HMBS/HPRT1 differ between groups.
  - A reference pair that differs between groups is wrong, not a fair alternative. Counting its flips makes the calls look more fragile than they are.
- **Trying every reference subset is not new.** Chervoneva et al. 2010 evaluated every subset with bootstrap (https://pmc.ncbi.nlm.nih.gov/articles/PMC2889935/). Drop "nobody has done this" for that decision.

**4. The biggest driver changes the question, not the analysis.**
- The MYCN cut explains 52% of variance and flips 17 calls on its own.
- It moves tumours between groups, so the true fold change is different under each cut. A flip there is a different question being answered.
- Bench experiments have designed groups (treated vs control) and no cut.
- Report it separately, or the reviewer will throw out the whole table.

**5. The 85% detection rate is almost entirely one fault type** (from `results/benchmark.csv`).
- **Reference shifts dominate.** They are 40 of the 46 trials that changed a call, and 34 of them were detected. The other five fault types together supplied 6 trials, 5 detected.
- **The no-template-control fault adds nothing.** It was detected 20 of 20 times but changed a call 0 times, so it is not part of the 85%.
- **Changing a call is too easy a test.** A 0.3-cycle shift changed a call in 20 of 20 trials, because 7 of the 40 calls sit within one SE of the 2-fold line. On 58 genes, almost any small push changes some call.
- **False alarms are not measured, and clean data is already noisy.**
  - The clean plates already produce 128 issues, 116 of them (91%) with no demonstrated effect, plus 11 no-template-control flags.
  - Row and edge faults add 1.4 to 2.55 extra findings elsewhere per trial.

**6. The "only when 2+ choices change together" flips are small changes adding up, not interactions.**
- The largest pairwise interaction explains 1.5% of variance, and the top five together explain 3.9%.
- The 19 genes flip because two small moves add up across the 2-fold line. A fold change with a confidence interval shows the reviewer the same thing.
- Say "small choices add up", not "interactions that one-at-a-time checks miss".

**7. The bench-scale results mostly show that n = 3 has no power.**
- At 3 vs 3, Welch's test has only 2 to 4 degrees of freedom, Mann-Whitney cannot reach significance, and BH correction over 58 genes removes every call. A reviewer will say we rediscovered that n = 3 is too small.
- The 6 vs 6 result (reference genes alone flip 10 of 11 calls) is the one we can use. It rests on only five draws; run 50 or more and report intervals.

**8. The severity citations are overstated.**
- **The 42% figure comes from microarrays, not qPCR.** It covers 986 microarray datasets, counts any ANOVA p < 0.05 and has no minimum effect size (https://pmc.ncbi.nlm.nih.gov/articles/PMC7473940).
- **The 93.2% figure is one simulated worst case.** It is a single row of Hampton 2025 Table 6: 5 vs 5, target–reference correlation 0.9, reference gene shifted by 1 SD (https://pmc.ncbi.nlm.nih.gov/articles/PMC12666847/). It is not a rate across the field. Give the conditions or drop it.

**9. Clarida's "no live preview" is a principle, not a gap.**
- Its founders wrote MIQE and geNorm, and they froze analyses on purpose to prevent p-hacking. Attacking that invites the reply that qPilot shows 22,599 ways to reach the answer you want.
- Clarida already calls Cq from raw curves by threshold, SDM or LinRegPCR (release 2026.9, https://clarida.bio/changelog/2026-9).
- qPilot has no threshold or baseline choice, which is the decision practitioners actually argue about.

## Rating

| What is rated | Score | Why |
|---|---|---|
| Is the problem real? | 7/10 | Real, but the citations above overstate it, so not 8 |
| As a sensitivity-analysis tool on raw two-group data | 6/10 | Exhaustive and reproducible; tiers and cut need fixing |
| As a simulator that tells a scientist whether their call is right | 3/10 today | Spread neither predicts error nor covers the truth |

## Minimum changes before I accept it as a convincing simulator

1. **Rename it.** Call it "sensitivity analysis across defensible settings, validated by simulation". Keep the word "simulator" for a future generative layer.
2. **Rerun Vermeulen with the current option labels.**
   - Per-well efficiency demoted; standard curve added if the plates allow it.
   - A reference subset counts as defensible only if its geNorm M is below 0.5 (below 1.0 for mixed tissue), its V is below 0.15, and it passes the group-difference detector.
   - Report the group cut separately.
   - Publish how many of the 46 genes survive.
3. **Fix the confidence intervals.** Baseline 95% CI coverage should reach 90% or more on Untergasser with dPCR truth, on at least two instruments. It is 73% now.
4. **Show that fragility predicts error.**
   - Target: AUROC of 0.70 or more for errors larger than 0.26 log2 (20%), on Untergasser and on Ruijter ds_94_4 subsamples.
   - The correlation is 0.12 and not significant today. If it fails, drop the "fragile" verdict.
5. **Run the no-difference test.** On Ruijter ds_380 there should be no "solid" calls, and 1% or fewer of analyses should make any call.
6. **Measure false alarms.**
   - The detector false-alarm rate on unchanged resamples should be 5% or less per plate.
   - Each fault type needs 30 or more call-changing trials.
   - Count only flips of genes that were more than one SE from the 2-fold line at baseline.
7. **Add the decisions practitioners argue about.**
   - Cq threshold and baseline method, and the late-Cq cut-off (35/38/40).
   - Then run on one designed treated-vs-control RT-qPCR dataset with technical triplicates.
8. **Speak their language.**
   - Report in MIQE units: ΔCq and log2 fold change with intervals.
   - Present a scenario table in the style of de Ronde.
   - Have an outside qPCR scientist sign off each option's label, with a citation for each option.
9. **Lock first.** Record the primary-analysis hash before the multiverse runs, and show it in the Analysis Record.

If items 2 to 6 pass, I accept it as convincing. Items 7 to 9 make it very hard to argue with.

Sources:
- https://doi.org/10.1002/sim.8086
- https://pmc.ncbi.nlm.nih.gov/articles/PMC7473940
- https://pmc.ncbi.nlm.nih.gov/articles/PMC12666847/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC2889935/
- https://pubmed.ncbi.nlm.nih.gov/22975077/
- https://clarida.bio/changelog/2026-9
- https://clarida.bio/resources/methods/exploration-and-stored-analyses
- https://patterninstitute.r-universe.dev/ruijter/doc/manual.html

Files are in /Users/gaddamshivateja/Wheel-hack/qpilot-simulator:
- results/validation_untergasser.json
- results/benchmark.csv
- results/benchmark_trials.csv
- results/summary.json
- results/REPORT.md
- src/qsim/decisions.py
- src/qsim/validate.py