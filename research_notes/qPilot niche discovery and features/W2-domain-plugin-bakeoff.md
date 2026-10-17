# W2. Domain-plugin bake-off: which application domain qPilot should serve next, with verified evidence

Date: 17 October 2026. Written for the two qPilot developers. Compares the ten candidate "plugins" proposed across research notes 08, 09, 10, 11, 15 and 05, re-verifies the load-bearing facts against primary sources (every URL in section 8 was fetched on 17 Oct 2026 unless marked otherwise), scores them with a transparent weighted rubric, and recommends what to build first and in what order.

How to read this: section 1 is the one-page answer. Section 2 is the scoring method. Section 3 is the per-candidate scorecard with evidence. Section 4 is the ranking table. Section 5 is the sequencing plan and what generalises in the existing engine. Section 6 holds the "why this domain first" pitches. Section 7 lists what could not be verified. Section 8 is the sources. Appendix A has the raw Europe PMC counts.

Vocabulary used throughout (defined once): **Cq** = the PCR cycle at which a well's fluorescence crosses a threshold; **standard curve / dilution series** = wells with known copy numbers used to convert Cq to copies; **LOD / LOQ** = limit of detection (lowest amount detected in 95 % of replicates) and limit of quantification (lowest amount quantified with acceptable precision); **T/S ratio** = telomere signal divided by single-copy-gene signal, the qPCR measure of telomere length; **ICC** = intraclass correlation, a repeatability statistic (1.0 = perfectly repeatable); **VCN** = vector copy number, integrated gene-therapy vector copies per cell; **partition** = one droplet or nanowell in digital PCR (dPCR); **HRM** = high-resolution melting, genotyping by the shape of the DNA melting curve; **allelic discrimination** = genotyping by comparing two dye signals at the end of a run.

---

## 1. The answer in one page

