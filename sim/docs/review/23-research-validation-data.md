# Known-answer qPCR datasets and a validation protocol for the qPilot decision simulator

## Bottom line
- There is a public dataset with real measured truth from 2024-2026. The Untergasser RDML set has raw curves, three qPCR machines, six mixes and 16-19 primer pairs on one single-copy gene, and it was quantified independently by dPCR. The authors' Data Availability statement points to the repo (https://pmc.ncbi.nlm.nih.gov/articles/PMC13026326/).
- The Vermeulen data qPilot already uses has per-gene dilution standards in the same repo. The deliberate dilutions are known to be imperfect, so the intended 10-fold steps are not exact truth (https://pmc.ncbi.nlm.nih.gov/articles/PMC12733170/).
- MAQC and SEQC give a known-ratio design, where C = 75% A + 25% B and D = 25% A + 75% B. Both are Cq-only, so qPilot needs a Cq import before it can use them.
- The Bioconductor example sets (nondetects, HTqPCR) have no ground truth. They are useful only for realistic missing-data patterns.

## Dataset inventory

| Dataset | Format | Ground truth | Size / design | Licence | URL |
|---|---|---|---|---|---|
| **Untergasser experiments** | Raw RDML curves, plus pipetting TSVs, results TSVs and dPCR TSVs | • gDNA 20/7/2/0.7/0.2 ng and NTC, in triplicate<br>• Purified amplicons 10^9 to 10^1 copies, in triplicate<br>• QX200 dPCR on the same dilutions (probe and EvaGreen) | • Machines: LC480 II (AMC, DKFZ), QuantStudio 6 Flex, StepOne (96-well)<br>• Mixes: Roche SYBR, SensiFast, LCGreen, Roche Probe, IDT Probe, own mix<br>• Amplicons 40-820 bp; 13 RDML files | Repo MIT; paper CC BY | https://github.com/RDML-consortium/rdmlpython/tree/main/experiments/untergasser |
| **Vermeulen standards** (same repo) | Raw RDML | • Five 10-fold dilutions (150,000 to 15 copies) × 3 for every gene ([qpcR doc](https://rdrr.io/cran/qpcR/man/qpcR_datasets.html))<br>• Published bias, linearity and reproducibility tables for 11 curve-analysis methods | 64 assay columns | MIT | https://github.com/RDML-consortium/rdmlpython/tree/main/experiments/vermeulen |
| **Ruijter 2013 ds_94_4** | Raw curves, CFX384, MYCN oligo, SYBR, 45 cycles | 15 / 150 / 1,500 / 15,000 copies | 94 replicates per level, plus 8 NTC | CC BY 4.0 (R package ruijter 0.1.3) | https://patterninstitute.r-universe.dev/ruijter/doc/manual.html |
| **ds_380** | Raw curves | One concentration, so any group difference is false | 380 replicates at 150,000 copies, plus 4 NTC | CC BY 4.0 | same |
| **ds_competimer** | Raw curves, LC480, AluSx | Known gDNA concentration and known competitor % (deliberately lowered efficiency) | Six 4-fold dilutions (64 to 0.0625 ng/µl) × 7 competitor levels (0-50%) × 3 | CC BY 4.0 | same |
| **qpcR package datasets** (v1.4-2, 2025-06-10) | Curve runs labelled FX.Y | • lievens1: five 5-fold dilutions<br>• lievens2: 5 isopropanol levels<br>• lievens3: 5 tannic-acid levels (each × 18 replicates)<br>• testdat: replicate 3 noisy, replicate 4 non-sigmoidal by design<br>• rutledge: 5 batches<br>• guescini1: 7 dilutions × 12 | 26 objects | GPL ≥ 2 | https://rdrr.io/cran/qpcR/man/qpcR_datasets.html, https://cran.r-project.org/package=qpcR |
| **MAQC TaqMan** (GSE5350 / GPL4097) | Values are 2^(Ct POLR2A − Ct gene); flag "A" if CT > 35 | Mixing ratios for A, B, C, D | 1,044 rows × 16 samples (A1-A4 … D1-D4); 997 TaqMan assays ([Canales 2006](https://dx.doi.org/10.1038/nbt1236)) | Public GEO (no licence verified) | https://ftp.ncbi.nlm.nih.gov/geo/platforms/GPL4nnn/GPL4097/soft/ |
| **SEQC PrimePCR** (GSE56457 / GPL18522) | Raw Cq ("single molecule Cq = 35"); CFX384, SsoAdvanced SYBR, 5 µl | Mixing ratios for A, B, C, D | 20,801 assays × one well per sample | Public GEO | https://ftp.ncbi.nlm.nih.gov/geo/series/GSE56nnn/GSE56457/suppl/ |
| **nondetects** (GPL-3, v2.42.0) | Cq (qPCRset) | **None** | oncogene2013: 77 × 24 (4 replicates); sagmb2011: 67 × 55; nature2008 | GPL-3 | https://rdrr.io/bioc/nondetects/man/ |
| **HTqPCR qPCRraw** (Artistic-2.0) | Cq, TaqMan Low Density Array | **None** | 384 features × 6 (3 samples × 2) | Artistic-2.0 | https://rdrr.io/bioc/HTqPCR/man/qPCRraw.html |
| **RDML technical files** | RDML | • shifted_baseline: a constant is added to each curve, so results must not change<br>• matrix_gaps: cycles deleted on purpose | 2 files | MIT | https://github.com/RDML-consortium/rdmlpython/tree/main/experiments/technical |

The rdrr.io man-page index for ReadqPCR and NormqPCR lists no bundled known-truth dataset (https://rdrr.io/bioc/ReadqPCR/man/).

## Truth-quality facts that change the protocol

**Untergasser (IJMS 2026)** (https://pmc.ncbi.nlm.nih.gov/articles/PMC13026326/)
- qPCR/dPCR ratios: 1.03, 1.11, 1.07 and 0.95 for 20, 7, 2 and 0.7 ng; 2.53 at 0.2 ng; 1.00-1.08 for amplicons 10^2-10^5.
- dPCR copies were higher than the mass-based expectation (9,031 vs 6,000 at 20 ng). **Use dPCR as truth, not nominal ng.**
- Ncopy/expected was about 0.71-0.89 on the LC480 II and 0.98-1.05 on QuantStudio and StepOne (my ratios, computed from their tables).
- Across machines and volumes, Cq spanned 11.61-24.91 while TD0 spanned 24.76-25.16. That is direct evidence for the missing threshold/Cq-method decision.
- Efficiency ran from 1.83 (820 bp) to 2.04 (40 bp). Five of 19 primer pairs were dropped for artefacts.
- Authors' limits: one single-copy gene, and Ncopy usually within a factor of 3 of expected.

**Vermeulen dilution standards**
- Actual steps were "between 8- and 9.9-fold"; none reached 10-fold. The standard curve's low bias is described as "the result of circular reasoning" ([Ruijter & van den Hoff 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12733170/), citing [Ruijter 2021](https://doi.org/10.1093/clinchem/hvab052)).
- The repo table shows Standard-Cq slope ≈ 1.000 by construction and LinRegPCR (old) ≈ 0.93 (data_vermeulen_methods_results.tsv, same repo).

**Ruijter labels**
- The original ds_94_4 dilution labels were reversed.
- ds_380 copies are 150,000, not the published 15,000, per author email (r-universe manual). qpcR's reps384 still says 15,000.
- Audit labels before scoring anything.

**MAQC titration**
- Deviations from the predicted titration are explained by different mRNA fractions in A and B ([Shippy 2006](https://www.nature.com/articles/nbt1241)), so a mixing-weight correction is needed.
- Derived (my maths): if A/B = r, then C/D = (3r+1)/(r+3). This is always between 1/3 and 3, reaches 2-fold only when r ≥ 5 or r ≤ 1/5, and must point the same way as A/B.

**Simulation truth for reference genes**
- When the reference gene responds to treatment, 2^-ΔΔCt false-positive rate reached 93.2% at correlation 0.9 ([Hampton 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12666847/)).

## Validation protocol

**V0 – Reproduction gate**
- **Data:** Vermeulen standard RDMLs.
- **Test:** qPilot's vendored LinRegPCR must reproduce RDML_Tools_bias.tsv and the LinRegPCR tables.
- **Pass:** relative difference ≤ 1e-6. Otherwise stop.

**V1 – Estimate bias against truth, per decision**

Efficiency (LinRegPCR assay mean / each well's own / assume 100%):
- **Data:** Untergasser gDNA 0.7-20 ng and amplicons 10^2-10^5.
- **Metric:** log2(estimated adjacent-level ratio ÷ dPCR ratio), per assay × mix × machine.
- **Pass:**
  - The simulator's preferred option has median |bias| ≤ 0.15 log2.
  - It is lowest or tied-lowest in ≥ 80% of strata.
  - The bias of assume-100% matches the simulator's own (2/E)^ΔCq prediction within 0.1 log2.
- **Competimer check:**
  - **Pass:** assume-100% bias rises with competitor % (Spearman ρ ≥ 0.8), and the curve-based options stay within ±0.25 log2 up to 30%.

Flagged wells and the <10-copies rule:
- **Data:** ds_94_4, steps 15→150 and 150→1,500 copies.
- **Pass:** dropping wells never increases |bias|, and the <10-copies rule fires on ≤ 5% of the 150-copy wells.

Non-detects:
- **Data:** SEQC genes detected in A but late or undetected in B.
- **Test:** for each substitution option, compute the titration residual (observed C quantity vs 0.75·A + 0.25·B).
- **Pass:** genes the simulator calls "sensitive to non-detect handling" have larger residuals (one-sided Wilcoxon p < 0.01).
- The nondetects multiple imputation ([Sherina 2020](https://doi.org/10.1186/s12859-020-03807-9)) is a comparator only, since it has no truth.

Reference genes (same-template null):
- **Data:** Untergasser, normalising FSTL1 amplicon X by amplicon Y. Both measure the same molecule, so the true normalised ratio between dilution groups is 1.
- **Pass:** median |log2| ≤ 0.15 and zero calls.

**V2 – Does the range across defensible analyses contain the truth?**
- **Data:** every known-truth comparison: Untergasser dPCR ratios, ds_94_4 subsampled 3 vs 3 and 6 vs 6 (1,000 draws), and MAQC C/D.
- **Pass:**
  - Truth lies within [min, max] across defensible analyses in ≥ 90% of comparisons.
  - That coverage is at least the baseline 95% CI's coverage.
  - Median range width at 6 vs 6 is ≤ 1 log2.
- **If it fails:** coverage below 80% means the multiverse is missing a systematic decision. The Cq spread across machines (11.6-24.9) points to threshold and baseline as the first one to add.

**V3 – Are "fragile" calls more often wrong?**
- **Data:** MAQC TaqMan C vs D at 4 vs 4, the public design closest to a bench 3 vs 3. A call is provably wrong if it exceeds 3-fold, or if it points the opposite way to an unambiguous A/B (|ΔCq| ≥ 3 in every analysis). The class "truly ≥ 2-fold" requires r ≥ 5. Repeat on ds_94_4 subsamples.
- **Metric:** AUROC of each fragility score (agreement share, margin, drop-k) for predicting wrong calls.
- **Pass:** AUROC ≥ 0.70 with bootstrap 95% lower bound > 0.55, and the error rate among fragile calls is ≥ 2× that among robust calls.
- **Fail:** the confidence interval includes 0.5.

**V4 – False calls on null data**
- **Data:** ds_380 (1,000 random 3 vs 3 and 6 vs 6 splits) and the Untergasser same-template comparisons.
- **Pass:** ≤ 1% of split × analysis combinations produce a call, and none is ever labelled robust.

**V5 – Detector calibration on real faults, not planted ones**

Positives:
- competimer ≥ 20%
- the top two inhibitor levels in lievens2 and lievens3
- testdat FX.3 and FX.4
- Untergasser NTC, "No Primer" and SYBR-addition wells
- the five artefact primer pairs
- the StepOne vs LC480 Cq offset

Negatives:
- ds_380
- ds_94_4 wells at ≥ 150 copies

**Pass:**
- sensitivity ≥ 80% on faults that move estimates by ≥ 0.5 log2
- false alarms ≤ 2% of clean wells
- issue-queue precision@10 ≥ 70%

If sensitivity on real faults falls below 70%, the 85% planted-fault figure is optimistic.

**V6 – Invariance**
- **Data:** shifted_baseline and matrix_gaps.
- **Pass:** shifted_baseline gives identical estimates and calls (|Δ| < 1e-9); matrix_gaps runs without crashing and flags the affected wells.

## What this cannot show
- Truth here comes from technical replicates. It tests whether measurement and analysis are accurate, not whether a biological inference is right.
- Untergasser covers one gene. MIQE 2.0 asks for efficiency-corrected quantities with prediction intervals and encourages raw-data export (https://doi.org/10.1093/clinchem/hvaf043).
- Remans 2014 (Plant Cell) already proposed an uncertainty interval between normalised and non-normalised results, without any truth data (https://academic.oup.com/plcell/article/26/10/3829/6101553). qPilot's coverage test (V2) is what goes beyond that.
- **Wet-lab next step:** NIST SRM 2373 has certified HER2/reference ratios of 1.3-17.7, set by qPCR and dPCR (https://www.nist.gov/programs-projects/nist-her2-genomic-dna-standard-reference-material-srmr-2373).

## UNVERIFIED
- Whether raw Ct (not POLR2A-normalised) exists anywhere for MAQC TaqMan.
- Whether GPL18522's synthetic 60-mer dilution data (2E7-2E1 copies) is public.
- The fold ratios in the ERCC ExFold mixes (I saw only vendor search snippets).
- The contents of Zenodo record 23219586 ("qPCR_data", 2026).
- A data licence for the medischebiologie.nl zip (https://medischebiologie.nl/files/ states none) and for the Hampton figshare set.
- The full MIQE 2.0 text on how raw data must be shared (I read only the abstract).