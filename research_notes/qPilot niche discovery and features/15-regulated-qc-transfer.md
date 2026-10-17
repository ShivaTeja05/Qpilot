# 15. Regulated QC transfer: what clinical, IVD, GLP and GMP qPCR labs do that research labs do not, and what qPilot can honestly adapt (research use only)

Researcher note on method and limits. The shared WebSearch budget for this session was already exhausted when this task started, so every finding below comes from pages fetched directly by URL (standards bodies, FDA/EMA/ICH documents, journal articles on PMC, vendor pages), from the Europe PMC literature database used only to resolve specific papers I already knew of, and from PDFs downloaded and text-extracted locally. Forum evidence (Reddit, ResearchGate, LinkedIn) could not be collected: those sites block automated fetching and no search was possible. Where a claim rests on inference rather than a source, it is labelled as such. Numbered sources are in section 6 and cited inline as [n].

Terms used throughout (defined once): Cq = quantification cycle (also Ct). NTC = no-template control (water instead of sample). NRT = no-reverse-transcriptase control (RNA without RT; detects genomic DNA). NAC = no-amplification control. IPC = internal positive control (a spiked synthetic target that proves extraction/amplification worked). IQC = internal quality control (controls you run yourself every run). EQA/PT = external quality assessment / proficiency testing (blind samples sent by a third party; your result is scored against peers). LoB/LoD/LoQ = limit of blank / detection / quantitation. LLOQ/ULOQ = lower/upper limit of quantitation. ISR = incurred sample reanalysis (re-measuring real study samples to prove reproducibility). Bridging = showing that a changed component (reagent lot, instrument, calibrator) gives equivalent results. Commutability = whether a reference material behaves like real samples across methods. Westgard notation: "1_3s" means one control value beyond ±3 SD; "2_2s" two consecutive beyond the same ±2 SD; "R_4s" two controls in one run differing by >4 SD; "4_1s" four consecutive beyond the same ±1 SD; "10x" ten consecutive on one side of the mean.

---

## 1. How this corner of the niche works

### 1.1 Roles and settings

Four kinds of lab run qPCR under rules that research labs do not have:

- **Clinical diagnostic labs** (hospital microbiology/virology, reference labs). In the US they are regulated under CLIA and inspected by CAP; internationally they are accredited to ISO 15189:2022 ("requirements for quality and competence in medical laboratories", valid from 30 Dec 2022) [19]. Their qPCR is either an FDA-cleared/CE-IVD kit run exactly per the instructions for use (IFU) or a laboratory-developed test (LDT) they validated themselves [3].
- **GLP bioanalytical labs** (CROs such as BioAgilytix, Charles River, Labcorp; pharma bioanalysis groups). They measure drug or vector in animal and human samples for regulatory submissions, under OECD/FDA GLP, with LIMS such as Thermo Watson [33]. For gene therapy they run biodistribution, shedding, vector copy number (VCN) and transgene-expression qPCR/ddPCR assays [43][52].
- **GMP QC labs** (cell and gene therapy manufacturers). They run release and potency assays per ICH Q2(R2) validation, with system-suitability rules and control charts expected by FDA's 2023 draft potency guidance [49].
- **CGT research and translational labs** (academic and biotech) doing the same measurements (VCN, AAV titre, biodistribution) before any GLP transfer. They are the "GLP-lite" audience: 4,487 gene, cell and RNA therapies were in development at Q2 2026, including 2,217 gene therapies (49%) and 940 non-genetically-modified cell therapies, with 1,896 open gene-therapy clinical trials [77].

The people: medical technologists and lab directors (clinical); bioanalytical scientists, study directors and QA units (GLP); QC analysts (GMP); and in research, the same postdoc or core-facility manager who already uses qPilot.

### 1.2 The clinical workflow, step by step (the practice to transfer)

1. **Every run carries typed controls.** A positive control and a negative control must be in every amplification run; quantitative assays carry a negative control and two positives at different levels (high near the top of the range, low near the detection limit, roughly 5–10× LoD); an extraction control goes through extraction; an internal (inhibition) control is added where inhibition is a known cause of false negatives; the negative control is placed last in pipetting order [3]. CDC's SARS-CoV-2 panel: "Always include a negative template control (NTC) and the appropriate positive control (nCoVPC) in each amplification and detection run", an extraction control (HSC) in every extraction batch, RNase P in every clinical sample, and "Test all positive controls prior to running diagnostic samples with each new kit lot" [5].
2. **Run validity is decided by explicit rules before any sample is read.** CDC: NTC must show no curve crossing threshold ("Invalidate the run and repeat"), nCoVPC must be positive for N1, N2 and RP at <40.00 Ct, HSC negative for N1/N2 and positive for RP <40 Ct; "If any of the above controls do not exhibit the expected performance ... Invalidate the run and re-test" [5]. Thermo TaqPath (interpreted automatically by the "COVID-19 Interpretive Software"): positive control viral targets valid at Cq ≤37 and its MS2 >37; negative control MS2 ≤32 and viral targets >37; clinical sample MS2 ≤32 (unless a viral target is positive); "All control wells must pass for the real-time RT-PCR plate to be considered valid" [4]. Roche cobas 6800/8800: one negative and one positive control per batch; "The batch is valid if no flags appear for any controls. If the batch is invalid, repeat testing of the entire batch"; a valid batch may still contain invalid samples [6]. BioFire: two in-pouch process controls with Tm windows (80.3–84.3 °C RNA process control; 73.8–77.8 °C PCR2 control); controls are reported Passed/Failed/Invalid; a Failed run is repeated with a new pouch [7].
3. **Per-sample validity** uses the internal control: a sample with all targets negative and the IPC/RNase P negative is "INVALID — repeat by re-extracting the original sample" [4][5].
4. **Control values are charted and judged with statistical rules.** A temporary target for a control is set from at least 20 measurements, ideally on 20 separate days (or ≤4 per day over ≥5 days), with limits as multiples of SD; the temporary target is used for 3–6 months or 20–30 runs and then recalculated; the worked example is a low-positive HSV-1 control with final target Cq 37.90 ± 1.60 [3]. Levey-Jennings rejection at ±2 or ±3 SD; at ±2 SD "an expected run failure rate of about 5%"; Westgard multirule "recommended, especially when there are two or more control measurements per run" [3]. The Westgard rules themselves: 1_2s warning; 1_3s, 2_2s, R_4s (within-run only), 4_1s, 10x rejection; extended rules 8x/12x, 2of3_2s, 3_1s, 6x/9x; 4_1s and 10x are "often ... used across runs" and across materials [1]. Baseline for a Levey-Jennings chart: at least "20 measurements over at least 10 days" [2].
5. **Monthly and periodic review.** CLIA requires QC review against lab rules before results are reported and documented corrective action; CAP requires QC data review at least monthly by the director or designee; calibration verification at least every 6 months and after reagent lot changes unless shown unnecessary; AMR (measuring-range) validation every 6 months and after lot changes [3].
6. **Lot and shipment changes are qualified.** Controls must be run "to qualify each shipment or lot-to-lot change of reagents" and after major maintenance [3]; CLSI EP26-Ed2 (2022) gives a two-stage protocol: stage 1 decides the medically acceptable difference and the acceptable risk of a wrong conclusion once per analyte; stage 2 tests each new lot against the current lot on patient samples [20].
7. **EQA/PT closes the loop.** QCMD serves over 2,000 participants in 120+ countries and is ISO 17043 accredited [9]; UK NEQAS Microbiology reports about 1,800 participants and 190 distributions [12]; INSTAND reports 380 EQA schemes and 12,000 participants [13]; CAP's PT spans 16 disciplines [14]. A QCMD individual report shows, per sample, the consensus log value (outliers removed), n, and the min–max range, and scores each lab 0–3 by how many SDs it sits from its assessment-group consensus (0 within 1 SD, 1 between 1–2 SD, 2 between 2–3 SD, 3 beyond 3 SD); it also tracks "duplicate sample performance over time" (your variation vs overall mean variation and SD across challenges) [10].

### 1.3 The GLP bioanalytical workflow (the second practice to transfer)

Method validation precedes sample analysis and is documented in a validation report; each sample-analysis run has acceptance criteria; failed runs are repeated; ISR re-measures a subset of real samples. ICH M10 (2022) is the reference text for small molecules and biologics, but its scope is explicitly "ligand binding assays (LBAs) and chromatographic methods" [44]; it does not cover PCR. For exploratory studies not submitted for regulatory decisions, M10 says "applicants may decide on the level of qualification that supports their own internal decision making" [44] — this is the exact posture of a research tool. Because there is no qPCR-specific regulation, the field runs on consensus papers: the Global CRO Council states that use of qPCR/ddPCR "has outpaced regulatory guidance, and there are no regulatory guidelines for ddPCR" and issued harmonised validation parameters [51]; the WRIB white papers repeat the consensus yearly [52][53]; Ma, Bell and Loker (2021) give the most complete numeric criteria (section 1.8, question 3) [43].

### 1.4 Standards and guidance (what each one actually says, as far as fetched)

