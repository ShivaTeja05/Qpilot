# 14. From qPCR results to a paper, a thesis or a core-facility report: journals, reviewers, deposition, figures, retractions, teaching

Researcher note on method: the shared WebSearch budget for this turn was exhausted before my first query ran, so every source below was reached by direct fetch of primary pages I already knew (journal author guidelines, Clinical Chemistry/OUP article pages, Europe PMC full-text API, NCBI E-utilities, repository APIs at Zenodo/Dryad/BioStudies, rdml.org, GitHub/PyPI/CRAN/Bioconductor, vendor and core-facility pages) plus the desktop browser pane for NCBI/GEO pages that block plain fetches. Forum evidence (Reddit, ResearchGate, Biostars, Biology StackExchange, PubPeer) could not be collected: those sites refused both the fetch tool and the browser (Cloudflare checks or a safety block). Where I say "no forum evidence" below, that is why; the report writer should treat reviewer-comment frequency estimates as literature-derived, not forum-derived. Everything cited was read in this session; nothing is from memory alone. Structure follows the brief (six sections); inside Section 1 each key question has Takeaway / Cited findings / Inferences / Gaps as the researcher instructions ask.

---

## 1. How this corner of the niche works

### Roles, the workflow, and where decisions are made

The people: a PhD student or postdoc who has the plates analysed and now needs a figure, a methods paragraph, a checklist and (increasingly) a data deposit; the PI who signs the submission; the reviewer who asks the same five questions every time; the editor of the one journal family that actually enforces a qPCR checklist (Clinical Chemistry); the core-facility manager who hands a client a "detailed report"; the funder's data-management officer (NIH DMS policy, since 25 January 2023 [43]); and the instructor teaching ΔΔCq to 30 students in Excel.

The workflow step by step, with the artefact each step needs:

1. Analysis done → Cq or (rarely) efficiency-corrected quantities per well. MIQE 2.0 says Cq values "are intermediate data" and that "many publications assume a 100% PCR efficiency or require readers to make this assumption" [1].
2. Figure → nearly always a bar chart of mean ± SEM fold change (85.6% of 703 physiology papers used bar graphs; 77.6% of those mean ± SE [57]).
3. Methods paragraph → scattered across main text, supplement and "as previously described" citations (in 432 top-journal genetics/plant papers, 27% used a shortcut citation; annealing temperature missing in 72–80%; cDNA input in 5–6% [5]).
4. Checklist → only at journals that ask. Clinical Chemistry: "For studies that include quantitative real-time PCR experiments, complete the MIQE checklist and upload it during electronic submission ... Incomplete information may be grounds for manuscript rejection" [25]. Journal of Experimental Botany: RT-qPCR "should conform to the MIQE guidelines ... Ideally, authors using RT-qPCR should upload a completed MIQE checklist" and "normalisation is usually conducted with at least two validated reference genes" [27]. The Plant Cell: authors are told "to follow MIQE guidelines", methods "must be described in full, including information on enzymes, kits, and machines used", and quantification must use "true biological replicates" [28]. PLOS ONE, BMC, Nature portfolio and eLife do not mention MIQE at all [29][30][31][33].
5. Data availability statement → "data available on request" is still common; MIQE 2.0 asks for "storage and submission of raw fluorescence data using RDES or RDML" [1], but a 20-paper survey found "none of the publications surveyed provided raw data or metadata consistent with recent standards" and "fewer than 10 researchers have deposited RDML files in the RDMLdb repository in the last 10 years" [6].
6. Review → reviewers (when they look) ask for reference-gene validation, efficiencies, replicate structure, primer sequences, raw data. The evidence is in the audits (below), not in forums (blocked).
7. Post-publication → duplicated RT-qPCR panels are a recurring retraction reason (five 2022–2026 notices found in one Europe PMC query [63]); fabricated qPCR data led to an ORI finding and an AJP-Renal retraction [65].

Vocabulary the developers will meet: MIQE (Minimum Information for Publication of Quantitative Real-Time PCR Experiments; 2009 = 85 items, 2.0 = 53 items), Cq (quantification cycle; Clin Chem requires "Cq instead of Ct, Cp, or TOP" [25]), E/D (essential/desirable, 2009 only), RDML (zipped XML data standard, v1.3), RDES (tab-separated raw-fluorescence export, MIT-licensed spec [45]), RDMLdb (the RDML repository, still answering at http://rdmldb.org/ but its HTTPS certificate is issued for cmgg.be, not rdmldb.org [49]), GEOarchive (GEO's spreadsheet submission route; RT-PCR template with Metadata / Matrix_non-normalized / Matrix_normalized / Fold_Change worksheets [35]), S-BSST (generic BioStudies accession), DMS plan (NIH), MDAR (Materials Design Analysis Reporting checklist, used by eLife [33]), EQUATOR/FAIRsharing (where BMC points authors [30]), SuperPlot (Lord 2020 [58]), LLOQ/LOD, NTC/NRT/NAC, inter-run calibrator (IRC), randomized block, ISO 20395:2019 (qPCR/dPCR performance evaluation standard, 50 pages, under revision as ISO/CD 20395.2 [67]).

What "good" looks like (per MIQE 2.0 [1]): efficiency-corrected target quantities per reaction; reference genes justified by "demonstrating the stability of their expression levels"; fold difference computed as mean(GOI/RG)treated ÷ mean(GOI/RG)control with "statistical analysis ... performed with the normalized data per sample before averaging per group"; "we strongly recommend against relying on the ΔΔCq approach in quantitative analysis"; raw fluorescence deposited as RDES or RDML; LLOQ/LOD reported where low expression matters (at 90% efficiency the ~10-copy LLOQ "is reached at 35 cycles, and LOD at 37 cycles. For 70% efficiency, the respective Cq values are 42 and 45 cycles"); standard curves reported with prediction intervals, not only confidence intervals.

What goes wrong (quantified below): single unvalidated reference gene; efficiency assumed; statistics on fold changes; technical replicates counted as n; Cq cut-offs applied blindly; figures that hide distributions; raw data never leave the instrument PC.

Money and time: a core charges about $54 per plate for instrument time and about $31 per sample for a triplicate assay (Stanford PAN, before 8% internal / 54% external overhead [79]); Emory's core lists TaqMan gene expression at $29 internal / $46 external per sample in triplicate [80]. Raw data for one 384-well plate are under 1 MB (amplification 150–400 KB, melt ~500 KB) [15]. Roughly 22,000 PubMed papers in 2021 mention quantitative/real-time PCR, about 60 per day [15].

Key sites and communities: gene-quantification.de (MIQE pages, ~500 recorded talks via econferences.de, software catalogue: GenEx, geNorm VBA, qBase Excel macros, REST, BestKeeper [76]); rdml.org (standard, RDES, compliance lists [44][45][46]); Clinical Chemistry author instructions [25]; Europe PMC/PMC for the audits; Bitesize Bio for practitioner how-tos (an "RT-qPCR Guide ... From RNA Quality to Reportable Data" and a "Double Delta Ct Calculator" are among its top qPCR pages [78]).

### Key question 1 — MIQE 2.0: every item, and which are machine-checkable

#### Takeaway
MIQE 2.0 (Clin Chem 2025) has 53 items in five sections, no essential/desirable split, and a Yes/No + "location or rationale" response format; by my item-by-item mapping, 22 items can be filled from an RDML 1.3 file plus qPilot's engine, 6 more from instrument/QC exports, 21 need a short human form, and 4 can never be machine-verified. Journals that enforce MIQE still hand authors 2009-era lists (Clinical Chemistry's mandatory .docx is a 44-item condensed 2009 checklist), so a report generator must emit the 2.0, the 2009 and the Clin Chem variants.

#### Cited findings
- MIQE 2.0 checklist structure (verbatim section titles from Table 1): 1. REAGENT PREPARATION (8 items), 2. SAMPLE PREPARATION (13), 3. REVERSE TRANSCRIPTION (7), 4. qPCR PROTOCOL (6), 5. DATA ANALYSIS (19) = 53 items. Response format: "Authors should insert 'Yes' or 'No'. If 'Yes', specify the location of the information in the article or include the information here. If 'No', outline the rationale for omission." — [1] (Table 1, footnotes a–j; PDF mirror at gene-quantification.de)
- Footnotes that change the 2009 rules: primer/probe sequence disclosure "is highly desirable and strongly encouraged. However, when commercial pre-designed assay vendors do not release this information, assay context sequences must be submitted"; the no-RT control "is desirable, but no longer essential" once a sample is validated DNA-free; reagent details "not always provided by commercial vendors", so "manufacturer, catalog and batch number as well as assay context sequences is necessary"; "Efficiency-corrected target quantity calculation is necessary." — [1]
- Raw data: "Storage and submission of raw fluorescence data using RDES or RDML"; "Instrument manufacturers should implement one of these options to enable raw fluorescence data export. Until this is provided, we encourage investigators to supply qPCR data as supplementary files in accessible formats, such as Excel." — [1]
- Enforcement wish: "the checklist can be incorporated into the submission process of journals, as is already the case with some journals, e.g., Clinical Chemistry" and an editable Supplemental Table 1 plus a supplemental "MIQE 2.0 Recommendations" file exist — [1]
- MIQE 2009: 85 items with E/D labels (Drude et al. count 57 essential, 28 desirable [5]); includes items that 2.0 dropped or merged, e.g. "Assay carried out by the core or investigator's laboratory? (D)", "RTPrimerDB identification number (D)", "Cq or raw data submission with RDML (D)", "Number and concordance of biological replicates (D)", "Power analysis (D)" — [2] (Table 1)
- Clinical Chemistry's mandatory checklist file (downloaded 17 Oct 2026) is a 44-item table in seven categories (SAMPLE, EXTRACTION, REVERSE TRANSCRIPTION, qPCR TARGET, qPCR PROTOCOL, qPCR VALIDATION, DATA ANALYSIS) with "Page No." and "Author Comments" columns; items include "Intra-assay variation in terms of concentration, not Cq", "Cqs with and without reverse transcriptase", "Justification of number and choice of reference genes" — it is not the 2.0 list — [26]
- Clin Chem also says the guidelines "are also a guide for reviewers and editors to judge the quality of qPCR data" and requires dMIQE for digital PCR — [25]
- Compliance history: Bustin & Wittwer 2026 (355 full-text articles, 2019 vs 2024): RNA integrity reporting 22%→11%, reference-gene validation 13%→5%, PCR efficiency 13%→1%; MIQE-citing 2024 papers: 31%, 47%, 40% respectively; "Asia now dominates RT-qPCR output by volume, while Europe contributes most MIQE-citing studies" — [4]
- Drude et al. 2026 (186 genetics + 246 plant-science papers from top-20 journals, Sept/Oct 2021; preregistered osf.io/9zp5m): primer sequences 88–93%; RNA integrity values 7–10%; efficiency reported 5–8% ("only about half gave actual values"); reference-gene stability (M-value) 0.4%; "we found no evidence for the use of NRT controls"; accession numbers 14% (genetics) / 31% (plant); analysis software not reported 48–59%; "RDML format: not mentioned in any paper"; "only two papers in our sample (n = 439) referenced the guidelines"; "due to inadequate reporting, it is impossible to determine whether > 90% of qPCR results are reliable" — [5]
- Dijkstra 2014 (179 colorectal-cancer qPCR papers 2006–2013): 92% single reference gene; 13% validated; 82% no efficiencies, yet 91% used efficiency-dependent methods; MIQE cited in 1%; only 3% (6/179) assessable; 70% used ACTB/GAPDH/18S — [11]
- Abdel Nour 2014 (Arabian-country papers, 15 essential criteria): median compliance 40% (0–93%); normalisation 3% — [12]
- Bustin 2013: "Two surveys of over 1,700 publications" found essential technical information often not transparently reported; MIQE-citing papers did better — [9]
- Bustin 2025 editorial: MIQE compliance "patchy, and in many cases, entirely superficial"; "Assay efficiencies are assumed, not measured"; fold changes of 1.2–1.5 reported "as biologically meaningful without uncertainty"; "guidelines alone are not enough" — [7]
- Drude's recommendations include "pre-submission tools to flag missing details" (SciScore cited as the MDAR example), reporting templates, training, and simplifying MIQE — [5]

