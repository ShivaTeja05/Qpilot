# How qPCR practitioners analyse data, and what would convince an expert of the decision simulator

## Access note

Several sources I was asked to check could not be opened, so their content is UNVERIFIED:

- **Reddit.** reddit.com is blocked for both search and fetch, so nothing from r/labrats, r/molecularbiology or r/bioinformatics was read.
- **ResearchGate and Biostars.** Both returned HTTP 403.
- **Protocol Online.** The specific threads return 404, so only search snippets were seen.
- **What I used instead.** Bioconductor support threads, lab wikis, core-facility SOPs, Bitesize Bio, vendor documents and primary papers. Every item below gives its URL.

## 1. Decisions practitioners argue about, and how they decide today

**Threshold and baseline: most people use the defaults, and anyone who adjusts judges by eye.**
- In a 2011 Bioconductor thread, the HTqPCR author said most users accept the instrument's default Ct settings and only need to stay consistent across plates. Another replier preferred a manual baseline set per probe. That replier judges quality by eye (a clean logistic curve with the threshold in the linear phase) and wished for a quantitative check. https://support.bioconductor.org/p/37399
- A core-facility SOP (UNL BORC, Bio-Rad CFX) only explains where the menus are: Regression versus Single Threshold Cq mode, and three baseline options. It gives no rule for choosing between them. https://borc.unl.edu/sites/unl.edu.cehs.biomedical-obesity-research-core/files/media/file/BORC%20SOP%20CFX%20RealtimePCR.pdf
- Ruijter 2009 (NAR) showed that baseline errors pass into the efficiency estimate and then grow exponentially into fold differences. Their analysis had less bias and variability when they used the mean efficiency per amplicon. https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=PMCID:PMC2665230&resultType=core&format=json
- Thermo's "Crt" relative-threshold method: UNVERIFIED, PDF not opened. https://assets.thermofisher.com/TFS-Assets/LSG/brochures/CO28730-Crt-Tech-note_FLR.pdf

**Late-Cq cut-off: 35 is common, but nobody agrees on one value.**
- De Ronde et al. 2017 (RNA) proposed 35 cycles as the critical Cq. They class each reaction as valid, invalid or undetectable. https://pmc.ncbi.nlm.nih.gov/articles/PMC5393188/
- Forum posts saying "35 or 40" for no-template controls: UNVERIFIED, threads return 404. https://protocol-online.org/biology-forums-2/posts/32181.html

**Replicate outliers: the 0.5-cycle rule of thumb.**
- Ruijter et al. 2017 (qPCR & NGS Freising) applied the 0.5-cycle rule strictly to 20,016 reactions. It rejected 39% of them. A rule based on Poisson sampling error rejected 7%. https://www.econferences.de/?p=3963
- The Barrick lab wiki wants replicate SD below 0.2. It removes a replicate only when its curve is clearly bad and keeps all three if they are evenly spread. https://barricklab.org/twiki/bin/view/Lab/ExperimentalqPCR
- Bitesize Bio (updated Sept 2026) gives about 0.2 SD as the sign of clean pipetting. https://bitesizebio.com/87931/qpcr-analysis/

**Efficiency: standard curve versus curve-based estimates.**
- Bitesize Bio gives the textbook rule: slope −3.32, efficiency 90–110%, R² > 0.99.
- Hastings et al. 2021 (Frontiers in Genetics) compared 7 ways of estimating efficiency. The instrument's standard curve gave impossible values above 100% (E 2.10–2.12), while LinRegPCR gave 1.92. Raw values changed with the method, but associations with age held. https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=PMCID:PMC8484782&resultType=core&format=json
- Bustin 2025 (IJMS) complains that efficiency is assumed rather than measured. https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/

**Reference genes: the most common real failure.**
- Hampton et al. 2020 (AJP Lung) looked at 986 human studies. The average reference gene was differentially expressed in about 42% of them.
- In the same paper, the IL8 ΔΔCt ranged from −1.24 to −0.352 depending only on which reference gene was used. https://pmc.ncbi.nlm.nih.gov/articles/PMC7473940
- Hampton/MacKenzie 2025 (preprint) found that when treatment moves the reference gene, both ANCOVA and 2^−ΔΔCT give invalid results. https://pmc.ncbi.nlm.nih.gov/articles/PMC11844642/