| Document | Status | What it contributes |
|---|---|---|
| Westgard multirules and Levey-Jennings lessons [1][2] | Free web lessons (Westgard QC) | Rule definitions, N=2/N=4 use, 20-measurement baseline, within-run vs across-run application |
| Burd 2010, Clin Microbiol Rev [3] | Open access review of CLIA/CAP practice | Controls per run, targets from 20 runs, Westgard for molecular, lot qualification, calibration verification, LoD study design (60 data points, probit, C95), precision over 20 days, accuracy with 40+ specimens |
| CLSI MM03-Ed3 (2015) [25], MM06-Ed3 (2026) [21], MM17-Ed2 (2018) [24], EP17-A2 (2012, reaffirmed 2017) [23], EP23-Ed2 (2023) [22], EP26-Ed2 (2022) [20]; EP05 page not retrievable | Paid (free to members) | Molecular methods, quantitative molecular methods (calibration, QC, PT, LoQ), multiplex validation (error-based approach), detection capability (LoB/LoD/LoQ), risk-based QC plans (IQCP), reagent lot change acceptance |
| ISO 15189:2022 [19] | Paid (€63 at EVS) | Medical lab competence; clause text not retrievable here |
| ISO 20395:2019 [18] | Paid (€241) | "Requirements for evaluating the performance of quantification methods for nucleic acid target sequences — qPCR and dPCR"; characteristics: precision, linearity, LoQ, LoD, trueness, robustness; excludes sampling and sample processing |
| ICH M10 (2022) [44] | Free | Acceptance numbers (below); scope excludes PCR |
| ICH Q2(R2) (2023) [45] | Free | Validation characteristics; linearity needs ≥5 concentrations; DL = 3.3σ/S, QL = 10σ/S; S/N 3:1 (DL) and 10:1 (QL) |
| ICH S12 (FDA final May 2023) [47] | Free | qPCR/dPCR "considered the standard" for biodistribution; spike-and-recovery in each tissue/biofluid; report performance parameters (sensitivity, reproducibility) |
| FDA Long Term Follow-Up (2020) [46] | Free | qPCR LoQ "<50 copies/μg genomic DNA" with 95% confidence; triplicates per tissue, one spiked |
| FDA shedding studies (2015) [48] | Free | Assays "qualified", not validated; LOD and LOQ; specificity; one-time spike recovery per matrix; parallel spiked sample when diluting |
| FDA draft Potency Assurance (Dec 2023) [49] | Draft | Pre-defined sample and system suitability; "An assay run should be invalidated if suitability criteria are not met"; control-chart trending of control samples over time; qualify replacement reference-material lots |
| EMA GTMP guideline (EMA/CAT/80183/2014) [50] | Free | VCN LoD/LoQ "preferably as vector copy number/genome" (integrating) or "copy number/µg host cell DNA" (episomal); NAT prone to cross-contamination so negative/positive controls must be indicated |
| 21 CFR Part 11 [35][36][37] | Regulation | Audit trail wording; signature manifestation (name, date/time, meaning); two-component e-signatures |
| 21 CFR 809.10(c)(2)(i) [38]; FDA RUO/IUO guidance 2013 [39]; EU IVDR Art. 1(3)(a) [40] | Regulation/guidance | The exact RUO statement and what disqualifies RUO status |
| OECD GLP No. 17 (computerised systems) | Not retrievable (HTTP 403) | Gap |

### 1.5 Instruments, software and formats

- **Clinical interpretation middleware.** UgenTec FastFinder (company now "Velsera" [31]) has modules Workflow, Analysis, Insights, Studio, QC and Genotyper; QC offers "Levey-Jennings charts", "preset Westgard rules" with alerts, and cross-contamination detection "based on proximity, trends, and positivity rates"; Analysis captures "all assay logic in an Assay Plugin", claims algorithms "100% reproducible" with accuracy "well above 99%", "full audit trails", and customer claims of a 50% reduction in interpretation time (Aalst) and a target of 15 seconds per plate (CHU Amiens); it is positioned as compatible with "any qPCR device" [26][27][28]. For pharma/CRO it sells "QC dashboards" and "Automation of SOPs as software rules" with CellCarta, Charles River and GSK logos, but names no Part 11/GLP features on that page [29]. For IVDR it sells document templates and "a full validation package" [30]. No pricing is published [31]. Seegene Viewer auto-interprets Seegene multiplex assays (MuDT), shows colour-coded tables beside raw curves and Ct for review and QC, and exports to a LIS; supported instruments AB7500 Fast Dx, CFX96/CFX96 Dx/CFX Opus 96 Dx [32]. Roche cobas 6800/8800 software "assigns test results for all tests" and flags controls [6]. BioFire software melts and calls automatically and prints a run report with Passed/Failed/Invalid controls [7]. PCR.AI/Diagnostics.ai pages returned HTTP 403 (gap).
- **Research-instrument software.** Thermo's QuantStudio Design & Analysis user guide opens with "For Research Use Only. Not for use in diagnostic procedures." [41]. The QuantStudio 6/7 Flex software has a separately licensed "Security, Audit, and Electronic Signature (SAE)" module: role-based security, auditing of library items and user actions, and e-signatures that can be required before a run or print, with the warning that disabling security "inactivates audit and electronic signature functions; however, no audit record is generated to indicate that audit and electronic signature functions are disabled" [42]. Bio-Rad sells a CFX qualification plate: "1-click pass/fail performance result" with "2-fold discrimination with 99.7% confidence level and single product melt peak criteria" [81]. Bio-Rad's PrimePCR control assays publish research-grade control rules: positive PCR control Cq ≥30 = poor PCR performance; between-sample ΔCq >1 = samples differ in inhibition; RT control Cq ≥30 = poor RT; gDNA control Cq <35 = gDNA contamination; RNA-quality ΔCq(RQ2−RQ1) >3.0 = degradation; ΔΔCq 1–2 slight-to-moderate, >2 significant effect [80].
- **Clinical QC data management.** Bio-Rad UnityWeb/Unity Real Time (peer comparison, "advanced charts, supervisor review, and comprehensive audit trails") and QCNet reports [34]; none mentions PCR.
- **GLP LIMS.** Thermo Watson LIMS: study templates and sample manifests, chain of custody, freeze/thaw tracking, "sets acceptance standards, and flags results outside the range" for PK/ADA, ISR, validation and sample-analysis reports, CDISC/SEND/SDTM output, integrations with Sciex Analyst and Chromeleon, 21 CFR Part 11 and FDA/EMA BMV support, in use "for more than two decades"; PCR and gene therapy are not mentioned [33].
- **Formats.** RDML 1.3 already types samples as unkn, ntc, nac, std, ntp, nrt, pos, opt; a sample can be flagged interRunCalibrator or calibratorSample and carry a quantity with unit for standard curves; targets carry type ref/toi, amplificationEfficiency and detectionLimit (copies/µL); a run carries instrument (free text), dataCollectionSoftware, runDate, pcrFormat and thermalCyclingConditions; there is no dedicated field for reagent lot, plate barcode or instrument serial — only free-text description and sample annotation property/value pairs [78]. Clinical LIS interfaces (HL7, ASTM/LIS2) could not be verified from fetched pages (gap).

### 1.6 Money and time

ISO 20395 costs €241 [18]; CLSI documents are free to members and paid otherwise [20][21]. QCMD/NEQAS/INSTAND/CAP are subscription schemes (prices not fetched). Clinical baselines cost 20 runs; calibration verification every 6 months; QC review monthly [3]. A GLP qPCR validation per Ma et al. uses at least two operators, multiple instruments of one model, at least two lots of assay components, five plates over a minimum of 3 days, each with a standard curve and four QC sets in duplicate [43]. BioAgilytix reports 800+ assays developed and 5,000,000+ tests reported per year company-wide, and 620+ assays and 160+ sponsors in gene therapy [54][55]. FastFinder pricing is not published; the local-market inference is that it is enterprise-licensed (not verified).

### 1.7 Where decisions are made, what good looks like, what goes wrong

Decisions in a clinical run are binary and pre-declared (valid/invalid; report/repeat), made by software against IFU rules and reviewed by a technologist; the lab director signs off QC monthly [3][4][6]. "Good" is a run whose controls sit inside their windows and on a flat Levey-Jennings line, a lot change that passes its EP26 comparison, and an EQA score of 0. What goes wrong: in the BioFire prospective study 10/1,621 completed runs (0.6%) failed pouch controls and 2/1,623 (0.1%) did not complete [7]; in an HPV lab 8 of 466 batches (1.7%) were out of control, attributed to technician error and cross-contamination [15]; at ±2 SD limits about 5% of good runs are falsely rejected [3]. In GLP, a failed standard curve or QC set means the plate is repeated, and a second consecutive failure escalates to the Study Director [43].

### 1.8 Key questions answered

#### Q1. Clinical QC practice: rules per run, control charts, Westgard sets for qPCR, EQA and inter-lab variation, rejection rates

Takeaway. Clinical qPCR is gated by typed controls with explicit Cq/Tm windows set by the IFU or by the lab's own 20-run baseline; charts and Westgard multirules are the documented norm; EQA shows that even accredited labs disagree by 0.4–1.5 log10 (IQR) and up to 3–5.7 log10 (range) on the same quantitative sample.

Cited findings.
- Controls per run (positive, negative, two positives for quantitative, extraction, internal), placement of negative control last, low positive near 5–10× LoD [3].
- Target from ≥20 measurements over 20 days; ±2 SD limits give ~5% false rejection; Westgard multirule recommended with ≥2 controls per run; the listed rules are 1 beyond 3 SD, 2 consecutive beyond 2 SD same direction across runs, and one above +2 SD with another below −2 SD [3].
- Westgard rule definitions, warning vs rejection, within-run (1_3s, 2_2s, R_4s) vs across-run (4_1s, 10x) application; computer implementations should let users pick rejection rules individually [1]; 20 measurements over ≥10 days to build a chart [2].
- CDC run-validity table (NTC no crossing; nCoVPC all <40 Ct; HSC RP <40; invalidate and re-test) and "Test all positive controls ... with each new kit lot" [5].
- TaqPath Ct cutoffs (PC viral ≤37, MS2 ≤32 for NC and samples, NC viral >37; RNase P NC >33, samples ≤33) and automatic validation by the interpretive software [4].
- cobas batch validity by control flags; valid batch may contain invalid samples [6].
- BioFire Tm windows for process controls; Passed/Failed/Invalid; external QC "with each new lot and shipment of reagents, at a minimum"; 0.6% control-failure rate, 0.1% incomplete runs [7].
- A published Levey-Jennings application in a PCR lab charted the daily positive rate (not Cq), set limits from the first 20 batches, applied 1_2s (warning), 1_3s and 2_2s, and found 8/466 batches out of control [15]. A prenatal lab listed 1_3s, 2_2s, 4_1s, R_4s and 10x as rejection rules with 1_2s as warning, limits from 20 consecutive daily runs (FISH, not qPCR) [16]. O'Brien and Finn applied SPC to qualitative assays via mutation-frequency confidence intervals (e.g., 242 samples to detect a 20% deviation from a 44% prior) [17].
- CAP viral-load surveys (554 labs, 2013): interquartile ranges in log10 copies/mL of 0.39–0.64 (CMV), 0.56–1.05 (BKV), 0.59–1.46 (adenovirus), 0.63–0.98 (HHV-6); total ranges up to 3.35 (CMV), 3.71 (BKV), 5.66 (ADV), 4.29 (HHV-6); WHO IU calibration narrowed CMV range to 1.52–2.90 but left IQR unchanged; variability associated with calibrators, extraction and manual handling [8].
- QCMD HIV RNA 2018 challenge: 259 participants from 35 countries; sample consensus 2.382 log copies/mL with range 1.643–3.401 (n=214), 3.727 with range 3.179–5.911 (n=218), 2.915 with range 1.875–5.504 (n=221); scoring 0–3 by SD bands; duplicate-sample performance tracked over time (overall SD about 0.18–0.23 log) [10].
- QCMD: ISO 17043, >2,000 participants, >120 countries; publication list of 18-year enterovirus QC and SARS-CoV-2 EQA papers [9][11]. UK NEQAS ~1,800 participants, 190 distributions [12]; INSTAND 380 schemes, 12,000 participants [13].
- FDA draft potency guidance: pre-defined system suitability (reference materials, positive and negative controls), run invalidated if not met, control-chart trending over time [49].