#### Machine-checkability map (all 53 MIQE 2.0 items)

Classes: **a** = derivable from RDML 1.3 + qPilot engine; **b** = derivable from instrument/QC exports or a lab profile that the tool can ingest once; **c** = needs a short human form each study; **d** = never machine-checkable (only a human can attest). RDML element names are from the v1.3 schema [44]; engine facts refer to what qPilot already computes (LinRegPCR per-well efficiency and N0, geNorm M/V, robustness grid, `qpilot plan`).

| # | Item (MIQE 2.0 wording, abbreviated) | Class | Source in qPilot | Note |
|---|---|---|---|---|
| 1.1 | Bioinformatics tools/versions/settings used to design assays | c (b) | form; lab profile "assay passport" | Primer3Plus can export targets into RDML but settings are not an RDML field |
| 1.2 | Official gene symbol, species, accession | a/c | `target/xRef` (name,id), `target/description`; else form | engine checks presence and format only |
| 1.3 | Location of amplicon | c (a*) | form; *optional module aligning `sequences/forwardPrimer`, `reversePrimer` to the accession | needs a sequence DB; off by default (offline) |
| 1.4 | Amplicon length | a/c | `target/sequences/amplicon` length if present; else form | |
| 1.5 | Primer and probe sequences | a/c | `target/sequences/{forwardPrimer,reversePrimer,probe1,probe2}/sequence`; or `commercialAssay/{company,orderNumber}` → "assay context sequences required" rationale | footnote c logic encoded |
| 1.6 | Location/identity of modifications | a/c | `threePrimeTag`, `fivePrimeTag` of each oligo | |
| 1.7 | Manufacturer of oligonucleotides | c (b) | lab profile | no RDML field |
| 1.8 | Details of optimization performed | d | human attestation | tool can link gradient runs if they exist in the workspace |
| 2.1 | Sample types and numbers | a | count of `sample` ids; `sample/type` (unkn/ntc/nac/std/ntp/nrt/pos/opt); `annotation` property/value for groups | |
| 2.2 | Sampling procedure incl. time to storage | d | form/attest | |
| 2.3 | Aliquoting, storage conditions, duration | c | form | |
| 2.4 | Extraction method, amount processed | c (b) | lab profile / form | |
| 2.5 | Source and amount of spike-in | c | form; sample `annotation` | |
| 2.6 | Elution buffer volume | c | form | |
| 2.7 | Number of extraction replicates | a/c | from sample annotations if encoded; else form | |
| 2.8 | Extraction blanks and percent yield | b/c | Nanodrop/Qubit export; blanks as `sample/type=ntp` wells | |
| 2.9 | Method to evaluate quality and quantity | b | Bioanalyzer/TapeStation RIN export → `sample/annotation` | 2.0 keeps the item but reporting fell to 11% [4] |
| 2.10 | Storage conditions (temp, conc, duration, buffer, aliquots) | c | form | |
| 2.11 | Dilution steps for working template | a/c | `sample/quantity` (unit cop/fold/dil/ng/nMol), `templateQuantity/conc` | |
| 2.12 | Template modification (DNase, pre-amp…) | a/c | `cdnaSynthesisMethod/dnaseTreatment` boolean; rest form | |
| 2.13 | Purification after modification | c | form | |
| 3.1 | cDNA priming method and primer concentration | a/c | `cdnaSynthesisMethod/primingMethod` enumeration (oligo-dt, random, target-specific, oligo-dt and random, other); concentration form | |
| 3.2 | One- or two-step protocol | c (a) | form; inferable if RT step is in `thermalCyclingConditions` | |
| 3.3 | Amount of RNA per reaction | a/c | `templateQuantity/{conc,nucleotide=RNA}` | |
| 3.4 | Reaction components and conditions | c (b) | lab profile; `cdnaSynthesisMethod/enzyme`, linked `thermalCyclingConditions` | |
| 3.5 | Estimated copies with and without RT | a | engine: N0 of `sample/type=nrt` wells vs matched unknowns | fully automatic when NRT wells exist; "No + rationale" otherwise |
| 3.6 | Reagent manufacturer, catalogue, lot | b/c | lab profile lot registry | |
| 3.7 | cDNA storage | c | form | |
| 4.1 | Template treatment (initial heating/denaturation) | a/c | first `thermalCyclingConditions/step` | |
| 4.2 | Primer/probe concentration and source | c | form | v1.3 schema has no oligo concentration field |
| 4.3 | Polymerase, Mg2+, dNTP | c (b) | kit → footnote f: manufacturer/cat/lot suffices | |
| 4.4 | Buffer/kit (manufacturer, cat, lot) | b/c | lab profile | |
| 4.5 | Complete thermocycling parameters incl. reaction volume | a/c | `thermalCyclingConditions/step/{temperature,duration,measure,...}`; volume is not in RDML → form or vendor export | |
| 4.6 | Manufacturer and type of instrument | a/b | `run/instrument`; vendor export | |
| 5.1 | Raw fluorescence stored/submitted as RDES or RDML | a | `react/data/adp` present → emit RDES + RDML 1.3; deposition DOI from record | the one item nobody reports today [5][6] |
| 5.2 | Identity of standards and quantification method | a/c | `sample/type=std` + `quantity`; identity (plasmid, IVT…) form | |
| 5.3 | Baseline correction and Cq determination | a | engine method (LinRegPCR per-well baseline); `run/cqDetectionMethod` enumeration; `backgroundDeterminationMethod` | |
| 5.4 | qPCR analysis program (source, version) | a | qPilot + rdmlpython versions in record | |
| 5.5 | Details of positive/negative controls | a/c | `sample/type` pos/ntc/nac/nrt/ntp; descriptions form | |
| 5.6 | Frequency and Cq of negative controls | a | engine fact | |
| 5.7 | Examples of positive and negative results | a | auto-figure of curves | |
| 5.8 | PCR efficiency estimation and method | a | `data/ampEff`, `ampEffSE`, `ampEffMet` from engine | |
| 5.9 | Method of target quantity calculation (efficiency-corrected) | a | `data/N0`; engine | |
| 5.10 | Description of replicates | a/c | technical = same sample+target; biological = group annotations → form confirms design | |
| 5.11 | Repeatability (intra-experiment) | a | CV of N0 across technical replicates | |
| 5.12 | Reproducibility (inter-run/user/lab) | a/c | engine when IRC (`sample/interRunCalibrator=true`) or multi-plate; else "No + rationale" | |
| 5.13 | Limit of detection calculated? | a/c | from std series if present; else "No" | |
| 5.14 | Dynamic range (LOQs) | a/c | as 5.13 | |
| 5.15 | Method of validation of reference genes | a | geNorm M/V + reverse-normalisation guard facts | the item that fell to 5% [4] |
| 5.16 | Normalisation method / calculation | a | engine; `target/type=ref`; geometric mean | |
| 5.17 | Statistical methods | a | engine's tests on per-sample log quantities | |
| 5.18 | Significance level and statistical power | a | `qpilot plan` facts | |
| 5.19 | Specificity (rare mutations, pathogens) | a/c/d | melt-peak check (roadmap) for dye assays; sequence-level specificity attested | |

Counts (my classification, primary class per row): a = 22, b = 6, c = 21, d = 4. Treat ±3 as the honest uncertainty; what matters is that all 19 Section-5 items except 5.19 are automatic once raw curves are in RDML, while most of Sections 1–4 are a short form plus a once-per-lab profile.

#### Inferences
- The two items whose reporting collapsed (reference-gene validation 5%, efficiency 1% [4]) are exactly the two qPilot already computes; a report that prints them with evidence addresses the most-cited reviewer criticism in the literature.
- Because the only journal with a hard requirement still distributes a 2009-style 44-item .docx [26], an auto-report must render three variants (2.0 Table 1 layout; 2009 85-item E/D; Clin Chem 44-item with page numbers) from one fact set.
- RDML 1.3 has no fields for oligo concentration, reaction volume, oligo manufacturer or reagent lots [44]; these must live in qPilot's lab profile/assay passport, which is already on the roadmap.

#### Gaps
- MIQE 2.0's supplemental "Recommendations" file and editable Supplemental Table 1 were not downloaded (OUP supplementary zip); the item list above is from the article's Table 1.
- Bustin & Wittwer 2026 full text (recommendations to journals/software) is paywalled; only the abstract numbers are cited.
- Whether other journals (J Mol Diagn, Endocrine Society, J Dairy Sci, animal) mandate MIQE could not be verified this turn (JMD blocked by Cloudflare; other URLs 404).

### Key question 2 — Journal policies, reviewer checks, common criticisms

#### Takeaway
Only Clinical Chemistry makes a MIQE checklist mandatory and threatens rejection; JXB and The Plant Cell require conformity in words; PLOS ONE, BMC, Nature portfolio and eLife never mention MIQE but do have data-point, source-data and "define n" rules that qPCR figures routinely violate. Reviewer criticisms are documented in the audit literature (reference genes, efficiency, replicates, statistics scale, raw data), not in forums I could reach.

