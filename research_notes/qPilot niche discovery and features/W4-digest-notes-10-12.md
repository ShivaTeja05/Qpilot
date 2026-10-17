# Digest of wave-1 notes 10, 11, 12 for qPilot

Conventions: `[n]` citations are resolved to the URL (or DOI, where the note gives only a DOI) from each note's §6. "(uncited in note)" marks numbers with no inline citation. "(estimate)" is the note's own label. Confidence and rank are the note's own.

---

# NOTE 10 — Digital PCR (dPCR / ddPCR): should qPilot extend into it, and how

Method caveat the note itself states: the WebSearch budget was exhausted after six queries; all evidence is from direct fetches of vendor manuals, RDML schema, GitHub/CRAN/Bioconductor, SEC filings, Zenodo and Europe PMC. **No forum evidence** (Reddit/ResearchGate/Biostars) was gathered; "analysts disagree" is evidenced from papers, manuals and GitHub issues. Items seen only in search snippets are marked "(snippet)".

## A. How this corner works

A dPCR reaction is split into thousands of partitions; each is read once per colour channel and called positive/negative; λ = −ln(Nneg/N) and concentration = λ/V, where V is partition volume (https://www.bio-rad.com/webroot/web/pdf/lsr/literature/10000107223.pdf). Every major platform exports per-partition fluorescence CSV, each in its own layout; vendor classification is a black box; native files (.qlp, .ddpcr, QIAcuity archives) are proprietary. Only Qiagen exposes a documented key-secured "Lab Automation API" (https://www.qiagen.com/en-US/resources/download/userManual/appendix-a-qiacuity-software-suite-api-v3200).

Key numbers: Bio-Rad claims ">12,000 peer-reviewed publications" (https://www.bio-rad.com/life-science/droplet-digital-pcr); QX Manager Standard is free after registration, Premium ships with a USB licence key, no price shown (https://www.bio-rad.com/en-us/sku/12018108-qx-manager-software-premium-edition?ID=12018108). Bio-Rad reduced droplet volume from 0.85 to 0.795 nL in QX Manager 2.0, "resulting in a 7–8% higher concentration" (https://www.bio-rad.com/webroot/web/pdf/lsr/literature/10000107223.pdf); QuantaSoft 1.3.2 used 0.91 nL (DOI 10.1007/s00216-017-0625-y); independent labs measured 13.1–15.9 % lower than stated (same DOI) and 0.786 nL (DOI 10.1021/acs.analchem.8b05828). QIAcuity nanoplates list at $1,676 (8.5k 96-well 10-pack), $699, $312 (https://www.qiagen.com/us/products/instruments-and-automation/pcr-instruments/qiacuity-digital-pcr-system); ~2 h per plate (same URL). Bio-Rad bought Stilla 30 June 2025 for $166.5 M cash plus debt/escrow/milestones and impaired Dropworks ($81.7 M) in Dec 2025 (https://www.sec.gov/Archives/edgar/data/12208/000001220826000010/bio-20251231.htm). Qiagen's dPCR product group "grew 3% in 2025 to $309.0 million" (https://www.sec.gov/Archives/edgar/data/1015820/000101582026000018/qgen-20251231.htm).

Community size (Europe PMC hit counts, 17 Oct 2026, https://www.ebi.ac.uk/europepmc/webservices/rest/search): dPCR vs qPCR records 2025: 4,104 vs 96,639; 2024: 3,308 vs 83,573 — i.e. dPCR ~4 % of PCR literature, growing ~25 % y/y while qPCR is flat (note's inference). Platform mentions 2025: QX200 811, QIAcuity 222 (+61 % vs 2024), Absolute Q 92, QX600 51. Application 2025: liquid biopsy/ctDNA 944, methylation 794, gene therapy/CAR-T 562, MRD 464. dMIQE2020 has 401 citations, dMIQE2013 652, EMMI 182 (same URL). Manual multiplex analysis takes "hours" per plate (https://academic.oup.com/bioinformatics/article-lookup/doi/10.1093/bioinformatics/bty136).

## B. Pain inventory (top 8 of 12)

| # | Pain | Who | Frequency / severity (as stated) | What exists today | Evidence URLs |
|---|---|---|---|---|---|
| P1 | 1D/2D threshold placement ambiguous; vendor auto-threshold fails (CHECK status, <10,000 droplets); user drags a line by eye | Bench scientist, core analyst | Every plate with rain/low input/FFPE/cfDNA; High (flips positive/negative, MAF, CNV) | QuantaSoft/QX Manager manual tools; QIAcuity 5 methods; R tools (GPL, single-plate, unmaintained); none reports sensitivity to the choice | https://www.bio-rad.com/webroot/web/pdf/lsr/literature/10000107223.pdf ; https://www.qiagen.com/en-US/resources/download/userManual/qiacuity-um-v3-5 ; DOI 10.1016/j.jviromet.2014.02.020 |
| P2 | Rain: count, exclude or model? Published rules contradict | Same | Common in degraded/FFPE/eDNA; High at low λ; "negative bias" if excluded | definetherain excludes; cloudy counts positive; Umbrella probabilistic; vendors ignore | https://academic.oup.com/clinchem/article/66/8/1012/5880117 ; https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0153317 ; DOI 10.1021/acs.analchem.6b04208 |
| P3 | Partition-volume constant differs by software version/platform and is wrong vs measurement (0.91→0.85→0.795 nL; measured 0.786; 13–16 % low) | PI, metrology/reference labs | Every cross-version/lab/platform comparison; Medium–High (7–8 % silent shift) | QX Manager 2.1+ legacy/new dropdown; QIAcuity VPF if loaded; nothing records which constant produced a number | https://www.bio-rad.com/webroot/web/pdf/lsr/literature/10000107223.pdf ; DOI 10.1007/s00216-017-0625-y ; DOI 10.1021/acs.analchem.8b05828 ; DOI 10.1016/j.talanta.2019.120293 |
| P4 | CIs Poisson-only, understate uncertainty; merged-well "Total" CI is a black box | Scientist, reviewer | Every study with replicates; Medium | GLMM R scripts; dpcR MRT; vendors print two CIs without method | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0153317 ; DOI 10.1016/j.bdq.2016.06.001 ; DOI 10.1186/1471-2105-15-283 |
| P5 | Multiplex cluster assignment manual and slow (16 clusters for 4-plex; hours per plate); sparse clusters ambiguous | Assay developer, GMO/VCN/MRD labs | Every multiplex >2 targets; High | ddPCRclust (R, 2019, 2 channels, ≤4 targets); Advanced Classification by hand; QIAcuity CXTM | https://academic.oup.com/bioinformatics/article-lookup/doi/10.1093/bioinformatics/bty136 ; DOI 10.1038/srep35451 ; https://www.qiagen.com/en-US/resources/download/scientificDocument/qpro-9346-an-dpcr-multiplex-12-plex-0125-ww |
| P6 | Multi-plate studies cannot be analysed together in open tools; vendor merge only inside one plate file | Scientist, core | Any study >1 plate; Medium–High | twoddpcr issue #3 open since 2019; QIAcuity hyperwells within plate | https://github.com/CRUKMI-ComputationalBiology/twoddpcr/issues/3 |
| P7 | LoB/LoD/LoQ drift with reagent lot (up to 4-fold); false-positive rates depend on sequence context | Liquid biopsy, MRD, pathogen labs | Every rare-target assay, each lot; High | CLSI EP17/ISO 20395 by hand in spreadsheets; no software keeps lot-specific LoB | DOI 10.1021/acs.analchem.6c04206 ; DOI 10.1038/s41598-019-49043-x |
| P8 | dMIQE's nine data-analysis items filled by hand; EMMI finds most papers omit controls | Authors, reviewers | Every manuscript; Medium | Checklist XLSX; RDMLdb; no tool fills it | https://rdml.org/files/docs/dMIQE_checklist.xlsx ; DOI 10.1021/acs.est.1c01767 |

Remaining pains: P9 vendor black box/version-breaking exports; P10 inter-platform comparability unknown; P11 only QIAcuity has an API, and template rules overwrite manual thresholds silently; P12 QC metrics (resolution, % rain) not standard in vendor outputs (QIAcuity v3.2 added some — snippet). All frequency columns are labelled "(estimate)" in the note's table header.

## C. Discoveries (note's rank order)

### D1. "Classify it every reasonable way": partition-level dPCR plugin whose output is agreement, not a threshold
- **Persona:** postdoc/core analyst with QX200/QX600 or QIAcuity plate of 24–96 wells of cfDNA/FFPE/eDNA/wastewater, weekly; wells show rain or few positives; vendor flags CHECK; SOP says set thresholds manually.
- **Pain evidence:** dMIQE calls thresholding "difficult" and warns of operator bias (https://academic.oup.com/clinchem/article/66/8/1012/5880117); Jacobs 2014: suboptimal thresholds "reduce the accuracy of concentration estimates considerably" (DOI 10.1186/1471-2105-15-283); Vynck 2023: comparative properties of classification methods "often unclear" (DOI 10.1093/clinchem/hvad063). Cost: manual thresholding of a rainy 96-well plate is tens of minutes to hours (note's own estimate, citing https://academic.oup.com/bioinformatics/article-lookup/doi/10.1093/bioinformatics/bty136).
- **Exists today / why fails:** vendor auto-threshold (undisclosed); QIAcuity's five methods; six R tools (GPL/Artistic, single plate, 2-channel, 2014–2021). None re-runs under all methods, quantifies dependence on the choice, or writes it into a re-runnable record.
- **Feature:** Inputs: Bio-Rad `*_Amplitude.csv` (QuantaSoft vs QX Manager header variants), QIAcuity "RFU values" zip incl. `Is Invalid`/`IsPositive`/`Threshold`/`Cycled volume`, Stilla per-droplet CSV, plus vendor results CSV. Deterministic grid per well/channel: (a) vendor call as recorded; (b) KDE "cloudy" with rain positive (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0153317, Apache-2.0 code https://github.com/Gromgorgel/ddPCR); (c) NTC-based GEV threshold (ddpcRquant, DOI 10.1007/s00216-015-8773-4); (d) k-means ±3 SD rain exclusion (definetherain DOI 10.1016/j.jviromet.2014.02.020; twoddpcr); (e) two-component Gaussian mixture (ddpcr/PoDCall, DOI 10.1093/bioinformatics/btac766); (f) partition-level posterior (Umbrella, DOI 10.1021/acs.analchem.6b04208). Each yields λ, concentration, binomial/Poisson CI (DOI 10.1371/journal.pone.0002876), QC facts. Robustness fact: "k of 6 classifications put well A03 above LoD". Decision Card only when the grid disagrees on a conclusion-level fact. Record: RDML 1.3 `partitions` with `endPtTable` (https://rdml.org/rdml_v_1_3.html). MCP: `dpcr_classify`, `dpcr_robustness`, `dpcr_decide`.
- **Feasibility:** Lievens 472 reactions Apache-2.0 (https://github.com/Gromgorgel/ddPCR); ddPCRclust 8 wells (https://github.com/bgbrink/ddPCRclust/tree/master/inst/extdata); ddpcr 5 wells MIT; PoDCall 5 wells (GPL, test use only); twoddpcr KRASdata. Libraries numpy/scipy/scikit-learn (BSD), rdmlpython (MIT). Effort (estimate): importers 3–5 days; classifiers 1–2 weeks; cards 1 week; acceptance tests 1 week. Hardest: 2D multi-colour (see D4) and QIAcuity invalid-partition semantics.
- **Why qPilot:** robustness engine + Decision Cards with partition table in place of curve; rdmlpython already has the dPCR model.
- **Risks/confidence:** vendor auto-threshold not recomputable; pain inferred from papers/UI, not users; regulated labs may trust vendor only. **High** that pain exists and is unsolved; **medium** on adoption. Rank 1.

### D2. The constants ledger: partition volume, dilution, reaction volume made visible
- **Persona:** PI comparing QIAcuity data with last year's QX200; GMO/reference lab transferring an accredited assay; core that upgraded QX Manager 1.2→2.x.
- **Evidence:** "7–8% higher concentration" from the 0.85→0.795 nL change (https://www.bio-rad.com/webroot/web/pdf/lsr/literature/10000107223.pdf); "a systematic error caused by uncorrected droplet volume in Naica" (DOI 10.1016/j.talanta.2019.120293); open tools hard-code 0.85/0.851/0.91/0.7/0.59 nL; dMIQE2020 requires "Partition volume" and program version (https://rdml.org/files/docs/dMIQE_checklist.xlsx).
- **Exists today:** QX Manager 2.1+ dropdown; QIAcuity VPF upload; nothing records which constant produced a number.
- **Feature:** every concentration derived from counts × named `volume_constant` fact with provenance; robustness axis over {export value, legacy vendor, measured literature}; card only when choice crosses a boundary (integer CN, LoQ, spec limit); platform-comparability fact; dMIQE items auto-filled. MCP `dpcr_recompute(study, volume_nl=…)`.
- **Feasibility:** pure arithmetic; literature constants with DOIs; effort (estimate) 2–3 days; hardest is convincing users it matters.
- **Why qPilot:** "no naked numbers" — binding each number to a fact is native.
- **Risks/confidence:** vendors may object; show vendor value first. **High** (documented by vendors themselves). Rank 2.

### D3. Study-level uncertainty and lab memory: replicate-aware CIs, merge policy, lot-specific LoB/LoD
- **Persona:** liquid-biopsy/pathogen lab calling detected/not on 1–5 positives weekly; CNV lab with 2–4 replicates; assay developer validating a lot.
- **Evidence:** Poisson CIs "underestimate total variability" (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0153317); vendor suites "do not allow ... the correct use of technical replicates" (DOI 10.1016/j.bdq.2016.06.001); LoB "varied up to 4-fold between different PCR reagent lots" (DOI 10.1021/acs.analchem.6c04206).
- **Exists today:** GLMM R code in a 2016 paper; dpcR MRT; EP17 spreadsheets; QIAcuity NTC rule per plate.
- **Feature:** (a) binomial GLMM with well random effect (statsmodels) beside Poisson CI; merge-policy card when the two CIs disagree; (b) LoB/LoD/LoQ engine from NTC/blanks across all plates (and across lots via lab memory): LoB = 95th percentile of blank positives (EP17 style); "detected?" card listing defining blanks; (c) QC facts per well (resolution, % rain, % compartmentalised, λ in range). MCP `dpcr_detection_limits(assay, lot)`, `dpcr_call(sample)`.
- **Feasibility:** maths in DOI 10.1016/j.bdq.2016.06.001, 10.1371/journal.pone.0002876, 10.1016/j.bdq.2014.08.001, 10.1007/978-1-4939-7778-9_3; statsmodels/scipy (BSD); Lievens 48 dilutions; Eawag wastewater CC-BY (https://zenodo.org/records/17226976). Effort (estimate): GLMM 1 week; LoB engine 1 week; cards 3 days. Hardest: LoB defaults with few blanks (surface as card).
- **Why qPilot:** multi-plate is the product's unit; GRADE-style confidence gets dPCR reasons.
- **Risks/confidence:** GLMM convergence on sparse counts. **High** for LoB/LoD, **medium** for GLMM uptake. Rank 3.

### D4. Multiplex cluster assignment with agreement scores and "orphan partition" cards
- **Persona:** assay developers and GMO/VCN/MRD labs running 3–4-plex on QX200, 6-colour on QX600, 5/12-plex on QIAcuity; every plate.
- **Evidence:** "sixteen clusters ... two individual exports" (DOI 10.1038/srep35451); "minutes rather than hours" and "very sparse clusters ... remain challenging" (https://academic.oup.com/bioinformatics/article-lookup/doi/10.1093/bioinformatics/bty136); "In some instances multiple thresholds could not be set" (https://www.qiagen.com/en-US/resources/download/scientificDocument/qpro-9346-an-dpcr-multiplex-12-plex-0125-ww).
- **Exists today:** ddPCRclust (R, 2 channels, ≤4 targets, last commit 2019, Artistic-2.0, deps unverified); Dobnik's Shiny tool; vendor lassoing.
- **Feature:** seedable ensemble on n-channel table: GMM with expected cluster count, density-peak/mean-shift, k-means with geometric init from single-positive controls; Hungarian label assignment; agreement = adjusted Rand index; per-partition "orphan" status; explicit recorded spillover matrix; cards when orphan allocation changes a call or controls are missing. MCP `dpcr_cluster(study, well)`.
- **Feasibility:** 8 annotated wells; scikit-learn; reimplement from paper. Effort (estimate) 2–3 weeks. Hardest: sparse clusters and arc-shaped double-positives (DOI 10.1016/j.bdq.2016.05.002).
- **Why qPilot:** agreement-as-confidence is the robustness engine.
- **Risks/confidence:** hard problem; vendors improving; licence checks. **Medium**. Rank 4.

### D5. dMIQE2020 auto-filled from the record, with RDML 1.3 dPCR file as "data transparency" artefact
- **Persona:** any author/reviewer; every manuscript.
- **Evidence:** checklist asks for classification method, partitions mean ± SD, volume, λ, program/version, replication, controls, data transparency (https://rdml.org/files/docs/dMIQE_checklist.xlsx); EMMI finds most papers omit controls (DOI 10.1021/acs.est.1c01767); 652 and 401 citations yet no compliance data (https://www.ebi.ac.uk/europepmc/webservices/rest/search).
- **Exists today:** XLSX by hand; RDMLdb; no dPCR vendor is RDML-compliant (https://rdml.org/software.html).
- **Feature:** table generator binding section-9 items to engine facts; "author must supply" fields for sections 1–6; RDML 1.3 export with `partitions`/`endPtTable` as single checksummed file. Machine-checkable: all nine section-9 items except experimental design; section-7 instrument model; section-8 LoB/LoD when blanks exist.
- **Feasibility:** rdmlpython writes the structures; effort (estimate) 3–5 days after D1. Hardest: honesty when a user analysed only part of the study.
- **Why qPilot:** record carries versions/checksums/decisions; MIQE 2.0 roadmap item becomes dMIQE.
- **Risks/confidence:** reviewers may not know dMIQE. **High**. Rank 5.

### D6. Application decision packs: CNV, VCN, wastewater, GMO
- **Persona:** CNV labs, CAR-T/gene-therapy QC, wastewater surveillance (EMMI), GMO control (JRC/ISO 17025).
- **Evidence:** CNV formulas are vendor prose (https://www.epfl.ch/research/facilities/gene-expression-core-facility/wp-content/uploads/2023/04/QIAcuity-dPCR-Applications-guide.pdf ; https://www.bio-rad.com/webroot/web/pdf/lsr/literature/Bulletin_6407.pdf); single-reference CNV ignores reference instability (DOI 10.1016/j.bdq.2016.06.001); adjusted VCN (DOI 10.1016/j.iotech.2024.101031); EuroMRD has no ddPCR guideline (DOI 10.1007/978-1-0716-2115-8_5).
- **Exists today:** vendor "experiment types" inside one plate; application papers' spreadsheets.
- **Feature:** declarative pack = decision space + facts + checklist: CNV (integer-call card when CI straddles n ± 0.5; multi-reference stability via geNorm logic), VCN (adjusted VCN; card when transduction efficiency unknown), wastewater (EMMI controls as required facts), GMO (JRC pass/fail facts). MCP `dpcr_pack_run(study, pack)`.
- **Feasibility:** formulas with DOIs; datasets at https://zenodo.org/records/15829164 and https://zenodo.org/records/17226976. Effort (estimate) 1 week per pack after D1–D3. Hardest: MRD has no consensus.
- **Why qPilot:** plugins add decision spaces cheaply.
- **Risks/confidence:** scope creep. **Medium–high** CNV/VCN, **medium** wastewater, **low** MRD. Rank 6.

### D7. Vendor capture for dPCR: QIAcuity API client and per-partition importers (lower priority, enabling)
- **Persona:** lab-automation engineer / agent-driven workflow with QIAcuity Four/Eight or QX200/QX600.
- **Evidence:** QIAcuity API with `thresholdSource` naming the rule that set a threshold (https://www.qiagen.com/en-US/resources/download/userManual/appendix-a-qiacuity-software-suite-api-v3200); Bio-Rad has no public API and Premium "external thresholding algorithms" undocumented (https://www.bio-rad.com/en-us/life-science/digital-pcr/qx-software); exports change structure between versions (QIAcuity 3.5).
- **Exists today:** vendor UIs; R importers keyed to one layout.
- **Feature:** versioned importers with header fingerprints; API client pulling results and rule names into the record as "vendor decisions"; watch-folder ingestion for Bio-Rad.
- **Feasibility:** 129-page API appendix; effort (estimate) 1–2 weeks; hardest: no public API test instance, needs partner lab.
- **Why qPilot:** fits vendor-capture roadmap and actor contract.
- **Risks/confidence:** API changes; QIAcuity-only. **Medium**. Rank 7.

## D. Data / libraries / standards / licences (12 most relevant)

| Name | What | Licence | URL |
|---|---|---|---|
| Lievens/Gromgorgel ddPCR + Dataset.zip | cloudy algorithm, QC, readers for QX and Naica, 472-reaction per-droplet dataset | Apache-2.0 | https://github.com/Gromgorgel/ddPCR |
| ddPCRclust example data | 8 multiplex `*_Amplitude.csv` | package Artistic-2.0; data licence not stated | https://github.com/bgbrink/ddPCRclust/tree/master/inst/extdata |
| ddpcr (CRAN) | ddPCR gating; 5 wells, 72,727 droplets | MIT; article data CC0 | https://cran.r-project.org/package=ddpcr ; https://github.com/daattali/ddpcr |
| PoDCall (Bioconductor) | GMM classification; 5 example wells | GPL-3 | https://bioconductor.org/packages/release/bioc/html/PoDCall.html |
| twoddpcr (Bioconductor) | k-means/Mahalanobis rain; KRASdata | GPL-3 | https://github.com/CRUKMI-ComputationalBiology/twoddpcr |
| definetherain | JS k-means tool + Albumin data | MIT | https://github.com/lukewarlow/definetherain |
| dpcR (CRAN) | GLM/MRT stats | GPL-3 | https://cran.r-project.org/package=dpcR |
| ddpcRquant | GEV threshold web tool | not stated | http://ddpcrquant.ugent.be/ |
| rdmlpython | RDML incl. dPCR import (Bio-Rad, Stilla) | MIT | https://github.com/RDML-consortium/rdmlpython |
| RDML v1.3 schema | `partitions`, `volume`, `endPtTable` | open spec | https://rdml.org/rdml_v_1_3.html |
| dMIQE2020 checklist | XLSX | from CC-BY paper | https://rdml.org/files/docs/dMIQE_checklist.xlsx |
| Zenodo Eawag wastewater / salmon .qlp / protist CN | well-level CSV; 8 proprietary .qlp; nanoplate vs droplet tables | CC-BY-4.0 | https://zenodo.org/records/17226976 ; https://zenodo.org/records/4957405 ; https://zenodo.org/records/15829164 |

Also: Python stack scikit-learn/scipy/statsmodels (BSD); PyPI has **no** `ddpcr`, `dpcr`, `pydpcr`, `ddpcrpy`, `digitalpcr`, `dpcr-tools`, `ddpcr-tools` (all 404, https://api.github.com/repos/ and PyPI JSON API). Bioconductor 2025 distinct-IP downloads: twoddpcr 2,184, ddPCRclust 2,176, PoDCall 1,467 (https://bioconductor.org/packages/stats/bioc/twoddpcr/). ddpcr CRAN: 79,523 downloads since 2015, 763 last month (https://cranlogs.r-pkg.org/downloads/total/last-month/ddpcr,dpcR,RDML).

**rdmlpython dPCR support (answering the brief's question):** yes — `import_digital_data` accepts "RDML", "Bio-Rad" and "Stilla" overview formats, writes default volumes 0.7/0.85/0.59 nL when none supplied, provides `get_digital_overview_data`, `get_digital_raw_data`, and migrates 1.3↔1.4 (https://github.com/RDML-consortium/rdmlpython). RDML dPCR "is only supported from RDML version 1.3 onwards" (https://www.gear-genomics.com/rdml-tools/help.html).

## E. Open questions / unverified
- No forum evidence (search budget); substitutes are vendor CHECK status, PoDCall/Dobnik statements, twoddpcr issue #3.
- Roche Digital LightCycler: nothing verifiable. Thermo Absolute Q export format unknown. Bio-Rad Premium "external thresholding algorithms" mechanism unknown.
- Exact QuantaSoft vs QX Manager amplitude column layouts and QX600 six-channel layout not read from Bio-Rad docs (>10 MB guides not fetched); known only via importer code.
- Licences of flowDensity/SamSPECTRAL/flowPeaks (ddPCRclust deps) and Umbrella's code location unverified.
- Whether RDML 1.4 is a published Recommendation (rdmlpython and Rust crate implement it; rdml.org lists up to 1.3).
- No public QIAcuity per-partition dataset; no inter-operator threshold-variability study; no dMIQE compliance survey; no market-size or installed-base figures.
- Qiagen release-note facts (RFU export Nov 2021; QC metrics v3.2; new thresholding v3.5) are from snippets only.

## F. Strongest verbatim quotes
1. "An overview of these partition classification methods is lacking and their comparative properties are often unclear" — Vynck 2023, DOI 10.1093/clinchem/hvad063
2. "the limit of blank varied up to 4-fold between different PCR reagent lots" — Kaudela 2026, DOI 10.1021/acs.analchem.6c04206
3. "The change resulted in a 7–8% higher concentration in experiments where all other variables were identical" — Bio-Rad QX Manager guide, https://www.bio-rad.com/webroot/web/pdf/lsr/literature/10000107223.pdf
4. "We call on manufacturers to provide sufficiently detailed output data" — Jacobs 2014, DOI 10.1186/1471-2105-15-283
5. "I cant analyse all the experiments at once on twoddPCR" — twoddpcr issue #3 (open since Aug 2019), https://github.com/CRUKMI-ComputationalBiology/twoddpcr/issues/3

---

# NOTE 11 — Melt-curve analysis beyond "single peak": HRM genotyping, species/strain ID, MS-HRM, allelic discrimination, multiplex deconvolution

Method caveat: WebSearch exhausted before the first query; all from direct fetches (vendor manuals, Google Patents, PubMed/Europe PMC, CRAN/PyPI/GitHub, RDML schema, Dryad/Zenodo APIs). **Forum evidence is a declared gap.** PubMed counts are title/abstract matches (undercounts).

## A. How this corner works

HRM records the fluorescence fall of a saturating dye during slow heating; curve shape (not only Tm) separates sequence variants. Users: clinical-genetics/PGx labs scanning for variants before sequencing — a region scan takes about 3 h plus about 3 h sequencing (https://pubmed.ncbi.nlm.nih.gov/20085814/); a PGx programme genotyped five DPYD variants in 617 patients over a year (https://pubmed.ncbi.nlm.nih.gov/42803377/). Microbiology types pathogens ("Minim typing": 268 S. aureus and 231 E. faecium melting types, https://pmc.ncbi.nlm.nih.gov/articles/PMC3486245/); outbreak HRM costs roughly €500 vs ~€5,000 MLST vs ~€10,000 WGS for a 100-isolate simulated outbreak (https://pmc.ncbi.nlm.nih.gov/articles/PMC7891011/); an AI-assisted CALR screen is under $10/test (https://pubmed.ncbi.nlm.nih.gov/42151105/). Plant breeders, food authentication (3 of 15 Acanthaceae products mislabelled, https://pubmed.ncbi.nlm.nih.gov/26011474/), MS-HRM epigenetics (0.1–1 % sensitivity, https://pmc.ncbi.nlm.nih.gov/articles/PMC1874596/).

The canonical five-step pipeline (background removal → normalisation → optional temperature shift → difference plot → clustering) has five judgement calls: normalisation windows, shift or not, reference cluster, cluster stringency, accept/re-call/exclude a well. Bio-Rad's knobs: shift bar default 0.20, Shape Sensitivity default 50 %, Tm Difference Threshold default 0.15 °C (0.05–1.00); the manual warns changing pre/post-melt regions changes clustering (https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/10000080911.pdf).

**Accuracy reality (Li 2014 claim):** on one SNP with predicted ΔTm = 0.00 °C across 10 instrument configurations, heterozygote accuracy was 99.7 % (n = 2,141) but homozygote accuracy only 70.3 % (n = 4,441); single-sample instruments beat plate imagers (78.1 % vs 61.8 %); the lab's custom software outperformed commercial software (P < 0.002); accuracy by amplicon length 72.3/83.1/59.8/65.9 % for 51/100/272/547 bp (https://pubmed.ncbi.nlm.nih.gov/24718912/). Nine instruments showed a 15-fold range in Tm SD (0.018–0.274 °C) (https://pubmed.ncbi.nlm.nih.gov/16423901/). Amplicons ≤300 bp scanned heterozygotes without error; 400–1000 bp gave 96.1 % sensitivity / 99.4 % specificity (https://pubmed.ncbi.nlm.nih.gov/15308590/).

**Literature trend:** PubMed HRM 3,920 total; by year 196 (2010), 336 (2015), 256 (2020), 170 (2024); MS-HRM 323; TaqMan allelic discrimination 1,200; microbiology 432, plant 216, veterinary 166, food 158 (https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=%22high+resolution+melting%22%5BTitle%2FAbstract%5D+OR+%22high-resolution+melting%22%5BTitle%2FAbstract%5D+OR+%22high+resolution+melt%22%5BTitle%2FAbstract%5D&rettype=count). Note's inference: bulk output peaked mid-2010s and has roughly halved; the frontier is digital melt and ML.

Money: Bio-Rad Precision Melt is paid, 2 user licences with 2 HASP HL hardware keys, price only after login (https://www.bio-rad.com/en-us/product/precision-melt-analysis-software?ID=df190aee-f184-497e-bfb6-b6dd632c99b5); Thermo HRM Software v2.0 (4397808) not orderable (https://www.thermofisher.com/order/catalog/product/4397808), and required a calibration plate (https://www.thermofisher.com/order/catalog/product/4409535).

## B. Pain inventory (top 8 of 13)

| # | Pain | Who | Frequency / severity | What exists today | Evidence URLs |
|---|---|---|---|---|---|
| P1 | Clusters change when pre/post-melt sliders move; no way to know which is "right" | Anyone calling genotypes | Every HRM plate (estimate); High (flips calls) | Vendor sliders; no robustness report | https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/10000080911.pdf ; https://patents.google.com/patent/US8606527B2/en |
| P2 | Homozygotes cannot be told apart reliably; temperature shifting hides Tm | SNP labs, breeders | Common; High | Vendor Tm-difference threshold (default 0.15 °C) | https://pubmed.ncbi.nlm.nih.gov/24718912/ ; https://www.gene-quantification.de/hrm.html |
| P3 | Sensitivity knob decides how many genotypes exist; vendors say turn it down on "false positives" | Variant scanning, species ID | Every plate with unknown allele count; High | Manual tuning | https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/10000080911.pdf |
| P4 | Ambiguous wells re-called by right-click, no reason recorded; "confidence %" unvalidated | All | Several wells per plate (estimate); Medium–High | Spreadsheet export; Call Type Automatic/Manual only | same URL |
| P5 | Runs not comparable across plates/days/instruments; reference isolates needed each run; Tm SD varies 15-fold | Typing labs, breeders, cores | Every multi-plate study; High | Reference controls per run; Bio-Rad Melt Study (CFX only) | https://pmc.ncbi.nlm.nih.gov/articles/PMC7891011/ ; https://pubmed.ncbi.nlm.nih.gov/16423901/ ; https://pubmed.ncbi.nlm.nih.gov/38438240/ |
| P6 | Dongle-locked, version-coupled software; files won't open after upgrades; calibration plates mandatory | Cores, shared instruments | Per lab, per upgrade; Medium | Buy another licence | https://www.bio-rad.com/en-us/product/precision-melt-analysis-software?ID=df190aee-f184-497e-bfb6-b6dd632c99b5 ; https://www.thermofisher.com/order/catalog/product/4409535 |
| P7 | HRM forces an unseen genotype into a known cluster | Clinical research, microbiology | Variant scanning, surveillance; High | Only ML research code | https://pmc.ncbi.nlm.nih.gov/articles/PMC11088152/ ; https://pubmed.ncbi.nlm.nih.gov/42151105/ |
| P11 | Allelic-discrimination "undetermined" wells need manual re-calling; vendor callers closed, dye-limited | Breeders (KASP), mouse colonies, PGx | Every genotyping plate; Medium | TaqMan Genotyper (FAM/VIC only), KlusterCaller (proprietary), SNPman (non-commercial), Excel | https://www.thermofisher.com/us/en/home/technical-resources/software-downloads/taqman-genotyper-software.html ; https://www.biosearchtech.com/support/tools/genotyping-software/klustercaller |

Others: P8 assay-design resolvability (uMelt web-only, login-walled); P9 multiplex melts hard (solved only by ML/Tm windows); P10 MS-HRM % read by eye against standards; P12 ML classifiers published without data; P13 no HRM reporting standard (RDML example file has 0 `meltTemp` results).

## C. Discoveries (note's rank order)

### D1. Open HRM genotyping engine where vendor knobs become Decision Cards and a robustness grid
- **Persona:** plant-breeding technician or microbiology RA calling genotypes from 96/384-well HRM plates on CFX/LightCycler/Rotor-Gene, several plates a week, with a dongle-locked vendor module; also the clinical-research lab scanning before sequencing.
- **Evidence:** homozygote accuracy 70.3 % and commercial software worse than custom (P < 0.002) (https://pubmed.ncbi.nlm.nih.gov/24718912/); normalisation windows change clustering (https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/10000080911.pdf); shifting discards Tm (https://www.gene-quantification.de/hrm.html). Cost: wrong homozygote = wrong genotype in mapping/clinical dataset; re-running a plate costs reagents plus a day (estimate).
- **Exists today:** vendor modules (closed clustering, one instrument each); uAnalyze-HRM (MIT, browser, user-chosen k, no confidence/record); rdmlpython finds peaks only; MBmca/qpcR (GPL) Tm only; ML code without data. None reports how many settings agree, logs re-call reasons, or is instrument-agnostic via RDML.
- **Feature:** Input RDML `mdp` (native from CFX Maestro, LightCycler 96, Rotor-Gene Q; via RDES/TableShaper for others) + plate map with known-genotype controls. Method: (a) rdmlpython bilinear/exponential/combined normalisation with explicit windows (https://raw.githubusercontent.com/RDML-consortium/rdmlpython/master/rdml.py); (b) optional integral-least-squares overlay (https://pubmed.ncbi.nlm.nih.gov/19216933/ ; https://patents.google.com/patent/US8296074B2/en); (c) difference curves; (d) hierarchical clustering on pairwise curve distance with a published cluster-count criterion + Tm-only step for homozygotes (that Li 2014's custom software was this clustering is the note's inference); (e) per-well confidence = distance to cluster relative to spread + leave-one-out stability. Robustness grid over windows × shift × stringency × metric; cards only for flipping wells: "Normalisation window", "Shift or not", "Number of genotypes", "Ambiguous well A7" (with Hardy–Weinberg consequence), "Control disagreement" (human only). Record in RDML `meltTemp`/`note`/`excl` + hash-chained log. Agent: `qpcr_hrm_genotype(study, assay, settings|"grid")`, `qpcr_hrm_explain(well)`.
- **Feasibility:** public maths; MIT code (rdmlpython, https://github.com/zachdwight/uAnalyze-HRM); CC BY curves (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0109094); CC0 Tm table (https://doi.org/10.5061/dryad.12g7j). Effort 3–5 weeks one developer (engine 1–2, grid/cards 1, importers 1, validation 1). Hardest: robust cluster-count criterion for 1/2/3-genotype plates; avoiding Bio-Rad's patented pipeline (https://patents.google.com/patent/US8606527B2/en) while counsel checks Utah patents.
- **Why qPilot:** same architecture (raw curves, robustness engine, cards, autonomy levels, record) applied to melt data; module reused for D4/D5.
- **Risks/confidence:** patent exposure for commercial users; declining HRM publication volume; Tm SD up to 0.274 °C limits any software; users may only have vendor `.melt` files. **High** pain real/implementable; **medium** adoption. Rank 1.

### D2. Cross-plate, cross-run melt alignment and reference-anchored typing ("melt passports")
- **Persona:** hospital/vet microbiology typing isolates by multilocus HRM over months; breeder with dozens of plates; core comparing a client's plate to last month's.
- **Evidence:** results from different datasets not directly comparable, references needed every run (https://pmc.ncbi.nlm.nih.gov/articles/PMC7891011/); Tm SD 0.018–0.274 °C (https://pubmed.ncbi.nlm.nih.gov/16423901/); ~0.2 °C ΔTm limit on Rotor-Gene (https://pmc.ncbi.nlm.nih.gov/articles/PMC3486245/); synthetic oligo calibrator (https://pubmed.ncbi.nlm.nih.gov/38438240/).
- **Exists today:** MeltingPlot (GPL, .xls Tm tables, 0.5 °C link rule); vendor Melt Study; Excel.
- **Feature:** per-assay "melt passport" in lab memory (expected Tm/curve per instrument and lot); per-run offset/scale from calibrator wells; cards when offset exceeds tolerance; MeltingPlot's rule (link isolates with all ΔTm ≤ δ, split by edge betweenness) reimplemented in Python/Apache-2.0 with δ as a card and robustness over δ. Agent: `qpcr_melt_align(run, calibrators)`, `qpcr_melt_type(study, delta)`.
- **Feasibility:** algorithm in CC BY paper; networkx (BSD); CC0 Tm table; RDML `meltTemp`. Effort 2–3 weeks. Hardest: how much shape to carry across runs.
- **Why qPilot:** multi-plate is native; lab memory and lot-drift alerts on roadmap.
- **Risks/confidence:** labs without references each run; mixed instruments may be beyond correction. **Medium–high**. Rank 2.

### D3. Permissive in-silico melt prediction and heterozygote composites
- **Persona:** assay developer designing HRM/multiplex melt; microbiologist assigning multiplex peaks.
- **Evidence:** uMelt web-only, login-walled, no source (https://www.dna-utah.org/umelt/quartz/um.php); absolute Tm depends on parameters (https://pubmed.ncbi.nlm.nih.gov/21300699/); experimental vs predicted 0.04 ± 0.48 °C at 50 % helicity (https://pubmed.ncbi.nlm.nih.gov/22889837/); heteroduplexes 25.7 ± 6.7 % of composite (https://pubmed.ncbi.nlm.nih.gov/24375593/); multiplex deconvolution: 0 PubMed hits for melt + deconvolution/peak fitting + PCR.
- **Exists today:** uMelt/HETS (web); DECIPHER MeltDNA (GPL-3, R); nothing permissive in Python; no open mixture fitter.
- **Feature:** `qpcr_melt_predict(sequence, Na, Mg)` implementing Tostesen 2003 multi-state partition function with SantaLucia 1998 parameters (https://rdrr.io/bioc/DECIPHER/man/MeltDNA.html) under Apache-2.0; HETS four-duplex composite. Uses: assay-import card ("predicted ΔTm 0.12 °C vs your instrument's Tm SD 0.09 °C"); auto-fill RDML `meltingTemperature`; multiplex deconvolution by NNLS onto predicted component curves, card when components are collinear.
- **Feasibility:** acceptance test = reproduce Athamanolap's CC BY simulated curves (92 serotypes × 9 salt conditions). Effort 3–5 weeks; hardest is near-linear partition function with loop entropy. scipy NNLS (BSD).
- **Why qPilot:** predictions as engine facts; extends `qpilot plan` to "can this assay resolve these alleles".
- **Risks/confidence:** absolute Tm off without calibration; reimplementation accuracy; prediction patents not found but not excluded. **Medium**. Rank 3.

### D4. MS-HRM methylation quantification with standard-curve and heterogeneity cards
- **Persona:** epigenetics or forensic/wildlife age-estimation lab with 0/0.1/1/10/50/100 % standards per plate, reading by eye.
- **Evidence:** profile matching to standards; heterogeneous methylation changes shape (https://pmc.ncbi.nlm.nih.gov/articles/PMC1874596/); 3 of 36 equivocal (https://pubmed.ncbi.nlm.nih.gov/18473334/); 323 MS-HRM papers; no open tool (gap).
- **Exists today:** general vendor HRM software; Excel.
- **Feature:** Wojdacz normalisation; per-plate calibration of a curve statistic (AUC between pure standards, or NNLS mixture weight) vs methylation %, monotonic fit with prediction intervals; cards "outside standard range", "not a two-component mixture (heterogeneous)", "standards not monotonic (PCR bias)". Agent `qpcr_mshrm_quantify(study)`.
- **Feasibility:** CC0 Dryad age-estimation sets with R scripts (https://doi.org/10.5061/dryad.66t1g1k2t etc.). Effort ~2 weeks. Hardest: statistic robust to heterogeneous methylation.
- **Why qPilot:** standards/groups/plate effects already modelled; GRADE maps to "within calibrated range".
- **Risks/confidence:** smaller community; PCR bias is wet-lab. **Medium**. Rank 4.

### D5. Allelic-discrimination (TaqMan/KASP) caller with whole-run evidence, model-based clusters, recorded re-calls
- **Persona:** breeder running KASP; mouse-facility technician (https://pubmed.ncbi.nlm.nih.gov/41966827/); PGx lab with sign-off (https://pubmed.ncbi.nlm.nih.gov/42803377/).
- **Evidence:** 1,200 PubMed papers; TaqMan Genotyper linear boundaries, FAM/VIC only (https://downloads.thermofisher.com/Taqman_Genotyper/v1.7.1/100121672_RevA_Taqman%20Genotyper_v1.7.1_Release%20Note.pdf); KlusterCaller proprietary; SNPman non-commercial (https://pubmed.ncbi.nlm.nih.gov/21697130/); Fujisawa 2004 model-based clustering flags unclear genotypes (https://pubmed.ncbi.nlm.nih.gov/14751987/).
- **Exists today:** TaqMan Genotyper (free, closed), KlusterCaller/Kraken, SNPman, Excel.
- **Feature:** Input RDML per-dye `adp`. ROX normalisation toggle; GMM with penalised likelihood on end-point angle/amplitude; whole-run consistency check (SNPman idea); plate QC (call rate, Hardy–Weinberg, control concordance, NTC cluster); cards "Undetermined wells", "Clusters not separated", "Control mismatch" (human only); robustness 2 vs 3 clusters, ± ROX. Agent `qpcr_snp_call(study, assay)`.
- **Feasibility:** scikit-learn (BSD); validation on SNPman demo data (licence check) or own plates. Effort 2–3 weeks. Hardest: dye crosstalk across instruments; FAM/HEX vs FAM/VIC naming in RDML.
- **Why qPilot:** same engine as D1; end-point genotyping is the second-most common qPCR use (uncited in note); hash-chained log answers PGx sign-off.
- **Risks/confidence:** free vendor tools "good enough"; LGC Kraken ecosystem. **Medium–high**. Rank 5.

### D6. Open HRM benchmark and deterministic "never-seen genotype" card
- **Persona:** method developers, reviewers; any lab asking "is this a new variant?"
- **Evidence:** ML papers share no data (data on request, https://pmc.ncbi.nlm.nih.gov/articles/PMC11088152/); novelty detection Youden 0.92; open-set needed for 57 of 64 untrained CALR variants (https://pubmed.ncbi.nlm.nih.gov/42151105/).
- **Exists today:** CC BY curves; unlicensed dHRM CSVs (https://github.com/aboussina/dHRM-novelty-detection); CC0 Tm tables; RDML example with 7,380 melt points; no cross-instrument benchmark with sequencing truth.
- **Feature:** publish CC0 "qPilot-HRM-bench" in RDML with genotype annotations; deterministic open-set rule in D1 (distance to every cluster exceeds leave-one-out-calibrated threshold → "unassigned/novel" card); public acceptance test for any future ML module.
- **Feasibility:** mostly curation; 1–2 weeks initial. Hardest: sequencing truth for homozygous pairs.
- **Why qPilot:** already validates against RDML benchmark; open commons of records planned.
- **Risks/confidence:** small initial set; unlicensed GitHub data. **Medium**. Rank 6.

### D7. Melt-informed quantification corrections (lower priority)
- **Persona:** SYBR/EvaGreen expression labs with primer-dimer/secondary peaks.
- **Evidence:** rdmlpython computes `corrF` (true-peak fluorescence share) and writes note texts ("no product with expected melting temperature", "several products...", "product detected in negative control") (https://raw.githubusercontent.com/RDML-consortium/rdmlpython/master/rdml.py); RDML-Tools excludes multi-product reactions.
- **Exists today:** rdmlpython CLI (MIT), GPL web tool; vendors show peaks but don't correct Cq.
- **Feature:** surface `corrF` and four note types as per-well facts; card "exclude or correct wells with secondary products" with per-gene consequence in the grid.
- **Feasibility:** wiring, 1 week. Hardest: verifying how LinRegPCR consumes `corrF`.
- **Why qPilot:** same MIT library already in the engine.
- **Risks/confidence:** overlaps existing melt-peak headline. **Medium**. Rank 7.

## D. Data / libraries / standards / licences (12 most relevant)

| Name | What | Licence | URL |
|---|---|---|---|
| rdmlpython | RDML + LinRegPCR + `meltCurveAnalysis` | MIT (PyPI 1.7.2, May 2023) | https://github.com/RDML-consortium/rdmlpython ; https://pypi.org/project/rdmlpython/ |
| RDML-Tools (web) | MeltingCurveAnalysis tab, RDES-TableShaper | GPL-3 | https://github.com/RDML-consortium/rdml-tools |
| RDML v1.3 schema + example | `mdp`/`tmp`/`fluor`/`meltTemp`/`meltingTemperature` | open standard | https://rdml.org/files/rdml/RDML_v1_3_REC.xsd ; https://rdml.org/files/rdml/example_1_3.rdml |
| uAnalyze-HRM | JS normalisation/overlay/difference/clustering; 8 instrument formats | MIT (2026); commercial use may need bioMérieux sublicence | https://github.com/zachdwight/uAnalyze-HRM |
| uMelt Quartz / HETS / uAnalyze (web) | curve prediction | free for research with citation; login required; no source | https://www.dna-utah.org/ |
| MBmca | Tm/peak functions, melt datasets | GPL (≥2) | https://cran.r-project.org/package=MBmca |
| qpcR | `meltcurve()` | GPL-2/3 | https://cran.r-project.org/package=qpcR |
| DECIPHER::MeltDNA | Tostesen 2003 melt simulation | Bioconductor (licence not confirmed) | https://rdrr.io/bioc/DECIPHER/man/MeltDNA.html |
| MeltingPlot | graph-based HRM typing from Tm tables | GPL | https://github.com/MatteoPS/MeltingPlot |
| Athamanolap 2014 S1–S8 | uMelt-simulated curves 92 serotypes × 9 conditions + in vitro | CC BY | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0109094 |
| Dryad Amphicarpaea HRM Tm table | 8 loci × 90 samples, 14 references | CC0 | https://doi.org/10.5061/dryad.12g7j |
| Patents to check | US 8,296,074 (Utah, clustering/overlay/exp. background; anticipated expiry 2026-09-20); US 8,068,992 (Utah, exp. background; "Active – Reinstated", 2029-02-01); US 7,582,429 (saturation dyes; expired 2025-12-08); US 8,606,527 (Bio-Rad clustering; to 2032-04-30) | — | https://patents.google.com/patent/US8296074B2/en ; https://patents.google.com/patent/US8068992B2/en ; https://patents.google.com/patent/US7582429B2/en ; https://patents.google.com/patent/US8606527B2/en |

Utah patent detail: US 8,296,074 claims hierarchical clustering by pairwise distance, exponential background subtraction from two slopes, integral-least-squares overlay, difference-plot distance; cited by Canon, Bio-Rad, Life Technologies, Roche, Idaho Technology, Seegene, Cepheid, Johns Hopkins (https://patents.google.com/patent/US8296074B2/en). The Bio-Rad patent is "the only public description of how a vendor's auto-clustering works" (https://patents.google.com/patent/US8606527B2/en). Note's inference: the bilinear baseline (2003) is not encumbered; exponential background may be to 2029 in the US.

## E. Open questions / unverified
- Prices of Bio-Rad Precision Melt, Roche Gene Scanning, Agilent AriaMx HRM, current Thermo HRM modules (logins/unreachable).
- Current Thermo QuantStudio HRM module docs and confidence metric; whether QuantStudio RDML includes melt.
- ScreenClust, LightScanner, Call-IT availability (pages 404).
- Roche LC480 Gene Scanning auto-grouping parameters.
- Whether CFX Maestro/LC96/Rotor-Gene RDML 1.1 exports contain `mdp`.
- Legal status of Utah patents (Google "Active"/expiry stated as assumptions); get counsel.
- Forum evidence: none.
- Zenodo/figshare coverage incomplete; DECIPHER licence unconfirmed.
- Full texts of Palais 2009, Erali 2010, Simko 2016, Druml 2014, Vossen 2009, Herrmann 2007 not read.
- Any HRM reporting guideline (none found); whether MIQE 2.0 has melt items.
- Melio Labs (digital-HRM spin-off) domain for sale (https://meliolabs.com/); status unverified.

## F. Strongest verbatim quotes
1. Li 2014: homozygote accuracy "70.3 %" vs heterozygote "99.7 %"; custom software beat commercial "(P < 0.002)" — https://pubmed.ncbi.nlm.nih.gov/24718912/ (figures as reported in the note)
2. Thermo FAQ: calibration wells "cannot be omitted"; files not opening after instrument software upgrades — https://www.thermofisher.com/order/catalog/product/4409535
3. Bio-Rad manual: changing pre/post-melt regions changes the clustering; "Call Type" = Automatic or Manual only — https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/10000080911.pdf
4. Clarida-era HRM cost comparison: "about €500 against about €5,000 for MLST and about €10,000 for whole-genome sequencing" — https://pmc.ncbi.nlm.nih.gov/articles/PMC7891011/
5. Boussina 2024 data "available on request" — https://pmc.ncbi.nlm.nih.gov/articles/PMC11088152/

---

# NOTE 12 — Competitor and tool matrix (as of 17 Oct 2026)

Method caveat: WebSearch exhausted; evidence labels **[documented]** (fetched 17 Oct 2026), **[reported]** (secondary/sibling note/prior knowledge), **[unverified]**. Reddit, Biostars, G2, ResearchGate, Stack Exchange and Thermo app library were all blocked; forum threads come second-hand via sibling notes 01 and 03.

## A. How this corner works

Scientists meet qPCR software at four layers: (1) bundled instrument software where raw curves live and the first silent decisions (threshold, baseline, omitted wells) are made; (2) dedicated products on Cq tables — Clarida (launched 6 Jan 2026 by the geNorm/qBase/MIQE authors; https://clarida.bio/changelog), GenEx (price on request, https://multid.se/), qbase+ (Biogazelle, acquired by CellCarta 2021, "fully deprecated" 2024, https://clarida.bio/what-happened-to-qbase-plus), AnnealIQ (free beta, Ct-only, https://www.annealiq.ai/); (3) Prism at $260 academic / $520 corporate per seat per year, institutions ~$100–160 (https://www.graphpad.com/how-to-buy/ ; https://www.bumc.bu.edu/it/support/site-licensed/graphpad-prism ; https://services.ncl.ac.uk/itservice/core-services/software/licences/statisticalanalysis/graphpadprism.html); (4) open tools — LinRegPCR/RDML-Tools (GPL-3 apps on MIT rdmlpython), a long R/Bioconductor tail, Python packages, Shiny apps and 20-year-old Excel macros.

Money: compliance editions are the vendor monetisation — Thermo 21 CFR Part 11 module GBP 3,885 for a 10-licence line (https://www.thermofisher.com/order/catalog/product/4486400); Bio-Rad Security Edition needs a USB key (https://www.bio-rad.com/en-us/sku/12005258-cfx-maestro-software-security-edition-1-license?ID=12005258). Clarida meters per experiment: academic €8–15, commercial €33–60, permanent free tier of 2 experiments/month (https://clarida.bio/pricing). Open ecosystem decays: `pcr` archived from CRAN 7 Nov 2025 (https://cran.r-project.org/web/packages/pcr/index.html), EasyqpcR removed in Bioconductor 3.14 (https://bioconductor.org/about/removed-packages/), tidyqpcr last push May 2024 (https://api.github.com/repos/ropensci/tidyqpcr), SATqPCR and PCR Miner unreachable (http://satqpcr.sophia.inra.fr/cgi/home.cgi ; https://ewindup.info/miner/), qbaseplus.com parked (https://www.qbaseplus.com/), rtprimerdb.org redirects to a reseller (https://omics.gentaur.com/).

Decisions are made in instrument software (Thermo documents omitting outliers by click-and-drag, https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0018200_QuantStDesgnAnalysisSW_v2_Desktop_UG.pdf), in spreadsheets (2026 Bio-Protocol still copies LinRegPCR efficiencies by hand, https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13347129/fullTextXML), and increasingly in cloud tools. The note's central claim: no documented tool lets the scientist see how many defensible analysis choices agree with the conclusion — that position is empty.

## B. Pain inventory (top 8 of 12)

| # | Pain | Who | Frequency / severity | What exists today | Evidence URLs |
|---|---|---|---|---|---|
| P1 | Getting instrument data out in standard form (EDS/PCRD → TXT/RDML; nonconforming RDML; format changes) | Everyone; worst for cores/bioinformatics | Every run; High | Vendor exports (inconsistent), AnnealIQ auto-detect (Cq only), RDML-Tools (needs conformant RDML) | https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0019142_Command-LineApplication_UG.pdf ; https://api.github.com/repos/RDML-consortium/rdmlpython/issues?state=all ; https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8386043/fullTextXML |
| P2 | Combining plates / inter-run calibration manual or absent | PhD students, postdocs, cores | Every multi-plate study; High (wrong conclusions) | Maestro Gene Study (Bio-Rad only), Clarida (paid cloud), qbase+ (dead) | https://www.annealiq.ai/ ; https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8556264/fullTextXML ; https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13347129/fullTextXML |
| P3 | Efficiency assumed 100 %; tools needing it not used; efficiencies copied by hand | Everyone | Majority of published RT-qPCR (reported); High | LinRegPCR (separate tool), Pfaffl in AnnealIQ/rtpcr (user supplies values) | Bustin & Nolan 2017 (DOI 10.1111/eci.12801 reported) ; https://api.github.com/repos/MahShaaban/pcr/issues?state=all |
| P4 | Excel is the analysis tool and is error-prone | Bench scientists | Daily; Medium-high | Free Shiny apps (Cq only), Clarida free tier | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8556264/fullTextXML ; https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12645216/fullTextXML ; Clarida "1 in 3 errors from copy-paste" (unsourced vendor claim, https://clarida.bio/) |
| P5 | R packages need skills; GUI tools old or dead | Bench scientists; R users hitting archived packages | Continuous; Medium | Maintained R core (qpcR, MCMC.qpcr, PCRedux) is GPL and model-specific | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5129434/fullTextXML ; https://bioconductor.org/about/removed-packages/ |
| P6 | Reference genes chosen by habit; no check that normalisers shift between groups | Everyone | Most studies; High | geNorm/NormFinder/RefFinder rank stability only | https://clarida.bio/ ; https://www.annealiq.ai/ |
| P9 | Tool death and data stranding (qbase+, REST 32-bit, NormFinder.xla 32-bit, RTPrimerDB) | Labs with archives | Episodic, catastrophic; High when it hits | Clarida read-only import of qbase+ only | https://clarida.bio/your-qbase-plus-data-in-the-cloud ; https://www.gene-quantification.de/rest-2009.html ; https://www.moma.dk/software/normfinder |
| P12 | Nobody can say how fragile a conclusion is to analysis choices | PIs, reviewers, agents | Every study; High | None | gap matrix §1.9 |

Others: P7 non-detects dropped/imputed/capped at 40 without a rule (Qiagen tool substitutes Ct 50→40, https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12404495/fullTextXML); P8 ad hoc statistics; P10 cloud residency (Clarida EU-only, AnnealIQ US-only, RDML-Tools 3-day deletion); P11 methods text/MIQE reconstructed after the fact.

## C. Discoveries (note's rank order)

### D1. The open qbase+ successor: import qbase+ archives and run the qBase model (inter-run calibration + error propagation), re-analysable
- **Persona:** any lab that bought qbase+ 2010–2023 (shipped with Bio-Rad Security Edition) with a workspace it cannot open after the next Windows update. Frequency: once per legacy project, each a thesis chapter or paper.
- **Evidence:** "As of 2024, qbase+ has been fully deprecated", "no longer available for download anywhere" (https://clarida.bio/what-happened-to-qbase-plus); "One Windows update away from losing all your qbase+ data"; Clarida import is read-only: "We don't reanalyze, recompute, or modify anything" (https://clarida.bio/your-qbase-plus-data-in-the-cloud); Bio-Rad SKU still promises a qbase+ licence (https://www.bio-rad.com/en-us/sku/12005258-cfx-maestro-software-security-edition-1-license?ID=12005258). Size unknown; qBase 2007 cited 3,262 times (https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=(DOI:...)).
- **Exists today:** Clarida read-only import; nothing open reads the workspace. Pabinger: error propagation in only five tools; no maintained permissive package does inter-run calibration (https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5129434/fullTextXML).
- **Feature:** `qpilot import qbase <workspace_dir>` parsing kernel.xml and experiment.xml into RDML 1.4; method card "qBase relative quantification (Hellemans 2007, doi 10.1186/gb-2007-8-2-r19)": RQ = E^ΔCq per target, geometric-mean normalisation factor, per-run calibration factor from shared inter-run calibrators, SE propagation; cards for calibrator samples, reference set, efficiency source. Record: file hashes, qbase+ version strings, parity report. Agent: `qpcr_import_qbase(path)`, `qpcr_study(study_id, method="qbase2007")`.
- **Feasibility:** open-access paper with formulas; XML schema undocumented — needs 2–3 donor workspaces; lxml (BSD), rdmlpython (MIT). Effort: 1 week reader, 1 week method card + parity tests, 2 days UI. Hardest: obtaining real workspaces and reproducing qbase+'s exact numbers.
- **Why qPilot:** adds Cq-input study type (needed for D5) and qBase method card; grid compares "qbase+ settings as saved" vs "qPilot defaults".
- **Risks/confidence:** finite, shrinking population; Clarida could add re-analysis; impossible without samples. **Medium**. Rank 1.

### D2. Vendor-export conformance and batch-capture kit (Thermo CLI first) with public per-vendor RDML conformance table
- **Persona:** lab data person/core manager with 20–200 EDS/PCRD files per month; every downstream tool author.
- **Evidence:** Thermo CLI batch-exports EDS to TXT (Header, Sample setup, Raw, Amplification, Multicomponent, Results) and RDML, "intended for advanced users who choose to create or export experiments using a scripting language", specs "subject to change" (https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0019142_Command-LineApplication_UG.pdf); RDML export limited to standard-curve/relative-standard-curve/comparative-Ct experiment types and is a "controlled function" (https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0018200_QuantStDesgnAnalysisSW_v2_Desktop_UG.pdf); Maestro RDML misnames zip members, rdmlpython issue #3 (https://api.github.com/repos/RDML-consortium/rdmlpython/issues?state=all); "Not all qPCR machines export RDML" (https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8386043/fullTextXML); import requests open for years in tidyqpcr #134 and pcr #29.
- **Exists today:** per-tool ad hoc parsers; RDES-TableShaper; RDML-Validate. Nobody publishes which vendor/version validates or a repair path.
- **Feature:** (a) `qpilot capture thermo --cli <path> --in <dir> --out <dir>` wrapping the documented CLI, parsing TXT by header name, recording software version and CLI guide revision; (b) `qpilot rdml check <file>` validating against 1.1–1.4, repairing known nonconformances, migrating to 1.4, reporting what is missing (no raw fluorescence → Cq mode, D5); (c) public conformance table with CC0 anonymised fixtures. Agent: `qpcr_capture(dir)`, `qpcr_rdml_check(file)`.
- **Feasibility:** CLI documented for Windows and Mac (requires D&A v2 on that host); RDML schemas public; rdmlpython migrates versions. Effort: wrapper 3–5 days; checker/repair 1 week; table ongoing. Hardest: Bio-Rad PCRD proprietary; Roche/Qiagen unverified.
- **Why qPilot:** engine starts from RDML; record hashes inputs; CLI rung on the "Ladder of Control"; public good Clarida/AnnealIQ cannot own.
- **Risks/confidence:** Thermo may change/withdraw CLI; fixtures must be lab-donated; Security Edition restricts exports. **High** for Thermo, **medium** Bio-Rad, **low** Roche/Qiagen. Rank 2.

### D3. Maintained, permissive engine-as-library with tidy output schema and R bridge
- **Persona:** bioinformatics core analyst or R-literate postdoc who found `pcr` archived Nov 2025, tidyqpcr frozen May 2024, EasyqpcR gone, rdmlpython PyPI wheel three years behind GitHub.
- **Evidence:** `pcr` "removed … issues were not corrected despite reminders" (https://cran.r-project.org/web/packages/pcr/index.html); tidyqpcr 27 open issues, Roche-only input (https://api.github.com/repos/ropensci/tidyqpcr); rdmlpython PyPI 1.7.2 (May 2023) vs GitHub main (May 2026), still 1,851 downloads/month (https://pypistats.org/api/packages/rdmlpython/recent); CRAN downloads/month: qpcR 1,320, chipPCR 598, ctrlGene 449, PCRedux 363, MCMC.qpcr 351, qPCRtools 251, pcr 89 (https://cranlogs.r-pkg.org/downloads/total/last-month/qPCRtools,pcr,MCMC.qpcr,ctrlGene,chipPCR,PCRedux,qpcR,EasyqpcR,RefFreeEWAS); HTqPCR ~3.5k distinct IPs in 2025 (https://bioconductor.org/packages/stats/bioc/HTqPCR/HTqPCR_stats.tab); GitHub "qpcr" 1,269 repos, top 13–60 stars (https://api.github.com/search/repositories?q=qpcr&sort=stars&order=desc&per_page=50).
- **Exists today:** permissive — rdmlpython, RDML (R), qPCRtools, PCRedux, tidyqpcr (stalled); GPL — qpcR, chipPCR, nondetects, MCMC.qpcr, pcr, Kleinschmidt qpcr, GeneQuantify. None gives a maintained permissive path from raw curves to group contrasts with a stable schema.
- **Feature:** (a) frozen `qpilot-tidy-v1` schema (one row per well: study_id, plate_id, well, sample, group, target, sample_type, Cq, N0, eff_well, eff_assay, flags[], excluded_reason, method_version, record_hash) via `qpilot export --tidy` and `qpcr_export_tidy` over MCP; (b) ~200-line R package `qpilotr` shelling out to CLI, one vignette reproducing a Vermeulen contrast; (c) documented `qpilot.engine.analyse(rdml_path, settings) -> StudyResult` with semver; (d) upstream PR to rdmlpython for a release workflow. `decisions_pending()` exposed.
- **Feasibility:** days for schema/export; one week for `qpilotr`; one day for PyPI PR. Hardest: committing to maintenance — mitigate with CI matrix, pinned deps, two-maintainer rule.
- **Why qPilot:** Apache-2.0 engine on MIT rdmlpython; MCP exists.
- **Risks/confidence:** R users prefer native; shelling out clunky on Windows. **High** (gap documented by archive dates and trackers). Rank 3.

### D4. Censored non-detect card
- **Persona:** anyone with low-abundance targets where a third of wells are "Undetermined" or Cq > 35; cores reporting detection.
- **Evidence:** complete-case tools force removal/imputation that "may bring unnecessary bias and decrease statistical power"; Qiagen tool "substituted Ct 50 values with the tool's maximum Ct cutoff 40" (https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12404495/fullTextXML); `nondetects` 12.5 years in Bioconductor, GPL-3 (https://bioconductor.org/packages/release/bioc/html/nondetects.html); Thermo flags "Unexpected Cq Status" but leaves decision to user. Internal: Vermeulen demo has 323 undetermined of 24,576 wells (reported from project memory, not re-measured).
- **Exists today:** `nondetects` (EM, reimplement from McCall 2014, DOI to be confirmed), MCTOT (rank test/Cox-type; code licence unstated, article CC0), Tobit regression. None wired to per-gene consequence or robustness grid.
- **Feature:** card "Non-detects (n wells, k genes)" with options drop / censor at cut-off with rank test (Zhuang 2025) or Tobit / EM impute (McCall 2014) / set to cut-off (flagged "not recommended"); per-gene fold-change and p-value consequence per option; policy becomes a grid axis. Agent: `qpcr_decide(card="nondetects", option=...)`.
- **Feasibility:** Tobit via statsmodels (BSD); EM from paper; 1–2 weeks. Validation: nondetects example data (licence check), Vermeulen (CC BY 4.0). Hardest: plain explanation of why "drop" inflates effects.
- **Why qPilot:** only a robustness engine shows sensitivity to policy; record makes it reportable.
- **Risks/confidence:** small-n censored groups uninformative; must not become p-hacking — escalation rule mitigates. **Medium**. Rank 4.

### D5. Cq-only mode with explicit "efficiency assumption" card
- **Persona:** bench scientist with only a results table (QuantStudio TXT/XLSX, Maestro CSV, LightCycler text); qbase+ migrant; AnnealIQ/Click-qPCR user with tidy Cq CSV.
- **Evidence:** every 2021–2026 open tool and both AI products take Cq only; Bustin & Nolan: efficiency "very rarely" measured, ΔΔCq without it is "a clear indicator that the data are suspect" (DOI 10.1111/eci.12801 reported); 2026 Bio-Protocol hand-copies efficiencies (https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13347129/fullTextXML); `pcr` users asked for efficiency since 2020; Thermo RDML export limited to certain experiment types.
- **Exists today:** calculators assuming 100 % (qDATA, Click-qPCR, Auto-qPCR); user-typed efficiencies (AnnealIQ, rtpcr, GeneQuantify) with no provenance; nothing shows the consequence.
- **Feature:** `qpilot run --cq table.csv --map` accepting Thermo TXT results, Maestro "Quantification Cq Results" CSV, generic long CSV, RDES/RDML without fluorescence; card "Amplification efficiency source": assume 100 % (not recommended) / per-assay dilution series / lab assay passport / sensitivity band 1.80–2.00 swept by grid; Study Confidence capped at "Low" when assumed. Agent: `qpcr_study` with `mode="cq"`.
- **Feasibility:** Thermo TXT documented; Maestro headers from donor files; Pfaffl 2002 and geNorm already implemented. Effort one week. Hardest: honest technical-replicate handling.
- **Why qPilot:** cards/grid/record/MCP input-agnostic; multiplies addressable users; nudges toward raw curves.
- **Risks/confidence:** cannibalises raw-curve pitch; must be labelled the weaker path. **High**. Rank 5.

Two further positions left in §1 as positioning, not features: unlimited-free-local against Clarida's metering; core-facility batch/QC segment (Clarida Center, Thermo Enterprise) that no open tool serves.

## The full competitor matrix (reproduced from §1.8)

Column key: Input R = raw curves, C = Cq only; Multi-plate IRC = inter-run calibration, MR = multi-run grouping; Efficiency PW = per-well, DS = dilution series, UE = user-entered, A = assumed 100 %; Ref genes G = geNorm, N = NormFinder, B = BestKeeper, S = stability. "—" not documented; "?" unverified.

| Tool (maker) | Type | Input | Multi-plate | Efficiency | Ref genes | Stats | MIQE / methods text | Export | API/CLI | Price | Licence | Last release / status | Adoption / sentiment | URL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Clarida | Cloud web app, EU-hosted | C (+ instrument-file import and raw-curve display since Sep 2026; re-quantification ?) | MR (Apr 2026) + IRC (claimed) | Efficiency correction (source ?) | G (+V), plate checks | "eight confirmatory tests", Mann-Whitney, 95% CI | MIQE score (47/51 example); methods text; decision audit trail | PDF, PPT, Excel, RDML | — | Free 2 exp/mo; acad €15 PAYG, €8–10 Lab (€4.8–9.6k/yr); comm €60 PAYG, €33–40 Lab (€19.8–39.6k/yr); Center custom | Proprietary | 2026.10 (12 Oct 2026); launched 6 Jan 2026 | No third-party reviews; monthly releases; qbase+ migration | https://clarida.bio/ ; https://clarida.bio/pricing ; https://clarida.bio/changelog |
| AnnealIQ | Browser app + cloud account + LLM | C (CSV/RDML 1.3+, Bio-Rad/ABI/Roche/generic) | None ("need manual correction before import") | UE (Pfaffl) or A | G, N; Grubbs; NTC/NRT | Welch, 1/2-way ANOVA, Tukey, non-parametric, bootstrap CI | MIQE 2.0 checklist; AI methods | SVG/PNG; "FAIR data export bundle" | — | Free during beta | Proprietary | Beta; compare page "Last verified March 2026" | Waitlist; no reviews; no company info | https://www.annealiq.ai/ |
| qbase+ (Biogazelle → CellCarta) | Windows/mac desktop | C | IRC (qBase model) | DS/UE | G | — | — | ? | — | Was paid; now unavailable | Proprietary | "fully deprecated" 2024 | Domain parked; Bio-Rad SKU still bundles licence | https://clarida.bio/what-happened-to-qbase-plus ; https://www.qbaseplus.com/ |
| GenEx / GenExGxP (MultiD) | Windows desktop | C (?) | ? | DS (LOD/LOQ/efficiency) | G, N | classification, time series, PCA (?) | ? | ? | — | On request (trial) | Proprietary | Version/date not shown | No reviews | https://multid.se/ |
| GraphPad Prism | Desktop + Cloud | n/a | n/a | n/a | n/a | general stats | none | pzfx, images | — | $142–520/seat/yr; perpetual $1,600–3,200; institutions ~$100–160 | Proprietary | Prism 11 | "750,000 scientists" (vendor) | https://www.graphpad.com/how-to-buy/ |
| Benchling | ELN/LIMS cloud | — | — | — | — | — | — | API | Enterprise | Proprietary | — | "1,300+ organizations"; no qPCR module found | https://www.benchling.com/platform |
| LabArchives / SciNote | ELNs | — | — | — | — | — | — | — | Free tiers + paid | Proprietary | — | Prism integration; AI protocol import | https://www.labarchives.com/ ; https://www.scinote.net/ |
| QuantStudio D&A v2 (Thermo) | Desktop Win/Mac (+ Connect) | R → C | ? (RQ per experiment) | Crt from "modeled amplification efficiency profile"; std curves | — | basic | — | TXT (raw/amp/multicomponent/results), CSV, Excel, PNG/SVG, RDML, XLSX/PDF | CLI (EDS→TXT/RDML batch) | Bundled; HRM plug-in paid; Part 11 module £3,885 per 10 | Proprietary | Guide rev. M 15 Oct 2025; v2.6 | Result Quality flags; omit by drag | https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0018200_QuantStDesgnAnalysisSW_v2_Desktop_UG.pdf |
| Thermo Connect apps | Cloud | from EDS | ? | ? | ? | ? | — | ? | — | Individual free (25 GB); Enterprise subscription | Proprietary | — | Login required | https://www.thermofisher.com/uk/en/home/digital-science/thermo-fisher-connect/editions.html |
| CFX Maestro 2.3 (Bio-Rad) | Windows desktop | R → C | MR (Gene Study) | DS | S ("GeNorm only" per AnnealIQ) | t-test, ANOVA | — | images; RDML (nonconforming naming reported); PrimePCR import | — | Login to see price; Security Edition USB key | Proprietary | 2.3 | ResearchGate "Maestro" 87 questions (reported) | https://www.bio-rad.com/en-us/product/cfx-maestro-software-for-cfx-real-time-pcr-instruments?ID=OKZP7E15 |
| LightCycler 480/96 (Roche) | Windows desktop | R → C | ? | DS (Rel Quant) | — | — | — | txt, ixo, RDML (?) | — | Bundled; HRM paid (?) | Proprietary | ? | — | unverified (pages 404) |
| Rotor-Gene Q / Q-Rex (Qiagen) | Windows desktop | R → C | ? | DS | — | — | — | ? | — | Bundled (?) | Proprietary | ? | — | unverified |
| GeneGlobe RT² Profiler (Qiagen) | Web | C | — | A | — | t-test | — | — | — | Free, registration | Proprietary | — | Substitutes Ct 50→40 | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12404495/fullTextXML (second-hand) |
| LinRegPCR web / RDML-Tools | Web apps (GPL-3) on rdmlpython (MIT) | R (RDML ≥1.1) | RDML-Merge, RDML-ExperimentAnalysis (IRC ?) | PW (window-of-linearity) | — | TestStat basics; Grubbs | — | CSV, SVG | library only | Free | GPL-3 / MIT | Pushed 2 May 2026; paper 2021 (121 cites) | Data deleted after 3 days; Windows version frozen | https://www.gear-genomics.com/rdml-tools/ ; https://github.com/RDML-consortium/rdml-tools |
| rdmlpython | Python library | R | — | PW | — | — | — | CSV | Python API | Free | MIT | GitHub May 2026; PyPI 1.7.2 May 2023 | 1,851 downloads/mo; 14 stars | https://github.com/RDML-consortium/rdmlpython |
| REST 2009 (Pfaffl/Qiagen) | Windows desktop | C | — | UE | — | randomisation, bootstrap | — | — | — | Free | Proprietary freeware | 2009; 32-bit issues | Pfaffl 2002 cited 5,689 | https://www.gene-quantification.de/rest-2009.html |
| Auto-qPCR (neuroeddu) | Python web app | C (QuantStudio exports) | no IRC | A | S | t-test etc. | — | tables, plots | — | Free | "Other" (?) | Pushed Aug 2022; 56 stars | Paper cited 21 | https://github.com/neuroeddu/Auto-qPCR |
| SATqPCR (INRAE) | Web | C | — | ? | S | stats | — | — | — | Free | ? | Site down 17 Oct 2026 | Paper cited 47 | http://satqpcr.sophia.inra.fr/cgi/home.cgi |
| PCR Miner | Web | R | — | PW (4-param logistic) | — | — | — | — | — | Free | ? | Unreachable | UI "do not comply with current standards" (Pabinger) | https://ewindup.info/miner/ |
| qPCRtools | R/CRAN | C | — | DS | S | t-test, ANOVA, plots | — | tables | R | Free | MIT | CRAN 1.0.1 Nov 2023; GitHub Jun 2026 | 251/mo; 18 stars | https://cran.r-project.org/web/packages/qPCRtools/index.html |
| pcr (Ahmed & Kim) | R | C | — | A (efficiency requested since 2020) | — | t-test, Wilcoxon, lm | — | tables | R | Free | GPL-3 | **Archived from CRAN 7 Nov 2025** | 89/mo; 31 stars; 89 cites | https://cran.r-project.org/web/packages/pcr/index.html |
| rtpcr | R/CRAN | C | — | UE (Pfaffl) | ≤2 ref genes | lmer, ANOVA/ANCOVA | — | ggplot | R | Free | ? | PeerJ 2025 | 1 cite | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12530193/fullTextXML |
| qDATA | R app | C | — | A (Livak) | — | tests on 2^-ΔCt | — | — | — | Free | ? | Biotechniques 2024; v1.1 2026 preprint | 3 cites | doi 10.1080/07366205.2024.2442217 |
| Click-qPCR | R Shiny | C (tidy CSV) | — | A | outside tool | Welch; ANOVA + Dunnett | — | — | — | Free | MIT | Pushed Aug 2026 | 13 stars; 3 cites | https://github.com/kubo-azu/Click-qPCR |
| MCTOT | R Shiny | C (censored Ct) | — | n/a | n/a | rank test; Cox-type | — | — | — | Free | ? (paper CC0) | PLoS One 2025 | 0 cites; no persistence | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12404495/fullTextXML |
| GeneQuantify | Python/Streamlit | C (RDML/RDES) | — | UE (Pfaffl) | G | Grubbs/IQR; BH | — | — | — | Free | GPL-3.0 | 2026 | 0 cites | https://github.com/burhanettiny/GeneQuantify |
| repDilPCR | Web + R/Shiny | C (dilution-replicate) | — | DS | multiple | auto test selection | — | plots | — | Free | ? | BMC Bioinf 2024 | 0 cites | doi 10.1186/s12859-024-05954-9 |
| HTqPCR | Bioconductor | C | — | A | — | limma-style | — | — | R | Free | Artistic-2.0 | 1.66.0; 17 years | ~3.5k IPs/yr; 188 cites | https://bioconductor.org/packages/release/bioc/html/HTqPCR.html |
| ddCt | Bioconductor | C | — | A | — | — | — | — | R | Free | LGPL-3 | 1.68.0; 17 years | ~3k IPs/yr | https://bioconductor.org/packages/release/bioc/html/ddCt.html |
| NormqPCR / ReadqPCR | Bioconductor | C | — | UE | G, N (reported) | — | — | — | R | Free | LGPL-3 | 1.58.0; 15 years | — | https://bioconductor.org/packages/release/bioc/html/NormqPCR.html |
| nondetects | Bioconductor | C | — | n/a | n/a | EM imputation | — | — | R | Free | GPL-3 | 2.42.0; 12.5 years | — | https://bioconductor.org/packages/release/bioc/html/nondetects.html |
| EasyqpcR | Bioconductor | C | — | UE | — | — | — | — | R | Free | — | **Removed in BioC 3.14** | — | https://bioconductor.org/about/removed-packages/ |
| qpcR (Spiess) | R/CRAN | R | — | PW (sigmoidal) | — | — | — | — | R | Free | GPL-2/3 | 1.4-2 Jun 2025 | 1,320/mo (highest) | https://cran.r-project.org/web/packages/qpcR/index.html |
| chipPCR | R/CRAN | R | — | pre-processing, Cq | — | — | — | — | R | Free | GPL-3 | 1.0-2 Mar 2021 | 598/mo; 24 cites | https://cran.r-project.org/web/packages/chipPCR/index.html |
| PCRedux | R/CRAN | R (ML features) | — | — | — | — | — | — | R | Free | MIT | 1.2-1 Nov 2025 | 363/mo | https://cran.r-project.org/web/packages/PCRedux/index.html |
| RDML (R) | R/CRAN | R (import) | — | — | — | — | — | — | R | Free | MIT | 1.1 Jul 2025 | 21 stars | https://cran.r-project.org/web/packages/RDML/index.html |
| MCMC.qpcr | R/CRAN | C | plates as factors | — | optional | Bayesian GLMM | — | — | R | Free | GPL-3 | 1.2.4 Nov 2025 | 351/mo; 128 cites | https://cran.r-project.org/web/packages/MCMC.qpcr/index.html |
| ctrlGene | R/CRAN | C | — | — | S | — | — | — | R | Free | GPL | 1.0.1 Jul 2019 | 449/mo | https://cran.r-project.org/web/packages/ctrlGene/index.html |
| tidyqpcr (rOpenSci) | R | C (+ raw Roche single-channel) | — | DS | — | ΔCq | — | — | R | Free | Apache-2 | **Last push May 2024; 27 open issues** | 60 stars | https://api.github.com/repos/ropensci/tidyqpcr |
| RefFinder | Web | C (paste) | — | — | G, N, B, ΔCt | — | — | — | — | Free | ? | Hosted at ciidirsinaloa.com.mx | 377 cites (2023 paper) | https://www.ciidirsinaloa.com.mx/RefFinder-master/ |
| NormFinder | Excel add-in / R | C | — | — | N | — | — | — | — | Free | No modification/redistribution | xla docs Jan 2024; 32-bit Office | 5,470 cites | https://www.moma.dk/software/normfinder |
| BestKeeper | Excel | C | — | — | B | — | — | — | — | Free (password) | ? | v1, 2004 | — | https://www.gene-quantification.de/bestkeeper.html |
| qpcr (Kleinschmidt) | Python/PyPI | C | — | UE | — | basic | — | plots | Python | Free | GPL-3 | 4.1.4 Apr 2025 | 29 stars | https://pypi.org/pypi/qpcr/json |
| pyQPCR | Python GUI | C | — | UE | — | — | — | — | — | Free | GPL | 0.7, 2010 | — | https://pypi.org/pypi/pyqpcr/json |
| Galaxy PIPE-T | Galaxy | C | — | — | — | — | — | — | Galaxy | Free | ? | 2019 | 510 downloads | https://toolshed.g2.bx.psu.edu/api/repositories?q=qpcr |
| Excel legacy (Q-Gene, DART-PCR, Gene Expression Macro, qCalculator, PREXCEL-Q, REST-384) | Excel | C or R (DART) | — | varies | — | — | — | — | — | Free (PREXCEL-Q licensed) | varies | 2002–2008 | — | https://www.gene-quantification.de/download.html |

## Gap matrix (reproduced from §1.9)

| Capability | Vendor desktop | Clarida | AnnealIQ | LinRegPCR web / RDML-Tools | R/Python packages | Excel | Position |
|---|---|---|---|---|---|---|---|
| Per-well efficiency from raw curves, published method | no (Thermo Crt from modelled efficiency) | display only (re-analysis ?) | no | yes | qpcR, chipPCR (GPL), rdmlpython (MIT) | no | Occupied only by GPL web apps and R; **nobody ships it with multi-plate statistics and a record** |
| Multi-plate inter-run calibration with error propagation (qBase model) | Maestro Gene Study (MR); Thermo ? | claimed | no | RDML-Merge (calibration ?) | none maintained | manual | **Open and local: empty** |
| Reference-gene stability with group-effect guard | Maestro stability; no guard | geNorm; guard ? | geNorm + NormFinder; no guard | no | NormqPCR, ctrlGene, RefFinder; no guard | no | **Empty everywhere (qPilot has it)** |
| Robustness across analysis choices | no | no | no | no | no | no | **Empty everywhere** |
| Decision log / audit trail for research use | Part 11 editions (paid) | "audit trail of decisions" | session saves QC decisions | no | no | no | Clarida only; hash-chained open record: empty |
| Censored non-detect handling as a choice | "Undetermined" dropped | ? | ? | ? | nondetects (GPL), MCTOT | manual | Niche R only |
| Methods text + MIQE checklist | no | yes (score) | yes (checklist) | no | no | no | Table stakes among paid/AI tools |
| Batch/CLI/API | Thermo CLI (export only) | no public API | no | library | yes | no | **Agent-callable analysis: empty (qPilot MCP)** |
| Local-first, offline, no account | yes (bundled) | no (cloud) | partly | no (3-day retention) | yes | yes | Open, local, maintained, raw-curve: effectively only R scripts |
| Price for unlimited plates | bundled | metered per experiment | free (beta) | free | free | Office licence | **Free-and-unlimited with a modern UI: empty** |
| Persona: teaching labs | no | free tier (2/mo) | beta | yes (manual) | no | yes | Weakly served |
| Persona: core-facility batch QC | Enterprise/Security tiers | Center tier | "single-user only" | no | scripts | — | Open batch tooling: empty |
| Persona: bioinformatics core wanting maintained permissive library | no | no | no | rdmlpython (stale on PyPI) | pcr archived, tidyqpcr stalled | — | Empty |

## Clarida facts (all [documented])
- Self-description: "The qPCR platform from the team behind MIQE, geNorm & qbase+"; five-stage workflow; geNorm on import; MIQE compliance score (example 47/51); "AI-proposed conclusions for user review"; "audit trail of decisions"; export PDF/PPT/Excel/RDML; no API mentioned (https://clarida.bio/). Homepage stats "5 disconnected tools per experiment", "2+ hrs lost reformatting", "1 in 3 errors from copy-paste" are unsourced.
- Pricing (https://clarida.bio/pricing): Free "Forever" — 4 experiments first month then 2/month, full functionality; academic PAYG €15/experiment (€300 for 20); Lab €8/experiment annual (600–1,200 experiments, €4,800–€9,600/yr) or €10 monthly, overage €12/€15; Center custom (SSO/SAML, audit log, SLA). Commercial: PAYG €60 (€1,200 for 20); Lab €33 annual (€19,800–€39,600/yr), €40 monthly; overage €60/€50. "Academic pricing is roughly 75% lower than commercial." All plans EU-hosted. Billing unit: "one experiment is a complete investigation" from one partial 96-well plate to tens of 384-well plates. Academic eligibility includes "core facilities running on cost-recovery".
- Changelog (https://clarida.bio/changelog): launch 6 Jan 2026; 19 Feb geNorm; 17 Mar RDML validation; 3 Apr relative quantification, multi-run, multiplex; 4 May qbase+ migration; 9 Jun "eight confirmatory statistical tests", paid plans; 6 Jul RDML import/export, ELN-ready records; 7 Sep 2026 "reads your instrument files directly, shows the raw amplification and melt curves"; 12 Oct 2026 genotyping and workflow presets. No API or MIQE in changelog.
- Free tools (https://clarida.bio/tools/genorm): geNorm (no account), concentration converter, plate homogeneity, RDML viewer, RDES validator.
- qbase+ pages (https://clarida.bio/what-happened-to-qbase-plus ; https://clarida.bio/your-qbase-plus-data-in-the-cloud): Biogazelle acquired by CellCarta 2021; "No new features. No bug fixes. No roadmap."; "fully deprecated" as of 2024; Hellemans co-founder, Vandesompele advisor; import of kernel.xml/experiment.xml read-only and free.
- Note's inference: monthly cadence means "Clarida cannot do X" claims have short shelf life; durable differences are cloud-only, metering, closed methods, no public API, raw curves displayed but (as far as documented) not re-analysed.

## AnnealIQ facts ([documented])
- "Upload Ct values, describe your experiment"; CSV/RDML 1.3+ auto-detect for CFX Maestro, QuantStudio, LightCycler; ΔΔCt and Pfaffl with user efficiencies; geNorm/NormFinder; Welch/ANOVA/Tukey/bootstrap; Grubbs; MIQE 2.0 checklist; AI methods; "Free during beta … invite code"; "For research use only". FAQ "What can't AnnealIQ do yet?": "interplate calibration (multi-plate experiments need manual correction before import), absolute quantification …, multi-user collaboration (single-user only), repeated measures ANOVA …, and three-way or higher factorial ANOVA." (https://www.annealiq.ai/)
- Security (https://www.annealiq.ai/security): maths "runs entirely in your browser"; only descriptions/summaries sent to the AI "under Anthropic API terms"; "infrastructure is US-based"; "No SOC 2 or ISO 27001 certification"; "We're a beta product".
- Comparison page (https://www.annealiq.ai/compare, "Last verified March 2026") rates CFX Maestro "GeNorm only" and QuantStudio D&A lacking Pfaffl and stability. Blog: 19 SEO posts Apr–May 2026 (https://www.annealiq.ai/blog). No company, founders, pricing, user count; nothing on YC/Product Hunt/HN (https://www.ycombinator.com/companies?query=qPCR ; https://www.producthunt.com/search?q=qPCR).

## GenEx, vendor software, open-tool maintenance status
- **GenEx** (https://multid.se/): "premier software for gene expression data processing and analysis"; LOD/LOQ/efficiency, NormFinder/geNorm, classification, time series; GenExGxP edition; only CTA "Request a Trial Version"; no price/version/date; support "invoiced for each 30 minutes interval". Editions Standard/Pro/Enterprise and TATAA resale [unverified].
- **Thermo D&A v2** (https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0018200_QuantStDesgnAnalysisSW_v2_Desktop_UG.pdf): built-in ΔΔCT and relative standard curve; HRM a paid plug-in; Crt from "modeled amplification efficiency profile"; Result Quality flags; omit outliers by drag; RDML export for three experiment types only, a "controlled function" under SAE. **CLI** (https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0019142_Command-LineApplication_UG.pdf): EDS→TXT/RDML batch, Windows and Mac, "intended for users who want to integrate the software with third-party applications", specs "subject to change". Connect Individual free with 25 GB (https://www.thermofisher.com/uk/en/home/digital-science/thermo-fisher-connect/editions.html); Part 11 module GBP 3,885 per 10 licences (https://www.thermofisher.com/order/catalog/product/4486400).
- **CFX Maestro 2.3** (https://www.bio-rad.com/en-us/product/cfx-maestro-software-for-cfx-real-time-pcr-instruments?ID=OKZP7E15): gene stability, t-tests/ANOVA, multi-run Gene Study; Security Edition USB key, encrypted files; price "Login to see your price". rdmlpython issue #3: Maestro RDML "use non-standard XML filenames"; issue #4: replicate runs show "about 1.5 Cq differences" (https://api.github.com/repos/RDML-consortium/rdmlpython/issues?state=all).
- **Roche LC480/96 and Qiagen Rotor-Gene/Q-Rex**: all pages 404 — [unverified]. Qiagen GeneGlobe substitutes Ct 50→40 (per MCTOT paper).
- **Open-tool maintenance:** pcr archived from CRAN 2025-11-07 ("issues were not corrected despite reminders"), 8 open issues incl. #21/#22 efficiency since 2020 (https://cran.r-project.org/web/packages/pcr/index.html ; https://api.github.com/repos/MahShaaban/pcr/issues?state=all); tidyqpcr last push 31 May 2024, 27 open issues (#134 QuantStudio, #18 RDML, #19 Cq from curves, #17 geNorm) (https://api.github.com/repos/ropensci/tidyqpcr); EasyqpcR removed in Bioconductor 3.14 (https://bioconductor.org/about/removed-packages/); LinRegPCR Windows "will no longer be updated" (https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8386043/fullTextXML); rdmlpython GitHub pushed 2 May 2026 but PyPI 1.7.2 is May 2023 (https://pypi.org/pypi/rdmlpython/json); REST 2009 may "cease working" on 64-bit (https://www.gene-quantification.de/rest-2009.html); NormFinder.xla 32-bit Office only, "Modification or redistribution ... not allowed" (https://www.moma.dk/software/normfinder); BestKeeper password-by-email ZIP, Excel 2003 (https://www.gene-quantification.de/bestkeeper.html); RTPrimerDB redirects to reseller (https://omics.gentaur.com/); SATqPCR connection refused; PCR Miner socket closed; QPCR (TU Graz) empty (https://genome.tugraz.at/QPCR/); Auto-qPCR last push Aug 2022 (https://api.github.com/repos/neuroeddu/Auto-qPCR). Bioconductor 3.23 biocViews "qPCR" lists 13 packages (https://bioconductor.org/packages/release/BiocViews.html#___qPCR).

## D. Data / libraries / standards / licences (12 most relevant)

| Name | What | Licence | URL |
|---|---|---|---|
| rdmlpython | RDML read/edit/validate + LinRegPCR | MIT | https://github.com/RDML-consortium/rdmlpython |
| RDML-Tools | web apps (Edit, Validate, Merge, RunAnalysis…) | GPL-3.0 (reference only) | https://github.com/RDML-consortium/rdml-tools |
| RDML (R) | import into R | MIT | https://cran.r-project.org/package=RDML |
| tidyqpcr | tidy Cq analysis | Apache-2 (stalled) | https://github.com/ropensci/tidyqpcr |
| qPCR-Pipeline | R auto-analysis, 44 stars | Apache-2.0 | https://github.com/tiramisutes/qPCR-Pipeline |
| nondetects | non-detect EM | GPL-3 (reimplement from McCall 2014) | https://bioconductor.org/packages/nondetects |
| NormFinder | Excel/R | free; no modification/redistribution (reimplement from Andersen 2004) | https://www.moma.dk/software/normfinder |
| Thermo D&A v2 CLI guide | EDS→TXT/RDML batch | vendor docs | https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0019142_Command-LineApplication_UG.pdf |
| Clarida free tools | geNorm, RDML viewer, RDES validator | proprietary, free, no account | https://clarida.bio/tools/genorm |
| Vermeulen/Ruijter 2013 RDML | 64-plate benchmark | CC BY 4.0 (per project notes) | inside rdmlpython repo (experiments/vermeulen) |
| Pabinger 2014 survey | 27-tool survey | CC BY-NC-ND | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5129434/fullTextXML |
| geNorm / qBase / Pfaffl / NormFinder / Ruijter papers | method sources | open-access papers | doi 10.1186/gb-2002-3-7-research0034 ; doi 10.1186/gb-2007-8-2-r19 ; doi 10.1093/nar/30.9.e36 ; doi 10.1158/0008-5472.CAN-04-0496 ; doi 10.1093/nar/gkp045 |

## E. Open questions / unverified
1. Whether Clarida's Sep 2026 raw-curve import re-quantifies from fluorescence or only displays.
2. Clarida's IRC implementation, group-effect guard, API plans, user numbers, funding, legal entity.
3. AnnealIQ's company, post-beta pricing, raw-curve roadmap.
4. GenEx editions, prices, version; TATAA resale.
5. Roche LC480/96 modules and pricing; Qiagen Rotor-Gene/Q-Rex; Thermo Connect RQ app specifics.
6. CFX Maestro list price; whether 2.3 still misnames RDML zip members; Prism export.
7. qLOOK, PlateVision, ProntoPCR, lazyQ: not found in Europe PMC.
8. Auto-qPCR licence text; MCTOT, rtpcr, qDATA, repDilPCR, RefFinder code licences.
9. No quantitative measure of Excel use, Prism seats per lab, qbase+ installed base.
10. Forum sentiment only second-hand via sibling notes 01/03.
11. Project memory's "72% of cores can't trace raw data" — source not found; treat as unverified.
12. Bustin & Nolan 2017 DOI (10.1111/eci.12801) is from memory; text read from shared scratchpad.

## F. Strongest verbatim quotes
1. "We don't reanalyze, recompute, or modify anything" / "One Windows update away from losing all your qbase+ data" — Clarida, https://clarida.bio/your-qbase-plus-data-in-the-cloud
2. "interplate calibration (multi-plate experiments need manual correction before import)" — AnnealIQ FAQ, https://www.annealiq.ai/
3. "researchers very rarely measure efficiency and assume it to be 100% … This is still the case today" — Bustin & Nolan 2017 (DOI 10.1111/eci.12801 reported)
4. "these closed source software modules are black boxes and do not provide full control over the entire process" — Pabinger 2014, https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5129434/fullTextXML
5. "intended for advanced users who choose to create or export experiments using a scripting language" — Thermo CLI guide, https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0019142_Command-LineApplication_UG.pdf
6. "Amplification efficiency values must be manually copied from the LinRegPCR output" — Bio-Protocol 2026, https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13347129/fullTextXML

---

## Cross-note observations for the report writer

- All three notes share the same evidence limitation: no forum sentiment (search budget exhausted / sites blocked); pains are evidenced from manuals, patents, papers and GitHub issue trackers. Note 12 labels every claim [documented]/[reported]/[unverified]; notes 10 and 11 use "(snippet)" and "(estimate)".
- The same structural gap appears in all three corners: no tool reports how many defensible analysis settings agree with a conclusion (dPCR thresholds; HRM normalisation/sensitivity; qPCR efficiency/reference genes/non-detects). Note 12's gap matrix states "Robustness across analysis choices: Empty everywhere".
- rdmlpython (MIT) is the common permissive foundation for all three: it already reads dPCR overview data (note 10), performs melt-curve analysis with `corrF` (note 11), and is the only maintained permissive raw-curve library, though its PyPI wheel lags GitHub by three years (note 12).
- Licence hazards flagged: GPL for most R dPCR/HRM/qPCR tools (reimplement from papers); Utah HRM patents US 8,296,074 (anticipated expiry 2026-09-20) and US 8,068,992 (2029-02-01) and Bio-Rad US 8,606,527 (2032) need counsel; NormFinder forbids redistribution.
- Market signals: dPCR literature ~4 % of PCR but growing ~25 % y/y (note 10); HRM output roughly halved since mid-2010s, arguing for a module not a standalone product (note 11); Clarida's monthly release cadence makes "cannot do X" claims perishable, while qbase+, REST and LinRegPCR Windows all dying argues for RDML + open record as the durable bet (note 12).