Inferences.
- The "rules" are a small, finite vocabulary (control type × metric × window × action) that is identical across vendors; it can be encoded once as a rule pack keyed to RDML sample types.
- A ±2 SD rule alone is unacceptable for a research tool (5% false alarms); the multirule set with 1_2s as warning is what to copy.
- Inter-lab spreads of 1.5–3.5 log10 among accredited labs mean that a research lab with no controls at all has no way to know where it sits; the honest claim is "consistency with your own baseline", not "accuracy".

Gaps. No source found giving overall clinical qPCR run-rejection rates beyond the BioFire 0.6% and HPV 1.7% figures. CAP checklist text, ISO 15189 clauses and QCMD scheme-level statistics were not retrievable.

#### Q2. Software: what FastFinder/PCR.AI/Seegene/cobas/QuantStudio Dx do, pricing and lock-in, what research users envy

Takeaway. Clinical software earns its keep with four things research software lacks: assay-specific validity rules executed automatically, control charting with Westgard alerts, cross-contamination detection from plate geometry, and audit trails; all are closed, per-assay-plugin, IVD-positioned products with unpublished prices.

Cited findings.
- FastFinder modules and claims (Levey-Jennings, preset Westgard rules, cross-contamination by proximity/trends/positivity, assay plugins, >99% accuracy, 50% interpretation-time reduction, 15 s per plate target, "any qPCR device", pharma/CRO positioning with GSK/Charles River/CellCarta, IVDR validation package); no pricing, no explicit regulatory class on fetched pages; UgenTec "is now Velsera" [26][27][28][29][30][31].
- Seegene Viewer: auto-interpretation, raw curves and Ct beside colour-coded calls for QC, LIS export, instruments listed [32].
- cobas software assigns results and flags; batch validity rule [6]. BioFire automated melt analysis and control fields [7]. TaqPath interpretive software validates runs from positive/negative control performance using published Ct cutoffs [4].
- QuantStudio research software is labelled RUO; the SAE module is a separately licensed add-on providing security, auditing and e-signatures; disabling security silently disables audit [41][42].
- Bio-Rad Unity Real Time offers supervisor review and audit trails for clinical QC; no PCR mention [34].
- Watson LIMS: acceptance-criteria evaluation, ISR, Part 11, validation reports; no PCR mention [33].
- A machine-learning qPCR interpretation paper (734 results; visual reading left 14.8% "doubtful") shows the clinical appetite for automated calling with kappa >0.83 [82].

Inferences.
- Lock-in is structural: validity rules live in vendor plugins and interpretive software versions (TaqPath lists software versions per IFU revision [4]); none exports rules in an open format.
- What research users would plausibly envy (inference; no forum data): one-click run validity; a control chart that just appears; "which plate drifted" answers; audit of who changed a threshold. These are the features D1, D2 and D5 below adapt.

Gaps. PCR.AI (403), Rotor-Gene AssayManager and CFX Maestro Dx SE pages (404/not found), Epic Beaker/Orchard interfaces, HL7/ASTM specifics, pricing, and forum evidence of envy were not obtained.

#### Q3. Method validation for qPCR in GLP/CRO settings: parameters, criteria, templates, duration, the Excel reality, guidance

Takeaway. There is no regulatory validation standard for qPCR; GLP labs use a consensus set (Ma et al. 2021; GCC 2022; WRIB) built on FDA's 50 copies/µg gDNA LoQ and ±25%/±45% accuracy and precision bands, run as a 5-plate, 3-day, 2-operator, 2-lot design, with explicit plate acceptance rules.

Cited findings (Ma, Bell and Loker 2021, Table 4 and text [43]).
- Design: ≥2 operators, multiple instruments of the same model, ≥2 lots of assay components; 5 plates over ≥3 days; each plate one standard curve and four QC sets in duplicate in 1,000 ng matrix DNA; bridging validation when sample prep, standard-curve range or instrument model changes.
- Standard curve: R² ≥0.980, efficiency 90–110%; ≥7 non-zero levels in validation and ≥8 in sample runs; standards Ct %CV ≤2.0% per duplicate; back-calculated within ±25% (±45% between LLOQ and QC-UL); inter-assay Ct CV ≤3.0%.
- LoD: lowest standard with Ct ≤40 in all replicates across five runs (cannot be below 3 copies by Poisson); LLOQ: positive in all replicates of all five runs, Ct %CV ≤2.0%, RE within ±45%, and ≤50 copies/µg host gDNA for biodistribution; ULOQ Ct %CV ≤2.0%, RE ±25%.
- QC levels 10² (UL), 10³ (L), 10⁵ (M), 10⁷ (H), optional 10⁸; per run ≥50% of QCs per level and ≥67% overall within CV ≤25% and RE ±25% (≤45%/±45% at QC-UL); intra/inter-assay mean CV ≤25%, mean RE ±25%.
- Specificity: all naive DNA from ≥3 animals (≥1 male) BLOD. Matrix effect: mean CV ≤25%, RE ±25%. Recovery 30–80% typical. Freeze–thaw up to 3 cycles. Clinical vector stability 30–170% of time zero. ISR ≥67% within ±45%.
- Run acceptance: standards in duplicate, NTCs in triplicate with ≥2/3 BLOD; ≥2 QC sets per plate; pretest/vehicle controls BLOD; spiked third well must recover >55% else reanalyse at ¼–1/10 input; if the standard curve or QCs fail the run is repeated; second consecutive failure escalates to the Study Director; reportable results within curve range with Qty %CV ≤25%.
- Sample analysis: triplicate wells, first two averaged, third spiked; blood at ~100 ng; above-ULOQ retest at 1/100–1/1,000 with matrix DNA top-up; report BLOD/BLOQ and single- vs double-stranded copies.
- qPCR vs ddPCR: qPCR ULOQ ~10⁸ copies/reaction vs ~10⁵ for QX200; ddPCR ~7 h vs <1 h; authors judge ddPCR "currently less suitable for biodistribution and shedding, though it is well suited to viral vector titration".
- Regulatory basis cited: FDA LTFU 2020 (LLOQ ≤50 copies/µg with 95% confidence), FDA shedding 2015, FDA BMV 2018 "partially applicable", EMA GTMP 2018 (EMA requires qPCR validation; FDA has not), 21 CFR Part 58, MIQE.

Other cited findings.
- FDA LTFU: "demonstrated limit of quantitation of <50 copies/μg genomic DNA ... with 95% confidence"; triplicates per tissue with one spiked replicate; individual animal data in the report [46].
- ICH S12: qPCR/dPCR "considered the standard"; spike-and-recovery per tissue/biofluid during development; describe performance parameters (sensitivity, reproducibility) [47].
- FDA shedding: "While the Agency does not expect shedding assays to be validated, the assays should be qualified"; LOD and LOQ; specificity; one-time percent recovery of a spiked reference standard per matrix; spiked parallel sample when diluting for inhibition [48].
- EMA GTMP: VCN LoD/LoQ units; controls must be indicated [50].
- GCC: "there are no regulatory guidelines for ddPCR"; consensus parameters and harmonised SOP approach [51].
- WRIB 2023: "consensus that previous recommendations of 50 copies/μg DNA" still apply; extraction efficiency by spiking a plasmid surrogate; units copies/µg gDNA for tissue; copies/cell only with a validated reference gene; run controls at known high and low copy numbers for dPCR; "no reference standard for a dPCR assay"; blinded proficiency testing with CROs using known positives/negatives; keep the same instrument through a study; platform switching needs cross-validation; RT assumed 100% efficient but reproducibility "can vary across kit lots, storage conditions, analysts, and equipment"; dPCR used 600 ng vs 3,200 ng input for a 4-plex CAR-T assay [52].
- ICH M10 numeric anchors (for context, not PCR): calibration standards within ±15% (±20% LLOQ), ≥75% of ≥6 standards; QCs ≥2/3 overall and ≥50% per level within ±15%; LBA ±20%/±25%; ISR ±20% (chromatographic) or ±30% (LBA) for ≥2/3 of repeats; scope limited to LBA and chromatography; exploratory studies may self-define qualification [44].
- ICH Q2(R2): ≥5 concentrations for linearity; DL = 3.3σ/S; QL = 10σ/S; S/N 3:1 and 10:1 [45]. CLSI EP17-A2 covers LoB/LoD/LoQ [23]. Burd: LoD with 60 data points over 5 days by probit (C95); precision over ≥20 days; accuracy with ≥40 specimens over ≥5 days [3].
- ISO 20395 characteristics: precision, linearity, LoQ, LoD, trueness, robustness [18].

Inferences.
- The qPCR validation "template" is effectively Ma Table 4; a research tool can implement it verbatim with every threshold editable and sourced.
- "How long validation takes": at least the 5 plates over ≥3 days of the core design plus stability runs (inference: 2–4 weeks of bench time; not sourced). "Excel reality": no fetched source documents it; the absence of PCR in Watson's feature list [33] is weak support that PCR data are reduced outside the LIMS.

Gaps. CRO white papers (Charles River 403; Labcorp/Eurofins not fetched), validation timelines, report templates and LIMS/Excel practice are unverified.

#### Q4. Evidence that research labs lack QC practice

Takeaway. Every audit of published qPCR work finds that the practices above are absent from the written record: efficiency reported in 1–18% of papers, reference-gene validation in 0.4–13%, RNA integrity in 7–22%, NRT controls essentially unused, NTC values hidden in supplements, and MIQE cited by 1–2%.