**ddCq order of operations.**
- Lixiang et al. 2025 (bioRxiv) show that taking arithmetic means of Cq values leaves the control group's mean fold change not equal to 1.
- In their cadmium data, irg-6 came out at 1.3–7.1-fold with that method versus 1–4.1-fold with theirs. https://www.biorxiv.org/content/10.1101/2025.07.16.665089v1
- Bitesize Bio tells readers to average technical replicates first and to run statistics on ΔCt, not on fold changes. https://bitesizebio.com/24894/4-easy-steps-to-analyze-your-qpcr-data-using-double-delta-ct-analysis/

**Non-detects.**
- The nondetects package vignette says most software sets non-detects to 40, and that this biases both absolute and differential expression. The package imputes them from a model instead. https://bioconductor.org/packages/release/bioc/vignettes/nondetects/inst/doc/nondetects.html
- In a Bioconductor thread, a user set NAs to 40 just to get imputation running. https://support.bioconductor.org/p/105015/
- De Ronde 2017 found that setting undetectables to the cycle count inflated the variances.

**Statistics.**
- Choices in use include a t-test on ΔCt, Welch's test (Click-qPCR 2025: https://www.biorxiv.org/content/10.1101/2025.05.29.656779v1) and ANCOVA (Hampton 2025).
- Bustin 2025 criticises 1.2–1.5-fold claims made without any estimate of uncertainty.

## 2. Do labs have a simulator or what-if tool?

I found nothing that runs analysis choices exhaustively and reports which calls change. That is "not found in what I could open", not proof that no such tool exists. What exists falls into five groups.

**Curve simulators that generate data but do not test analysis choices:**
- chipPCR AmpSim, a 5-parameter Richards curve. Its own documentation says real curve shapes cannot be modelled fully. https://rdrr.io/cran/chipPCR/man/AmpSim.html
- qpcR pcrsim, which that page cites.

**Uncertainty tools that perturb the numbers, not the choices:**
- qpcR ratiocalc puts confidence intervals on ratios using Monte Carlo, REST-like permutation or error propagation. https://rdrr.io/cran/qpcR/man/ratiocalc.html
- REST uses a pair-wise fixed reallocation randomisation test (UNVERIFIED, product page not opened). https://gene-quantification.de/rest.html

**Model-based imputation of non-detects:** the nondetects package (above).

**Hand-run sensitivity checks published as one-off papers:**
- De Ronde 2017 compared 5 data-handling scenarios (A–E) on 834 patients. Only their full pipeline found the quartile difference.
- Ruijter 2017: 39% versus 7% rejected.
- Hastings 2021: 7 efficiency methods.
- Hampton 2020: the IL8 result under each reference gene.
- Reference-gene validation papers routinely normalise one target with the most versus least stable genes. One Chilo suppressalis example is UNVERIFIED (search snippet only). https://dbpia.nl.go.kr/jee/article/110/2/683/2937913

**Clarida:**
- It is Cq-based: users paste Cq values into the free geNorm reference-gene finder. It also has a free plate-homogeneity tool, a 51-item MIQE score, and replicate QC with efficiency correction.
- I found no sensitivity or what-if feature on its pages.
- Pricing: €15 per experiment pay-as-you-go, €10 or €8 on the Lab plan.
- The "sample on/off toggle" in your brief is UNVERIFIED.
- https://clarida.bio and https://clarida.bio/pricing

**Why nobody seems to have built this (my inference):**
- Vendor software outputs one Cq per well.
- Re-running every analysis path needs raw curves, and MIQE 2.0 only now asks vendors to allow raw-data export.
- The "multiverse" idea comes from psychology (Steegen 2016; not opened): https://doi.org/10.1177/1745691616658637

## 3. What an experienced qPCR person would need to see