#### Cited findings
- Clinical Chemistry: mandatory MIQE checklist upload; "Incomplete information may be grounds for manuscript rejection"; nomenclature "qPCR", "RT-qPCR", "Cq instead of Ct, Cp, or TOP"; dMIQE checklist for digital PCR; "Present measures of uncertainty, such as standard error or 95% confidence limits"; the journal "may decline to publish a study which it deems has insufficient information for reproducibility" — [25]
- JXB: "Reverse transcription quantitative PCR experiments should conform to the MIQE guidelines"; checklist upload "ideally"; "normalisation against a single reference gene is only acceptable if clear evidence is presented"; "at least two validated reference genes" — [27]
- The Plant Cell: "Quantitative PCR (qPCR) assays are preferred for quantification of nucleic acids"; methods "in full, including information on enzymes, kits, and machines used", normalisation and primers; follow MIQE; "true biological replicates"; the term "semi-quantitative" is rejected; cites Remans et al. 2014 — [28]. The journal's 2008 letter "Eleven golden rules" asks for ≥3 biological replicates, RIN > 7 (ideally > 9), DNase + no-template checks, ≥4 candidate reference genes validated with geNorm/BestKeeper, efficiency from LinRegPCR, and efficiency-incorporating calculations — [22]
- PLOS ONE: no MIQE/qPCR mention; "report the number of independent replications for each experiment"; state "which measures of variance (standard deviation, standard error of the mean, confidence intervals)"; "Format plots so that they accurately depict the sample distribution"; "make individual data points, underlying graphs and summary statistics available at the time of publication"; repositories acceptable if data "at least as open as CC BY" — [29]
- BMC (Springer Nature): points to EQUATOR and FAIRsharing "for reporting checklists for biological and biomedical research"; MIAME named, MIQE not (in the visible text); "Where a suitable discipline-specific resource does not exist, data should be submitted to a generalist repository"; "inability to gain access to the requested data may lead to a retraction" — [30]
- Nature portfolio: no MIQE; gene expression data "must be MIAME compliant" with GEO/ArrayExpress; "authors can deposit and share data via figshare or Dryad"; code to "Zenodo or Code Ocean" — [31]. The reporting summary has no qPCR section (Materials & methods sections are Antibodies, Eukaryotic cell lines, Palaeontology, Animals, Clinical data, Dual use, Plants, ChIP-seq, Flow cytometry, MRI) but requires "The exact sample size (n) for each experimental group/condition" and "A statement on whether measurements were taken from distinct samples or whether the same sample was measured repeatedly" — [32]
- eLife: MDAR checklist mandatory; "Each source data file should relate directly to a single figure or table"; figures with error bars should "clearly indicate the sample size (n), define the error bars"; code must let a researcher "precisely reproduce all published results"; no PCR/MIQE mention — [33]
- Molecular Oncology, whose own Viewpoint called for raw RT-qPCR data at submission [15], has author guidelines with no "PCR" text (checked in the browser 17 Oct 2026) — [34]
- Untergasser 2023: "reporting quantification cycle (Cq) and PCR efficiency values is insufficient"; raw data let reviewers "assess datasets early on during the peer review process" and editors "analyze data completeness and data integrity even before the initiation of peer review"; suggests GEO for ≥20 samples and 20 genes — [15]
- The error taxonomy reviewers draw on (Ruiz-Villalba 2021): assuming E = 2 at Cq 28 with true E = 1.7 makes "the target quantity calculated with an efficiency of 2 ... 100 times lower than it actually is"; ΔCq-as-ratio bias "can range between 100-fold underestimation and 100-fold overestimation"; ratios of Cq values "should therefore never be used or reported"; dividing Cq by a plate factor "is wrong"; reporting SD of Cq "is never appropriate"; for Cq up to 35 "a variation between technical replicates up to two cycles should be considered acceptable" at low copy — [13]
- Ruijter 2021: a 2% efficiency deviation turns a reported 8-fold ratio into 5.9–10.4 ("35% overestimation or 24% underestimation"); efficiencies 1.93–2.05 give actual ratios 1.45–42.6 — [14]
- Hampton 2025 (20-paper survey): "about 75 % of published qPCR results use the 2−ΔΔCT method"; "None of the authors in our sample mentioned amplification efficiency"; "none explained how they selected their reference"; "CT values of the same sample calculated by the software provided by different qPCR equipment manufacturers" differ; "Many laboratories currently use software such as GraphPad Prism or Excel"; simulation: when treatment affects a correlated reference gene "the 2−ΔΔCT falsely rejects the null hypothesis with a frequency of 93 %" — [6]
- Rieu & Powers 2009 (Plant Cell letter): ≥3 biological replicates, ≥2 technical; plate = block, randomized block design, IRCs; "NRQ data should not be used for inferential statistics"; analyse on log scale (Cq′) with ANOVA; a formula for the SE of a ratio of means — [23]
- Bustin & Nolan 2017 (abstract): "elementary protocol errors, inappropriate data analysis, and inadequate reporting"; most published RT-qPCR data "likely reflect technical noise" — [10]
- Taylor & Mrkusich 2014 (Bio-Rad field observations): lab-specific designs produce "wide variation in quality, reproducibility, and interpretability" — [18]

#### Inferences
- A deterministic "reviewer's report" can be built from eight checks that the audits show are the actual failure points: reference-gene validation evidence; efficiency per assay; normalisation method and number of references; biological vs technical n; statistics on per-sample log quantities; Cq cut-off vs LLOQ for the measured efficiency; controls (NTC/NRT) results; raw data and primer sequences present. Each is an engine fact in qPilot today or on the frozen roadmap.
- Journal "packs" are small: Clin Chem (44-item docx + nomenclature), JXB (≥2 validated references), Plant Cell (biological replicates, full methods), PLOS (individual points, variance measure named), eLife (source data per figure, n and error bars defined), Nature (distinct samples statement). These are rule sets, not prose.

#### Gaps
- No forum threads ("reviewer asked me for…") could be retrieved; the frequency ranking of reviewer comments is inferred from audit non-compliance rates, which is a proxy (reviewers may not ask).
- Clinical Chemistry's internal reviewer checklist (if any beyond the author docx) is not public.
- JMD, Endocrine Society, J Dairy Sci, "animal", CCLM policies unverified.

### Key question 3 — Data deposition: where qPCR data go (and do not)

#### Takeaway
GEO does accept RT-qPCR through a dedicated GEOarchive template, but only for panels of roughly ≥50 genes (≥20 genes if >20 samples), and it wants raw Ct, normalised and fold-change matrices; everything smaller goes to Zenodo/figshare/Dryad/BioStudies as unstructured files, and the one qPCR-specific repository (RDMLdb) is effectively unused. NIH's DMS policy nevertheless applies to every NIH-funded dataset "regardless of funding level", so a one-click, correctly-described deposit is now a compliance need, not a nicety.

#### Cited findings
- GEO RT-PCR page: "we consider RT-PCR analysis of over 50 genes to be high-throughput, but if you have a moderate number of samples (over 20), we will accept submissions with as few as 20 genes"; required worksheets: Metadata; "Matrix_non-normalized ... (e.g., raw Ct values)"; "Matrix_normalized ... (e.g., target gene signal normalized to housekeeping genes)"; "Fold_Change"; commercial PCR panels have GPL accessions (FIND PLATFORM); "Incomplete submissions will result in processing delays" — [35]
- GEOarchive generally: metadata spreadsheet + matrix + raw files "required ... as described in the MIAME and MINSEQE standards"; the "Other data types" section lists NanoString and RT-PCR; Excel auto-formatting warnings (dates, leading zeros) — [36]; submissions "can remain private until a manuscript citing the data is published"; reviewers get anonymous access; accessions "normally approved within 5 business days" — [37]
- Count: 1,046 GEO Series carry the DataSet type "Expression profiling by RT-PCR" (E-utilities, 17 Oct 2026) — [39]
- BioStudies: a search for "qPCR" returns 18,812 hits (not exact) but the first ten are S-EPMC records (Europe PMC supplementary files auto-imported), none S-BSST generic submissions — [40]
- Zenodo: 2,214 records for "qPCR"; among the ten most recent, one dataset ("CRISPR-B WP1 qRT-PCR phenotyping") contains 23 `.pcrd` Bio-Rad raw run files plus an xlsx; others are CSVs, software (MIT) and PDFs; no RDML in the sample — [41]
- Dryad: 324 datasets match "qPCR", all CC0; descriptions mention derived ΔΔCt values or copy numbers, rarely raw Cq, never RDML in the ten shown — [42]
- RDMLdb: "fewer than 10 researchers have deposited RDML files in the RDMLdb repository in the last 10 years" [6]; the site still serves a search page at http://rdmldb.org/ but its TLS certificate is for cmgg.be [49]; rdml.org lists RDMLdb as RDML 1.2-compliant [46]; the 2015 paper says uploads get "a unique identifier provided by RDMLdb", can carry a PubMed ID, and release "can be delayed for up to one year" — [48]
- RDES v1.0 (MIT): one TSV per run for amplification and one for melting; seven leading columns Well, Sample, Sample Type (unkn/ntc/nac/std/ntp/nrt/pos/opt), Target, Target Type (toi/ref), Dye, Cq-or-Tm; then one column per cycle (or temperature) of raw fluorescence; "essential that no correction for baseline fluorescence was performed"; convertible to RDML with RDML-Edit — [45]
- RDML 1.3 (schema): root `rdml` with `experimenter`, `documentation`, `dye` (`dyeChemistry` enumeration), `sample` (types, `annotation`, `templateQuantity`, `cdnaSynthesisMethod`, `quantity`, `calibratorSample`, `interRunCalibrator`), `target` (`type` ref/toi, `amplificationEfficiency`, `amplificationEfficiencySE`, `meltingTemperature`, `detectionLimit`, `sequences`, `commercialAssay`), `thermalCyclingConditions`, `experiment/run` (`instrument`, `dataCollectionSoftware`, `cqDetectionMethod`, `pcrFormat`, `runDate`), `react/data` (`cq`, `N0`, `ampEffMet`, `ampEff`, `ampEffSE`, `corrF`, `corrP`, `corrCq`, `meltTemp`, `excl`, `note`, `adp`, `mdp`, `endPt`, `bgFluor`, `bgFluorSlp`, `quantFluor`) and `partitions` for dPCR; 1.2→1.3 added the efficiency/N0 fields and partition tables — [44]
- RDML-compliant instruments listed by the consortium: Bio-Rad CFX Maestro (1.1), Roche LightCycler 96 (1.1), Qiagen Rotor-Gene Q (1.1), IT-IS MyGo (1.2), Life Technologies StepOne / QuantStudio 12K Flex / ViiA 7 (version unlisted) — [46]. Compliant software includes "Clarida's RDML viewer" (1.3), LinRegPCR (1.2), the RDML R package (1.1) — [46]
- The original RDML paper's minimum: "A Cq value should be provided for each reaction well", sample id and type, target id and type; "All elements of this data format are optional" — [47]
- NIH DMS Policy: effective 25 January 2023; applies to "all research funded or conducted in whole or in part by NIH, that results in the generation of scientific data", "regardless of funding level"; scientific data = "data commonly accepted in the scientific community as of sufficient quality to validate and replicate research findings, regardless of whether the data are used to support scholarly publications"; plans are reviewed by program staff, compliance is "a term and condition of award", updates go in annual progress reports — [43]
- Untergasser 2023: raw data per 384-well plate "less than 1 MB"; proposes RDES, RDML or Excel at submission — [15]
- RO-Crate: "a lightweight approach to packaging research data with their metadata"; adopters include WorkflowHub and OME (no qPCR use found) — [55]; ISA has tabular/JSON/RDF serialisations and open-source tools, no qPCR mention — [56]