Cited findings.
- Two surveys of >1,700 publications found essential technical information "often not reported transparently"; reporting is better where MIQE is cited, but those papers are greatly outnumbered [56].
- Colorectal cancer qPCR papers (n=179, 2006–2013): 3% gave enough detail to assess reliability; 13% reported reference-gene validation; 18% reported efficiency; 92% used a single reference gene; 1% cited MIQE [57].
- Ten randomly selected 2014 Nature-titled papers: 0/10 reported RNA integrity, purity, RT conditions or efficiency; every one used "a single, unvalidated reference gene" with 2^−ΔΔCq [58].
- Arabian-country papers (n=461, 2009–2013): median 40% of 15 criteria; efficiency 24–30%; RNA integrity 22–25%; normalisation process 3%; 2% cited MIQE [59].
- 2021 genetics and plant-science papers (n=432): efficiency reported in 5%/8% (half without values); reference-gene stability M-value 0.4%; RNA integrity 7–10%; annealing temperature missing in 72–80%; software unreported in 48–59%; "no evidence" of NRT controls; NTC Cq values "often hidden in graphs, tables, or supplements"; 2 of 439 cited MIQE; authors call for "automated compliance tools" [60].
- 2007–2025 corpus (355 articles 2019/2024 plus 100 topic papers): RNA integrity reporting fell 22%→11%, reference-gene validation 13%→5%, efficiency 13%→1% [61].
- Bustin & Nolan 2017: most published RT-qPCR data "likely represent technical noise" [62]. MIQE 2.0 editorial: "Assay efficiencies are assumed, not measured"; reference genes "neither stable nor validated"; compliance "patchy ... entirely superficial" [64]. MIQE 2.0 itself recommends efficiency-corrected quantities with prediction intervals, detection limits and dynamic ranges, and asks manufacturers to enable raw-data export [63].
- Physical causes that the missing controls would catch: Ct values differed significantly among three DNA-extraction kit lots, so the authors recommend a standard curve per new lot [65]; 33 thermal cyclers in 18 UK labs: 9.4% showed substantial yield variation and RAPD repeatability was 88% in calibrated vs 63% in non-calibrated instruments [66]; 19 cyclers of 8 models under/overshot temperatures and varied between wells [67]; a "6-times difference between runs 2 and 5" in a six-plate experiment [69]; inter-run calibrators in one run were "systematically higher (0.77 cycles)", NRQs differed "on average, by 72%", a single IRC "increases the uncertainty ... by about 70%", three IRCs by 40% [68]; AAV8 reference material titres across 16 labs spanned "a two-log difference" attributed to PCR machines, primer/probe sources, reagent handling and plasmid-standard preparation [72].

Inferences.
- Research labs do run some controls (NTC is common) but do not act on them with rules, do not chart them, and do not record lots; the failure is procedural and tooling-related, not conceptual. Drude et al.'s call for automated compliance tools is a direct product signal.

Gaps. No source quantifies "% of research papers with no positive control". No survey of research-lab QC behaviour (as opposed to reporting) was found.

#### Q5. What a research-use tool can legally and honestly offer

Takeaway. RUO status is defined by intended use, not by features: a tool may compute run-validity rules, control charts, lot bridges and validation drafts for research, provided it makes no clinical-interpretation or clinical-performance claims and is not marketed to clinical labs; Part 11 vocabulary may be borrowed for features, never for a compliance claim.

Cited findings.
- 21 CFR 809.10(c)(2)(i): products in the laboratory research phase must bear "For Research Use Only. Not for use in diagnostic procedures." [38].
- FDA 2013 guidance: RUO covers "instrumentation, software, or other electrical/mechanical components under development" and products "intended for use in the conduct of non-clinical laboratory research"; "Software that is a stand-alone IVD product ... labeled for research or investigational use only, may be distributed for research or investigational use"; evidence against RUO status includes "performance claims, instructions for clinical interpretation, clinical information", suggestions that clinical labs can validate it as an LDT, "solicitation of business from clinical laboratories", and "inclusion of clinical interpretive information, discussion of clinical significance" [39].
- EU IVDR Article 1(3)(a) excludes "products for general laboratory use or research-use only products" unless specifically intended for in vitro diagnostic examination; recital 17: software for "general purposes, even when used in a healthcare setting" is not an IVD [40].
- Part 11 features that can be described without claiming compliance: 11.10(e) "secure, computer-generated, time-stamped audit trails to independently record the date and time of operator entries"; "Record changes shall not obscure previously recorded information" [35]; 11.50 signature manifestations: printed name, date and time, and "the meaning (such as review, approval, responsibility, or authorship)" [36]; 11.200 two distinct identification components [37].
- Comparable research tools: Thermo's QuantStudio D&A guide is RUO-labelled while still offering an SAE module [41][42]; Bio-Rad's qualification plate is sold for research "performance verification" [81].
- M10 explicitly leaves exploratory studies to self-defined qualification [44]; FDA says shedding assays should be "qualified", not validated [48].

Inferences.
- Safe wording: "Research-use method qualification summary", "run acceptance against lab-defined rules", "control trend"; unsafe wording: "validated", "Part 11 compliant", "IVD", "diagnostic result", "clinically acceptable".
- The honest differentiator is provenance: every rule has a named source and every threshold is lab-set.

Gaps. OECD GLP No. 17 text (computerised systems) not retrievable; no example disclaimers from Clarida/qbase+ fetched.

#### Q6. Cell and gene therapy research labs: VCN, biodistribution, potency, volume, complaints, software

Takeaway. CGT is large (4,487 programmes), its qPCR measurements are known to vary by orders of magnitude between labs because of calibrators and standards, regulators now expect control charts and reference-material qualification for potency assays, and the only published software evidence is of instrument vendors (QuantStudio, QX200/QX ONE, QIAcuity) and Part 11 LIMS that do not mention PCR.

Cited findings.
- Sector size: 4,487 therapies in development; 2,217 gene therapies (preclinical 1,332, Phase I 427, Phase II 387, Phase III 59 in Q2 2026); 940 non-GM cell therapies; 1,370 RNA therapies; 1,896 open gene-therapy trials; 46 approved gene therapies, 37 RNA, 76 non-GM cell therapies; 8 approvals in Q2 2026 [77].
- Inter-lab variability: AAV2 RSM, 16 labs, genome titre CI "less than 0.5 log" but raw replicate values 1.31×10⁹–1.27×10¹¹ vg/mL; variation attributed to reagents, equipment, operator technique [71]. AAV8 RSM, 16 labs, vg titre 4.6×10¹⁰–4.7×10¹² ("two-log difference"), raw CV roughly 114%; within-lab correlation 0.96 so variation is between institutions; recommends ddPCR and calibration to RSMs [72]. NIST lentiviral VCN study, 12 labs (4 qPCR, 7 ddPCR, 2 QIAcuity, 3 NGS): qPCR spread larger, one lab overestimated VCN 4 "by nearly 50%", attributed to "different calibrator DNAs and reference-gene choices"; dPCR consensus 4.02/1.96/0/2.85/0.882 with lab-effect SD 0.07–0.11 [73]. Chinese rAAV genome-copy reference material, 12 labs, dPCR only, RSD 10.2–10.6% [74]. AAV full/empty interlab: "PCR and ELISA showed poor reproducibility" [75]. Dobnik 2019: qPCR replicate spread 1.4–3.2× vs ddPCR 1.1–1.6×; qPCR CVs 6–42% vs ddPCR 2–12%; a 64× qPCR/ddPCR titre gap collapsed to 5.5× after re-valuing the standard by ddPCR [76].
- Requirements: FDA LTFU 50 copies/µg [46]; EMA VCN units and controls [50]; FDA potency draft: sample/system suitability, run invalidation, control charts, reference-material lot qualification, transgene mRNA/protein potency assays for gene therapy vectors [49]; ICH S12 [47]; WRIB: proficiency testing with CROs, same instrument through a study, no platform switching without cross-validation [52].
- Software/instruments in use: QuantStudio 7 Flex/Pro, TaqMan Array Cards, Bio-Rad QX200/QX ONE at BioAgilytix [55]; QX200 and QIAcuity in the NIST study [73]; Watson LIMS features without PCR mention [33]; BioAgilytix: 620+ CGT assays, 160+ sponsors [54].

Inferences.
- The CGT research lab's recurring problem is calibrator/standard-driven bias and lot drift; D3 (bridging, including reference-material lot replacement) and D4 (qualification report) address exactly what the potency draft and NIST paper describe.
- qPCR remains the biodistribution workhorse per Ma et al., while VCN and titre are migrating to dPCR; qPilot's qPCR focus fits biodistribution, shedding, transgene expression and research-stage VCN.

Gaps. Direct scientist complaints (forums, LinkedIn) could not be collected; the LIMS/ELN actually used by CGT research labs is unverified.

---

## 2. Pain inventory

| # | Pain | Evidence | Frequency (estimate where marked) | Who feels it | Severity | What exists today |
|---|---|---|---|---|---|---|
| P1 | Runs are analysed with no explicit control gate: NTC values hidden, NRT unused, positive controls not windowed | [60][57][58] | Most published research qPCR (3% adequately documented [57]) | Students, postdocs, core users | Wrong conclusions; irreproducible papers | Clinical IFU rules [4][5][6][7]; vendor control assays with thresholds [80]; nothing in research analysis tools (none found) |
| P2 | Efficiency assumed, not measured; reference genes unvalidated | [61][64][57][60] | Efficiency reported in 1–18% of papers | Everyone publishing qPCR | Biased fold changes | qPilot already measures per-well efficiency; the gap is acting on it with rules |
| P3 | No trending of the lab's own controls, so lot and instrument drift go unseen | [65][66][67][72][8] | Every lab that changes a lot or instrument (estimate: several times a year) | PI, core manager, CGT scientist | Silent bias across months | Unity Real Time, FastFinder QC (clinical, closed) [34][28]; R qcc (GPL) [79]; Excel |
| P4 | Between-plate factors of several-fold are uncorrected or corrected ad hoc | [69][68] | Any multi-plate study | Anyone running >1 plate | Group effects confounded with plate | qbase+ IRC (commercial); Factor-qPCR (licence unknown) [69] |
| P5 | New reagent/primer/standard lots used without qualification | [3][5][7][20][65] | Every lot change | Bench scientist | Step changes in Cq | EP26 (paid, clinical chemistry); nothing in research tools |
| P6 | CGT qPCR titres/VCN differ 2 log between labs because of calibrators and standards | [72][71][73][76] | Structural | CGT research and translational labs | Mis-dosing, failed transfers | Reference materials (ATCC RSMs, NIST candidates) exist; no tool checks a lab against them |
| P7 | qPCR validation has no regulatory template; labs assemble criteria from papers | [51][43][44][52] | Every assay going to GLP/IND | CRO scientists, CGT labs | Weeks of design and reporting | Ma Table 4 in a PDF; CRO SOPs; Watson (no PCR) [33] |
| P8 | Validation design and reports live in spreadsheets (inference; not sourced) | — | — | GLP-lite labs | Transcription errors | Excel/Word |
| P9 | False rejections if naive ±2 SD limits are used | [3] | ~5% of good runs | Any lab adopting QC | Lost runs, distrust of QC | Westgard multirules [1] |
| P10 | Research targets have no EQA; even clinical EQA shows 1.5–3.6 log spreads | [8][10] | Structural | Core facilities, consortia | Nobody knows who is right | QCMD/NEQAS/INSTAND/CAP for pathogens only |
| P11 | Instrument qualification is rarely done in research (inference; qualification plates exist) | [81][66][67] | Estimate: annual PM only | Core facilities | Well-to-well bias | CFX qualification plate (commercial) |
| P12 | Audit features are optional add-ons and can be silently disabled | [42] | Every research instrument | Any lab needing traceability | Unrecoverable history | Vendor SAE modules (licensed) |

