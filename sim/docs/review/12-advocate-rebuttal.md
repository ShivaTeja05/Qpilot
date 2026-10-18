# Advocate's rebuttal: point by point, with new numbers run today

**What I ran for this rebuttal.** All runs use the Vermeulen RDML with seed 2026. The scripts are in `/private/tmp/claude-501/-Users-gaddamshivateja-Wheel-hack/c8da661c-7b77-4935-b4b4-48e1317df5ba/scratchpad/` (`strict.py`, `smalln2.py`, `cuts.py`, `refs.py`).
- **Strict space.** I removed per-well efficiency, the drop below 10 copies, the Cq 40 substitute, single reference genes and Mann-Whitney.
- **Small-n truth test.** I drew 200 random 3 vs 3 and 200 random 6 vs 6 experiments (MYCN-high vs rest). The reference answer is the prespecified call on all 366 tumours.
- **Null test.** I drew 200 more, with both groups taken from MYCN-low tumours, so every call is false.
- **A known-answer run the skeptic missed.** `/Users/gaddamshivateja/Wheel-hack/qpilot-simulator/results/validation_untergasser.json` covers 711 wells, 188 comparisons with known ratios and 7,280 analyses.

## 1. "Not a simulator": conceded on the word
It simulates analysis choices and data perturbations, not molecules.
- **Fix:** with experts, call it "a robustness audit across defensible analysis settings", which is their vocabulary. Keep the word "simulator" for a generative plate model, built as follows:
  - Poisson loading of molecules into wells, plus Richards-curve kinetics (start from [chipPCR AmpSim](https://rdrr.io/cran/chipPCR/man/AmpSim.html)).
  - Calibrate it on the Untergasser dilution series.
  - Accept it only if KS tests pass on a held-out instrument for Cq SD versus input and for the non-detect fraction at 10 copies or fewer.

## 2. The 3 vs 3 result is partly built in: conceded, but the result survives
- **Mann-Whitney cannot call anything at 3 vs 3.** Our code uses the asymptotic test, whose smallest two-sided p at 3 vs 3 is 0.081; the exact test's is 0.10. The multiple-testing flips also depend on the panel having 58 genes.
- **What happens without these options.** I removed Mann-Whitney, multiplicity and the cut. Changing only the reference set (among subsets of two or more genes) still changes:
  - 912 of 996 calls at 3 vs 3 (92%);
  - 80% of calls at 6 vs 6.
- **Fix:** disable Mann-Whitney below 4 samples per group, and label multiple-testing results "for a 58-gene panel".

## 3. Which options are defensible, and how many each decision has: mostly conceded
- **Per-well efficiency.** Our own known-answer data backs the skeptic. Median absolute fold-change error on Untergasser:

  | Efficiency method | Median absolute error |
  |---|---|
  | Each well's own | 89.1% |
  | LinRegPCR assay mean | 7.9% |
  | Standard curve | 7.7% |
  | Assume 100% | 11.4% (bias +7.0%) |

  **Fix:** mark per-well efficiency "common but biased" in `decisions.py`. `validate.py` already does, so the two files currently disagree.
- **Variance shares depend on the cut range** (confirmed today, strict space):

  | Cut range | Share of fold-change variance from the cut |
  |---|---|
  | 14–16% | 17% |
  | 10–20% | 64% |
  | 5–30% | 83% |

  So retire "52%" as a headline.
- **What does not depend on the range:** 26 of 58 genes change call from the reference-set choice alone, in all three ranges.
- **Option counts.** In a full factorial the "holds" share already weights each option of a decision equally. "Changes call somewhere" is a maximum, though, so it grows with the number of options. That part is conceded.
  - In the strict space it falls from 46 to 38 of 58 genes.
  - **Fix:** report per-decision flip rates and Sobol total effects, and have an outside methods expert sign off the option tiers.
- **No multiple-testing correction in the baseline:** conceded. Make Benjamini-Hochberg the baseline for panels.

## 4. Groups come from the data itself: conceded for the demo
- **The finding survives a fixed cut.** With the cut fixed, reference-set choice alone changes 13 of 40 calls and creates calls in 13 of 18 uncalled genes.
- **The mechanism is not threshold noise.** Changing the reference set shifts every gene's fold change by the same factor:
  - up to 1.58× across sets of two or more genes;
  - up to 1.36× across sets of three or more genes, which still changes 7 of 40 calls.

  This happens because the candidate reference genes differ between the groups. It is the failure [Hampton 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7473940) documents.
- **Fixes:**
  - Define groups by MYCN amplification status, which comes from outside the panel.
  - Re-derive the groups for each reference set.
  - Use designed contrasts: Untergasser, and MAQC ([Canales 2006](https://doi.org/10.1038/nbt1236)) once a Cq-only import exists.
- **Conceded:** variation between tumours overstates how fragile a cell-line bench experiment would be.

## 5. "Fragile" does not mean "wrong": tested today, half conceded
Measured against the call on all 366 tumours:

| | 3 vs 3 | 6 vs 6 |
|---|---|---|
| Calls | 996 | 2,741 |
| Wrong, overall | 25.0% | 21.6% |
| Wrong, fragile (fewer than 95% of analyses agree) | 28.1% (n=864) | 26.5% (n=2,023) |
| Wrong, robust | 4.5% (n=132; Wilson 95% CI 2.1–9.6%) | 7.7% (n=718) |
| AUROC, share of analyses that agree | 0.673 (95% CI 0.637–0.710) | 0.663 (95% CI 0.642–0.684) |
| AUROC, distance to the 2-fold line in SE units | 0.714 | 0.784 |
| Cross-validated AUROC, p + distance, then adding agreement | 0.755, then 0.756 | 0.851, then 0.850 |

**Null splits.** At the baseline, 2.5% (3 vs 3) and 3.3% (6 vs 6) of gene tests produce a call, all false. Requiring 95% of analyses to agree cuts this to 0.17% and 0.37%.

**Verdict against the skeptic's own tests:**
- **Passed:**
  - Fragile calls are wrong 6.2× (3 vs 3) and 3.4× (6 vs 6) as often as robust ones, against a 2× bar.
  - The AUROC's lower bound clears 0.55.
  - False calls on null data stay under 1%.
- **Missed:** an AUROC of 0.70.
- **The skeptic is right about the main point.** The agreement share adds nothing once the distance to the 2-fold line and the p-value are known.
- **The 95% filter is harsh.** It keeps only 13% of 3 vs 3 calls.
- **Coverage fails.** The span between the lowest and highest fold change across defensible analyses contains the 366-tumour fold change only 54–58% of the time. The baseline 95% CI contains it 96% of the time. On Untergasser it is 64.4% versus 73.4%. A wider spread does not signal a larger error there either (Spearman 0.118, p=0.106).
- **Fixes:**
  - Stop presenting the span as a measure of uncertainty. Lead with the effect size and its CI.
  - Use the sweep to explain which choice moves a call and by how much, and to say which choices to lock in advance.
  - Repeat this test against lab-known answers.

## 6. Missing decisions: conceded, partly covered
- **Already covered.** `validate.py` varies standard-curve efficiency and five replicate rules, including the 0.5-cycle drop.
  - Dropping the outlying replicate does not help: error is 13.0% versus 12.8% for the mean of logs.
- **Still missing:**
  - Cq method and threshold;
  - a late-Cq cut-off of 35, 38 or 40;
  - global-mean normalisation ([Mestdagh 2009](https://genomebiology.biomedcentral.com/articles/10.1186/gb-2009-10-6-r64)), which a 58-gene panel qualifies for;
  - paired and ANOVA designs;
  - the order of operations in ddCq.
- **Out of scope.** No re-analysis tool can capture RNA quality or reverse-transcription variation, Clarida included. We should say so.

## 7. The fault benchmark is circular: conceded
- **Conceded by construction:**
  - The 100% detection of contaminated controls is guaranteed.
  - The reference-shift fault and its detector use the same group mask.
- **Unplanted real data.** In Untergasser, 32 of 96 wells with 0 ng of DNA amplified. The MIQE 2.0 rule (control within 5 Cq of the samples) flags 4 of 16 assays. We need melt-curve labels before calling that sensitivity.
- **Replicate detector.** It caught all 300 planted 3-cycle single-well faults. But it also flagged 7.4% of clean triplicates, which fails the 2% bar.
- **Fixes:**
  - Run step V5 on competimer, lievens and testdat with the detectors frozen.
  - Quote the headline as 39/46 (Wilson 95% CI 72–92%).

## 8. Nothing new: partly rebutted
- **The rebuttal.** geNorm ranks how stable each reference gene is; it does not tell a lab whether its own conclusion changes. 24 years after geNorm, the average reference gene is still differentially expressed in about 42% of 986 studies (Hampton 2020).
- **What is new is the per-study answer.** For example: "this call is lost under 13 of 26 defensible reference sets; lock the reference genes and the cut."
- **Who owns the data: a fair point.**
  - Vermeulen is Clarida's founders' data.
  - Van den Hoff co-authored the Untergasser set and also writes for Clarida.
  - So move the headline to MAQC.

## 9. Adoption: conceded
- A Cq-only import comes first; it also unlocks MAQC.
- Plain-language verdicts exist, but only in the CLI and CSV output.
- **Fix:** a one-page report in MIQE terms, and letters of intent from three core facilities.

## 10. Clarida could copy it: conceded on code
- **Conceded.** A batch robustness report on a locked run fits Clarida's "no live preview" principle.
- **The moat:**
  - published validation, with the section 5 table as a start;
  - independence, since the auditor is not the analysis vendor;
  - local-first and Apache-2.0;
  - an MCP server that is already built, while Clarida's is only on its planned list.

## Revised claim
**Today.** For one raw-curve qPCR study, qPilot runs every combination of 7 analysis settings (22,599 analyses in 14 s). It reports which settings change which calls, and which samples and wells each call depends on.
- **What it can claim:**
  - On real tumour data, the reference-set choice alone changes 92% of 3 vs 3 calls, by shifting every fold change up to 1.58×.
  - Calls that hold in at least 95% of defensible analyses are wrong 4.5% of the time, against 28% for the rest.
  - On null splits, that filter cuts false calls from 2.5% to 0.17%.
- **What it cannot claim:**
  - It does not predict wrong calls better than the distance to the 2-fold line does.
  - Its spread across analyses is not a confidence interval.
  - Its fault benchmark is not independent of its detectors.

**After the fixes.** These are the fixes listed above:
- a calibrated generative plate model;
- a Cq-only import;
- known-answer tests on MAQC and Untergasser;
- the missing decisions;
- option tiers signed off by an outside expert;
- detectors frozen before scoring on real faults (V5).

With those in place it becomes a validated, independent robustness audit to run before publication. It also becomes the only qPCR tool we have found that reports whether a conclusion survives the other defensible analyses.