#### Inferences
- There is no qPCR-specific metadata schema in any generalist repository; the de-facto schema is "GEO's RT-PCR workbook" for panels and "whatever the author zips" for everything else. A deposit generated from an RDML-backed Analysis Record (RDML 1.3 + RDES + record JSON + methods + MIQE report + figure source data, described by an ro-crate-metadata.json) would be the first machine-readable qPCR deposit most reviewers ever see.
- GEO's 20/50-gene thresholds mean most single-gene-panel papers cannot use GEO; the tool should route by size: GEO workbook if ≥20 genes and >20 samples (or ≥50 genes), else Zenodo/figshare/Dryad/BioStudies.

#### Gaps
- ArrayExpress's current stance on qPCR could not be read (help page is JavaScript-rendered); BioStudies' generic-submission docs likewise.
- How many Zenodo/Dryad qPCR records include raw curves is unknown beyond the ten-record samples above.
- No evidence that any journal checks DMS-plan compliance for qPCR specifically.

### Key question 4 — Figures: what is expected, what is criticised

#### Takeaway
The field's default qPCR figure (bar of mean fold change ± SEM, technical replicates pooled) is the figure type most criticised in the data-visualisation literature; journals now ask for individual points, defined n, defined error bars and per-figure source data; MIQE 2.0 adds log-scale amplification plots and per-sample normalised quantities before group averaging. SuperPlot-style figures bound to engine facts, with an auto-generated n-honest caption and a source-data CSV, meet all of these at once.

#### Cited findings
- Weissgerber 2015: 85.6% of 703 physiology papers had ≥1 bar graph (77.6% mean ± SE, 15.3% mean ± SD); univariate scatterplots 13.4%, box plots 5.3%; median minimum group size 4 (IQR 3–6); "many different data distributions can lead to the same bar or line graph"; "Showing the SE rather than the SD magnifies the apparent visual differences between groups"; recommends univariate scatterplots and journal policy change — [57]
- Lord 2020 (SuperPlots): "superimpose summary statistics from repeated experiments on a graph of the entire cell-level dataset"; n = biological replicates; "counting each cell as a separate n can easily result in false-positive rates of >50%"; "it is critical to list the number of independent experiments in the figure or caption"; recipes for Prism 8, Excel, R (ggplot2/ggbeeswarm), Python (matplotlib/seaborn) — [58]
- Tools: SuperPlotsOfData (R/Shiny, GPL-3.0, hosted at huygens.science.uva.nl) [59]; superviolin (Python CLI, MIT, v1.0.6 Nov 2021) [60]
- Rieu & Powers: present mean NRQ ± SE but infer on the log scale; SE of a ratio needs the proper formula; block-correct before plotting — [23]
- Hampton 2025: "use of candid graphics that show reference gene responses"; "Better qPCR graphics, statistics and data management could improve reproducibility"; "remaining on the log scale throughout can avoid possible statistical problems involved with back transformation" — [6]
- MIQE 2.0: amplification plots "typically plotted with log[fluorescence] on the y-axis"; standard curves with prediction intervals; "statistical analysis should be performed with the normalized data per sample before averaging per group" — [1]
- Journal rules: PLOS "Format plots so that they accurately depict the sample distribution" [29]; eLife "clearly indicate the sample size (n), define the error bars" and one source-data file per figure [33]; Nature reporting summary "distinct samples or ... the same sample was measured repeatedly" [32]; Clin Chem "measures of uncertainty, such as standard error or 95% confidence limits" [25]
- Retraction notices involving RT-qPCR figures (Europe PMC, 2022–2026): "the real-time PCR results in Figure 6A are duplicated with those shown in Figure 6B" (FEBS Lett); RT-qPCR data in Fig. 2A "appeared duplicated" (Oncol Rep 2026); "the same loading controls for the RT-PCR experiments" reused (Oncol Rep 2025); "the results of RT-PCR could not be repeated" (Med Sci Monit 2022) — [63]
- Kenneth Walker (Pittsburgh) ORI case: "falsified and/or fabricated quantitative real-time polymerase chain reaction (qPCR) data" to show a difference "when there was none"; AJP-Renal Physiol retraction lists Figs. 1E, 4C, 7G, 7J, 8F, 12A; a 2013 PLOS ONE paper flagged (Fig. 2E) — [65]

#### Inferences
- A figure whose points, replicate means, error bars and P values are each bound to an engine fact id, with the caption generated from those facts, removes both the pseudoreplication error and the "redraw for reviewer 2" cycle; emitting the source-data CSV per figure satisfies eLife/EMBO-style policies by construction.
- GPL-3.0 SuperPlotsOfData cannot be bundled; the SuperPlot is a layout convention, trivially re-implemented in matplotlib; superviolin (MIT) can be reused.

#### Gaps
- PubPeer figure-duplication threads for qPCR could not be read (Cloudflare); counts of qPCR-related PubPeer comments unknown.
- No source quantifies how often qPCR papers are rejected for figure style; the retraction notices are the only hard evidence.
- JCB's and EMBO's current instructions were not readable (Cloudflare / Springer cookie wall).

### Key question 5 — Retractions and corrections where qPCR analysis was the issue