**Build first: the eDNA "assay LOD/LOQ passport" (Klymus 2020 modelled LOD/LOQ from the study's standard-curve plates, with the model-choice robustness grid and the detection-call rule pack).** Score 93/100. It is the only candidate where all four of these are true at once: (a) the method is a published numeric specification with a CC BY paper [24] and a US-government public-domain reference implementation plus regression data (36 assays, 7 labs) [23][25]; (b) the pain is quantified by the method's own authors (model choice alone moves the LOD 1.07- to 8.72-fold; eDNA studies "rarely report" LOD/LOQ) [24]; (c) there is a champion with a mandate (US Fish & Wildlife Service runs 9,000–10,000 qPCR samples a year under a public Quality Assurance Project Plan whose acceptance and negation rules are numeric and encodable) [26][27]; (d) the only existing tool is a provisional R script that depends on a GPL-2 package [25][30]. It also builds the "standard series substrate" (typed standard wells, per-well positive/negative call, dilution-series fits, acceptance windows) that four other candidates reuse (absolute quantification, gene-therapy packs, wastewater, GMO).

**Build second: Telomere Study Mode.** Score 87/100. Highest pain-to-competition ratio of the ten: a reporting audit found ICC reported in 2 of 25 method-comparison studies [13]; the field's consortium (the Telomere Research Network, sponsored by NIA and NIEHS) publishes recommendations and an R script that users must run by hand [11][12]; data are public and permissively licensed (Nettle 2019, CC BY 4.0 [9]; Dagnall 2017, CC0, 576 reproducibility results [10]); the incumbent analysis tool (Clarida) does not mention telomeres [18]; the only open pipeline has one star and no tests [17]. It reuses most of qPilot's expression engine (per-well efficiency, ratio to a reference target, replicate rules, plate effects, robustness over analysis choices) and adds ICC and a plate/well mixed model.

**Then:** composite standard curves for absolute quantification (78) because it is the shared base for the gene-therapy (68), wastewater (64) and GMO (64) packs; the dPCR partition-level plugin (80) as the second *data kind* once the domain-agnostic core has been proven on a second qPCR domain; miRNA normalisation robustness (76) as a cheap win on the existing geNorm code when a public dataset is secured. HRM genotyping (59) and allelic discrimination (59) rank last: no public raw datasets, live patents (HRM), and free vendor tools that users consider good enough.

What changed versus the original notes' own rankings: note 08 already put eDNA first [2]; note 09 put telomeres first [3]; note 10 put the dPCR classifier first [4]. This bake-off agrees with 08 and 09 and demotes dPCR from "first" to "third data kind" on effort (4–7 weeks, five classifiers plus importers plus multiplex) and on the unverified status of rdmlpython's dPCR support (see section 7).

---

## 2. Scoring method

Eight criteria, weights chosen before scoring and stated here so the developers can re-weight:

| # | Criterion | Weight | 5 means | 1 means |
|---|---|---|---|---|
| 1 | Community size and growth | 15 | large and growing; institutions and regulatory drivers | small or shrinking; no institutional driver |
| 2 | Severity and frequency of the analysis pain | 20 | quantified by primary sources; every run or every study | anecdotal; occasional |
| 3 | Public data with licence | 15 | permissive-licence data that can serve as an acceptance test, record page verified | none found |
| 4 | Method determinism | 10 | a published numeric rule set or model with a DOI | methods published but contested or vendor-prose only |
| 5 | Fit with qPilot's architecture | 15 | reuses raw curves, robustness grid, cards, record, MCP with few new decision kinds | needs a new data model or a new engine |
| 6 | Effort for two developers and licence/patent risk | 10 | ≤ 3 weeks, permissive dependencies, no patents | > 6 weeks or live patents / GPL-only methods |
| 7 | Champion user with budget or mandate | 10 | consortium, agency SOP or regulator that names the computation | no identifiable champion |
| 8 | Competitive landscape | 5 | nothing serves it; an open tool would be welcomed | free vendor tools that users accept |

Score = Σ (criterion score 1–5 × weight) / 5, giving 0–100. Scores are judgments; the evidence behind each is in section 3 so the developers can disagree with a number and re-run the sum.

Community size uses Europe PMC counts run through the REST API on 17 Oct 2026 [8]. Two query families were run: a broad full-text family (over-counts, because Europe PMC searches open-access full text) and a title-or-abstract family (under-counts, but comparable across domains). Both are in Appendix A. The title/abstract numbers are used in the scorecards.

---

## 3. Scorecards with evidence

### 3.1 Telomere Study Mode (note 09, D1)

What it is: cohort-scale T/S from every plate of a study, computed three ways (per-plate standard curve, efficiency-corrected ratio, ΔΔCq), with replicate rules, QC-DNA plate gates, well/plate effects in a mixed model, ICC from re-run samples, Z-scored output, and the TRN reporting items filled from the record [3].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 3 | Europe PMC title/abstract: 1,359 papers all-time; 80 (2019), 116 (2022), 114 (2025): large, flat [8]. Driver: the Telomere Research Network (TRN), "a NIA and NIEHS sponsored network", publishes Recommendation 1 (assay precision, ICC) and Recommendation 2 (DNA extraction), minimum reporting guidelines for qPCR telomere length, pilot awards and annual meetings [11][12]. No member count is published (not verified). |
| 2 Pain | 5 | Lindrose 2021 (PLoS One, CC BY, 75 citations): method-comparison audit; note 09 reports 51 % reporting completeness and ICC in 2 of 25 studies [13][3]. Nettle 2021 (Am J Epidemiol, CC BY): 20 people measured twice 6.6 years apart; cross-sectional qPCR–Southern correlation r = 0.90 but correlation of *change* only r = 0.48 [16]. Nettle 2019 (PLoS One, CC BY): repeatability of T/S falls "sharply" as Cq error rises [15]. Dagnall 2017: 576 reproducibility results; extraction, purification and storage all shift T/S [10]. Inter-lab CV 20.7 % and the 40 % extraction shift are from note 09 (not re-fetched) [3]. |
| 3 Data | 4 | Zenodo (Nettle): dataset1.csv, dataset2.csv, simulation code; CC BY 4.0; DOI 10.5281/zenodo.2615735 (v3) [9]. Dagnall S1–S4: plate, well, instrument, standardized T/S; **CC0** [10]. TRN example.xls and ICC R script (licence not stated) [11]. Cq-level only; no public raw-curve telomere set (gap). |
| 4 Determinism | 4 | Cawthon 2009 MMqPCR (NAR, 1,153 citations) defines the assay and T/S [14]; ICC and repeat-sample design per TRN Recommendation 1 [11]; replicate rules (Cq SD < 1; CV > 5 % single-outlier deletion) from note 09 [3]. Three legitimate T/S computations exist, which is exactly what the robustness grid is for. |
| 5 Fit | 5 | Multi-plate study, a target normalised to a reference (single-copy gene), per-well efficiency (LinRegPCR, already in qPilot), replicate rules, plate effects, robustness over analysis choices, checklist auto-fill from the record. New decision kinds: "QC-DNA plate gate", "extraction-kit calibration vs within-kit Z-scoring". |
| 6 Effort/risk | 4 | 2–3 weeks engine and cards + 1 week MMqPCR two-acquisition mapping (note 09) [3]. ICC and mixed models via statsmodels (BSD); no GPL, no patents. Hardest: representing two-temperature acquisition in RDML across instruments; validating ICC against the TRN script. |
| 7 Champion | 5 | TRN is NIH-sponsored, writes the recommendations and the reporting guideline, and runs award programmes [12]. The computation qPilot would do (ICC, protocol-as-fixed-effect) is the one TRN asks for. |
| 8 Competition | 5 | Clarida's page lists gene expression, reference-gene validation and CNV; no telomere [18]. cgrtelomeres: MIT, R, Excel plate reports in, 1 star, "Plots and testing not implemented" [17]. TRN R script is manual [11]. |

Weighted: 45 + 100 + 60 + 40 + 75 + 40 + 50 + 25 = **435 → 87**.

### 3.2 Gene and cell therapy run-acceptance packs: VCN, AAV titre, biodistribution (note 09 D2; note 15 D1/D4)

What it is: a versioned rule pack applied to standard-curve plates: curve acceptance, QC-sample acceptance, spike recovery / inhibition, NTC rule, BLOQ policy, copies per µg gDNA or per cell, with escalation events and a qualification summary [3][6].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 4 | Title/abstract: 252 all-time; 11 (2019) → 35 (2025), tripling [8]. Broad full text 6,866; 1,017 in 2025 [8]. Pipeline: 2,217 gene therapies in development in Q2 2026 (1,332 preclinical, 427 Phase I, 387 Phase II, 59 Phase III, 12 pre-registration), 4,487 gene, cell and RNA therapies in total (Citeline/ASGCT, July 2026) [22]. |
| 2 Pain | 4 | NIST interlaboratory study of candidate VCN reference materials (12 labs: 4 qPCR, 7 ddPCR, 2 QIAcuity, 3 NGS): "qPCR spread was larger than dPCR spread"; one lab overestimated the VCN-4 sample by nearly 50 % [21]. Ma 2021: dozens of numeric criteria applied by hand under SOPs; "if the plate fails a second, consecutive run, the Study Director will be notified" [19]. FDA LTFU 2020 asks for LOQ < 50 copies/µg gDNA, triplicates and a spike in one replicate per tissue, and a stated method for values below LOQ [20]. AAV topology bias up to 8× and qPCR-vs-ddPCR discrepancies are from note 09 (not re-fetched) [3]. |
| 3 Data | 1 | No public raw-curve or Cq dataset for VCN, titre or biodistribution was found by note 09 or by this check. NIST data: "available from the corresponding authors on reasonable request"; NGS data withheld under an MTA [21]. Reference materials are purchasable (ATCC AAV RSMs; NIST candidate VCN RMs) [3][21]. |
| 4 Determinism | 5 | Ma 2021 (verified): efficiency 90–110 %, R² ≥ 0.980, ≥ 8 non-zero standards in duplicate for sample analysis (≥ 7 passing in validation), ≥ 75 % of standards with Ct %CV ≤ 2 % and back-calculation within ±25 % (±45 % at the low end); QC: 50 % per level and 67 % overall with %CV ≤ 25 % and %RE ±25 % (±45 % at QC-UL); spike recovery ≥ 55 % else re-run at 1/10–1/4 loading; sample-analysis NTC ≥ 2/3 BLOD; LLOQ ≤ 50 copies/µg gDNA [19]. FDA LTFU: "< 50 copies/μg genomic DNA", triplicates, spike control [20]. |
| 5 Fit | 4 | Same substrate as 3.3/3.10 (typed standards, acceptance windows, per-well efficiency, BLOQ policy as a robustness axis, rule-pack hash in the record). New decision kinds: "drop a standard level or repeat plate", "declare inhibition and re-run", "BLOQ policy flips positivity". Needs the composite/standard-curve engine first. |
| 6 Effort/risk | 3 | 2 weeks rule engine + 1 week per extra pack (note 09) after the standard-curve engine exists [3]. Risks: users will ask for 21 CFR Part 11 (refused by design); VCN and titre migrating to dPCR [21]; no public acceptance-test data, so synthetic plates only. |
| 7 Champion | 3 | Regulatory text names the computation [19][20], but the natural users (CROs, biotech PD) have LIMS and SOPs; the realistic champion is the academic vector core or method-development group. No consortium. |
| 8 Competition | 3 | Vendor standard-curve modules and Excel-under-SOP; no open rule engine. ddPCR vendor software is the growing incumbent [21]. |

Weighted: 60 + 80 + 15 + 50 + 60 + 30 + 30 + 15 = **340 → 68**.

### 3.3 eDNA LOD/LOQ passport and detection-call engine (note 08, D1 + D2)

What it is: (a) from the study's standard plates, binary detection per standard from qPilot's own amplification call, a family of log-dose models fitted and selected per Klymus 2020, LOD at 95 % detection with CI, effective LOD for n replicates, LOQ from a CV-vs-concentration model at a stated threshold, the discrete-threshold alternative, outlier and standard-drift cards, and the robustness spread across models; (b) a rule pack encoding the lab's QAPP for positive calls, control negation, positive-control minimums, standard-curve acceptance and inhibition, with every negation a human-only Decision Card and a detection-matrix export [2].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 4 | Title/abstract: 540 all-time; 44 (2019) → 51 (2022) → 79 (2025), +80 % over six years, the strongest growth among the qPCR-only candidates [8]. Institutions: USFWS Whitney Genetics Laboratory processes "roughly 9,000–10,000 samples annually" by qPCR for invasive carp, plus hellbender, cavefish and wood turtle programmes [27]. Thalinger's validation scale (Environmental DNA 2021, CC BY-NC): 217 citations [28]. |
| 2 Pain | 5 | Klymus 2020 (Environmental DNA, CC BY, 580 citations on Crossref): "eDNA studies rarely report" LOD/LOQ; across 36 assays, different model functions gave LODs "ranging from 1.07-fold to 8.72-fold" apart; Weibull II and asymptotic regression solved for 35 of 36 assays, log-logistic and Michaelis–Menten for 24; going from one to eight replicates gave a mean 11.1-fold drop in effective LOD (3- to 41-fold per assay); the CV threshold for LOQ is unstandardised (25–35 %) [24]. The only calculator is "preliminary or provisional", R, Cq/SQ CSV in, 26 stars, 1 open issue [25], and it depends on `drc`, which is GPL-2 on CRAN [30]. USFWS negation rules live as prose in a QAPP: "if field blanks are 11, 22 and 33 and 22 is positive … then samples 12–32 will be negated" [26]. |
| 3 Data | 5 | USGS data release 10.5066/P9AKHU1R: public domain; `GEDWG_LOD_DATA3.csv` is "raw qPCR data from multiple labs running multiple standards of known concentration"; `Comparison-Data.csv` is the calculator's output under several model settings, i.e. a ready-made regression target [23]. Zenodo 18833966 (March 2026, CC BY 4.0): environmental Cq values, LOD/LOQ standard data, specificity data for a flat-oyster assay [29]. Cq-level; raw curves are a gap. |
| 4 Determinism | 5 | Klymus 2020 defines the model family, the 95 % detection criterion, the LOQ CV rule and the effective-LOD formula [24]. USFWS QAPP 2025 (verified text): standard curves accepted at E = 80–120 % and R² ≥ 0.95, errant points may be dropped if a 3-point curve remains, failed curves mean re-amplification; PCR positive control passes with 1 of 2 replicates; positive extraction control 1 of 8; negative extraction control with any product negates its batch; field-blank and hood-control negation rules as quoted [26]. |
| 5 Fit | 5 | Raw curves let the engine make the positive/negative call itself; the robustness grid reports the model spread Klymus found; outlier removal and CV threshold become logged decisions; negations are conclusion-flipping and so human-only under the existing escalation rule; the record is the assay passport the lab-memory roadmap wants. New decision kinds: "model family / outlier / CV threshold", "negate a sample range", "below-LOD positive interpretation". |
| 6 Effort/risk | 4 | 2–3 weeks for LOD/LOQ engine and regression tests; 3–4 weeks for rules, cards and exports (note 08) [2]. `drc` must not be vendored (GPL-2) [30]; fit the same models with scipy/statsmodels (BSD). Hardest: matching `drc`'s model selection closely enough to pass the Comparison-Data regression, and capturing well roles (which blanks bracket which samples) from vendor layouts. |
| 7 Champion | 4 | USGS/USFWS working group authored both the method and the data [23][24]; the USFWS QAPP is a public, numeric SOP [26]; agencies with QAPPs need a defensible audit trail. Risk: agencies adopt third-party software slowly; consultancies and university labs first. |
| 8 Competition | 5 | Provisional R script only [25]; validation website is a manual checklist (note 08) [2]; vendor software does no detection modelling. |

Weighted: 60 + 100 + 75 + 50 + 75 + 40 + 40 + 25 = **465 → 93**.

### 3.4 Wastewater-epidemiology run packet (note 08, D4)

What it is: on top of the composite-curve engine (3.10), map engine facts to the CDC NWSS data dictionary and PHES-ODM, compute copies per litre, normalisation and the CDC trend classification with non-detect policy as a recorded choice [2].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 4 | Title/abstract: 595 all-time; 0 (2019) → 102 (2022) → 89 (2025): large but past peak [8]. PHES-ODM "used or planned for use in 23 countries" [34]. NWSS site/lab counts: not published on the pages reached [31][76]. |
| 2 Pain | 4 | Pecson 2021 (186 citations): 36 methods compared in an interlaboratory evaluation; 7-log10 LOD spread per note 08 [32][2]. NWSS requires labs to report concentration, extraction and quantification methods, recovery efficiency and inhibition, and to convert copies/reaction to copies per volume themselves; below-LOD samples are set to half the LOD in trend analysis [31]. |
| 3 Data | 2 | Eawag Zenodo 17226976 (CC BY 4.0) is sample-level (gene copies/L, LOD, partition counts), not well- or partition-level [33]. No raw-curve public WBE dataset found. NWSS public dataset archived (note 08, not re-fetched) [2]. |
| 4 Determinism | 3 | NWSS presence rules: RT-qPCR "below 40" cycles; dPCR "three or more positive droplets"; half-LOD substitution; log10 regression on ≥ 3 points [31]. Normalisation: "no consensus method" [31]. EPA 1696.1 gives curve criteria (3.10). |
| 5 Fit | 3 | Mostly export mapping and unit chains on top of 3.10; dPCR inputs are a large share, which the qPCR engine cannot serve until 3.6 exists. |
| 6 Effort/risk | 3 | 2–3 weeks on top of 3.10 [2]. PHES-ODM enters "long-term maintenance phase" from September 2026; its licence statement is inconsistent (CC BY 4.0 vs CC BY-SA 4.0) [34]; dictionaries change versions. |
| 7 Champion | 3 | CDC dictionary v5.2.3 defines the fields [31]; but programme funding and platform shifts (dPCR) make the qPCR-only packet a shrinking target. |
| 8 Competition | 3 | Commercial pipelines closed; WES archived from CRAN (note 08) [2]; an open packet builder would be welcomed by academic labs, less so by labs already on vendor pipelines. |

Weighted: 60 + 80 + 30 + 30 + 45 + 30 + 30 + 15 = **320 → 64**.

### 3.5 GMO percentage module (note 08, D5)

What it is: two standard curves → event and taxon copies → GM %, ENGL acceptance as a method card, copy-to-mass conversion factors with propagated uncertainty, expanded uncertainty and the compliance decision on C − U [2].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 2 | Title/abstract: 266 all-time; 6 (2019), 9 (2022), 6 (2025): small, flat [8]. GMOMETHODS lists 228 validated methods [42]; the users are official control labs under ISO/IEC 17025. |
| 2 Pain | 3 | EURL VL-01/22 (MON 95275, 12 NRLs, CC BY 4.0): "One laboratory could not fill in the excel template"; calculations "were done over not rounded data. This approach might create small" inconsistencies [41]. Real, but routine labs will not swap an accredited spreadsheet for a research tool. |
| 3 Data | 3 | EURL validation reports publish per-lab results under CC BY 4.0 but not raw Cq [41]; CRMs cost money; ISO 21570 is paid (note 08) [2]. |
| 4 Determinism | 5 | ENGL MPR 2015 (verified text): inhibition-test slope −3.1 to −3.6 (efficiency 110–90 %), ΔCq < 0.5; R² ≥ 0.98 over ≥ 5 runs; trueness ±25 %; dynamic range ≥ 50–2,520 copies (GM module) and 50–56,000 (taxon module); LOD < 25 copies at 95 % confidence for individual modules, < 0.045 % for combined; robustness annex [40]. |
| 5 Fit | 4 | Dual-curve ratio with uncertainty is a small extension of 3.10; MU maps to the robustness grid. |
| 6 Effort/risk | 4 | ~2 weeks after 3.10 [2]; all JRC documents CC BY 4.0 [40][41]; no patents. |
| 7 Champion | 2 | EURL/ENGL exist but mandate accredited SOPs, not research software; the plausible users are method developers and students. |
| 8 Competition | 3 | No open tool; the incumbent is a regulator-accepted spreadsheet. |

Weighted: 30 + 60 + 45 + 50 + 60 + 40 + 20 + 15 = **320 → 64**.

### 3.6 Digital PCR partition-level plugin (note 10, D1–D3)

What it is: import per-partition exports, classify every well under six published methods (vendor call, KDE "cloudy", NTC-based GEV, k-means with rain exclusion, Gaussian mixture, model-based posterior), report agreement as the confidence statement, make the partition-volume constant a provenance-carrying fact, add replicate-aware CIs and LoB/LoD from blanks, write RDML 1.3 partition tables [4].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 5 | Title/abstract: 8,503 all-time; 522 (2019) → 797 (2022) → 994 (2025): largest and fastest-growing [8]. dMIQE 2020 (Clin Chem, CC BY): 401 citations [43]. |
| 2 Pain | 5 | Bio-Rad's own user guide: "In QX Manager Software, Version 2.0, Bio-Rad reduced the droplet volume used to calculate concentration from .85 nL to .795 nL. The change resulted in a 7–8% higher concentration in experiments where all other variables were identical"; from 2.1 both volumes are selectable [52]. Jacobs 2014 (50 citations) and the Umbrella paper (33) show threshold choice changes concentration estimates [47][48]; ddpcRquant (113) and definetherain (129) exist because vendor thresholds were distrusted [49][50]. dMIQE's checklist requires "Partition classification method (thresholding)", "Partition volume", "Copies per partition (λ)", "Number of partitions", "dPCR analysis program (source, version)" [44]. Manual multiplex "hours" and operator bias are from note 10 (not re-fetched) [4]. |
| 3 Data | 4 | Gromgorgel/ddPCR: Apache-2.0; Dataset.zip with 472 reactions × up to 16,985 droplet fluorescence values plus design metadata [46]; Lievens 2016 paper (CC BY, 101 citations) [45]. ddpcr R package: MIT, 5 wells / 72,727 droplets sample data, single-plate [51]. Zenodo 15829164 (CC BY 4.0): QX200 vs QIAcuity copy-number comparison, summary-level files [53]. No QIAcuity per-partition public set (gap). |
| 4 Determinism | 4 | Each classifier has a DOI [45][47][48][49][50]; there is no consensus, which is the product thesis (agreement, not a threshold). Poisson/binomial CI maths standard. |
| 5 Fit | 4 | Robustness engine and cards with "partition table" in place of "amplification curve"; record, MCP and autonomy unchanged. Needs new importers and a new data model; whether rdmlpython already reads dPCR partition tables could not be confirmed from its README or PyPI page (section 7) [54][55]. |
| 6 Effort/risk | 2 | Note 10's own estimate: importers 3–5 days, five classifiers 1–2 weeks, cards 1 week, acceptance tests 1 week, multiplex 2–3 weeks: 4–7 weeks [4]. Vendor export formats drift between versions; the six open R tools are GPL/Artistic and cannot be copied; 2D multiplex clustering is hard. |
| 7 Champion | 3 | dMIQE group and the Lievens/JRC lineage; no agency mandate; many users are also eDNA, wastewater and gene-therapy labs (cross-sell). |
| 8 Competition | 3 | Vendor software is free with the instrument and improving (QIAcuity multiple thresholds per note 10); open tools are single-plate and old; no open multi-method, multi-plate tool exists. |

Weighted: 75 + 100 + 60 + 40 + 60 + 20 + 30 + 15 = **400 → 80**.

### 3.7 HRM genotyping engine (note 11, D1)

What it is: normalisation windows, optional temperature shift, difference curves, cluster calls with per-well confidence and a robustness grid over the vendor's knobs; cards for flipped wells and control disagreements [5].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 3 | Title/abstract: 4,200 all-time; 244 (2019) → 226 (2022) → 159 (2025): declining [8]. MS-HRM (methylation) 42 papers in 2025 [8]. Wittwer 2003 (859 citations) is the founding paper [57]. |
| 2 Pain | 3 | Vendor modules are paid, Windows, with unexplained confidence scores (note 11; vendor pages for Precision Melt could not be reached, section 7) [5]. The "homozygote accuracy 70.3 %, commercial software worse than custom analysis" claim (Li 2014 in note 11) could not be located in Europe PMC and is **unverified** [5]. ScreenClust (48 citations) and uMelt (182) show demand for better analysis [66][65]. |
| 3 Data | 3 | Athamanolap 2014 (PLOS ONE, CC BY): S1–S7 are uMelt-*simulated* curves; no in vitro curve files [61]. Dryad 10.5061/dryad.12g7j: HRM Tm table, 8 loci × 90 samples with 14 references (Dryad terms; CC0 per note 11, not shown on page) [62]. Zenodo 6045374 (CC BY 4.0): two supplementary tables for a 19-serovar HRM assay, contents not described [63]. No raw-curve HRM set with sequencing truth (gap). |
| 4 Determinism | 3 | Normalisation/shift/difference are standard; the cluster-count criterion is not; MeltingPlot's Tm-link rule is published (BMC Bioinformatics 2021, 6 citations) but the repo shows no licence [64]. |
| 5 Fit | 4 | RDML carries melt data; rdmlpython has a melt-curve analysis command [54]; the cluster-plus-grid engine would be shared with 3.8. |
| 6 Effort/risk | 2 | 3–5 weeks for one developer (note 11) [5]. Patents: US 8,296,074 (Utah; clustering of melting profiles; Google lists "Active", anticipated expiry 2026-09-20, i.e. four weeks ago, but Google states the date is an assumption) [58]; US 8,068,992 (Utah; exponential background subtraction; "Active – Reinstated", adjusted expiry 2029-02-01) [59]; Bio-Rad clustering patent to 2032 (note 11) [5]. Counsel needed before shipping exponential background or overlay code. |
| 7 Champion | 2 | None found; MeltingPlot's hospital-epidemiology niche is the closest. |
| 8 Competition | 3 | uAnalyze-HRM (MIT, hierarchical clustering with user-set k, 1 star) [60]; vendor modules; nothing records decisions. |

Weighted: 45 + 60 + 45 + 30 + 60 + 20 + 20 + 15 = **295 → 59**.

### 3.8 Allelic-discrimination caller (note 09 D3; note 11 D5)

What it is: two-dye full-curve genotype calls (best-cycle difference + clustering, and endpoint mixture models) with per-sample confidence, agreement between methods, Hardy–Weinberg and control checks, and recorded re-calls [3][5].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 4 | Title/abstract: 5,139 all-time; 301 (2019) → 400 (2025), growing (KASP in plant breeding) [8]. |
| 2 Pain | 3 | The full-curve algorithm paper (Callegaro 2006, NAR) reports 12 of 84 sequenced endpoint calls wrong (note 09) but has only 10 citations [67][3]; Fujisawa 2004's mixture model (12 citations) "succeeded in cases where maximum likelihood and k-means clustering failed" [68]. TaqMan Genotyper: free, Windows 10, user-drawn linear boundaries or "Autocalling", manual call changes allowed, no API [69]. Pain is plausible but thinly evidenced. |
| 3 Data | 1 | No public two-dye raw-curve dataset found (notes 09 and 11, and this check) [3][5]. |
| 4 Determinism | 3 | Methods published [67][68] but little-used; vendor methods proprietary. |
| 5 Fit | 4 | Two-dye raw curves in RDML; shares the cluster engine with 3.7; override logging fits the record. |
| 6 Effort/risk | 4 | 1–3 weeks; scikit-learn (BSD); no patents found (not exhaustively searched). Hardest: dye naming and passive-reference normalisation across instruments. |
| 7 Champion | 2 | None; breeders live in LGC's KASP ecosystem (note 11) [5]. |
| 8 Competition | 2 | Free vendor callers (TaqMan Genotyper, KlusterCaller, SNPviewer) that users accept [69][5]. |

Weighted: 60 + 60 + 15 + 30 + 60 + 40 + 20 + 10 = **295 → 59**.

### 3.9 miRNA panel normalisation robustness (note 09, D4)

What it is: panel presets (spike-ins, inter-plate calibrator, hemolysis pair), expressed-call threshold, global mean, geNorm/NormFinder sets, spike-in and IPC normalisation, hemolysis flag; robustness over normaliser family; per-miRNA "stable under n of m analyses" [3].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 4 | Title/abstract (normalisation-specific): 262 all-time, 13–19/yr; broad miRNA-qPCR full text 68,809 all-time, 6,210 in 2025 [8]. Big, flat field. |
| 2 Pain | 5 | Faraldi 2019 (Sci Rep, CC BY, 146 citations), Table 1: miRNAs "up" at ≥ 5-fold were 43 (global mean), 43 (mean endogenous), 41 (miR-21), 40 (miR-320d), 55 (mean spike-in), 74 (cel-39 spike-in); spike-in methods gave "a completely inverted trend" [71]. Mestdagh 2009 global-mean paper: 844 citations [70]. Hemolysis 13-fold and the vendor ΔCq > 7 rule are from note 09; the Qiagen panel page reached names GeneGlobe but not the rule (not verified on page) [3][72]. |
| 3 Data | 2 | Faraldi: "available from the corresponding author on reasonable request" [71]. No public Cq panel dataset located in this check (gap; GEO may hold TaqMan-array series, not searched). |
| 4 Determinism | 4 | Global mean [70], geNorm (in qPilot), spike-in and IPC arithmetic, hemolysis ΔCq rule (vendor). |
| 5 Fit | 5 | The robustness engine was built for "which normaliser"; miRNA is where the answer flips. |
| 6 Effort/risk | 4 | 1–2 weeks on existing geNorm code (note 09) [3]; 384-well TLDA/OpenArray imports are an existing roadmap item. |
| 7 Champion | 2 | No consortium; vendor free web tools. |
| 8 Competition | 3 | GeneGlobe and ExpressionSuite are free; Clarida does not list miRNA today [18]. |

Weighted: 60 + 100 + 30 + 40 + 75 + 40 + 20 + 15 = **380 → 76**.

### 3.10 Absolute-quantification composite standard curves (note 08, D3)

What it is: per-run weighted regression and a pooled (composite) curve after an ANCOVA homogeneity test, optional hierarchical model, switchable acceptance cards (EPA 1696.1, Draft Method C, ENGL), standard-vs-sample efficiency check from raw curves, unit chains, non-detect policies, robustness over calibration choices [2].

| Criterion | Score | Evidence |
|---|---|---|
| 1 Community | 4 | Title/abstract (narrow): 435 all-time, 26/yr; broad full text 41,269, 3,354 in 2025 [8]. Serves wastewater, EPA beach methods, microbial load, veterinary and plant pathogens. |
| 2 Pain | 4 | Pecson's 36-method interlaboratory spread [32]; EPA methods require per-run acceptance that labs check in spreadsheets [35]; Lane 2020 exists because "Bayesian master curves" were too hard and an Excel workbook replaced them (8 citations) [37]; Ruijter 2021 (92 citations): efficiency correction is required for accurate reporting [39]. |
| 3 Data | 3 | EPA "data for Lane et al. 2020": xlsx of standard curves and example samples, public, under the EPA Science Hub licence (terms not read) [36]. USGS multi-lab standards (public domain) [23]. |
| 4 Determinism | 5 | EPA 1696.1 (verified text): E 0.90–1.10, R² ≥ 0.980, LLOQ = the 95 % prediction upper limit at the lowest standard, IAC (multiplex VIC) Cq SD ≤ 1.16, SPC Sketa22 SD ≤ 0.62 Cq, 3-SD blank thresholds [35]. Sivaganesan 2008 Bayesian master curve (76 citations) [38]; Lane 2020 WLR + ANCOVA [37]; Ruijter efficiency correction [39]. |
| 5 Fit | 5 | Per-well efficiency is native; standard-vs-sample efficiency mismatch and one-point calibration are nearly free; multi-plate studies are the unit of work; this engine is the base for 3.2, 3.4 and 3.5. |
| 6 Effort/risk | 3 | 3–5 weeks including three method cards (note 08) [2]; EPA licence terms to check; PyMC/NumPyro optional (Apache-2.0). |
| 7 Champion | 3 | EPA methods are mandates for beach-monitoring labs; EMMI for environmental microbiology; no single consortium. |
| 8 Competition | 4 | Vendor software: one curve per plate; WES archived; no open multi-run composite-curve tool. |

Weighted: 60 + 80 + 45 + 50 + 75 + 30 + 30 + 20 = **390 → 78**.

---

## 4. Ranking

| Rank | Candidate | Community (15) | Pain (20) | Data (15) | Determinism (10) | Fit (15) | Effort/risk (10) | Champion (10) | Competition (5) | **Score** |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | eDNA LOD/LOQ passport + detection calls | 4 | 5 | 5 | 5 | 5 | 4 | 4 | 5 | **93** |
| 2 | Telomere Study Mode | 3 | 5 | 4 | 4 | 5 | 4 | 5 | 5 | **87** |
| 3 | dPCR partition-level plugin | 5 | 5 | 4 | 4 | 4 | 2 | 3 | 3 | **80** |
| 4 | Absolute-quant composite curves | 4 | 4 | 3 | 5 | 5 | 3 | 3 | 4 | **78** |
| 5 | miRNA panel normalisation | 4 | 5 | 2 | 4 | 5 | 4 | 2 | 3 | **76** |
| 6 | Gene/cell therapy run-acceptance packs | 4 | 4 | 1 | 5 | 4 | 3 | 3 | 3 | **68** |
| 7 | Wastewater run packet | 4 | 4 | 2 | 3 | 3 | 3 | 3 | 3 | **64** |
| 7 | GMO percentage module | 2 | 3 | 3 | 5 | 4 | 4 | 2 | 3 | **64** |
| 9 | HRM genotyping engine | 3 | 3 | 3 | 3 | 4 | 2 | 2 | 3 | **59** |
| 9 | Allelic-discrimination caller | 4 | 3 | 1 | 3 | 4 | 4 | 2 | 2 | **59** |

Sensitivity: if Data is weighted 0 (you are willing to collect your own plates), the order of the top two is unchanged (eDNA 90, telomere 87) and dPCR rises to 80 → tied third with absolute quant. If Effort is weighted 20 instead of 10, dPCR falls to 73 and miRNA rises to 78; the top two still hold. If Community is weighted 25, dPCR becomes second (84) ahead of telomere (82) and eDNA stays first (92). The eDNA recommendation is robust to every re-weighting tried; the telomere-vs-dPCR order depends on how much you value community size over effort.

---

## 5. Recommendation, sequencing, and what generalises

### 5.1 Build order

1. **Weeks 1–3: the "standard-series substrate" and the eDNA LOD/LOQ passport.** Add typed standard wells with nominal copies and lot; a per-well positive/negative call from the raw curve (plateau, efficiency and Cq rules, reported alongside the instrument's "Undetermined"); the detection table per standard; model-family fits (Weibull I/II, asymptotic regression, log-logistic, Michaelis–Menten, 2–4 parameters) by maximum likelihood with AIC selection; LOD at p = 0.95 with bootstrap CI; effective LOD for n = 1…12 via p = 1 − 0.05^(1/n); LOQ from a CV-vs-concentration fit at a stated threshold (default 35 %, exposed); the discrete LOD/LOQ alongside. Acceptance test: reproduce `Comparison-Data.csv` from `GEDWG_LOD_DATA3.csv` within a stated tolerance for the 35 solvable assays [23]. Cards: outlier standards (Cq outside 90–110 % of the standard's median), CV threshold, model choice when the spread crosses a replicate-count boundary. Record: the Klymus reporting minimum as facts. MCP: `qpcr_lod`.
2. **Weeks 4–7: Telomere Study Mode.** Sample sheet (individual, extraction method/lot, plate, well, replicate run, role); T/S three ways; replicate rules; QC-DNA plate gate; plate/well mixed model; ICC with CI from re-run subset; Z-scored output; TRN items auto-filled. Acceptance tests: Nettle dataset1/2 [9] and Dagnall S1 (576 results, CC0) [10]; ICC must match the TRN R script on `example.xls` [11]. MCP: `qpcr_study` with a `telomere` method card.
3. **Weeks 8–11: composite standard curves (3.10)** on the substrate from step 1, with EPA 1696.1 and ENGL cards; acceptance test on the EPA Lane 2020 workbook [36]. This unlocks the gene-therapy (3.2), wastewater (3.4) and GMO (3.5) rule packs as declarative YAML "method cards", each ~1–2 weeks.
4. **Weeks 8–11 in parallel, or after:** eDNA detection-call rule pack (3.3b) encoding the USFWS QAPP, with negations human-only and a detection-matrix export.
5. **Quarter 2: dPCR partition plugin (3.6)** as the second data kind, starting with the Lievens Apache-2.0 per-droplet set [46] and the single-channel classifiers; multiplex later. Confirm rdmlpython's partition-table support first (section 7).
6. **Opportunistic: miRNA normalisation (3.9)** once a public panel dataset is secured or a partner lab shares plates; HRM and allelic discrimination only if a champion appears, and HRM only after patent counsel.

### 5.2 Existing decision kinds and record fields: what generalises

Generalises as-is:
- **Replicate outlier (drop/keep)**: telomere replicate rules, eDNA outlier standards, gene-therapy QC duplicates.
- **Empty-well / non-detect rules**: become the non-detect policy axis (zero, half-LOD, LOQ/2, censored) in eDNA, wastewater, gene therapy.
- **Group cut-offs** as a robustness axis: Cq ≤ 40 positive-call cut-offs, CV thresholds, acceptance windows.
- **Impact-ranked cards, autonomy levels, escalation rule**: unchanged; "conclusion-flipping" maps to "a sample's call flips", "a site's detection flips", "a cohort member crosses a tertile", "an integer copy number changes".
- **Record**: hash-chained decision log, versions, checksums, "no naked numbers", explain-any-number, methods paragraph, MCP contracts (`qpcr_study`, `qpcr_robustness`, `qpcr_decide`) all carry over. The checklist auto-fill mechanism carries over with a different item list (TRN, Klymus/Thalinger, dMIQE, ENGL).
- **GRADE-style study confidence**: reason sets change per domain ("ICC from 8 % re-runs", "LOD from one plate", "LoB from 3 blanks").
- **`qpilot plan`**: extends to "replicates needed for an effective LOD" and "ICC needed for this cohort size".

Needs new decision kinds:
- **Model-family choice** (eDNA LOD; composite-curve model).
- **Plate / run gate** (accept, accept with exclusions, reject): telomere QC DNAs, gene-therapy curve/QC failures, EPA/ENGL windows. Note 15's "Run Gate" is this, and should be built once as a generic rule-pack evaluator.
- **Control negation of a sample range** (eDNA field blanks, hood controls, extraction negatives): human-only.
- **Calibration bridging** (extraction-kit or lot calibrator vs within-group Z-scoring): telomere, gene therapy.
- **Constant provenance** (partition volume, genome size, conversion factor): dPCR, GMO, wastewater.
- **Cluster assignment / orphan** (dPCR multiplex, HRM, allelic discrimination): new, and the reason those three share an engine.

Needs new record fields: standard nominal quantity and lot (RDML `quantity` exists), sample roles beyond RDML's set (field blank, hood control, extraction negative, IPC, spike, calibrator, QC DNA, replicate run id, individual id, extraction method); assay passport facts (LOD, LOQ, effective LOD table, model, CI, intercept/efficiency history); ICC with CI; plate/well variance components; rule-pack id, version and hash; constants with provenance.

Does **not** generalise: geNorm M/V and the reverse-normalisation guard (expression-specific; telomere uses one single-copy gene, eDNA has no reference), ΔΔCq group comparisons and "per-gene consequence" (becomes per-assay, per-sample, per-site or per-individual), amplification-curve facts (baseline, efficiency, plateau) for dPCR partitions, and MIQE 2.0 item wording.

---

## 6. "Why this domain first" pitches

**eDNA (to an agency or consultancy eDNA lab lead).** Your QAPP already says what a positive is, which blanks negate which samples, and that a curve passes at E = 80–120 % and R² ≥ 0.95 [26]; your LOD and LOQ come from a provisional R script that reads a hand-built Cq/SQ CSV and whose answer moves up to 8.7-fold depending on which model it happens to pick [24][25]. qPilot reads every plate of the validation study, calls positive and negative from the raw curves rather than from "Undetermined", fits every model in Klymus 2020 and tells you the spread, logs the standards you dropped and why, and writes an assay passport (LOD, LOQ, effective LOD per replicate count, CI, model, criteria) that is re-run byte-for-byte when you transfer the assay or change reagents. Every negation in a survey run is a card a human signs; the record is what you hand over when a detection is challenged. The regression test is the USGS data release you already trust [23].

**Telomere (to a TRN member lab).** Your methods section will be judged against the TRN items, and the two things reviewers now ask for (an ICC from re-run samples and an explicit handling of extraction and plate effects) are the two things no analysis tool computes; the TRN script requires reshaping data by hand [11][13]. qPilot takes all your plates, computes per-well efficiency instead of the per-plate average, derives T/S three accepted ways and tells you how many cohort members change tertile between them, gates plates on your QC DNAs, fits the plate/well model, computes the ICC with its CI from the re-run subset, and auto-fills the TRN reporting items from the record. Acceptance is against Nettle's and Dagnall's public data [9][10]. Clarida does not do this [18]; the one open pipeline has no tests [17].

**(Reserve) dPCR (to a core-facility dPCR analyst).** Your software vendor changed the droplet volume constant and your concentrations moved 7–8 % with no change in the wet lab [52]; dMIQE asks you to state the classification method, partition volume, λ and software version [44]. qPilot classifies every well six published ways, reports how many agree on the conclusion, carries the volume constant as a fact with provenance, and writes RDML 1.3 partition tables so the "raw data" checklist item is one checksummed file.

---

## 7. What could not be verified (and what to do about it)

- **rdmlpython dPCR support.** Note 10 states rdmlpython has a dPCR data model and importers (Bio-Rad, Stilla). Neither the GitHub README nor the PyPI page (1.7.2, May 2023) mentions digital PCR; the rdml.org 1.3 page lists only the XSD [54][55][56]. Read the XSD and the library source before estimating 3.6.
- **Li 2014 HRM accuracy (70.3 % homozygotes; commercial worse than custom)**: not found in Europe PMC by title or author filter; treat as unverified [5].
- **Bio-Rad Precision Melt and Thermo QuantStudio Design & Analysis module pages**: 404/redirect loops; vendor module facts in this note come from notes 05 and 11 [5][7].
- **Faraldi "spike-ins invert the trend"**: Table 1 counts verified (43 vs 74 "up"); the inversion is the authors' description of Figure 4, not a per-miRNA count [71].
- **Telomere inter-lab CV 20.7 %, ICC 0.81 vs 0.93, extraction 40 % shift**: from note 09's sources, not re-fetched [3]; Nettle 2021's r = 0.48 for change is verified [16].
- **TRN membership count**: not published [11][12]. **NWSS site and lab counts**: not on the pages reached [31][76].
- **USGS data file "Cq" label**: the record page says "raw qPCR data" for `GEDWG_LOD_DATA3.csv`; open the CSV to confirm columns before writing the importer [23].
- **Dryad licence** for 10.5061/dryad.12g7j: page says "licensed for reuse" without naming CC0 [62]; Dryad's policy is CC0 but confirm on the record.
- **Patent dates** on Google Patents are stated by Google as assumptions; US 8,296,074's anticipated expiry (2026-09-20) has just passed, US 8,068,992 is "Reinstated" to 2029-02-01 [58][59]. Get counsel before HRM.
- **EPA Science Hub licence terms** for the Lane 2020 workbook: the licence URL is given but was not read [36].
- **Search engines**: Bing returned unrelated results and DuckDuckGo a bot challenge; Brave worked once. Forum-level practitioner evidence (Reddit, ResearchGate) was therefore not collected for any candidate; all pain evidence here is from papers, agency documents and vendor manuals.
- **Europe PMC counts** depend on query wording; both families are in Appendix A so they can be re-run. Title/abstract counts under-count (many papers mention qPCR only in Methods).

---

## 8. Sources

Local notes:
1. `00-brief-for-researchers.md` (this folder).
2. `08-edna-pathogen-absolute-quant.md`.
3. `09-genetics-therapy-applications.md`.
4. `10-digital-pcr.md`.
5. `11-melt-hrm-genotyping.md`.
6. `15-regulated-qc-transfer.md`.
7. `05-instruments-formats-standards.md`.

Counts:
8. Europe PMC REST API, https://www.ebi.ac.uk/europepmc/webservices/rest/search (queries run 17 Oct 2026; Appendix A).

Telomere:
9. Nettle, code and data archive, Zenodo, CC BY 4.0, https://zenodo.org/records/1994386 (v3 DOI 10.5281/zenodo.2615735).
10. Dagnall et al. 2017, PLoS One, CC0, https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0184098
11. Telomere Research Network, Study design & analysis (ICC script, example.xls, Recommendations 1–2), https://trn.tulane.edu/resources/study-design-analysis/
12. Telomere Research Network home ("A NIA and NIEHS sponsored network"), https://trn.tulane.edu/
13. Lindrose et al. 2021, PLoS One, DOI 10.1371/journal.pone.0245582 (Europe PMC: 75 citations, CC BY).
14. Cawthon 2009, Nucleic Acids Res, DOI 10.1093/nar/gkn1027 (1,153 citations).
15. Nettle et al. 2019, PLoS One, DOI 10.1371/journal.pone.0216118 (CC BY).
16. Nettle et al. 2021, Am J Epidemiol, DOI 10.1093/aje/kwab025 (CC BY).
17. NCI-CGR/cgrtelomeres, MIT, https://github.com/NCI-CGR/cgrtelomeres
18. Clarida product page, https://clarida.bio/

Gene and cell therapy:
19. Ma, Bell, Loker 2021, Mol Ther Methods Clin Dev, CC BY-NC-ND, https://pmc.ncbi.nlm.nih.gov/articles/PMC7786041/
20. FDA, Long Term Follow-Up After Administration of Human Gene Therapy Products (2020), https://www.fda.gov/media/113768/download
21. He et al. 2025, Interlaboratory assessment of candidate reference materials for lentiviral vector copy number, Mol Ther Methods Clin Dev, CC BY, https://pmc.ncbi.nlm.nih.gov/articles/PMC12229725/
22. ASGCT/Citeline Gene, Cell & RNA Therapy Landscape Report, Q2 2026, https://www.asgct.org/uploads/files/general/Final-ASGCT-Citeline-Q2-2026.pdf

eDNA:
23. USGS data release, Reporting the limits of detection (LOD) and quantification (LOQ) for environmental DNA assays: Data, DOI 10.5066/P9AKHU1R, public domain, https://data.usgs.gov/datacatalog/data/USGS:5d36fbfce4b01d82ce8a6cbf
24. Klymus et al. 2020, Environmental DNA, DOI 10.1002/edn3.29, CC BY (Crossref: 580 citations); full text https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download
25. cmerkes/qPCR_LOD_Calc, USGS provisional, https://github.com/cmerkes/qPCR_LOD_Calc
26. USFWS, Invasive Carp eDNA Monitoring Program Quality Assurance Project Plan 2025, https://www.fws.gov/sites/default/files/documents/2025-03/edna_qapp_2025.pdf
27. USFWS Whitney Genetics Laboratory, https://www.fws.gov/office/whitney-genetics-laboratory
28. Thalinger et al. 2021, Environmental DNA, DOI 10.1002/edn3.189, CC BY-NC (Crossref: 217 citations).
29. Zenodo 18833966, Ostrea edulis eDNA assay data, CC BY 4.0, https://zenodo.org/records/18833966
30. CRAN `drc` 4.0-0, GPL-2, https://cran.r-project.org/package=drc

Wastewater:
31. CDC NWSS, Wastewater surveillance data reporting and analytics (data dictionary v5.2.3), https://archive.cdc.gov/www_cdc_gov/nwss/reporting.html
32. Pecson et al. 2021, Environ Sci Water Res Technol, DOI 10.1039/d0ew00946f (186 citations).
33. Eawag, Digital PCR data for wastewater-based pathogen surveillance, Zenodo 17226976, CC BY 4.0, https://zenodo.org/records/17226976
34. PHES-ODM, https://github.com/Big-Life-Lab/PHES-ODM

Absolute quantification / EPA:
35. EPA Draft Method 1696.1 (HF183/BacR287), https://www.epa.gov/system/files/documents/2022-01/draft_method-1696.1-hf183_01052022_508.pdf
36. EPA data for Lane et al. 2020 Water, DOI 10.23719/1517793, https://catalog.data.gov/dataset/epa-data-for-lane-et-al-2020-water
37. Lane et al. 2020, Water 12:775, DOI 10.3390/w12030775 (CC BY).
38. Sivaganesan et al. 2008, BMC Bioinformatics 9:120, DOI 10.1186/1471-2105-9-120.
39. Ruijter et al. 2021, Clin Chem, DOI 10.1093/clinchem/hvab052.

GMO:
40. ENGL, Definition of minimum performance requirements for analytical methods of GMO testing (2015), CC BY 4.0, https://gmo-crl.jrc.ec.europa.eu/doc/MPR%20Report%20Application%2020_10_2015.pdf
41. EURL GMFF, Validation report maize MON 95275 (VL-01/22), CC BY 4.0, https://gmo-crl.jrc.ec.europa.eu/summaries/EURL-VL-01-22-VR.pdf
42. GMOMETHODS database (228 methods), https://gmo-crl.jrc.ec.europa.eu/gmomethods/

Digital PCR:
43. dMIQE Group, Huggett 2020, Clin Chem, DOI 10.1093/clinchem/hvaa125 (401 citations, CC BY).
44. dMIQE 2020 checklist (XLSX), https://rdml.org/files/docs/dMIQE_checklist.xlsx
45. Lievens et al. 2016, PLoS One, DOI 10.1371/journal.pone.0153317 (101 citations, CC BY).
46. Gromgorgel/ddPCR (cloudy; Dataset.zip, 472 reactions), Apache-2.0, https://github.com/Gromgorgel/ddPCR
47. Jacobs et al. 2014, BMC Bioinformatics, DOI 10.1186/1471-2105-15-283.
48. Jacobs et al. 2017, Umbrella, Anal Chem, DOI 10.1021/acs.analchem.6b04208.
49. Trypsteen et al. 2015, ddpcRquant, Anal Bioanal Chem, DOI 10.1007/s00216-015-8773-4.
50. Jones et al. 2014, definetherain, J Virol Methods, DOI 10.1016/j.jviromet.2014.02.020.
51. CRAN `ddpcr` 1.16.0, MIT, https://cran.r-project.org/package=ddpcr ; https://github.com/daattali/ddpcr
52. Bio-Rad, QX200 Droplet Reader and QX Manager Software Standard Edition User Guide (10000107223), droplet-volume note, https://www.bio-rad.com/webroot/web/pdf/lsr/literature/10000107223.pdf
53. Zenodo 15829164, dPCR copy-number precision (QX200 vs QIAcuity), CC BY 4.0, https://zenodo.org/records/15829164
54. RDML-consortium/rdmlpython, MIT, https://github.com/RDML-consortium/rdmlpython
55. rdmlpython on PyPI (1.7.2, 22 May 2023), https://pypi.org/project/rdmlpython/
56. RDML v1.3 Recommendation page, https://rdml.org/rdml_v_1_3.html

HRM and allelic discrimination:
57. Wittwer et al. 2003, Clin Chem, DOI 10.1373/49.6.853 (859 citations).
58. US 8,296,074 B2 (University of Utah Research Foundation), https://patents.google.com/patent/US8296074B2/en
59. US 8,068,992 B2 (University of Utah Research Foundation), https://patents.google.com/patent/US8068992B2/en
60. zachdwight/uAnalyze-HRM, MIT, https://github.com/zachdwight/uAnalyze-HRM
61. Athamanolap et al. 2014, PLoS One, CC BY, https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0109094
62. Dryad, Kartzinel et al. HRM Tm table, https://datadryad.org/stash/dataset/doi:10.5061/dryad.12g7j
63. Zenodo 6045374, A. pleuropneumoniae HRM supplementary tables, CC BY 4.0, https://zenodo.org/records/6045374
64. MatteoPS/MeltingPlot (no licence shown), https://github.com/MatteoPS/MeltingPlot ; Perini et al. 2021, BMC Bioinformatics, DOI 10.1186/s12859-021-04020-y
65. Dwight et al. 2011, uMELT, Bioinformatics, DOI 10.1093/bioinformatics/btr065 (182 citations).
66. Reja et al. 2010, ScreenClust, Methods, DOI 10.1016/j.ymeth.2010.02.006 (48 citations).
67. Callegaro et al. 2006, Nucleic Acids Res, DOI 10.1093/nar/gkl185 (10 citations).
68. Fujisawa et al. 2004, Bioinformatics, DOI 10.1093/bioinformatics/btg475 (12 citations).
69. Thermo Fisher, TaqMan Genotyper Software v1.7.1, https://www.thermofisher.com/us/en/home/technical-resources/software-downloads/taqman-genotyper-software.html

miRNA:
70. Mestdagh et al. 2009, Genome Biol, DOI 10.1186/gb-2009-10-6-r64 (844 citations).
71. Faraldi et al. 2019, Sci Rep, CC BY, https://pmc.ncbi.nlm.nih.gov/articles/PMC6367481/
72. Qiagen miRCURY LNA miRNA Serum/Plasma Focus PCR Panels page (names GeneGlobe), https://www.qiagen.com/us/products/discovery-and-translational-research/pcr-qpcr-dpcr/mirna-research/mircury-lna-mirna-qpcr-panels-and-arrays/mircury-lna-mirna-serum-plasma-focus-pcr-panels

Other:
73. EuroMRD (69 labs, 26 countries; 2024 guidelines; biannual QA), https://www.euromrd.org/
74. Allotrope ASM LICENSE.md (CC BY-NC 4.0 non-commercial; CC BY-ND 4.0 commercial; member licence for modification), https://gitlab.com/allotrope-public/asm/-/raw/main/LICENSE.md
75. Crossref REST API (citation counts for 24, 28), https://api.crossref.org/
76. CDC, About wastewater data (no site counts), https://www.cdc.gov/nwss/about-data.html

---

## Appendix A. Europe PMC counts (run 17 Oct 2026)

A1. Title-or-abstract family (comparable across domains; used in the scorecards):

| Domain | Query (TITLE or ABSTRACT) | All | 2019 | 2022 | 2025 |
|---|---|---|---|---|---|
| Telomere | "telomere length" AND (qPCR OR "quantitative PCR" OR "T/S ratio") | 1,359 | 80 | 116 | 114 |
| VCN / AAV / biodistribution | ("vector copy number" OR "vector genome" OR biodistribution OR "AAV titer") AND (qPCR OR ddPCR OR "digital PCR" OR "quantitative PCR") | 252 | 11 | 16 | 35 |
| eDNA | "environmental DNA" AND (qPCR OR "quantitative PCR" OR ddPCR OR "digital PCR") | 540 | 44 | 51 | 79 |
| Wastewater | ("wastewater-based epidemiology" OR "wastewater surveillance") AND (qPCR OR "RT-qPCR" OR ddPCR OR "digital PCR") | 595 | 0 | 102 | 89 |
| GMO | ("genetically modified" OR GMO) AND ("event-specific" OR quantification) AND ("real-time PCR" OR qPCR OR "digital PCR") | 266 | 6 | 9 | 6 |
| dPCR | "digital PCR" OR "droplet digital PCR" OR ddPCR OR dPCR | 8,503 | 522 | 797 | 994 |
| HRM | "high resolution melting" OR "high-resolution melting" OR "high resolution melt" OR "high-resolution melt" | 4,200 | 244 | 226 | 159 |
| Allelic discrimination | "allelic discrimination" OR KASP OR "TaqMan SNP" OR "TaqMan genotyping" | 5,139 | 301 | 370 | 400 |
| miRNA normalisation | (miRNA OR microRNA) AND (qPCR OR "RT-qPCR") AND (normalization OR normalisation OR "reference gene") | 262 | 19 | 14 | 13 |
| Absolute quant | ("absolute quantification" OR "standard curve") AND (qPCR OR "quantitative PCR" OR "real-time PCR") AND (copies OR "gene copies") | 435 | 17 | 28 | 26 |
| MS-HRM (extra) | "MS-HRM" OR "methylation-sensitive high resolution melting" | — | — | — | 42 |

A2. Broad full-text family (over-counts; shows the same growth pattern):

| Domain | All | 2015 | 2019 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| Telomere qPCR | 9,204 | 424 | 577 | 723 | 694 | 676 | 809 |
| VCN / AAV / biodistribution | 6,866 | 169 | 310 | 513 | 581 | 659 | 1,017 |
| eDNA qPCR/dPCR | 2,625 | 71 | 163 | 228 | 213 | 235 | 329 |
| Wastewater epidemiology PCR | 2,233 | 0 | 2 | 458 | 403 | 304 | 304 |
| GMO quantification PCR | 14,611 | 563 | 918 | 1,076 | 993 | 1,265 | 1,559 |
| Digital PCR | 30,747 | 549 | 1,781 | 3,400 | 3,293 | 3,308 | 4,104 |
| HRM | 13,820 | 835 | 888 | 1,036 | 831 | 871 | 796 |
| Allelic discrimination / KASP | 21,546 | 1,089 | 1,250 | 1,605 | 1,294 | 1,237 | 1,411 |
| miRNA qPCR normalisation | 68,809 | 2,903 | 5,088 | 6,347 | 5,130 | 4,993 | 6,210 |
| Absolute quant standard curve | 41,269 | 1,603 | 2,076 | 3,451 | 3,098 | 2,894 | 3,354 |

Scripts and raw JSON are in the session scratchpad (`epmc.py`, `epmc2.py`, `epmc_counts*.json`); re-run them to refresh.
