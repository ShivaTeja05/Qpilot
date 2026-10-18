# Closing the V2 coverage gap: what the field does, and what to test

18 Oct 2026. The calibration addendum in `30-validation-round-2.md` raised V2 coverage only from 83 % to 88 %, and it did so by widening the interval. This note collects three things:

- what published methods and commercial tools do about efficiency bias and interval coverage;
- what our data show without looking at the truth;
- a ranked test plan whose estimators are fixed here, before anything is scored.

Sources: two literature searches and checks on the data, using no truth. I opened one source myself (Košir 2017). The rest were opened by the research agents unless marked UNVERIFIED.

## Short answer

- **The bias cannot be fixed from another plate.** Every efficiency offset we can see is specific to its plate and template, so a correction has to come from inside the run.
- **The miss is mostly variance the interval leaves out.** The same tubes give different answers on different plates and instruments, by 0.1–0.2 log2. That is visible without any truth. No published tool models it, and it is the most promising thing to add.
- **Coverage rests on very few truths.** 168 of the 197 cases rest on just 4 genomic dPCR values, so the coverage figure behaves like a handful of trials. Any result should carry a confidence interval over truths.
- **No method can guarantee 90 % for a new plate from 3 plate groups.** Prediction intervals need t with 1 df (12.7), and conformal methods need ≥ 10 groups. So the honest claim is "measured coverage on these plates", not a guarantee.

## What the data show without the truth