#### Takeaway
Hard evidence of qPCR-driven retractions is of two kinds: duplicated or reused RT-qPCR panels (publishers' notices, mostly Spandidos/Wiley oncology journals) and fabricated qPCR values (ORI case). "Analysis was wrong" retractions (wrong reference gene, wrong ΔΔCt) were not found as retractions, only as corrections and as the audits' complaint that "97% cannot be reliably assessed".

#### Cited findings
- Five notices (2022–2026) above [63]; a 2026 corrigendum where "the same GAPDH primer was in fact used as a negative primer control for both the ChIP and the RT-qPCR analyses" and primer sequences were "inadvertently copied across" [64]
- Walker/ORI: see KQ4 [65]; Retraction Watch's own site search for "qPCR" returns the two Walker posts and otherwise unrelated items [65]
- The Corman-Drosten SARS-CoV-2 RT-PCR retraction request was answered by a Eurosurveillance editorial (4 Feb 2021, open access), but its body text did not render through my tools; I cannot quote the allegations or decision [66]
- Dijkstra's example of a result that cannot be trusted: a CD133 colorectal paper using 18S rRNA as single unvalidated reference with ΔΔCq and no efficiencies, maximum fold difference 2.5, 16/53 pairs reversed [11]

#### Inferences
- The tool's hash-chained record and per-figure source data are a defence against the main documented failure (panel duplication) because every panel is regenerable from named wells; a "figure provenance" line in captions (record root hash + fact ids) is cheap.

#### Gaps
- Retraction Watch Database counts for "qPCR" were not obtained (form-based site).
- No PubPeer evidence (blocked).

### Key question 6 — How qPCR analysis is taught; where students go wrong

#### Takeaway
Published teaching labs (BAMBED, JMBE) teach the bench and a manual ΔΔCt or standard-curve analysis; none I found gives instructors a dataset with a known answer, seeded errors, or a way to grade decisions; vendor education (Thermo handbook and learning centre, Bio-Rad videos) teaches the 90–110% efficiency rule but is vendor-centric; the audits explicitly blame "insufficient training" and ask for templates and training. The conceptual errors are well enumerated in the literature and are the natural content of a teaching mode.

#### Cited findings
- Hancock 2010 (BAMBED): four 3-hour sessions, MEL cells ± DMSO, three genes vs 18S rRNA; "the undergraduate student experience in practical classes with such sensitive techniques is often mixed" — [68]
- Harshitha & Arunraj 2021 (BAMBED): exercise for undergraduate and graduate students "covering RT-qPCR principles and data analysis using both manual and software methods", focusing on primer characteristics, PCR efficiency and melt-curve analysis — [69]
- Other teaching labs using real-time PCR: Gunn 2013 (85 students; >95% met objectives), Bauer 2016 (Arabidopsis FIT/FRO2 vs reference gene), Weinlander 2010 (allelic discrimination on students' own DNA), Birnbaum 2010 — [70]
- Müller & Tiret 2026 (Bio-protocol): "efficiency-corrected relative quantification using LinRegPCR and a spreadsheet-based workflow", normalised to the geometric mean of two reference genes — i.e. the teaching-grade workflow is still a spreadsheet — [71]
- Kubista 2026 (IJMS tutorial review): how standard curves define efficiency, LOD, LOQ; proposes "variance PCR" — [72]
- Thermo handbook: "A good reaction should have an efficiency between 90% and 110%, which corresponds to a slope of between −3.58 and −3.10"; the comparative method "assumes that the PCR is operating at 100% efficiency"; reference gene "must be present at a consistent level in all samples being compared" — [73]; learning centre pages "Understanding Ct", "Real-Time PCR Data Analysis", troubleshooting tool; the "Real-Time PCR Training Series" link now redirects to a general education-services page — [74]
- Bio-Rad's PCR page lists videos "Data Analysis: Real-Time Quantitative PCR" and "Validating a SYBR Green I Assay" — [75]
- gene-quantification.de: about 500 recorded talks (econferences.de), MIQE iBook, software catalogue — [76]; TATAA's site (which "co-authored the MIQE guidelines") lists services only; a site search for "course" finds no course page (17 Oct 2026) — [77]
- Drude 2026: possible causes of poor reporting include "low awareness of qPCR pitfalls, insufficient training"; recommends "reporting templates, training materials, and stronger editorial and community expectations" — [5]; Bustin 2024 names "awareness, resources, and publication pressure" as barriers — [8]
- Conceptual errors enumerated by the literature: efficiency assumed [1][6][13][14]; statistics on fold changes instead of log/ΔCq [23][6]; technical replicates as n [58][23]; SD of Cq, ratios of Cq, plate correction by dividing Cq [13]; threshold above the exponential phase [13]; arbitrary Cq cut-offs (a 40-cycle cut-off "may be either too low... or too high" [13]; LLOQ depends on efficiency [1]); single unvalidated reference gene [11]; 0.5-cycle replicate rule misapplied at low copy [13]; Cq reported as "sensitivity" ("meaningless") [13]
- A 2026 web tool (GeneQuantify, Python/Streamlit) was validated "against manual Excel calculations" and offers six interface languages — a signal that Excel is still the reference implementation in teaching labs — [85]

#### Inferences
- Instructors have reproducible wet-lab exercises but not reproducible analysis exercises; the missing piece is a dataset family with planted, named errors and a key. qPilot's robustness engine can generate the "how many reasonable analyses agree" answer that makes grading objective.
- Willingness to pay by instructors is undocumented; adoption is more plausible through free classroom use (already in scope: worksheet with hidden key) feeding later lab adoption.

#### Gaps
- No syllabus, lab manual, YouTube or Labster page was retrievable (guessed Labster URL 404; no search).
- No education paper quantifies student error rates in ΔΔCt; evidence of "grading Excel ΔΔCt" pain is absent.

### Key question 7 — Core facilities: what they deliver

#### Takeaway
Cores sell instrument time per plate and full-service runs per sample and promise a "detailed report" whose content is not specified; the only standard that defines what a quantitative report should contain (ISO 20395:2019: acceptance criteria, threshold setting, normalisation, validation, measurement uncertainty) is a paid 50-page document under revision. No recent ABRF survey of qPCR cores was found.

#### Cited findings
- Stanford PAN: StepOnePlus; self-service (book instrument, free software copy, staff help with "plate setup, instrument use, software, and data analysis") or full service ("You provide total RNA samples and primers ... PAN runs the qPCR and returns a 'detailed report'"); rates: instrument run $53.90/plate, RT $64.90/sample "Bioanalyzer QC included", qPCR triplicate $30.80/sample; +8% F&A internal, +54% external — [79]
- Emory EIGC (rates effective Oct 2026): TaqMan gene expression $29/$46 per sample in triplicate; ddPCR assisted $17/$27, unassisted $11/$18; instrument $69/$108 per hour; deliverables, QC and turnaround not stated — [80]
- ISO 20395:2019 scope: "data quality control and analysis including acceptance criteria, threshold setting and normalization"; "method validation (precision, linearity, limit of quantification, limit of detection, trueness and robustness)"; "metrological traceability and estimating measurement uncertainty"; published 2019-08, 50 pages, TC 276/SC 1, stage 90.92 "to be revised", successor ISO/CD 20395.2 under development — [67]
- MIQE 2009 had a desirable item "Assay carried out by the core or investigator's laboratory?" — [2]; MIQE 2.0 dropped it [1]
- ABRF: only a 2010 NARG study abstract on cDNA priming strategies surfaced (no abstract text) — [81]; a 2026 multisite ABRF study concerns single-cell RNA-seq, not qPCR
- RDML export exists for CFX Maestro, LightCycler 96, Rotor-Gene Q, MyGo and some Life Technologies instruments [46]; MIQE 2.0 asks manufacturers to implement RDES or RDML export [1]

#### Inferences
- A core that returns an RDES/RDML file, a per-plate QC sheet (NTC/NRT, efficiency per assay, melt check, replicate spread vs expected Poisson spread, LLOQ flags, IRC drift) and the pre-filled MIQE Sections 4–5 would be delivering something no price list currently names; it also protects the core when a client's reviewer asks "what was the efficiency?".

#### Gaps
- No public SLA, complaint thread or client survey for qPCR cores was found; the "cannot tell a client why a run failed" pain is plausible but unevidenced here.
- Harvard, VIB, FGCZ, Vanderbilt pages had no qPCR detail.

---

## 2. Pain inventory

| # | Pain | Evidence | Frequency (estimate) | Who feels it | Severity | What exists today |
|---|---|---|---|---|---|---|
| P1 | Reviewer/editor asks for reference-gene validation and efficiencies after submission; experiment or analysis redone | 5% and 1% of 2024 papers report them [4]; 0.4% report M-values [5]; Clin Chem may reject [25]; JXB demands ≥2 validated references [27] | Most submissions with qPCR (audits: >90% non-compliant) | Student/postdoc, PI | High (weeks; sometimes a new plate) | Clarida "MIQE score" (paid); manual geNorm in Excel; nothing tied to raw curves |
| P2 | MIQE checklist filled by hand, items unknown or unknowable; three different checklist versions in circulation (2.0, 2009, Clin Chem 44-item) | [1][2][26]; 2 of 439 papers cite MIQE [5] | Every Clin Chem/JXB submission; rare elsewhere | Student, PI | Medium (hours) + rejection risk | Word/Excel templates from the journal |
| P3 | Methods paragraph scattered; "as previously described"; annealing temp, cDNA input, software omitted | 27% shortcut citations; 72–80% no annealing temp; 48–59% no software [5] | Most papers | Author, reader, replicator | Medium | Templated methods text (qPilot stretch) |
| P4 | Raw curves never leave the instrument PC; Cq-only data cannot be re-analysed | "none ... provided raw data" [6]; <10 RDML depositors in 10 years [6]; MIQE 2.0 item 5.1 [1] | Nearly universal | Reviewers, re-users, the lab itself a year later | High (unverifiable science) | RDES/RDML exist [44][45]; vendor export patchy [46] |
| P5 | Deposition confusion: GEO needs ≥20–50 genes and three matrices; generalist repos take anything; no qPCR metadata schema | [35][41][42][40] | Every paper with a data-availability statement | Author, data steward | Medium (hours–days) | GEOarchive xlsx; Zenodo web form |
| P6 | NIH DMS plan must describe qPCR data types, formats and repositories | policy applies regardless of funding level [43] | Every NIH grant since 2023 | PI, grants office | Medium | Boilerplate generators (institutional) |
| P7 | Figures: bar ± SEM with technical replicates as n; redrawn for reviewers; no source data | 85.6% bar graphs [57]; >50% false-positive risk from pseudoreplication [58]; eLife/PLOS rules [29][33] | Most papers | Student | Medium–high | Prism habits; SuperPlotsOfData (GPL) |
| P8 | Statistics on the wrong scale (fold change, ΔΔCq) | MIQE 2.0 discourages ΔΔCq [1]; 93% false rejection in one simulation [6]; [23] | ~75% of papers use ΔΔCt [6] | Everyone | High (wrong conclusions) | Excel/Prism |
| P9 | Cq cut-off disputes ("Cq > 35 is noise") | LLOQ 35 at 90% efficiency but 42 at 70% [1]; arbitrary cut-offs [13] | Common in low-expression studies | Author vs reviewer | Medium | Rule of thumb |
| P10 | Duplicated/reused RT-qPCR panels → retraction | five notices [63]; ORI case [65] | Rare but catastrophic | Authors, institutions | Very high | Image-forensics after the fact |
| P11 | Teaching analysis by hand in Excel; no answer key; students learn the E=100% habit | [68][69][71][5] | Every course | Instructors, students | Medium | Vendor handbooks [73][74]; worksheet (qPilot) |
| P12 | Core "detailed report" undefined; client cannot answer reviewer; core cannot show why a run failed | [79][80][67] | Per full-service order | Core manager, client | Medium | Vendor software reports; ISO 20395 (paid) |
| P13 | Vendor software gives different Cq for the same sample; no raw export | [6][1][46] | Every multi-instrument study | Everyone | Medium | RDML-compliant instruments list [46] |

---

## 3. Discoveries (ranked by impact × feasibility × fit)

### D1. "MIQE 2.0 Auto-Report": 53 items, 28 filled from the record, three journal renderings, every answer traceable

1. **Persona and situation.** A PhD student submitting to Clinical Chemistry, JXB or The Plant Cell (or any journal when a reviewer asks); a PI who must sign the checklist; a core delivering MIQE-ready runs. Once per manuscript, and again at revision.
2. **Evidence of the pain.** The one journal that mandates the checklist threatens rejection for incomplete information [25] yet still hands authors a 44-item 2009-style .docx [26]; reporting of the two automatable items collapsed to 5% and 1% [4]; "only two papers in our sample (n = 439) referenced the guidelines" [5]; Drude explicitly asks for "pre-submission tools to flag missing details" [5]. Time cost: hours per submission (estimate), and the far larger cost of a rejection or a repeated experiment.
3. **What exists today.** Clarida sells a "MIQE score" from Cq input (closed, paid); SciScore checks MDAR but not MIQE [5]; journals supply Word templates. None works from raw curves, none records provenance, none produces the 2.0 list.
4. **The feature.** Input: the Analysis Record (RDML 1.3 with `adp`, `ampEff`, `N0`, sample/target annotations; engine facts for geNorm M/V, NTC/NRT, repeatability, power) plus a lab profile (instrument, kits, lots, oligo vendor, extraction method) and a per-study form of ~21 questions (Sections 2–4 items classed c/d above). Deterministic mapping per the table in Section 1 (KQ1). Output: (i) MIQE 2.0 Table 1 layout with "Yes/No", "location" = "Supplementary MIQE report §x / fact id", or "No" with an engine-written rationale ("LOD not calculated: no standard dilution series in study; samples' Cq range 18–27 is >8 cycles above the 37-cycle LOD expected at the measured 92% efficiency" — every number a fact id); (ii) the 2009 85-item E/D rendering; (iii) the Clin Chem 44-item .docx with page numbers left for the author; (iv) a JSON with item → fact ids. Decision the scientist makes: approve/edit each human item; the tool never answers d-class items. Record: form answers and renderings are appended to the hash chain. Agent call: `qpcr_miqe_report(study, journal_pack)` returning the JSON and a completeness score ("28/53 machine-filled, 19 answered, 6 missing").
5. **Feasibility.** python-docx (MIT) and openpyxl (MIT) for renderings; item wording is factual checklist text (cite the paper; keep the journal's docx layout rather than copying the OUP table verbatim if the team is cautious); rdmlpython (MIT) already parses the fields; 1–2 weeks. Hardest part: the lab profile data model (lots, oligo vendors) and keeping three renderings in sync.
6. **Why qPilot.** Raw-curve analysis makes items 5.3, 5.8, 5.9, 5.11, 5.15 true rather than asserted; the decision log gives "rationale for omission" text for free; the record makes the report reproducible; MCP lets an agent fill it for a batch of studies.
7. **Risks.** Journals lag (2009 lists) — mitigated by three renderings; a checklist can become theatre — mitigated by binding every "Yes" to a fact id; the MIQE 2.0 item text is in a paywalled article — low legal risk but the supplemental editable table's terms were not checked. Confidence: high.

### D2. "Reviewer's Report": the eight questions reviewers actually ask, answered from the record with field base rates

1. **Persona.** The same student before submission; the PI at sign-off; a journal editor or reviewer who receives the report as a supplement; a core manager attaching it to a client delivery.
2. **Evidence.** The audit literature is a list of what reviewers should have caught: single unvalidated reference gene (92%) [11]; efficiency assumed (82% unreported while 91% use efficiency-dependent methods) [11]; no NRT evidence, no M-values [5]; statistics on ΔΔCq discouraged by MIQE 2.0 [1]; pseudoreplication [58]; arbitrary Cq cut-offs [13]; raw data absent [6]. Reviewers at Clin Chem are told to use MIQE "to judge the quality of qPCR data" [25]. (Forum confirmation unavailable this turn — see Section 5.)
3. **What exists today.** Nothing generates a reviewer-style critique from data; Clarida's score is a number without reasons; a "reviewer-critic agent" is a roadmap headline, but without a fixed, deterministic question set it would be an LLM opinion.
4. **The feature.** A deterministic rule module `review_rules.yaml` with eight checks, each with: engine inputs, pass/fail/undetermined logic, the literature reason, and a base rate. (1) Reference genes: ≥2 references, geNorm M < threshold and V < 0.15, reverse-normalisation guard passed → cite [27][11]. (2) Efficiency: per-assay LinRegPCR efficiency reported with SE; flag assays outside 90–110% [73] or with high SE. (3) Normalisation: geometric mean of references; per-sample normalised quantities exist. (4) Replicates: biological n per group from annotations; technical replicates collapsed; flag if any statistic used wells as n. (5) Scale: tests run on log quantities per sample before group means [1][23]. (6) Non-detects and cut-offs: Cq vs LLOQ/LOD computed from measured efficiency [1]; censored handling (roadmap). (7) Controls: NTC Cq ≥ sample Cq + 5 (MIQE 2.0 rule [1]), NRT present, melt-peak check (roadmap). (8) Disclosure: primer sequences or commercial assay ids present; raw curves present and exported. Output: a one-page "Reviewer's Report" in the voice of a reviewer ("The authors validated reference genes (geNorm M = 0.41, V2/3 = 0.09; fact f-123). Only 5% of 2024 RT-qPCR papers report this [4]."), a list of what could not be checked, and the journal pack diff (Clin Chem/JXB/Plant Cell/PLOS/eLife/Nature rules in Section 1 KQ2). Any prose from a model is checked against the engine ("no naked numbers"). Agent call: `qpcr_review(study, journal)`; the human decides which flags to fix, and each dismissal is logged with a reason.
5. **Feasibility.** All inputs exist or are on the frozen roadmap; the base-rate table is five numbers from [4][5][11]; 1–2 weeks. Hardest: defining "undetermined" honestly (e.g. no standards → LOD unknown, not failed).
6. **Why qPilot.** The robustness grid answers the reviewer's deepest question ("would the conclusion change under another reasonable analysis?") which no checklist can; decision cards already carry the reasons; the record makes the report citable.
7. **Risks.** Over-flagging causes fatigue — rank by impact like the cards; base rates age — version them with citations; reviewers may distrust machine text — keep it fact-bound and short. Confidence: high.

### D3. Fact-bound SuperPlot figures with n-honest captions and per-figure source data

1. **Persona.** Student making Figure 3 for the third time after reviewer 2 asked for "individual data points and the n"; PI who wants Prism-looking output; instructor demonstrating pseudoreplication.
2. **Evidence.** 85.6% of papers use bar graphs that hide distributions [57]; counting technical replicates as n yields >50% false positives [58]; PLOS wants plots that "accurately depict the sample distribution" and individual points available [29]; eLife wants n and error bars defined and one source-data file per figure [33]; Nature's summary asks whether "the same sample was measured repeatedly" [32]; MIQE 2.0 wants per-sample normalised quantities and log-scale plots [1]; Hampton asks for "candid graphics that show reference gene responses" [6]; duplicated panels are a retraction cause [63].
3. **What exists today.** Prism (commercial; Lord gives a manual recipe), SuperPlotsOfData (GPL-3.0 Shiny app [59]), superviolin (MIT, Python [60]), ggplot2 recipes; none is connected to the analysis, none writes the caption, none emits source data with provenance.
4. **The feature.** From the record, per gene: points = biological replicates (per-sample log2 normalised quantity, technical replicates collapsed), colour or marker = plate/block, overlaid replicate means with error bars computed from biological n, P value from the engine's per-sample test; optional second panel "reference-gene response" (target and reference N0 per sample, Hampton Fig 5A style); amplification-curve inset on request (log fluorescence, MIQE 2.0). Caption generated from facts: "n = 6 biological replicates (3 plates), 2 technical replicates each (collapsed); points: per-sample normalised quantity (geometric mean of HPRT1, TBP; geNorm M 0.38); error bars: 95% CI of biological means; two-sided t-test on log2 quantities, P = 0.012 [fact ids]; source data: fig3_source.csv; record root hash …". Outputs: SVG/PNG/PDF via matplotlib, source-data CSV per figure, and the already-planned Prism .pzfx. Decision: style choices only; the data mapping is not editable. Agent call: `qpcr_figure(study, gene, style)`.
5. **Feasibility.** matplotlib (PSF-compatible licence), numpy/pandas (BSD); superviolin (MIT) for violin variant; 1 week; hardest part is caption templating that stays correct under every design (unbalanced blocks, missing groups).
6. **Why qPilot.** The figure is a view of the record, so duplication is impossible without a visible provenance mismatch; robustness results can be drawn as a small "agreement" glyph; the no-naked-numbers rule already governs captions.
7. **Risks.** Journals' style guides vary; some PIs insist on bars — offer the bar as an overlay but never as the only view. Confidence: high.

### D4. One-click deposition: GEOarchive RT-PCR workbook, RO-Crate deposit to Zenodo/BioStudies/Dryad, and a DMS-plan paragraph

1. **Persona.** The student at the data-availability-statement step; the PI writing an NIH DMS plan; a data steward asked "what format is qPCR data?".
2. **Evidence.** NIH DMS policy applies to all NIH-funded research generating scientific data "regardless of funding level" [43]; GEO's RT-PCR route requires specific worksheets and ≥20–50 genes [35]; Zenodo and Dryad hold thousands of ad-hoc qPCR deposits, mostly CSV/xlsx, occasionally raw `.pcrd` [41][42]; RDMLdb is moribund [6][49]; MIQE 2.0 asks for RDES/RDML raw data and "data repositories for sharing experimental details, raw fluorescence data, and analysis scripts" [1]; Hampton recommends figshare for raw Ct and GitHub for code [6]; a plate is <1 MB [15].
3. **What exists today.** GEO's xlsx template (manual, panel-sized studies only); repository web forms; institutional DMS-plan boilerplate; no RO-Crate profile for qPCR (none found [55]).
4. **The feature.** `qpilot deposit --target zenodo|biostudies|dryad|geo` builds a package: `study.rdml` (1.3), one RDES TSV per run (amplification + melt), `analysis_record.json` (hash chain), `methods.md`, `miqe_report.{docx,json}`, `figures/*.svg` + `*_source.csv`, `REPLICATE.json`; an `ro-crate-metadata.json` (schema.org Dataset/File entries with MIQE 2.0 item ids as `additionalProperty`, instrument, organism, targets with accessions, licence); for GEO (only when ≥20 genes and >20 samples or ≥50 genes) the Metadata / Matrix_non-normalized (raw Cq) / Matrix_normalized / Fold_Change worksheets filled from the record, with the GPL platform id looked up via GEO's FIND PLATFORM if a commercial panel. Zenodo via its REST API with a local token (sandbox first); Dryad requires CC0 — the tool warns; BioStudies via PageTab. The DOI/accession is written back into the record and into the MIQE item 5.1 answer and the data-availability statement. DMS text: "Data type: raw per-well fluorescence (RDML 1.3, RDES TSV), ~1 MB/plate; metadata: MIQE 2.0; repository: Zenodo (DOI at publication); timeline: at publication or end of award". Decision: licence, embargo, repository. Agent: `qpcr_deposit_package(study, target)` (packaging), with the upload itself kept as a human-approved step (agent-requests inbox).
5. **Feasibility.** rocrate (Python; licence to verify, believed Apache-2.0), requests; GEO template parsing from the public xlsx; 2–3 weeks; hardest: GEO's field semantics and curator expectations; keeping tokens local.
6. **Why qPilot.** The record already is the deposit; checksums and the hash chain give integrity; RDML in/RDML out is native.
7. **Risks.** GEO may decline small studies (route elsewhere); repository APIs change; metadata profile needs community buy-in (propose it to the RDML consortium). Confidence: medium-high.

### D5. Core-facility client report and "why did this run fail", from raw curves, instrument-agnostic

1. **Persona.** Core manager returning a full-service run (PAN: "returns a detailed report" [79]); the client's student who is asked by a reviewer for efficiencies six months later; the core answering "why are my Cqs 3 cycles later than last month?".
2. **Evidence.** Price lists name plates and samples but not report contents [79][80]; ISO 20395 defines acceptance criteria, threshold setting, normalisation, validation and measurement uncertainty, but is a paid 50-page standard [67]; MIQE 2.0 asks manufacturers for raw export and asks for repeatability/reproducibility, negative-control Cq frequencies and LOD/LLOQ [1]; vendor software disagrees on Cq [6]; RDML export is limited to a handful of instruments [46]. The "cannot tell a client why a run failed" pain is inferred (no client complaints found).
3. **What exists today.** Vendor desktop reports (CFX Maestro, QuantStudio D&A) tied to one instrument; LIMS; Excel.
4. **The feature.** A `lab profile` for the core (instruments, kits, lot registry, SOP ids) plus per-order inputs (client, samples, assays) produce: (i) a QC page per plate: NTC/NRT/NAC Cq table with the "≥5 cycles" rule [1], per-assay efficiency with SE and a 90–110% flag [73], replicate spread judged against copy-number expectation (0.5 cycles high copy; up to 2 cycles near Cq 35 [13]), melt-peak check (roadmap), inter-run calibrator drift versus the core's running history (lab memory, roadmap), LLOQ/LOD from measured efficiency; (ii) MIQE 2.0 Sections 4–5 pre-filled with the core's details and the record's facts, so the client's later manuscript inherits them; (iii) RDES + RDML regardless of vendor (vendor capture roadmap); (iv) a signed record hash on the PDF. Decision: the core signs off outliers and exclusions via cards; the client gets an MCP-callable record. Agent: `qpcr_core_report(order)`.
5. **Feasibility.** Mostly composition of existing engine facts; 2 weeks; hardest: vendor exports and the lot registry.
6. **Why qPilot.** Whole-study, instrument-agnostic analysis and the record are what a core lacks; the core-attribution item that MIQE 2009 had ("core or investigator's laboratory?" [2]) becomes an actor field in the closed-loop contract.
7. **Risks.** Cores are conservative and many are self-service only (clients analyse themselves); the ISO text cannot be reproduced; must stay research-use (no 21 CFR Part 11 claims). Confidence: medium.

### D6. Teaching mode with seeded-error datasets and an instructor key graded by the robustness engine

1. **Persona.** An instructor of a 3rd-year molecular biology practical (Hancock-style four sessions [68]) or a graduate methods course; lab heads onboarding new students; a self-learner with a vendor handbook.
2. **Evidence.** Teaching labs exist but analysis is "manual and software" [69] or spreadsheet-based [71]; vendor education teaches the slope rule but not validation [73][74]; audits blame "insufficient training" and ask for training materials and templates [5][8]; the canonical errors are enumerated [13][14][23][58][1].
3. **What exists today.** Vendor handbooks and videos; gene-quantification talks [76]; BAMBED protocols; Labster (unverified); qPilot's planned worksheet with hidden key. No dataset with planted errors and an objective grading rule.
4. **The feature.** `qpilot teach` ships 6–8 RDML datasets derived from public raw-curve sets (RDML consortium benchmark; Brintz 2025 CC0 curves; the Vermeulen/Ruijter 2013 benchmark if its licence allows [54]) with one planted, documented problem each: an assay at 70% efficiency; a reference gene that shifts between groups; technical replicates mislabelled as biological; a plate effect without IRCs; non-detects at Cq 38–40; a threshold set above the exponential phase; a contaminated NTC. Students work in "Teach me" autonomy; each decision card is a graded question; the hidden key is the record of the intended analysis; `records compare` scores the student's record (decisions and conclusions) and the robustness grid shows which wrong choices would have flipped the conclusion. Instructor view: per-student decision logs, aggregate error rates per concept (gives the first quantitative data on where students go wrong). Agent: an "examiner" agent can run the same flow for onboarding in labs.
5. **Feasibility.** Perturbation generator over RDML (rdmlpython, MIT), dataset licences to confirm; 1–2 weeks after the worksheet exists; hardest: making planted errors realistic and licence-clean.
6. **Why qPilot.** Autonomy levels, cards, records and the robustness engine are exactly a grading harness; the classroom worksheet already exists.
7. **Risks.** Instructor adoption is slow and unpaid (no willingness-to-pay evidence); courses are wet-lab-centred. Confidence: medium.

Also worth noting but not a stand-alone discovery (already roadmap headlines): the "methods text from the decision log" should be generated in the Clin Chem/JXB/Plant Cell/eLife "journal pack" forms described above; the "censored non-detects" and "Cq cut-off" cards should quote the MIQE 2.0 LLOQ/LOD-vs-efficiency table so the cut-off is computed, not assumed.

---

## 4. Data, libraries, standards, licences found

| Item | What it is | URL | Licence / access |
|---|---|---|---|
| MIQE 2.0 (Bustin et al. 2025) | 53-item checklist, recommendations | https://academic.oup.com/clinchem/article/71/6/634/8120574 (PDF mirror https://www.gene-quantification.de/bustin-et-al-miqe-2.0-clinical-chemistry-2025.pdf) | Paywalled article; checklist in editable Supplemental Table 1 |
| MIQE 2009 | 85-item E/D checklist | https://www.gene-quantification.de/miqe-bustin-et-al-clin-chem-2009.pdf | Free PDF |
| Clin Chem MIQE checklist .docx | 44-item journal form | https://static.primary.prod.gcms.the-infra.com/static/site/clinchem/document/MIQE%20Checklist.docx?node=1642b8670c419e947ad2 | Journal document |
| MIQE précis (2010) | minimal reporting set, reference-gene paper rules | https://doi.org/10.1186/1471-2199-11-74 (PMC2955025) | CC BY |
| RDML 1.3 schema | XSD, change log, example | https://rdml.org/files/rdml/RDML_v1_3_REC.xsd ; https://rdml.org/files/rdml/changes_v1.2_to_v1.3.txt | Licence not stated on page |
| RDES v1.0 | TSV raw-data export spec | https://rdml.org/rdes.html | MIT (per page) |
| rdmlpython | RDML library, LinRegPCR, melt analysis | https://github.com/RDML-consortium/rdmlpython | MIT |
| RDML-Tools | web apps (Edit/Validate/LinRegPCR) | https://github.com/RDML-consortium/RDML-Tools | GPL-3.0 (do not bundle) |
| RDML R package | R handling of RDML ≤1.2 | doi:10.1093/bioinformatics/btx528 | licence not verified |
| RDML-Ninja / RDMLdb | editor (GPL) and repository | https://doi.org/10.1186/s12859-015-0637-6 ; http://rdmldb.org/ | GPL; repository online but cert mismatch |
| RDML-compliant instruments/software lists | vendor export support | https://rdml.org/instruments.html ; https://rdml.org/software.html | public |
| GEO RT-PCR submission template | xlsx with Metadata/Matrix_non-normalized/Matrix_normalized/Fold_Change | https://www.ncbi.nlm.nih.gov/geo/info/geo_rtpcr.html | public |
| GEO E-utilities | counts/queries (db=gds) | https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gds&term=... | public API |
| BioStudies API | search/submission | https://www.ebi.ac.uk/biostudies/api/v1/search?query=qPCR | public |
| Zenodo REST API | records/search/deposit | https://zenodo.org/api/records?q=qPCR | public; deposit needs token |
| Dryad API | search | https://datadryad.org/api/v2/search?q=qPCR | public; deposits CC0 |
| NIH DMS Policy | policy text | https://grants.nih.gov/policy-and-compliance/policy-topics/sharing-policies/dms/policy-overview | public |
| RO-Crate | packaging spec | https://www.researchobject.org/ro-crate/ | spec open; tool licences not checked |
| ISA framework | ISA-Tab/JSON | https://isa-tools.org/ | open source (licence not stated) |
| ISO 20395:2019 | qPCR/dPCR performance evaluation | https://www.iso.org/standard/67893.html | paid, 50 pages, under revision |
| SuperPlots paper + recipes | figure convention | https://doi.org/10.1083/jcb.202001064 | CC BY-NC-SA |
| SuperPlotsOfData | Shiny app | https://github.com/JoachimGoedhart/SuperPlotsOfData | GPL-3.0 |
| superviolin | Python violin SuperPlots | https://pypi.org/project/superviolin/ | MIT |
| HTqPCR | Bioconductor Ct analysis | https://bioconductor.org/packages/release/bioc/html/HTqPCR.html | Artistic-2.0 |
| pcr (R) | ΔΔCt package | https://cran.r-project.org/web/packages/pcr/index.html | archived from CRAN 2025-11-07; licence unverified |
| Drude 2026 audit | data + preregistration | https://doi.org/10.1186/s41073-026-00188-0 ; osf.io/9zp5m | CC BY |
| Hampton 2025 | R code for ANCOVA/simulations | https://doi.org/10.1016/j.bbrep.2025.102356 | CC BY-NC-ND (paper) |
| Ruiz-Villalba 2021 | Cq misuse taxonomy | https://doi.org/10.3390/life11060496 | CC BY |
| Dijkstra 2014 | 179-paper screening table (xlsx) | https://pmc.ncbi.nlm.nih.gov/articles/PMC5528534/ | free |
| Thermo Real-time PCR handbook | vendor teaching PDF | https://www.thermofisher.com/content/dam/LifeTech/global/Forms/PDF/real-time-pcr-handbook.pdf | vendor copyright |
| Müller & Tiret 2026 | LinRegPCR + spreadsheet teaching protocol | https://doi.org/10.21769/bioprotoc.5729 | CC BY-NC |
| Kubista 2026 | standard-curve tutorial | https://doi.org/10.3390/ijms27062904 | CC BY |
| Stanford PAN / Emory EIGC | core price lists | https://pan.stanford.edu/rates.html ; https://www.cores.emory.edu/eigc/services/index.html | public |

---

## 5. Open questions and what could not be verified

- Forum-level reviewer comments (Reddit r/labrats, ResearchGate, Biostars, Biology StackExchange, PubPeer) — all blocked this turn; the reviewer-question ranking in D2 is literature-derived.
- Full texts of Bustin & Wittwer 2026 (recommendations), Bustin 2013 Nat Methods, Bustin & Nolan 2017, Taylor 2019 — paywalled or redirect-walled; abstracts only.
- Journals with possible MIQE requirements not verified: J Mol Diagn (Cloudflare), Endocrine Society, J Dairy Sci, "animal", CCLM; EMBO Journal and JCB figure policies (Springer cookie wall / Cloudflare).
- Whether Clinical Chemistry will switch its author docx to MIQE 2.0 (as of 17 Oct 2026 it has not).
- ArrayExpress/BioStudies official stance on qPCR submissions (JS-only pages).
- Counts of qPCR records with raw curves on Zenodo/figshare/Dryad; figshare not queried (API needs POST).
- Licence of the RDML XSD itself; licence of the RDML R package and of the archived `pcr` package.
- Any ABRF survey of qPCR core practice after 2010; any public core SLA or complaint evidence.
- Courses: TATAA appears to have removed course pages; EMBL/EMBO qPCR course pages, Bio-Rad classroom kits, Labster and YouTube material not retrievable without search.
- The Eurosurveillance editorial on the Corman-Drosten retraction request exists (DOI confirmed) but its text did not render; not cited for content.
- Instructor willingness to pay or adopt, and any quantified student error rates — no evidence found.

---

## 6. Sources

1. Bustin SA, Ruijter JM, van den Hoff MJB, et al. MIQE 2.0: Revision of the Minimum Information for Publication of Quantitative Real-Time PCR Experiments Guidelines. Clin Chem 2025;71(6):634–651. https://academic.oup.com/clinchem/article/71/6/634/8120574 ; PDF https://www.gene-quantification.de/bustin-et-al-miqe-2.0-clinical-chemistry-2025.pdf
2. Bustin SA, et al. The MIQE Guidelines. Clin Chem 2009;55(4):611–622. https://academic.oup.com/clinchem/article/55/4/611/5631762 ; PDF https://www.gene-quantification.de/miqe-bustin-et-al-clin-chem-2009.pdf
3. gene-quantification.de MIQE page. https://www.gene-quantification.de/miqe.html
4. Bustin SA, Wittwer CT. RT-qPCR Methodological Standards and Reporting Practices. Clin Chem 2026;72(6):641. https://academic.oup.com/clinchem/article/72/6/641/8443183
5. Drude N, Baselly C, Gazda MA, et al. Reporting quality of qPCR methods in scientific publications. Res Integr Peer Rev 2026. https://doi.org/10.1186/s41073-026-00188-0 (full text via https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12961777/fullTextXML)
6. Hampton TH, et al. Analyzing qPCR data: Better practices to facilitate rigor and reproducibility. Biochem Biophys Rep 2025. https://doi.org/10.1016/j.bbrep.2025.102356 (PMC12666847)
7. Bustin SA. MIQE 2.0 and the Urgent Need to Rethink qPCR Standards. Int J Mol Sci 2025. https://doi.org/10.3390/ijms26114975 (PMC12154065)
8. Bustin SA. Improving the quality of quantitative PCR experiments: 15 years of MIQE. Mol Aspects Med 2024. https://doi.org/10.1016/j.mam.2024.101249
9. Bustin SA, et al. The need for transparency and good practices in the qPCR literature. Nat Methods 2013;10:1063–1067. https://doi.org/10.1038/nmeth.2697
10. Bustin S, Nolan T. Talking the talk, but not walking the walk. Eur J Clin Invest 2017. https://doi.org/10.1111/eci.12801
11. Dijkstra JR, van Kempen LC, Nagtegaal ID, Bustin SA. Critical appraisal of quantitative PCR results in colorectal cancer research. Mol Oncol 2014;8:813–818. https://pmc.ncbi.nlm.nih.gov/articles/PMC5528534/
12. Abdel Nour AM, et al. Five years MIQE guidelines: the case of the Arabian countries. PLoS One 2014. https://doi.org/10.1371/journal.pone.0088266
13. Ruiz-Villalba A, Ruijter JM, van den Hoff MJB. Use and Misuse of Cq in qPCR Data Analysis and Reporting. Life 2021;11:496. https://doi.org/10.3390/life11060496 (PMC8229287)
14. Ruijter JM, et al. Efficiency Correction Is Required for Accurate Quantitative PCR Analysis and Reporting. Clin Chem 2021;67:829. https://academic.oup.com/clinchem/article/67/6/829/6174590
15. Untergasser A, et al. Disclosing quantitative RT-PCR raw data during manuscript submission: a call for action. Mol Oncol 2023. https://doi.org/10.1002/1878-0261.13418 (PMC10158759)
16. Bustin SA, et al. MIQE précis. BMC Mol Biol 2010;11:74. https://doi.org/10.1186/1471-2199-11-74 (PMC2955025)
17. Taylor S, et al. A practical approach to RT-qPCR: Publishing data that conform to the MIQE guidelines. Methods 2010. https://doi.org/10.1016/j.ymeth.2010.01.005
18. Taylor SC, Mrkusich EM. The state of RT-quantitative PCR. J Mol Microbiol Biotechnol 2014. https://doi.org/10.1159/000356189
19. Taylor SC, et al. The Ultimate qPCR Experiment. Trends Biotechnol 2019. https://doi.org/10.1016/j.tibtech.2018.12.002
20. Derveaux S, Vandesompele J, Hellemans J. How to do successful gene expression analysis using real-time PCR. Methods 2010. https://doi.org/10.1016/j.ymeth.2009.11.001
21. Bustin SA, et al. Primer sequence disclosure: a clarification of the MIQE guidelines. Clin Chem 2011. https://doi.org/10.1373/clinchem.2011.162958
22. Udvardi MK, Czechowski T, Scheible WR. Eleven Golden Rules of Quantitative RT-PCR. Plant Cell 2008;20:1736–1737. https://pmc.ncbi.nlm.nih.gov/articles/PMC2518243/
23. Rieu I, Powers SJ. Real-Time Quantitative RT-PCR: Design, Calculations, and Statistics. Plant Cell 2009;21:1031–1033. https://pmc.ncbi.nlm.nih.gov/articles/PMC2685626/
24. Yuan JS, et al. Statistical analysis of real-time PCR data. BMC Bioinformatics 2006;7:85. https://doi.org/10.1186/1471-2105-7-85
25. Clinical Chemistry, General Instructions for authors. https://academic.oup.com/clinchem/pages/General_Instructions
26. Clinical Chemistry MIQE Checklist (.docx). https://static.primary.prod.gcms.the-infra.com/static/site/clinchem/document/MIQE%20Checklist.docx?node=1642b8670c419e947ad2
27. Journal of Experimental Botany, Editorial policies. https://academic.oup.com/jxb/pages/editorial-policies
28. The Plant Cell, General Instructions. https://academic.oup.com/plcell/pages/General-Instructions
29. PLOS ONE submission guidelines. https://journals.plos.org/plosone/s/submission-guidelines
30. BMC editorial policies. https://link.springer.com/brands/bmc/editorial-policies
31. Nature portfolio, Reporting standards and availability of data. https://www.nature.com/nature-portfolio/editorial-policies/reporting-standards
32. Nature Portfolio Reporting Summary (PDF). https://www.nature.com/documents/nr-reporting-summary-flat.pdf
33. eLife author instructions / journal policies. https://elife-rp.msubmit.net/html/elife-rp_author_instructions.html
34. Molecular Oncology author guidelines (checked for "PCR"). https://febs.onlinelibrary.wiley.com/hub/journal/18780261/about/author-guidelines
35. GEO, Recommendations for real time PCR submissions. https://www.ncbi.nlm.nih.gov/geo/info/geo_rtpcr.html
36. GEO, GEOarchive submission instructions. https://www.ncbi.nlm.nih.gov/geo/info/spreadsheet.html
37. GEO, Submitting data. https://www.ncbi.nlm.nih.gov/geo/info/submission.html
38. GEO Overview. https://www.ncbi.nlm.nih.gov/geo/info/overview.html
39. NCBI E-utilities count of GEO Series with DataSet type "Expression profiling by RT-PCR". https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gds&term=%22expression+profiling+by+rt+pcr%22%5BDataSet+Type%5D+AND+gse%5BEntry+Type%5D
40. BioStudies API search for qPCR. https://www.ebi.ac.uk/biostudies/api/v1/search?query=qPCR&pageSize=10
41. Zenodo API search for qPCR. https://zenodo.org/api/records?q=qPCR&size=10&sort=mostrecent
42. Dryad API search for qPCR. https://datadryad.org/api/v2/search?q=qPCR&per_page=10
43. NIH, Data Management & Sharing Policy Overview. https://grants.nih.gov/policy-and-compliance/policy-topics/sharing-policies/dms/policy-overview
44. RDML consortium: site https://rdml.org/ ; RDML 1.3 page https://rdml.org/rdml_v_1_3.html ; schema https://rdml.org/files/rdml/RDML_v1_3_REC.xsd ; change log https://rdml.org/files/rdml/changes_v1.2_to_v1.3.txt
45. RDES specification. https://rdml.org/rdes.html
46. RDML compliant instruments and software. https://rdml.org/instruments.html ; https://rdml.org/software.html
47. Lefever S, et al. RDML: structured language and reporting guidelines for real-time quantitative PCR data. Nucleic Acids Res 2009. https://doi.org/10.1093/nar/gkp056 (PMC2673419)
48. Ruijter JM, et al. RDML-Ninja and RDMLdb for standardized exchange of qPCR data. BMC Bioinformatics 2015;16:197. https://doi.org/10.1186/s12859-015-0637-6 (PMC4474546)
49. RDMLdb. http://rdmldb.org/
50. rdmlpython (GitHub, MIT). https://github.com/RDML-consortium/rdmlpython
51. RDML-Tools (GitHub, GPL-3.0). https://github.com/RDML-consortium/RDML-Tools
52. Untergasser A, et al. Web-based LinRegPCR. BMC Bioinformatics 2021;22:398. https://doi.org/10.1186/s12859-021-04306-1
53. Rödiger S, et al. Enabling reproducible real-time quantitative PCR research: the RDML package. Bioinformatics 2017. https://doi.org/10.1093/bioinformatics/btx528
54. Ruijter JM, et al. Evaluation of qPCR curve analysis methods for reliable biomarker discovery. Methods 2013. https://doi.org/10.1016/j.ymeth.2012.08.011
55. RO-Crate. https://www.researchobject.org/ro-crate/
56. ISA tools. https://isa-tools.org/
57. Weissgerber TL, et al. Beyond Bar and Line Graphs. PLoS Biol 2015;13:e1002128. https://doi.org/10.1371/journal.pbio.1002128
58. Lord SJ, Velle KB, Mullins RD, Fritz-Laylin LK. SuperPlots. J Cell Biol 2020;219:e202001064. https://pmc.ncbi.nlm.nih.gov/articles/PMC7265319/
59. SuperPlotsOfData (GitHub, GPL-3.0). https://github.com/JoachimGoedhart/SuperPlotsOfData
60. superviolin (PyPI, MIT). https://pypi.org/project/superviolin/ ; https://github.com/kynnemall/superviolin
61. pcr R package (CRAN, archived 2025-11-07). https://cran.r-project.org/web/packages/pcr/index.html
62. HTqPCR (Bioconductor, Artistic-2.0). https://bioconductor.org/packages/release/bioc/html/HTqPCR.html
63. Retraction notices (via Europe PMC, PUB_TYPE "Retraction of Publication"): FEBS Lett 2026 https://doi.org/10.1002/1873-3468.70426 ; Oncol Rep 2026 https://doi.org/10.3892/or.2026.9078 ; Oncol Rep 2025 https://doi.org/10.3892/or.2025.8882 ; Oncol Rep 2025 https://doi.org/10.3892/or.2024.8850 ; Med Sci Monit 2022 https://doi.org/10.12659/MSM.936562
64. Corrigendum, Mol Med Rep 2026. https://doi.org/10.3892/mmr.2026.14024
65. Retraction Watch, "1st retraction for ex-Pitt postdoc who admitted to doctoring data" (19 Jul 2016). https://retractionwatch.com/2016/07/19/1st-retraction-for-ex-pitt-postdoc-who-admitted-to-doctoring-data/ ; site search https://retractionwatch.com/?s=qPCR
66. Eurosurveillance editorial team. Response to retraction request and allegations of misconduct and scientific flaws. Euro Surveill 2021;26(5). https://doi.org/10.2807/1560-7917.ES.2021.26.5.2102041 (text not retrieved)
67. ISO 20395:2019. https://www.iso.org/standard/67893.html
68. Hancock D, et al. Introducing undergraduate students to real-time PCR. Biochem Mol Biol Educ 2010;38:309–316. https://doi.org/10.1002/bmb.20414
69. Harshitha R, Arunraj DR. Real-time quantitative PCR: A tool for absolute and relative quantification. Biochem Mol Biol Educ 2021;49:800–812. https://doi.org/10.1002/bmb.21552
70. Gunn KE, et al. J Microbiol Biol Educ 2013 https://doi.org/10.1128/jmbe.v14i2.542 ; Bauer P. Biochem Mol Biol Educ 2016 https://doi.org/10.1002/bmb.20967 ; Weinlander KM, et al. Biochem Mol Biol Educ 2010 https://doi.org/10.1002/bmb.20357 ; Birnbaum MJ, et al. Biochem Mol Biol Educ 2010 https://doi.org/10.1002/bmb.20433
71. Müller LA, Tiret L. Efficiency-Corrected Relative Quantification of qPCR Data Using LinRegPCR and a Spreadsheet-Based Workflow. Bio-protocol 2026. https://doi.org/10.21769/bioprotoc.5729
72. Kubista M, et al. Understanding the qPCR Standard Curve. Int J Mol Sci 2026;27:2904. https://doi.org/10.3390/ijms27062904
73. Thermo Fisher Scientific. Real-time PCR handbook (PDF). https://www.thermofisher.com/content/dam/LifeTech/global/Forms/PDF/real-time-pcr-handbook.pdf
74. Thermo Fisher Real-Time PCR Learning Center. https://www.thermofisher.com/us/en/home/life-science/pcr/real-time-pcr/real-time-pcr-learning-center.html
75. Bio-Rad PCR page with qPCR education videos. https://www.bio-rad.com/en-us/applications-technologies/what-real-time-pcr-qpcr?ID=LUSO3HC4S
76. gene-quantification.de home page. https://www.gene-quantification.de/
77. TATAA Biocenter qPCR technology and services pages. https://www.tataa.com/technologies/qpcr/ ; https://www.tataa.com/services/
78. Bitesize Bio site search "qPCR reviewer". https://bitesizebio.com/?s=qPCR+reviewer
79. Stanford PAN facility qPCR service and rates. https://pan.stanford.edu/section_html/QPCR/index.html ; https://pan.stanford.edu/rates.html
80. Emory Integrated Genomics Core services and rates. https://www.cores.emory.edu/eigc/services/index.html
81. Hunter T, et al. NARG 2009-2010 Study: Optimal Priming Strategies for cDNA Synthesis in Real-Time RT-qPCR. J Biomol Tech 2010;21(3 Suppl):S15 (PMC2918187)
82. PubMed search "MIQE", sorted by date (listing used to locate items 4–8, 72, 85–87). https://pubmed.ncbi.nlm.nih.gov/?term=MIQE&sort=date&size=50
83. Bustin SA, et al. When Two-Fold Is Not Enough: Quantifying Uncertainty in Low-Copy qPCR. Int J Mol Sci 2025. https://doi.org/10.3390/ijms26167796
84. Bustin SA, Wittwer CT. Fragile methods, fractured trust: rethinking scientific responsibility. Methods 2025. https://doi.org/10.1016/j.ymeth.2025.07.003
85. Yalçınkaya B. GeneQuantify: a web-based tool for qPCR gene expression and copy number variation analysis. Mol Cell Biochem 2026. https://doi.org/10.1007/s11010-026-05621-y
86. Europe PMC REST API (used for abstracts/full texts above). https://www.ebi.ac.uk/europepmc/webservices/rest/
87. Mirzaghaderi G. rtpcr: a package for statistical analysis of real-time PCR data in R (preprint 2024). https://doi.org/10.21203/rs.3.rs-4193266/v1