---

## 3. Discoveries (ranked by impact × feasibility × fit)

### D1. "Run Gate": named, sourced run-acceptance rules keyed to RDML sample types, with failures turned into Decision Cards

1. **Persona and situation.** A postdoc running 2–6 plates a week of SYBR/TaqMan gene expression; a core-facility manager returning analysed plates to clients; a CGT research scientist running VCN or biodistribution plates with a standard curve. Today each plate's NTC, NRT, positive control and standard curve are eyeballed, if at all; nothing records the decision.

2. **Evidence of the pain.** NTC values "often hidden" and NRT unused in 432 audited papers [60]; 3% of 179 papers adequately documented [57]; efficiency reported in 1% of 2024 papers [61]; "assay efficiencies are assumed, not measured" [64]. Clinical practice shows what the gate looks like and that it is cheap: CDC's three-control validity table [5], TaqPath's Ct cutoff tables and "All control wells must pass" [4], cobas "batch is valid if no flags appear for any controls" [6], BioFire's Tm windows [7], Burd's per-run control set [3], Ma's plate acceptance (≥2/3 NTC wells BLOD; R² ≥0.980; E 90–110%; QC 50%/67% rule; spike recovery >55%) [43], FDA's "An assay run should be invalidated if suitability criteria are not met" [49]. Cost estimate (mine): one undetected contaminated NTC or failed RT control can waste a plate (reagents plus a day) or, worse, survive into a figure.

3. **What exists today.** Clinical middleware encodes rules per assay plugin, closed and IVD-positioned [26][27]; vendor research software is RUO-labelled and, as far as fetched, flags wells but does not evaluate plate validity against typed controls [41]; Bio-Rad publishes threshold rules for its own PrimePCR control assays (PCR control Cq ≥30; gDNA Cq <35; RQ ΔCq >3) but only on paper [80]; Cq-input research tools (Clarida, qbase+) are not known to gate runs (no evidence found either way).