**Evidence they already trust:**
1. **MIQE 2.0 vocabulary and requirements.** It asks for efficiency-corrected quantities with prediction intervals, confidence intervals on efficiency, LOD and dynamic range, outlier detection, and raw data for re-analysis. Source: the Biosearch summary https://blog.biosearchtech.com/miqe-2.0-for-qpcr. The primary PDF (https://doi.org/10.1093/clinchem/hvaf043) would not extract, so the exact wording is UNVERIFIED.
2. **Known-answer validation.** Run the simulator on dilution series with known copies (Untergasser data, Ruijter 2013 benchmark: https://pubmed.ncbi.nlm.nih.gov/22975077/, not opened). Show that it gets the fold changes right and flags the planted problems. Hastings 2021 is a model to copy: report whether the conclusion holds, not whether the raw numbers match.
3. **Catching the failures they actually fear.**
   - A reference gene that moves with treatment (Hampton).
   - A contaminated no-template control.
   - Over-rejection by the 0.5-cycle rule (Ruijter 2017).
   - The control-mean-not-1 artefact (Lixiang 2025).
4. **A precedent they recognise.** A scenario table like de Ronde's A–E is already accepted in the literature, so present results in that form.
5. **Results in their units (my recommendation).**
   - ΔCq and log2 fold change with intervals, one line per analysis.
   - Amplification curves with the threshold and baseline drawn on, since they judge by eye (Bioconductor 2011).
   - The geNorm M and V plots they already use.

**What would make them dismiss it (inferred from the sources):**
- **"Black box."** Bustin 2025: "We must stop treating qPCR as a 'black box' technology". https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/ Every number has to trace back to a curve.
- **"Garbage in, garbage out."** Ståhlberg 2004 found most RT-qPCR variation comes from the reverse-transcription step. https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=%22Properties%20of%20the%20reverse%20transcription%20reaction%20in%20mRNA%20quantification%22&resultType=core&format=json Drude 2024 found RNA integrity is seldom reported. https://www.biorxiv.org/content/10.1101/2024.12.04.626769v1 The simulator models neither.
- **Options an expert would call indefensible.**
  - "Each well's own efficiency": Ruijter 2009 shows the per-amplicon mean is better.
  - "Set to Cq 40": the nondetects authors call it biased.
  - Keep these in the space only if they are labelled "common but biased".
- **The Mann-Whitney result at 3 vs 3.** The exact two-sided Mann-Whitney test at 3 vs 3 has a minimum p of 0.1, so it can never reach significance (this is arithmetic, not from a source). An expert will read "the test flips every call" as a built-in artefact, not as fragility. Present it as "this option cannot detect anything at n=3".
- **Multiple-testing flips** depend on how many genes are on the panel. Say so up front, or it looks like a trick.
- **Looking like a p-hacking tool.** Lead with "lock your decisions before you see the result" and the hash-chained record.
- **The 2-fold cut.** Your own permutation result says the fragility comes from the threshold. Expect a challenge on why 2-fold, and show results with intervals instead.

## 4. The exact words they use

**Measurements and settings:**
- Cq (MIQE's term; vendors say Ct or Cp)
- threshold; baseline subtraction
- Cq Determination Mode: Regression or Single Threshold (CFX)
- Undetermined; non-detects
- max Cq; cut-off (35/38/40)

**Replicates and controls:**
- technical replicates; replicate SD
- the 0.5-cycle rule
- NTC; −RT control
- edge effect; plate homogeneity (Clarida)

**Efficiency and quantities:**
- efficiency (E, or %)
- standard curve slope −3.32; 90–110%; R²
- efficiency-corrected
- Pfaffl versus Livak (2^−ΔΔCq)
- LOD/LOQ; dynamic range; prediction interval

**Reference genes and normalisation:**
- reference genes (MIQE prefers this to "housekeeping")
- reference gene stability
- geNorm M value; pairwise variation V (V < 0.15)
- NormFinder; BestKeeper
- normalization factor; geometric mean of at least 3 genes
- NRQ/CNRQ; inter-run calibrator; calibrator

**Statistics and reporting:**
- ΔCq; ΔΔCq; fold change; ANCOVA
- MIQE-compliant; RDML

**They do not use** multiverse, decision simulator, flip, fault injection, covering array or drop-k. Suggested translations:
- multiverse → "sensitivity analysis across defensible analysis settings"
- flip → "the call changes" or "the result is not robust to X"
- fault injection → "planted artefacts, known-answer test"
- drop-k-to-flip / leave-one-out → "how much the result depends on a few samples or wells"