| Check | Result | Consequence |
|---|---|---|
| LinRegPCR settings: outlier rule mean/include, keep no-plateau wells, exclusion range 0.10 | Assay-mean efficiency moves by a median of 0.000 log2 on AMC and at most −0.006 on DKFZ | Not the cause. |
| Exponential-phase window length (`maxCycExpPhase` 9 → 7 → 5) | E falls by up to 0.013 (AMC) and 0.039 (QuantStudio) | A shorter window makes E lower, the wrong direction. 9 is already the longest. |
| qPilot's LinRegPCR version | Vendored rdmlpython **3.0.2**, the TD0-anchored window from Untergasser 2026 | The newest LinRegPCR, which the literature ranks best, is already what we run. |
| Individual well efficiency by input level, AMC | Within ±0.007 log2 of the run mean at every level | No high-input inhibition, so a per-sample efficiency will not help. |
| Standard-curve efficiency (run's own nominal dilution, leave-pair-out) minus LinRegPCR | AMC +0.030 (+0.020 for assays passing QC); DKFZ −0.010; LC480 Feb 2024 +0.003; QuantStudio −0.045; StepOne −0.012 | Same signs as the dPCR-fitted offsets (AMC +0.014, DKFZ −0.011). The run's own dilution sees its plate's offset; another plate does not. |
| AMC vs DKFZ, same genomic tubes, 8 months apart | Median estimates differ by +0.00 (20→7), +0.12 (7→2), −0.23 (2→0.7), −0.17 (20→0.7), −0.23 (0.7→0.2) log2 | A plate×pair component the interval does not include. The run effect is estimated within each plate, so it cannot see this. |
| LC480, QuantStudio, StepOne, one dilution series | Median SD across the three instruments is 0.13 log2 per pair | The same component, between instruments, plus dilution error: only QuantStudio and StepOne share reaction tubes. The LC480 plate used its own premixes, and its 0.2 and 0.5 ng/µl levels came from a separate 1:100 dilution. |
| Distinct truths behind the 197 cases | 13. The 4 genomic pairs each carry 42 cases. | A truth error of 1.5 SE on one pair fails up to 42 cases together. |
| dPCR per tube | Relative to nominal, dPCR puts the 2 ng tube 0.06 log2 low. F_109 and K_219 differ by 0.04–0.15 per tube. | The "2 ng tube disagreement" in the addendum is within about 1.5 truth SE. It may be truth error rather than qPCR error. |

## What the literature and the tools do

### Efficiency bias

- **Ruijter 2013 benchmark** (Methods 59:32, full text paywalled; ranks recovered from the PMCMRplus `qPCR` dataset).
  - Bias ranks: standard-Cq 1.92, Cy0 1.98, MAK2 5.02, LRE-E100 5.27, PCR-Miner 5.98, LinRegPCR 6.54, 5PSM 8.97. LinRegPCR was best on precision and resolution.
  - Ruijter & van den Hoff 2025 ([IJMS](https://pmc.ncbi.nlm.nih.gov/articles/PMC12733170/)) show the real dilution steps were 8–9.9-fold, not 10-fold. The standard curve's bias win was "circular reasoning", and LinRegPCR ranks best once that is corrected. Our dPCR truth avoids that circularity.
- **Untergasser 2026** (IJMS 27:2717, [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC13026326/)).
  - The TD0-anchored window ranks 4th on bias, against LinRegPCR's 8th, with the best mean rank overall. We already run it.
  - "Curve E below dilution E" most often points to baseline-correction problems or machine-processed data.
  - The LightCycler 480 II reads Ncopy about a quarter low, against 0.98–1.05 on QuantStudio and StepOne. No cause is given.
- **Tellinghuisen & Spiess.**
  - 2015 (Anal Chem, abstract): single-reaction exponential-window methods are "inherently low-biased in E".
  - 2019 ([BDQ](https://pmc.ncbi.nlm.nih.gov/articles/PMC6554483/)): recommends a single-step 4-parameter log-logistic + baseline fit on raw fluorescence, with a Cy0 or relative-threshold marker. Calibration curves were nonlinear in 4 of 6 datasets, with no consistent direction.
- **Ruijter 2009** ([NAR](https://pmc.ncbi.nlm.nih.gov/articles/PMC2665230/)). An underestimated baseline gives a low E; the E error is about the size of the baseline error, and the N0 error is about 10 times larger.
- **Švec 2015** ([BDQ](https://pmc.ncbi.nlm.nih.gov/articles/PMC4822216/)). Efficiency differs significantly between instruments, LC480 included. This matches our plate-specific offsets.
- **The Untergasser genomic dilutions are made independently from one stock, not serially.** Per-tube pipetting error is therefore independent between tubes, which fits step errors that are not proportional to ΔCq. dPCR measured the same tubes, so this matters for nominal truth, not dPCR truth.

### Interval coverage and the tools on the market

No tool reports how often its interval contains an independent truth. qPilot's round-2 interval already does more than any of them.

| Tool | Efficiency uncertainty | Run, plate or sample effect | Coverage checked |
|---|---|---|---|
| qbase+ (Hellemans 2007, [Genome Biol](https://pmc.ncbi.nlm.nih.gov/articles/PMC1852402/)) | Delta method, propagates SD(E) | Inter-run calibrators, error propagated; no random effect | No |
| REST 2009 | Point value inside randomisation | None | No |
| GenEx | CI on efficiency | Nested-ANOVA variance per step (Pro) | No |
| QuantStudio D&A, RQ module | Fixed user entry | None; RQ Min/Max cover "only the test samples" | No |
| CFX Maestro | UNVERIFIED (formulas not extracted) | — | No |
| LinRegPCR web (Untergasser 2021) | Per-target mean, outlier removal; no CI | None | No |
| qpcR `ratiocalc` / `propagate` | Monte Carlo, permutation, Taylor with covariances | None | No |
| MCMC.qpcr (Matz 2013), Steibel 2009 | Fixed input | Sample random effect | Null p-values only |
| Bilgrau 2016 ([BMC Bioinf](https://pmc.ncbi.nlm.nih.gov/articles/PMC4827196/)) | Fitted jointly; delta / Monte Carlo / bootstrap | Sample random effect | False-positive rate only (delta method 5.3 % at α 5 %) |

**Closest to qPilot:** qbase+ for error propagation, and GenEx for variance components.

**Metrology already treats the tube × method term as real and dominant.**
- NIST certifies SRM 2372a by ddPCR with 10 assays. Its Bayesian model has between-assay, between-dataset and pipette-bias terms ([SP 260-189](https://doi.org/10.6028/NIST.SP.260-189)).
- In Table D-1, 16 commercial qPCR kits measured ratios between the SRM components. Against ddPCR, the kits spread 0.25–0.32 log2 SD. Each kit's own ±1.96u interval covered the ddPCR ratio in only 56 % and 31 % of kits; this is the research agent's own calculation from the table.
- CCQM-P103.1 ([Devonshire 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4906133)) needed a coverage factor k = 4.3 with 3 ratios. Only two labs put efficiency into their uncertainty budget.
- MIQE 2.0 (Bustin 2025, abstract) asks for efficiency-corrected quantities "reported with prediction intervals".

**Methods for intervals with few groups, and why they fail here.**
- **HKSJ prediction interval** (IntHout 2016, [BMJ Open](https://pmc.ncbi.nlm.nih.gov/articles/PMC4947751)): t with k − 2 df, which is 12.7 at k = 3. Honest, but unusably wide.
- **Conformal over groups** (Dunn, Wasserman & Ramdas 2023, JASA): needs ≥ 10 groups for a finite-sample 90 % guarantee.
- **Wild cluster bootstrap:** only 8 distinct draws at G = 3.

### A check that changed a plan

One agent cited Košir 2017 as "QX200 droplet volume varies 4.4–5.8 % between wells". I planned to use that as an outside value for the dPCR well error. I opened the paper ([ABC 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5670190/)):

- **What 5.84 % is.** It is the RSD of individual droplet volumes (0.739 nL), not of well means.
- **Well-to-well effects.** The paper found no significant well-to-well (intra-cartridge) effect.
- **Systematic volume bias cancels in ratios.** The 13 % volume bias is systematic, so it cancels in a ratio of two tubes.

**So there is no sound outside number to replace our estimated dPCR well SD (0.048 log2), and that test is dropped.**

## Not allowed, and why

These were suggested in the literature searches. Each would fit something on the truth being scored.

- **Per-tube offset or tube×method variance from other runs' or plates' residuals against dPCR.**
  - The 38 AMC runs share AMC's truth, and DKFZ shares the same tubes' truth, so either would carry the scored truth's error into its own interval.
  - The only truth-disjoint source is the instrument comparison, with nominal truth and 13 cases, which is too thin.
- **Conformal or prediction-interval scaling fitted on other groups' errors.** This is allowed in principle, but with 3 groups it gives either no guarantee or t₁ = 12.7.

## Test plan (estimators fixed here, before any scoring)

**Applies to every test:**
- **Bar.** The round-2 V2 pass rule, unchanged.
- **What is reported.**
  - coverage with truth SE over all 197 cases;
  - coverage per plate group and per truth pair;
  - a 90 % cluster-bootstrap interval for coverage, resampling the 13 truths (2,000 draws, seed 2026);
  - median half-width;
  - median \|error\| per machine.
- **What is kept.** Every variant goes into `validation_dpcr.json`. Nothing is retuned after scoring.
- **Tiers.** Tiers do not change. If an estimator that is not the baseline does better, that goes to the outside reviewer.

**P1. A plate×pair term, estimated without truth. Highest priority, about 45 min.**
- **Unit.** One physical tube pair measured on two or more plates:
  - the genomic series on AMC and DKFZ, all 6 pairs, including those dPCR could not resolve, since no truth is used;
  - the volume series on the three instruments, 5 pairs.
- **Plate value.** For each pair and plate, m_p is the median baseline estimate over runs. s_p² is the median over runs of (se_rep² + ΔCq²·se_log2E²), divided by the number of runs.
- **Pooled term.** For each pair, take the sample variance of m_p across plates minus the mean s_p². The term is σ_pp² = max(0, mean of that excess over pairs).
- **Interval.** Variance += σ_pp². Everything else is the round-2 interval.
- **Held out.** AMC and DKFZ use σ_pp from the volume series; the volume plates use σ_pp from the AMC and DKFZ series.
- **Variant.** One σ_pp pooled from both series. It is truth-free, so in-sample is allowed, and it is reported.
- **Caveat.** Upstream says the AMC and DKFZ plates used the same tubes, but the research found the README ambiguous. If they are different tubes, the AMC–DKFZ term also contains dilution error. That is fine for an interval, but the description would change.

**P2. The run's own standard curve as the calibrator. About 30 min.**
- **Estimator.** The existing `std_curve` option: efficiency from the run's other nominal dilution levels, leave-pair-out, so no dPCR is used.
- **Interval.** Slope SE as se_log2E, plus a held-out run effect re-estimated on `std_curve` rows.
- **Realistic check (descriptive, 4 runs).** On DKFZ, quantify the genomic pairs with the efficiency from the same run's amplicon standard. A lab would use a separate standard, and the addendum showed the amplicon offset differs from genomic DNA.

**P3. P2 plus P1's term. About 10 min after P1 and P2.**

**P4. Curve-fit Cq. About 2–3 h; only if time allows.**
- **Fit.** A single-step 4-parameter log-logistic + baseline fit on raw fluorescence (Tellinghuisen & Spiess 2019), with Cy0 as the Cq.
- **Efficiency.** Quantify with the LinRegPCR assay mean, and separately with the standard-curve efficiency.
- **Data.** Raw and baseline-corrected curves are available from the vendored rdmlpython.
- **Why.** It tests the "machine-processed LC480 data / baseline" explanation.

**Likely outcome, before scoring:**
- **P1** is the only test aimed at the component we can see is missing, so it is the most likely to reach 90 %. The price is width: the volume instruments alone suggest σ ≈ 0.13 log2.
- **P2** targets the bias. A pass would argue for the standard curve as the baseline, which is a tier question for the reviewer.
- **P4** is exploratory.

## Results of P1–P3 (run 18 Oct, after this plan was committed as 4ee0c45)

The numbers are under `coverage_gap_tests` in `results/validation_dpcr.json`, and `qsim validate` prints them. The estimators are exactly as fixed above, and every round-2 and addendum number is unchanged.

| Test | Coverage (197 cases) | 90 % CI over the 13 truths | Median half-width, log2 (fold) | Bar |
|---|---|---|---|---|
| Round 2, for reference | 83.2 % | 75.9–89.1 % | 0.251 (±1.19×) | Fail |
| **P1** plate×pair term, held out (primary) | **92.4 %** | 89.1–95.6 % | 0.410 (±1.33×) | **Pass** |
| P1 variant: one term from both series | 91.4 % | 86.8–95.2 % | 0.383 (±1.30×) | Pass |
| P1 without the lowest tubes (post hoc, not counted) | 85.8 % | 79.7–91.0 % | 0.298 (±1.23×) | Fail |
| **P2** run's own standard curve | **92.4 %** | 85.9–94.9 % | 0.344 (±1.27×) | **Pass** |
| **P3** standard curve + plate×pair term | **96.4 %** | 93.2–98.3 % | 0.474 (±1.39×) | **Pass** |

Coverage by plate:

| Test | AMC (152) | DKFZ (32) | LC480 Feb 2024 (5) | QuantStudio (4) | StepOne (4) |
|---|---|---|---|---|---|
| Round 2 | 81.6 % | 87.5 % | 100 % | 75 % | 100 % |
| P1 | 91.4 % | 93.8 % | 100 % | 100 % | 100 % |
| P1 without lowest tubes | 84.9 % | 87.5 % | 100 % | 75 % | 100 % |
| P2 | 96.7 % | 81.2 % | 100 % | 0 % | 100 % |
| P3 | 97.4 % | 93.8 % | 100 % | 75 % | 100 % |

Median \|error\| by machine, log2. P1 changes only the interval, so its errors are round 2's.

| Machine | Cases | Assay mean (round 2, P1) | Standard curve (P2, P3) |
|---|---|---|---|
| LightCycler 480 AMC | 157 | 0.121 | 0.089 |
| LightCycler 480 DKFZ | 32 | 0.218 | 0.245 |
| QuantStudio 6 Flex | 4 | 0.205 | 0.231 |
| StepOne | 4 | 0.087 | 0.149 |

### What each result means

**P1 passes, but the pass is fragile.**
- **The terms.** The term is 0.169 log2 for AMC and DKFZ, taken from the three instruments on 4 pairs. For the instrument comparison it is 0.132, taken from AMC against DKFZ on 6 pairs.
- **One pair drives the AMC/DKFZ term.** The 1 vs 0.2 ng/µl pair contributes an excess variance of 0.081 (71 % of the total) against 0.000–0.023 for the other pairs. On the LC480 plate its 0.2 ng/µl level came from a separate 1:100 dilution, so this is partly dilution error, not only instrument disagreement. In the genomic term, the two 0.2 ng pairs carry about 62 %.
- **Without the lowest tubes, it fails.** Leaving out pairs that use the lowest tube of each series cuts the terms to 0.071 and 0.099, and coverage falls to 85.8 %. This check was added after scoring and is not counted.
- **The confidence interval reaches below the bar.** Its lower end, 89.1 %, is under 90 %.
- **Reading.** Between-plate disagreement is real and visible without truth, but it is much larger for low-copy tubes. A single constant term borrowed from a low-copy tube widens every interval.

**P2 passes overall on the strength of one plate.**
- **AMC, 152 of 197 cases.** AMC is at 96.7 %, and its median \|error\| falls from 0.121 to 0.089.
- **The other plates get worse.**
  - DKFZ coverage is 81.2 %. QuantStudio is 0 of 4: its standard-curve interval is narrow (0.152) and misses all four.
  - Median \|error\| rises on DKFZ, QuantStudio and StepOne.
- **The leave-pair-out curve is optimistic.** It uses the same genomic tubes' other levels, which a real experiment would not have.
- **A separate standard does not help.** On DKFZ, quantifying the genomic pairs with the same run's amplicon-standard efficiency (E 1.90–1.93) gave:
  - median bias +0.187 and median \|error\| 0.189, against 0.199 with the assay mean;
  - 80 % coverage in both cases, over 20 cases, when both are scored with P2's run effect. Scored with its own round-2 interval, the assay mean covers 85 %, so the separate standard is worse, not equal. (Corrected after review.)

**P3 over-covers.** It reaches 96.4 % with ±1.39-fold intervals. It combines the two tests above and adds nothing new.

### What to claim

**Recommended wording:** *"The 95 % interval covers dPCR truth in 92 % of 197 cases (90 % CI over truths 89–96 %) once a between-plate term estimated without truth is added. That makes it 63 % wider, ±1.33-fold. Without that term it covers 83 %. The between-plate term comes mostly from low-copy tubes."*
- **Why P1.** It is the pre-registered primary, and it is the only test aimed at the component we could see was missing.

**Not recommended:**
- calling V2 "passed" without the fragility and width caveats;
- choosing P3 because it scores best;
- changing the baseline to the standard curve on the strength of P2.

**Left to the outside reviewer:**
- which interval to adopt;
- any tier change, including whether the standard curve should be the baseline.

**Possible next step.** A plate×pair term that grows at low input, for example scaled by Poisson copies per reaction. It would need its own pre-registration, because it was suggested by these results.

**Added after scoring:**
- the lowest-tube sensitivity row;
- the per-pair breakdown of the term;
- this interpretation.

## P5: an input-dependent plate×pair term (plan fixed before scoring)

**What I looked at first.** These checks use no truth. I compared each pair's excess variance from P1 with the Poisson scale x = 1/c_hi + 1/c_lo, where c is the nominal genome copies per reaction (303 copies per ng; the instrument comparison uses ng/µl × 10 µl reactions). I fitted the slope b by least squares through the origin:

| Series | Pairs | Fitted b | Poisson theory, 1/ln²2 | Reading |
|---|---|---|---|---|
| Genomic, Dec 2024 (AMC vs DKFZ) | 6 | 1.77 | 2.08 | Matches one Poisson draw per tube per plate. |
| Instrument comparison, Feb 2024 | 4 | 28.5 | 2.08 | 14 times too large. The lowest tube there is 606 copies per reaction, so this is not sampling: it is instrument disagreement plus the LC480 plate's separate 1:100 dilution. |

**Primary.**
- **Term.** σ²_pp(pair) = (1/c_hi + 1/c_lo) / ln²2: the variance of log2 of one extra Poisson draw of each tube per plate.
- **No fitting.** Nothing is fitted, so nothing can be tuned on any plate, and no hold-out is needed.
- **Copies per reaction.** These come from the design only:
  - genomic DNA: ng × 303;
  - instrument comparison: ng/µl × 10 µl × 303;
  - amplicon standard: the label, read as copies per reaction.
- **Interval.** The round-2 interval plus this term. It replaces P1's constant term rather than adding to it.

**Variants (reported, not counted):**
- **P5a.** b fitted on the other series, through the origin: AMC and DKFZ get 28.5 from the instrument comparison, and the instrument comparison gets 1.77 from the genomic series.
- **P5b.** b fitted on both series together. It is truth-free, so in-sample is allowed.

**Reporting.** As for P1–P3, with the same rule and bar.

**Decision rule, fixed now.**
- **If P5 reaches ≥ 90 %,** report P5 as the interval. It has no fitted parameter and a physical reason.
- **If it does not,** report P1's 92.4 % with its caveats, and give P5's figure as what sampling alone explains.
- **Tiers.** Either way, tiers are left to the outside reviewer.

### P5 results (run after the plan was committed as 4b25cc5)

| Test | Coverage | 90 % CI over truths | Median half-width, log2 (fold) | AMC / DKFZ / instrument comparison | Bar |
|---|---|---|---|---|---|
| Round 2, for reference | 83.2 % | 75.9–89.1 % | 0.251 (±1.19×) | 81.6 / 87.5 / 92.3 % | Fail |
| **P5** Poisson term, nothing fitted (b = 2.08) | **87.3 %** | 82.1–91.7 % | 0.312 (±1.24×) | 86.8 / 87.5 / 92.3 % | **Fail** |
| P5a: b from the other series (28.5 for AMC/DKFZ, 1.77 for the comparison) | 92.9 % | 89.3–95.3 % | 0.594 (±1.51×) | 93.4 / 90.6 / 92.3 % | Pass |
| P5b: b from both series (2.01) | 87.3 % | 82.1–91.7 % | 0.310 | 86.8 / 87.5 / 92.3 % | Fail |
| P1, for comparison | 92.4 % | 89.1–95.6 % | 0.410 (±1.33×) | 91.4 / 93.8 / 100 % | Pass |

**Reading:**
- **Sampling explains part of the gap.** One Poisson draw per tube per plate, with no fitted number, explains about half the gap: 83 → 87 %, at a small cost in width (±1.19 → ±1.24-fold). The fitted slope from both series (2.01) agrees with theory (2.08).
- **The rest is instrument and dilution disagreement.** It is larger than sampling, and so far we have seen it only on the instrument comparison, where the LC480 plate's lowest level came from a separate dilution.
- **P5a passes, but it does not count.** It reaches 90 % only by projecting that disagreement onto low-copy AMC tubes, which gives ±1.51-fold intervals. It is a variant.

**Decision, by the rule fixed in the plan.** P5 is below 90 %, so the reported interval is **P1: 92.4 %, ±1.33-fold, with its caveats**.

**The claim:** *"Replicate, efficiency, run, premix and sampling error together explain 87 % coverage. Reaching 92 % needs a between-plate term the size of the disagreement between three instruments on one dilution series (0.17 log2, which includes one plate's separate dilution). Without it, a new instrument's interval is too narrow."*

**Checks run:**
- `pytest` (28 pass, including P5's scale, slope and propagation);
- `qsim validate`;
- an independent recompute of the round-2, P1 and P5 coverage from `validation_dpcr_baseline.csv` and the JSON, with code that does not import qsim. It matched 0.832 / 0.924 / 0.873 exactly.