4. **The concrete feature.** Input: the study's RDML files, whose samples are already typed unkn/ntc/nac/std/ntp/nrt/pos/opt and whose standards carry quantity [78]; a lab "rule pack" (YAML, versioned, hashed into the record) in which every rule has an id, a plain-language statement, parameters, a source citation and an action. Deterministic method, per plate and per target: 
   - R-NTC: any NTC/NAC well with a Cq (or a Cq within k cycles of the lowest unknown; k lab-set) → fail, with the LinRegPCR per-well efficiency and melt (if present) attached so "primer-dimer vs contamination" can be shown. Source: CDC "If any of the NTC reactions exhibit a growth curve ... Invalidate the run" [5]; Ma "≥2/3 NTC wells BLOD" [43].
   - R-NRT: NRT Cq − RT Cq smaller than the lab's threshold → gDNA warning per target. Source: PrimePCR gDNA rule and ΔCq logic [80] (threshold lab-set; vendor default 35 cycles for its assay only).
   - R-POS: positive control Cq outside the lab's window (absolute window from an IFU-style setting or mean ± 3 SD from the lab's own baseline, see D2) → fail. Source: TaqPath PC ≤37 [4]; Burd's 20-run target [3].
   - R-IPC: internal/extraction control Cq above cutoff in any sample → that sample invalid (not the plate). Source: TaqPath MS2 ≤32 [4]; CDC RP <40 [5].
   - R-STD: standard curve R² and efficiency thresholds, minimum levels, back-calculation error, replicate Ct %CV. Source: Ma Table 4 [43]; ISO 20395 linearity [18].
   - R-SPIKE: spiked-well recovery below threshold → inhibition flag and re-analysis suggestion. Source: Ma >55% [43]; FDA shedding parallel spiked sample [48].
   - R-REP: replicate disagreement (ΔCq or %CV) with Bar/Tichopad-style kinetic-outlier evidence from the raw curves (the amplification-compatibility test compares each well's fitted efficiency parameters to a reference set and reports a Z-score [70]).
   - R-GEO: carry-over check: NTC or low wells adjacent (plate geometry) to the highest-copy wells; and a warning when negative controls are not pipetted last (ordering from the run file if available). Source: FastFinder "proximity" detection [28]; Burd placement rule [3].
   Output: facts per rule (pass/fail/not-applicable with numbers), a plate status (valid / valid-with-sample-exclusions / invalid), and Decision Cards only for failures that could change a conclusion (e.g., "NTC amplified for Gapdh at Cq 35.8 on plate 3; options: exclude Gapdh on plate 3 / treat as late primer-dimer (melt supports) / accept; per-gene consequence shown"). The record stores the rule-pack hash, each evaluation and the chosen action. Agent call: `qpcr_run_gate(study, rule_pack) → {plate: status, failures: [...]}`.

5. **Feasibility.** RDML typing exists [78]; rdmlpython is MIT; evaluation is pure Python; the engine already yields per-well efficiency and Cq. Effort: 1–2 weeks for the rule engine, defaults, cards and record fields; 1 week for a "type your controls" prompt when a plate has untyped wells (persisted per assay so it is asked once). Hardest part: honest defaults. Thresholds must ship as "examples with sources" and be lab-set; nothing should silently reject.

6. **Why qPilot.** Raw curves allow rules that Cq-only tools cannot express (per-well efficiency, kinetic outliers, melt evidence); the Decision Card and impact ranking stop the gate from becoming approval fatigue; the record makes the gate auditable; the robustness engine can rerun the study with and without each excluded plate.

7. **Risks.** False rejections if users adopt ±2 SD windows (5% [3]) — ship multirule logic and warnings; rule packs could be mistaken for clinical validity rules — label every pack "research use; lab-defined"; plates with no typed controls make the gate silent — show "no gate possible" loudly. Confidence: high.

### D2. Control-trend engine: Levey-Jennings and Westgard multirules over the lab's own records (assay × control material × instrument), with lot and instrument event markers

1. **Persona and situation.** Any lab that runs the same assay repeatedly: a core facility running a client's assay weekly; a CGT lab running a VCN plasmid standard every plate; a lab that includes an inter-run calibrator or a positive-control plasmid/gBlock on every plate. They notice drift only when a result "looks wrong".

2. **Evidence of the pain.** Lot effects on Ct [65]; cycler non-uniformity and drift [66][67]; between-run factors of 6× [69] and 0.77 cycles [68]; AAV8 variation from "PCR machines, primer/probe sources, reagent storage and handling" [72]; clinical labs chart controls precisely to catch these [3][1][2]; FastFinder sells exactly this ("Levey-Jennings charts", "preset Westgard rules", alerts) [28]; FDA now asks GMP labs for "control chart analysis of control sample data to detect any adverse trends" [49]; research audits show no equivalent practice [60][61].

3. **What exists today.** Unity Real Time (clinical chemistry QC, peer groups, audit trails) [34]; FastFinder QC (clinical, closed) [28]; R qcc for Shewhart/CUSUM/EWMA charts but GPL [79]; Excel. None reads RDML or ties points to a study record.

4. **The concrete feature.** A "control series" is identified by (target/assay id, control material id + lot, instrument id, optionally operator); its points come from every Analysis Record in the workspace: Cq, efficiency-corrected N0, per-well LinRegPCR efficiency, melt Tm, and NTC amplification rate per plate. Baseline policy copied from clinical practice: provisional mean and SD after 20 points (status "provisional" with widened limits before that; recalculation after 20–30 further runs) [2][3]. Rules (each named and cited): 1_2s warning; 1_3s, 2_2s, R_4s (within-run only), 4_1s, 10x rejection; 4_1s and 10x evaluated across runs and across control levels [1]. Event markers from metadata: lot change, instrument, operator, software version, drawn on the chart (RDML has no lot field, so lots are read from sample/run annotation property/value pairs and from the lab profile [78]). Output: a chart fact set per series, a per-run verdict, and a Decision Card when a rule fires on a plate that contributes to a conclusion ("Positive control Cq has risen 1.1 cycles over 8 runs since master-mix lot B (4_1s); options: accept / exclude plates 5–8 / re-run bridging (D3); robustness shows conclusion for gene X flips if plates 5–8 are excluded"). Also chart the per-plate mean efficiency and NTC rate, which Cq-only clinical charts cannot do. Agent call: `qpcr_control_trend(series) → {status, rule_hits, chart_facts}`.

5. **Feasibility.** Pure Python, deterministic; the hard part is metadata discipline (lot, instrument) — mitigated by a per-assay "passport" that remembers the control material and asks for the lot once per plate; and by small-n baselines (show provisional status). Effort: 2–3 weeks. Statistical caveat: Cq of a fixed-copy control is approximately normal, but normality should be checked (the HPV paper warns the method fails if not normally distributed [15]).

6. **Why qPilot.** The workspace of records is the longitudinal dataset nobody else has; decisions and robustness turn a chart into an action; MCP exposes the trend to an agent that can answer "has this assay drifted since the lot change?" with engine facts.

7. **Risks.** Labs that run no consistent control get nothing — mitigate by having `qpilot plan` propose a positive-control well per plate; false alarms during provisional phase; misreading of a drift that is biological (control material degradation) as instrument drift — show both hypotheses. Confidence: medium-high.

### D3. Lot and run bridging: an EP26-style two-stage lot check plus a run-factor model (plate, lot, instrument as multiplicative factors) with the robustness engine deciding whether the bridge changes the answer

1. **Persona and situation.** A lab opening a new primer lot, master-mix lot, standard plasmid or calibrator lot, moving to a new instrument, or adding an operator mid-study; a CGT lab replacing its reference material lot.

2. **Evidence of the pain.** Clinical rules require qualification of every lot and shipment [3], positive controls with each new kit lot [5], external QC "with each new lot and shipment" [7]; CLSI EP26 formalises a two-stage acceptance protocol [20]; Ma requires bridging validation when sample prep, curve range or instrument model changes [43]; FDA asks that replacement reference-material lots be qualified against the current lot [49]; WRIB warns RT reproducibility varies across kit lots and against platform switching without cross-validation [52]; extraction-lot Ct shifts [65]; NIST attributes qPCR VCN spread to calibrator DNA choice [73]; between-run factors of several-fold [69][68]. Research tools have no lot concept at all (no evidence found of any).

3. **What exists today.** EP26 (paid, chemistry-oriented); Hellemans' inter-run calibration in qBase/qbase+ (commercial) [68]; Factor-qPCR (standalone; licence not stated) [69]; Excel.

4. **The concrete feature.** Two linked objects. (a) *Bridge*: the lab declares, once per assay, the acceptable difference (e.g., ΔCq ≤0.5 or ≤25% in copies; lab-set, EP26 stage 1 [20]) and then, for a lot change, runs old and new lot on the same n samples on one plate (stage 2); the engine computes paired ΔCq with confidence interval and an equivalence test (two one-sided tests) → pass / fail / undetermined (n too small), recorded with lot identities. (b) *Run factors*: for multi-plate studies, estimate per-plate (or per-lot, per-instrument) multiplicative factors from all overlapping technical and biological replicates by the geometric-mean-of-ratios method (Ruijter eqs. 1–5: pairwise run ratios, nested geometric means for missing pairs, factors normalised to multiply to 1, correction by division) [69], or, when inter-run calibrators are flagged in RDML, by the geometric mean of IRC NRQs with Hellemans' formula 13′ and delta-method error propagation [68]. Report the factor magnitude as a QC fact ("plate 4 is 2.1× plate 3"), because a large factor is itself a warning. The robustness engine then reruns the study with and without correction and with/without the bridged lot; a Decision Card appears only when a conclusion depends on it. Agent call: `qpcr_bridge(study, old_lot, new_lot)` and `qpcr_run_factors(study)`.

5. **Feasibility.** Formulas are published in open-access papers and can be reimplemented permissively (do not reuse Factor-qPCR code until its licence is known) [68][69]; statistics via scipy/statsmodels (BSD). Effort: 2–3 weeks. Hardest: experimental design capture — the engine must know which samples overlap across plates and which wells are old vs new lot; `qpilot plan` should propose the overlap (ties to the plate-design roadmap item) and the RDML interRunCalibrator flag should be set at import.

6. **Why qPilot.** Only a whole-study, robustness-driven tool can show whether a lot or plate factor flips a conclusion; records keep the bridge as evidence for a methods paragraph or a GLP transfer package.

7. **Risks.** Over-correction when the multiplicative assumption fails (Ruijter's caveat) [69]; calibrator failures biasing factors (Hellemans recommends ≥2 IRCs) [68]; users treating a research bridge as a regulatory bridging study — label clearly. Confidence: medium.

### D4. Research-use assay qualification report: ISO 20395 / Ma Table 4 / ICH Q2(R2) characteristics computed from the lab's own dilution-series plates, for GLP-lite and CGT research labs

1. **Persona and situation.** A CGT research scientist (VCN, AAV genome titre, biodistribution) preparing an assay for GLP transfer or an IND-enabling package; a translational lab asked by a reviewer or a CRO for LoD, LLOQ, linearity and precision; any lab that wants the MIQE 2.0 items "detection limits and dynamic ranges" [63] without a week in Excel.

2. **Evidence of the pain.** No regulatory validation guideline for qPCR; CROs harmonise via GCC/WRIB [51][52]; M10 excludes PCR and leaves exploratory work to self-defined qualification [44]; the FDA LoQ of <50 copies/µg gDNA with 95% confidence [46]; ICH S12 spike-and-recovery and performance parameters [47]; FDA shedding "qualified ... LOD and ... LOQ ... percent recovery ... one-time basis" [48]; EMA VCN units [50]; Ma's full numeric design (5 plates, ≥3 days, 2 operators, 2 lots, 7–8 levels, CV/RE bands) [43]; inter-lab failures driven by standards [72][73][76]; sector volume 4,487 programmes [77]; BioAgilytix's 620+ CGT assays shows the demand side [54]. Cost estimate (mine, unsourced): a manual qualification write-up is days of spreadsheet work per assay and is redone at every change.

3. **What exists today.** CRO SOPs and Watson LIMS for LC/LBA (no PCR features on its page) [33]; Ma's table in a PDF; ISO 20395 and CLSI EP17/EP05 as paid documents [18][23]; Excel.

4. **The concrete feature.** A "qualification study" type in qPilot with a wizard that maps wells (RDML quantity for standards; sample annotations for operator, instrument, lot, matrix, spike) and computes, deterministically, with every criterion editable and cited: linearity (log-linear fit, R², slope → efficiency; ≥5 levels per Q2(R2), ≥7 per Ma); LoB/LoD by probit hit-rate across levels at C95 (Burd/EP17 design: ~60 data points) and the Poisson floor (≥3 copies); LLOQ as the lowest level meeting the lab's CV/RE bands across all runs (Ma: CV ≤25%, RE ±45%, positive in all replicates of all runs); ULOQ; intra- and inter-run precision via nested variance components (run, operator, instrument as factors, EP05-style terms); accuracy (RE vs nominal); matrix effect and spike recovery (Ma; ICH S12; FDA shedding); specificity (naive-matrix wells all BLOD); freeze–thaw/bench stability (if plates are tagged); robustness supplied by the existing robustness engine (analysis-choice sensitivity) plus the run-factor magnitude from D3; and the FDA check "LLOQ ≤50 copies/µg gDNA at 95%" expressed in the lab's DNA-input units. Output: a report draft (Markdown/PDF/Excel) with a criteria table (value, threshold, source, pass/fail), the raw-curve evidence, and a fixed header: "Research-use method qualification summary generated by qPilot. Not a GLP validation; no QA review; the software is not validated as a GLP computerised system and makes no 21 CFR Part 11 claim." Agent call: `qpcr_qualify(study, criteria_pack)`.

5. **Feasibility.** statsmodels (BSD) for probit regression and mixed/nested ANOVA; scipy (BSD); report templating exists already (Excel/CSV export, methods paragraph). Effort: 3–5 weeks including the wizard. Hardest: design capture (which wells belong to which level/replicate/operator/day) and keeping defaults honest (ship Ma Table 4 and ISO 20395 characteristic names as examples; the lab edits and signs the thresholds).

6. **Why qPilot.** Per-well efficiencies allow an efficiency-aware LLOQ and kinetic-outlier exclusion that Cq-only pipelines cannot do; robustness is a native "robustness" characteristic; the record makes the qualification re-runnable and hash-verified, which is what a receiving CRO or QA unit wants to see.

7. **Risks.** Being mistaken for a validated system (mitigate with the fixed header and no "validated" vocabulary); CGT titre/VCN work migrating to dPCR (NIST, Ayuso) [73][72] — scope D4 to qPCR biodistribution, shedding, expression and research VCN, and design the criteria pack to be format-agnostic so a dPCR plugin can reuse it; design burden on the user. Confidence: medium-high for academic/biotech CGT research, medium for CROs.

### D5. Honest audit posture: Part 11 vocabulary mapped to the Analysis Record without the claim

1. **Persona and situation.** A lab head or core manager asked "who changed that threshold and why?", or a CGT lab preparing to hand data to QA; a reviewer asking for provenance.

2. **Evidence of the pain.** Research-instrument audit features are optional, licensed add-ons and can be disabled with "no audit record ... generated" [42]; FDA's audit-trail wording is precise and short [35]; signature manifestation requires name, date/time and meaning [36]; RUO status is lost by claims, not by features [39].

3. **What exists today.** Vendor SAE modules (licensed) [42]; Unity Real Time audit trails (clinical) [34]; qPilot's hash-chained decision log (built).

4. **The concrete feature.** Add to the record: (a) a sign-off object with printed name, timestamp and meaning drawn from the 11.50 vocabulary (review / approval / responsibility / authorship) [36]; (b) an "audit statement" page auto-generated from the record that lists which 11.10 items the record supports technically (time-stamped entries, previous values never obscured, accurate copies) and which it does not and cannot (system validation by the lab, procedural controls, identity verification) [35]; (c) a fixed disclaimer: "Research use only. Not an IVD. Not 21 CFR Part 11 compliant; no claim of GLP computerised-system validation." Agent call: `records audit_statement`.

5. **Feasibility.** Days of work on top of the existing log. Hardest: wording review.

6. **Why qPilot.** The hash chain already exists; this gives it the regulated vocabulary that lab QA units recognise.

7. **Risks.** Over-promising by implication; keep the "cannot" list prominent. Confidence: medium (small feature; value is in trust, not capability).

### D6. Ring mode: QCMD-style scoring across users, instruments or sites that measure the same material

1. **Persona and situation.** A core facility with many users running one assay; a multi-site CGT programme; a consortium sharing a reference material (ATCC AAV RSMs, NIST lentiviral VCN candidates) [72][73].

2. **Evidence of the pain.** Inter-lab spreads of 1.5–5.7 log10 in clinical EQA [8][10]; two-log AAV8 spread [72]; WRIB recommends blinded proficiency testing with known positives/negatives [52]; no EQA exists for research targets (I found none in the sources fetched).

3. **What exists today.** QCMD, UK NEQAS, INSTAND, CAP for clinical pathogens [9][12][13][14]; nothing for gene expression or research VCN.

4. **The concrete feature.** A "ring" object over Analysis Records (or exported facts) from multiple participants on the same blinded material: robust consensus (outliers removed), SD, each participant's estimation score 0–3 by SD band and detection score, assessment groups by method/instrument, and a "duplicate performance over time" chart, copied from the QCMD report structure [10]. Output: a ring report per challenge. Agent call: `records ring`.

5. **Feasibility.** Easy once records exist (1–2 weeks); the hard part is organising materials and participants, which is a community task, not software.

6. **Why qPilot.** Records are comparable by construction (same open method, same facts); the opt-in commons roadmap item is the natural home.

7. **Risks.** Low uptake without a reference-material partner; scoring misread as accreditation. Confidence: low-medium.

---

## 4. Data, libraries, standards, licences found

| Item | What it gives qPilot | URL | Licence / cost |
|---|---|---|---|
| RDML v1.3 schema | Sample types (ntc, nac, nrt, ntp, pos, std, opt, unkn), interRunCalibrator, calibratorSample, quantity, target ref/toi, efficiency, detectionLimit, run metadata | https://rdml.org/files/rdml/RDML_v1_3_REC.xsd | Open schema (licence text not shown); rdmlpython is MIT per brief |
| Westgard multirules and Levey-Jennings lessons | Rule definitions and baseline policy | https://www.westgard.com/mltirule.htm ; https://www.westgard.com/lesson12.htm | Public web lessons (reimplement; no code) |
| Burd 2010 CMR | Control set, 20-run targets, lot/calibration rules, LoD/precision/accuracy designs | https://pmc.ncbi.nlm.nih.gov/articles/PMC2901657/ | Journal article (PMC) |
| CDC / TaqPath / cobas / BioFire IFUs | Worked examples of run-validity tables and Ct/Tm windows | https://www.fda.gov/media/134922/download ; /136112/ ; /136049/ ; /137583/ | US government / vendor documents (cite, do not copy) |
| Ma, Bell, Loker 2021 | Table 4 criteria for qPCR biodistribution validation; run acceptance | https://pmc.ncbi.nlm.nih.gov/articles/PMC7786041/ | Open access (PMC) |
| ICH M10, Q2(R2), S12 | Acceptance vocabulary, linearity/DL/QL formulas, biodistribution method expectations | https://database.ich.org/... ; https://www.fda.gov/media/167605/download | Free |
| FDA LTFU 2020; shedding 2015; potency draft 2023; RUO guidance 2013 | 50 copies/µg; qualification vs validation; system suitability and control charts; RUO limits | https://www.fda.gov/media/113768/download ; /89036/ ; /175132/ ; /87374/ | Free |
| EMA GTMP guideline | VCN LoD/LoQ units; controls | https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-quality-non-clinical-and-clinical-aspects-gene-therapy-medicinal-products_en.pdf | Free |
| ISO 20395:2019 | Characteristic list for qPCR/dPCR method performance | https://www.evs.ee/en/iso-20395-2019 | €241 |
| CLSI EP26-Ed2, EP17-A2, EP23-Ed2, MM03-Ed3, MM06-Ed3, MM17-Ed2 | Lot-change protocol; LoB/LoD/LoQ; risk-based QC plans; molecular QC | https://clsi.org/... (see sources) | Paid; free to members |
| Hellemans 2007 (qBase) | Inter-run calibration formulas and error propagation | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1852402/fullTextXML | Open access article; qBase software free but qbase+ commercial |
| Ruijter 2015 (Factor-qPCR) | Run-factor estimation equations; RDML export | https://pmc.ncbi.nlm.nih.gov/articles/PMC4822202/ | Open access article; tool licence not stated |
| Tichopad 2010 | Amplification-compatibility test (kinetic outlier Z-scores) | Methods 2010 (local PDF; DOI unverified) | Journal article |
| QCMD example report | Scoring scheme (0–3 by SD band), consensus/range reporting, duplicate-over-time | https://www.qcmd.org/wp-content/uploads/2024/03/HIVRNA_specimen.pdf | Public example |
| NIST lentiviral VCN candidate RMs; AAV2/AAV8 RSMs (ATCC VR-1816 for AAV8) | Reference materials for D4/D6 | https://pmc.ncbi.nlm.nih.gov/articles/PMC12229725/ ; PMC4236062 | Materials for purchase/request |
| statsmodels, scipy | Probit, nested ANOVA, equivalence tests | pypi | BSD (permissive) |
| R qcc | Control charts (reference only) | https://cran.r-project.org/package=qcc | GPL ≥2 — do not ship |
| Bio-Rad PrimePCR control assays; CFX qualification plate | Published research-grade control thresholds; instrument pass/fail plate | Local PDFs (Bio-Rad manual 2014; Bulletin 6323) | Commercial products; thresholds citable |
| ASGCT/Citeline Q2 2026 landscape | Market sizing for CGT | https://www.asgct.org/uploads/files/general/Final-ASGCT-Citeline-Q2-2026.pdf | Free report |
| Europe PMC REST API | Literature lookup used in this research | https://www.ebi.ac.uk/europepmc/webservices/rest/ | Free |

---

## 5. Open questions and what could not be verified

- Forum and social evidence (Reddit r/labrats, r/medlabprofessionals, ResearchGate, LinkedIn) was not collected: WebSearch was unavailable and those sites block fetching. The "envy" and "complaints" questions are therefore answered by inference from vendor claims and audits, not by practitioner quotes.
- PCR.AI/Diagnostics.ai (HTTP 403), Rotor-Gene AssayManager, CFX Maestro Dx SE, Epic Beaker and Orchard pages were not retrievable; LIS interface specifics (HL7 v2 ORU, ASTM/LIS2) are unverified. No clinical software pricing was found.
- ISO 15189:2022 clause text on IQC/EQA and OECD GLP No. 17 (computerised systems) could not be fetched; CLSI EP05 page returned 404.
- Whether GLP qPCR labs reduce data in Excel and which LIMS/ELN CGT research labs use: not sourced (Watson's page does not mention PCR; BioAgilytix pages name instruments only).
- No source gives the percentage of research papers lacking a positive control, nor a survey of research-lab QC behaviour (as opposed to reporting).
- Clinical run-rejection rates beyond BioFire (0.6% control failures) and the HPV lab (1.7% batches out of control) were not found; QCMD scheme-level performance statistics sit behind participant login.
- Whether Westgard rules applied to Cq are statistically sound in small research series (normality, autocorrelation) needs a check on real lab data before defaults are chosen.
- Licence of Factor-qPCR and the exact DOI of Tichopad 2010 are unverified; the Thermo manuals (MAN0010408, Pub. 4489821) and Bio-Rad PrimePCR manual were read from local PDF copies whose download URLs were not verified.
- The 2023 WRIB white paper body on numeric qPCR/dPCR acceptance criteria was only partially readable (first part of the PMC page); its PCR-specific software/Part 11 statements, if any, were not seen.
- EQA schemes for research targets (gene expression, VCN): none found, but absence was not proven.

---

## 6. Sources

1. Westgard QC, "Westgard Rules" and multirules — https://www.westgard.com/mltirule.htm
2. Westgard QC, "QC — The Levey-Jennings Control Chart" — https://www.westgard.com/lesson12.htm
3. Burd EM. Validation of laboratory-developed molecular assays for infectious diseases. Clin Microbiol Rev 2010 — https://pmc.ncbi.nlm.nih.gov/articles/PMC2901657/
4. Thermo Fisher, TaqPath COVID-19 Combo Kit Instructions for Use (FDA EUA; marked revoked) — https://www.fda.gov/media/136112/download
5. CDC 2019-nCoV Real-Time RT-PCR Diagnostic Panel IFU, CDC-006-00019 Rev 08 — https://www.fda.gov/media/134922/download
6. Roche cobas SARS-CoV-2 (cobas 6800/8800) Instructions for Use (EUA) — https://www.fda.gov/media/136049/download
7. BioFire Respiratory Panel 2.1 Instructions for Use (EUA) — https://www.fda.gov/media/137583/download
8. Hayden RT et al. Progress in quantitative viral load testing: variability and impact of the WHO quantitative international standards. J Clin Microbiol 2017;55:423 — https://pmc.ncbi.nlm.nih.gov/articles/PMC5277511/
9. QCMD home page — https://www.qcmd.org/
10. QCMD example individual EQA report, HIV RNA 2018 challenge C1 — https://www.qcmd.org/wp-content/uploads/2024/03/HIVRNA_specimen.pdf
11. QCMD publications list — https://www.qcmd.org/en/qcmd-publications/
12. UK NEQAS for Microbiology — https://www.ukneqasmicro.org.uk/
13. INSTAND e.V. — https://www.instand-ev.de/en/
14. CAP Proficiency Testing / EQA — https://www.cap.org/laboratory-improvement/proficiency-testing
15. Peng P et al. A unique Levey-Jennings control chart used for internal quality control in human papillomavirus detection. Virol J 2022;19:125 — https://pmc.ncbi.nlm.nih.gov/articles/PMC9331565/
16. Levey-Jennings charts for internal QC in prenatal molecular diagnosis (FISH). BMC Med Genomics 2020 — https://pmc.ncbi.nlm.nih.gov/articles/PMC7395379/
17. O'Brien CP, Finn SP. Application of statistical process control to qualitative molecular diagnostic assays. Front Mol Biosci 2014 — https://pmc.ncbi.nlm.nih.gov/articles/PMC4429644/
18. ISO 20395:2019 listing (EVS) — https://www.evs.ee/en/iso-20395-2019
19. EVS-EN ISO 15189:2022 listing — https://www.evs.ee/en/evs-en-iso-15189-2022
20. CLSI EP26-Ed2, User Evaluation of Acceptability of a Reagent Lot Change (2022) — https://clsi.org/standards/products/method-evaluation/documents/ep26/
21. CLSI MM06-Ed3, Quantitative Molecular Methods for Infectious Diseases (2026) — https://clsi.org/shop/standards/mm06/
22. CLSI EP23-Ed2, Laboratory Quality Control Based on Risk Management (2023) — https://clsi.org/standards/products/method-evaluation/documents/ep23/
23. CLSI EP17-A2, Evaluation of Detection Capability (2012, reaffirmed 2017) — https://clsi.org/shop/standards/ep17/
24. CLSI MM17-Ed2, Validation and Verification of Multiplex Nucleic Acid Assays (2018) — https://clsi.org/shop/standards/mm17/
25. CLSI MM03-Ed3, Molecular Diagnostic Methods for Infectious Diseases (2015) — https://clsi.org/shop/standards/mm03/
26. UgenTec FastFinder overview — https://www.ugentec.com/fastfinder
27. UgenTec FastFinder Analysis — https://www.ugentec.com/fastfinder/analysis
28. UgenTec FastFinder QC — https://www.ugentec.com/fastfinder/qc
29. UgenTec, Pharma, CRO and Biotech — https://www.ugentec.com/applications/pharma
30. UgenTec, IVDR for labs — https://www.ugentec.com/resources/ivdr-for-labs
31. UgenTec home page ("UgenTec is now Velsera") — https://www.ugentec.com/
32. Seegene Viewer product page — https://www.seegene.com/products/software/detail/3
33. Thermo Scientific Watson LIMS — https://www.thermofisher.com/uk/en/home/digital-solutions/lab-informatics/lab-information-management-systems-lims/solutions/watson.html
34. Bio-Rad QC data management (UnityWeb, Unity Real Time, QCNet) — https://www.bio-rad.com/qc
35. 21 CFR 11.10 Controls for closed systems (LII) — https://www.law.cornell.edu/cfr/text/21/11.10
36. 21 CFR 11.50 Signature manifestations — https://www.law.cornell.edu/cfr/text/21/11.50
37. 21 CFR 11.200 Electronic signature components and controls — https://www.law.cornell.edu/cfr/text/21/11.200
38. 21 CFR 809.10 Labeling for in vitro diagnostic products — https://www.law.cornell.edu/cfr/text/21/809.10
39. FDA, Distribution of In Vitro Diagnostic Products Labeled for Research Use Only or Investigational Use Only (Nov 2013) — https://www.fda.gov/media/87374/download (landing: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/distribution-in-vitro-diagnostic-products-labeled-research-use-only-or-investigational-use-only)
40. Regulation (EU) 2017/746 (IVDR), Article 1(3)(a), Article 2(2), recitals 7 and 17 — https://eur-lex.europa.eu/eli/reg/2017/746/oj
41. Thermo Fisher, QuantStudio Design and Analysis Software User Guide, Pub. MAN0010408 Rev B.0 (local PDF copy; download URL not verified)
42. Thermo Fisher, QuantStudio 6 and 7 Flex Real-Time PCR Systems Maintenance and Administration Guide, Pub. 4489821 Rev B, Appendix E (SAE module) (local PDF copy; URL not verified)
43. Ma H, Bell KN, Loker RN. qPCR and qRT-PCR analysis: Regulatory points to consider when conducting biodistribution and vector shedding studies. Mol Ther Methods Clin Dev 2021;20:152 — https://pmc.ncbi.nlm.nih.gov/articles/PMC7786041/
44. ICH M10 Bioanalytical Method Validation and Study Sample Analysis (Step 4, May 2022) — https://database.ich.org/sites/default/files/M10_Guideline_Step4_2022_0524.pdf
45. ICH Q2(R2) Validation of Analytical Procedures (Nov 2023) — https://database.ich.org/sites/default/files/ICH_Q2%28R2%29_Guideline_2023_1130.pdf
46. FDA, Long Term Follow-Up After Administration of Human Gene Therapy Products (Jan 2020) — https://www.fda.gov/media/113768/download
47. ICH S12 Nonclinical Biodistribution Considerations for Gene Therapy Products (FDA final, May 2023) — https://www.fda.gov/media/167605/download (landing: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/s12-nonclinical-biodistribution-considerations-gene-therapy-products)
48. FDA, Design and Analysis of Shedding Studies for Virus or Bacteria-Based Gene Therapy and Oncolytic Products (Aug 2015) — https://www.fda.gov/media/89036/download
49. FDA draft guidance, Potency Assurance for Cellular and Gene Therapy Products (Dec 2023) — https://www.fda.gov/media/175132/download
50. EMA, Guideline on the quality, non-clinical and clinical aspects of gene therapy medicinal products (EMA/CAT/80183/2014) — https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-quality-non-clinical-and-clinical-aspects-gene-therapy-medicinal-products_en.pdf
51. Global CRO Council. Recommendations on qPCR/ddPCR assay validation by GCC. Bioanalysis 2022;14(12):853 (abstract) — https://europepmc.org/article/MED/35703321
52. 2023 White Paper on Recent Issues in Bioanalysis (WRIB; dPCR vs qPCR, gene therapy). Bioanalysis 2024 — https://pmc.ncbi.nlm.nih.gov/articles/PMC11849449/
53. 2020 White Paper on Recent Issues in Bioanalysis, Part 3 (qPCR assay validation) (abstract) — https://europepmc.org/article/MED/33533276
54. BioAgilytix, Gene Therapy — https://www.bioagilytix.com/modalities/gene-therapy/
55. BioAgilytix, Molecular Assays — https://www.bioagilytix.com/techniques/molecular-assays/
56. Bustin SA et al. The need for transparency and good practices in the qPCR literature. Nat Methods 2013;10:1063 (abstract) — https://europepmc.org/article/MED/24173381
57. Dijkstra JR et al. Critical appraisal of quantitative PCR results in colorectal cancer research. Mol Oncol 2014 — https://pmc.ncbi.nlm.nih.gov/articles/PMC5528534/
58. Bustin SA. The reproducibility of biomedical research: Sleepers awake! Biomol Detect Quantif 2014 — https://pmc.ncbi.nlm.nih.gov/articles/PMC5121206/
59. Abdel Nour AM et al. Five years MIQE guidelines: the case of the Arabian countries. PLoS One 2014 — https://pmc.ncbi.nlm.nih.gov/articles/PMC3913779/
60. Drude N et al. Reporting quality of quantitative polymerase chain reaction (qPCR) methods in scientific publications. Res Integr Peer Rev 2026 — https://pmc.ncbi.nlm.nih.gov/articles/PMC12961777/
61. Real-Time Reverse Transcription Quantitative PCR (RT-qPCR) Methodological Standards and Reporting Practices. Clin Chem 2026 (abstract) — https://europepmc.org/article/MED/41603592
62. Bustin SA, Nolan T. Talking the talk, but not walking the walk. Eur J Clin Invest 2017 (abstract) — https://europepmc.org/article/MED/28796277
63. Bustin SA et al. MIQE 2.0: Revision of the MIQE guidelines. Clin Chem 2025 (abstract) — https://europepmc.org/article/MED/40272429
64. MIQE 2.0 and the Urgent Need to Rethink qPCR Standards. Int J Mol Sci 2025 — https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/
65. Statistical assessment of DNA extraction reagent lot variability in real-time quantitative PCR. Lett Appl Microbiol 2010 (abstract) — https://europepmc.org/article/MED/20070509
66. Saunders GC et al. Interlaboratory study on thermal cycler performance in controlled PCR and RAPD analyses. Clin Chem 2001 (abstract) — https://europepmc.org/article/MED/11148176
67. Kim YH et al. Performance evaluation of thermal cyclers for PCR in a rapid cycling condition. BioTechniques 2008 (abstract) — https://europepmc.org/article/MED/18476814
68. Hellemans J et al. qBase relative quantification framework and software. Genome Biol 2007;8:R19 — https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1852402/fullTextXML (DOI 10.1186/gb-2007-8-2-r19)
69. Ruijter JM et al. Removal of between-run variation in a multi-plate qPCR experiment. Biomol Detect Quantif 2015 — https://pmc.ncbi.nlm.nih.gov/articles/PMC4822202/
70. Tichopad A et al. Quality control for quantitative PCR based on amplification compatibility test. Methods 2010 (local PDF; DOI not verified)
71. Lock M et al. Characterization of a recombinant adeno-associated virus type 2 Reference Standard Material. Hum Gene Ther 2010 — https://pmc.ncbi.nlm.nih.gov/articles/PMC2957240/
72. Ayuso E et al. Manufacturing and characterization of a recombinant adeno-associated virus type 8 reference standard material. Hum Gene Ther 2014 — https://pmc.ncbi.nlm.nih.gov/articles/PMC4236062/
73. Interlaboratory assessment of candidate reference materials for lentiviral vector copy number and integration site measurements (NIST). Mol Ther Methods Clin Dev 2025 — https://pmc.ncbi.nlm.nih.gov/articles/PMC12229725/
74. Preparation and collaborative study of a rAAV genome copy number reference material. J Pharm Anal 2026 — https://pmc.ncbi.nlm.nih.gov/articles/PMC13578975/
75. Interlaboratory Measurement of Adeno-Associated Virus: Comparative Quantification of Full and Empty Capsids. Hum Gene Ther 2024 (abstract) — https://europepmc.org/article/MED/39723438
76. Dobnik D et al. Accurate quantification and characterization of adeno-associated viral vectors. Front Microbiol 2019 — https://www.frontiersin.org/articles/10.3389/fmicb.2019.01570/full
77. ASGCT/Citeline, Gene, Cell & RNA Therapy Landscape Report Q2 2026 — https://www.asgct.org/uploads/files/general/Final-ASGCT-Citeline-Q2-2026.pdf
78. RDML v1.3 XML schema (RDML_v1_3_REC.xsd) — https://rdml.org/files/rdml/RDML_v1_3_REC.xsd
79. CRAN package qcc (GPL ≥2) — https://cran.r-project.org/package=qcc
80. Bio-Rad, PrimePCR Assays, Panels, and Controls for Real-Time PCR, Instruction Manual (2014), Chapter 3 (local PDF; URL not verified)
81. Bio-Rad Bulletin 6323, PCR Instrument Validation Tools: CFX Qualification Plate (local PDF; see www.bio-rad.com/cfxqualification)
82. Godmer A et al. Machine learning to improve the interpretation of intercalating dye-based quantitative PCR results. Sci Rep 2022 (abstract) — https://europepmc.org/article/MED/36180590
83. Raymaekers M et al. Checklist for optimization and validation of real-time PCR assays. J Clin Lab Anal 2009 (abstract) — https://pmc.ncbi.nlm.nih.gov/articles/PMC6649018/
84. Europe PMC REST API (used to resolve papers and read abstracts) — https://www.ebi.ac.uk/europepmc/webservices/rest/
