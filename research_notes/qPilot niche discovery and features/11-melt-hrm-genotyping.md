# 11 — Melt-curve analysis beyond "is there a single peak": HRM genotyping, species/strain ID, MS-HRM, allelic discrimination, multiplex deconvolution, and open vs vendor tools

Researcher notes for the qPilot niche-discovery effort. Date: 17 October 2026.

**Method note (read first).** The shared WebSearch budget for this run was exhausted before my first query, so every finding below comes from direct fetches of primary sources whose addresses I already knew or could derive: vendor product pages and manuals (PDF text extracted locally), Google Patents, PubMed/Europe PMC records and full texts via the NCBI/EBI APIs, CRAN/PyPI/GitHub pages, the RDML schema and example file, and the Dryad/Zenodo APIs. Community forums (Reddit, Biostars, Biology Stack Exchange, ResearchGate) all refused automated access in this session, so **forum evidence is a declared gap**; the pain inventory is built from vendor manuals, patents and the methods literature instead. PubMed counts were taken with the E-utilities on 17 Oct 2026 and are title/abstract matches (undercounts). All numbers are cited; where I infer, I say so.

**Terms used below.** *Melt curve*: after PCR, the instrument heats the well slowly and records fluorescence of a DNA-binding dye; double-stranded DNA "melts" (strands separate) and fluorescence falls. *Tm*: temperature of the steepest fall (peak of the negative first derivative). *HRM* (high-resolution melting): recording that fall with a saturating dye and fine temperature steps so that curve *shape*, not just Tm, distinguishes sequence variants. *Heterozygote*: a sample carrying two different alleles; after PCR it contains mismatched "heteroduplexes" that melt early and change the curve shape. *Homozygote*: one allele; two homozygotes differ only by a small Tm shift. *Normalisation*: scaling each curve to 100 % fluorescence before the melt and 0 % after. *Temperature shift (overlay)*: sliding curves along the temperature axis so they coincide at a chosen fluorescence level, which hides Tm differences and emphasises shape differences. *Difference plot*: subtracting a reference curve from each curve. *MS-HRM*: methylation-sensitive HRM on bisulphite-treated DNA. *Allelic discrimination*: end-point two-colour (FAM/VIC or FAM/HEX) probe assays (TaqMan, KASP) where a genotype is read from a scatter plot of the two dyes.

---

## 1. How this corner of the niche works

### 1.1 Who does this, and what their week looks like

- **Clinical-genetics research and pharmacogenetics labs** run HRM as a cheap *scan* for variants before sequencing (a scan of a gene region takes about 3 h, plus about 3 h of sequencing when a variant is found) and as a closed-tube SNP genotyping method [26][22]. Pharmacogenetics programmes genotype a handful of variants (e.g. five DPYD variants in 617 patients over a year) by TaqMan allelic discrimination with an in-house calling and QC pipeline [69].
- **Clinical and veterinary microbiology** use HRM to type pathogens (e.g. "Minim typing", a multilocus HRM scheme that resolves known *S. aureus* sequence types into 268 "melting types" and *E. faecium* into 231) [44], to detect resistance alleles (KPC-2-like vs KPC-3-like in 166 isolates, confirmed by sequencing) [21], and to investigate hospital outbreaks where HRM is costed at roughly €500 against about €5,000 for MLST and about €10,000 for whole-genome sequencing for a 100-isolate simulated outbreak [64]. PubMed holds 432 HRM papers mentioning bacteria/fungi/parasites/typing/species identification and 166 mentioning veterinary or livestock species [86].
- **Plant breeders and plant scientists** use HRM for high-throughput genotyping, gene mapping and seed/food testing [45]; 216 HRM papers mention plant/cultivar/crop/breeding [86]. A typical dataset is a Tm table: 8 loci × 90 samples with 14 reference samples of known genotype, and unknowns assigned by comparing Tm to the references (Dryad, CC0) [84].
- **Food and herbal-product authentication** labs use "Bar-HRM" (DNA barcoding + HRM): e.g. 3 of 15 Acanthaceae medicinal products did not contain the labelled species [47]; 3 of 11 soursop tea products were adulterated [48]; ginseng substitution detected with ITS2 [49]. 158 HRM papers mention food/adulteration/authentication [86].
- **Epigenetics and forensic/age-estimation researchers** use MS-HRM to quantify locus methylation to 0.1–1 % sensitivity [40][43]; open CC0 datasets exist for age estimation in cats, dolphins and elephants [82].
- **Diagnostics-platform developers** (digital HRM, multiplex melt) are the ML frontier: universal digital HRM on 20,000-partition chips with novelty detection [52], 9-plex digital PCR with one dye via kinetics + melt (99.33 % accuracy) [60], six targets in one channel on droplet dPCR [59].

### 1.2 The analysis pipeline step by step, and where the judgement calls are

The canonical HRM pipeline, as defined by the Wittwer lab and reproduced in every vendor package, is:

1. **Background removal.** Either a linear "bilinear" baseline fitted to pre- and post-melt regions, or exponential background subtraction fitted from two slopes in regions containing only background [25][38]. rdmlpython (MIT) implements `exponential`, `bilinear` and `combined` methods with default windows 65–92 °C (exponential) and 65–67 / 93–94 °C (bilinear) [2].
2. **Normalisation** to 1 (start of pre-melt) and 0 (end of post-melt). In Bio-Rad's software the average at the start of the pre-melt range is set to one and the average at the end of the post-melt range to zero; the software auto-detects the melt region but lets the user drag the pre-/post-melt sliders, and the manual warns that changing those regions changes the clustering [12]. **Decision 1: where the normalisation windows sit.**
3. **Temperature shift (overlay).** Curves are shifted so they intersect at a fluorescence level; Bio-Rad's default bar height is 0.20 (range 0 = baseline to 1 = top of melt region) [12]. The gene-quantification.de HRM resource argues that temperature shifting removes the discriminatory power of the temperature axis: it helps heterozygote calls but hinders homozygote calls, which differ only by Tm [19]. **Decision 2: shift or not, and at which level.**
4. **Difference plot** against a reference cluster's mean curve [12][25]. **Decision 3: which cluster is the reference.**
5. **Clustering / genotype calling.** Vendors differ (see 1.3). Bio-Rad exposes two knobs: *Melt Curve Shape Sensitivity* (percentage slider, default 50 %; higher gives more heterozygote clusters) and *Tm Difference Threshold* (0.05–1.00 °C, default 0.15 °C; lower gives more homozygote clusters), and tells the user to lower sensitivity or raise the Tm threshold by hand when there are many false positives [12]. **Decision 4: cluster stringency, i.e. how many genotypes exist.**
6. **Per-well confidence and manual override.** Bio-Rad computes a probability distribution per cluster from the standard deviation of the curves in that cluster, maps each sample onto each cluster's distribution, and reports a *Percent Confidence* as an "integrity check" for auto-calls; users right-click to reassign a well, create a new cluster, exclude a well, or undo a manual call, and the results sheet records *Call Type* = Automatic or Manual [12]. **Decision 5: accept, re-call, or exclude an ambiguous well.** This is exactly a Decision-Card shape, but today it is a right-click with no reason logged.

Accuracy reality check (bench truth, not vendor claims): in a 10-configuration instrument study on one SNP with predicted ΔTm = 0.00 °C, heterozygote accuracy was 99.7 % (n = 2,141) but homozygote accuracy only 70.3 % (n = 4,441); instruments that read one sample at a time beat full-plate imagers for homozygotes (78.1 % vs 61.8 %); and the authors' custom analysis software outperformed the commercial software (P < 0.002); accuracy also depended on amplicon length (72.3 %, 83.1 %, 59.8 %, 65.9 % for 51, 100, 272, 547 bp) [27]. Earlier, nine instruments showed a 15-fold range in Tm standard deviation (0.018–0.274 °C) on the same amplicon [24]. For heterozygote scanning, amplicons of 300 bp or less were called without error (280 heterozygous and 296 wild-type cases), while 400–1000 bp products gave 96.1 % sensitivity and 99.4 % specificity [23].

### 1.3 Instruments, software, formats, money

| Vendor / tool | What it does (documented) | Licence / price / status | Source |
|---|---|---|---|
| **Bio-Rad Precision Melt Analysis Software** (cat. 1845025 with calibration kit; 1845015 software only; 1845020 Melt Calibration Kit) for all CFX systems | Negatives detection (NTC and low-RFU wells excluded), RFU normalisation, automatic clustering, difference curves, temperature-shift bar (default 0.20), Shape Sensitivity (default 50 %), Tm Difference Threshold (default 0.15 °C), per-well Percent Confidence, manual re-calling with Call Type, Melt Study module to compare several melt files, Well Groups, export to Excel/CSV/XML/HTML of Raw, Normalised and Difference RFUs | Paid; 2 user licences with 2 HASP HL hardware keys; CFX Maestro `.pcrd` files are converted to `.melt`; v1.3 patch needs CFX Manager 2.0+/Maestro 1.0+ and Windows 7/8/10; price shown only after login (not retrieved) | [11][12][13] |
| **Bio-Rad patent US 8,606,527** (Houser; priority 2009; granted 2013; Google lists anticipated expiry 2032-04-30) | Documents a melt-region detector (smoothed second derivative, boundary at 0.35 × peak, pooled at about the 25th/75th percentiles), a two-step normalisation with a threshold crossing (0.2–0.5), reduction of each curve to about 7 segment means, mixture-of-Gaussians or k-means clustering, a cluster-separation score (over roughly 3.5 = well separated), sub-clustering by Tm, and a sensitivity setting that sets distance thresholds | Active patent; this is the only public description of how a vendor's auto-clustering works | [14] |
| **Thermo Fisher HRM Software v2.0 (cat. 4397808)** | Legacy add-on for 7500 Fast / 7900HT; v2.0.1 and v3.0.1 referenced in FAQs, with a mandatory HRM dye-calibration plate | Not orderable; FAQs on the MeltDoctor page list supported instruments (7500 Fast, 7900HT, StepOne/Plus, ViiA 7, QuantStudio 12K Flex, 3, 5, 6 Flex, 7, 6/7 Pro) | [15][16] |
| **Thermo HRM in current QuantStudio software** | Not verifiable in this session (pages 404) | Gap | — |
| **Roche LightCycler 480 Gene Scanning** | Normalisation, temperature shifting, difference plot (third-party description) | Product page not reachable; price unknown | [19] |
| **Qiagen Rotor-Gene Q + ScreenClust** | Built-in HRM auto-assigns genotypes using difference plots [19]; ScreenClust adds supervised discriminant analysis with likelihoods and unsupervised cluster analysis [20]; robust ΔTm discrimination limit about 0.2 °C on Rotor-Gene [44] | ScreenClust product page not found (status unknown) | [19][20][44] |
| **Agilent AriaMx HRM module; Canon/Idaho LightScanner** | Not reachable (403/404). uAnalyze still reads LightScanner-32/96 and HR-1 exports | Gap | [33][35] |
| **Wittwer-lab web tools (dna-utah.org)**: uMelt Quartz (curve prediction), uMelt HETS, uAnalyze 2.1/3.0, Tm Tool, uVariants, PrimerSPY, uSnapBack | Free for research and academic use with citation; commercial use via contact | uMelt Quartz now requires a login because of bot traffic; no API or source for uMelt | [31][32] |
| **uAnalyze-HRM (GitHub)** | JavaScript web app: baseline and exponential normalisation, derivative and difference plots, 2D offset vs a reference, agglomerative clustering with user-chosen k, predicted curves with uMelt parameters; reads HR1, LS32, LC480, LC96, LS96/CFX96, Rotor-Gene, QuantStudio and generic formats | MIT (copyright 2026 Zachary Dwight); the project page says commercial use may require a sublicence from bioMérieux because of US patents | [34][35][36][33] |
| **rdmlpython** (RDML consortium) | `meltCurveAnalysis()` with exponential/bilinear/combined normalisation, smoothing by Friedman super-smoother, peak finding on the first derivative with width and ΔH-share cut-offs, expected-Tm matching (`truePeakWidth`), artefact peaks, write-back of `excl`/`note` texts and a saturating-dye correction factor `corrF` | MIT; v1.7.2 on PyPI (May 2023); the web RDML-Tools wrapper is GPL | [1][2][3][10] |
| **MBmca** (R) | `diffQ`/`diffQ2` Tm from first/second derivative, `mcaSmoother`, `mcaPeaks`, `MFIerror`; datasets DMP, DualHyb, MultiMelt | GPL (≥ 2); v1.1-0, June 2025 | [72][73] |
| **qpcR::meltcurve** (R) | Cubic-spline derivative, super-smoother, peak finding, peak areas with baseline, span optimisation against known Tm | GPL-2/3; v1.4-2, June 2025 | [74][75] |
| **MeltingPlot** (R + PHP web) | HRM epidemiological typing from Tm tables: average replicates, connect isolates whose Tm differ by ≤ 0.5 °C for every primer set, split connected components by edge-betweenness clustering, label clusters by reference isolates | GPL; .xls input | [64][65][66] |
| **DECIPHER::MeltDNA** (Bioconductor) | Simulates melt and derivative curves and positional helicity with the Tostesen 2003 multi-state model and SantaLucia 1998 parameters; up to 100 kb | Bioconductor package (licence not confirmed on the page fetched; GPL-3 in my recollection, verify) | [80] |
| **TaqMan Genotyper Software v1.7.1** | Free SNP calling from end-point or real-time files of QuantStudio/ViiA 7/StepOne/7500; auto-calls with user-settable linear boundaries for homozygote, heterozygote and undetermined regions; manual editing; only FAM and VIC dyes supported | Free, Windows 10 | [17][18] |
| **LGC SNPviewer / KlusterCaller / Kraken** | SNPviewer only displays cluster plots (no re-calling); KlusterCaller auto-classifies into two homozygotes, heterozygote or inconclusive with proprietary algorithms, ROX normalisation toggle | SNPviewer free; KlusterCaller proprietary | [70][71] |
| **SNPman** | Calls TaqMan genotypes from fluorescence over the whole run, not only the end point; reanalysed 3,738 samples; works with three common instruments | Free for non-commercial use (SourceForge) — not permissive | [68] |

**Data formats.** RDML v1.3 (recommendation of 26 Oct 2022) stores per-reaction melting data points `mdp` (`tmp`, `fluor`, unbounded; the schema states fluorescence must not be baseline-corrected), an optional per-reaction `meltTemp`, the per-target expected `meltingTemperature`, and `excl`/`note` strings with semicolon-separated reasons [5][6]. The consortium's own v1.3 example file holds 90 reactions with 3,420 amplification points and 7,380 melting points (82 per reaction), five target `meltingTemperature` values and no `meltTemp` results, dye SYBR Green I [7]. Instruments listed as RDML-compliant: CFX Maestro (1.1), LightCycler 96 (1.1), Rotor-Gene Q (1.1), MyGo (1.2), StepOne/QuantStudio 12K Flex/ViiA 7 (version not stated) [8]; third-party software: Clarida viewer (1.3), Primer3Plus (1.3), LinRegPCR (1.2), RDML R package (1.1) [9]. RDML-Tools imports vendor melt tables through the RDES layout (temperatures as header columns, column 7 = "Tm") [3]. Bio-Rad's melt exports are Excel/CSV/XML/HTML sheets of Raw, Normalised and Difference RFUs [12]; uAnalyze's format list shows that LightCycler 480/96, Rotor-Gene, CFX96 and QuantStudio all export raw melt text that third parties parse [35].

**Money and time.** Vendor HRM add-ons are licensed per PC with hardware dongles (Bio-Rad) [11]; Thermo's older HRM software needed a calibration plate run before analysis and had version-coupling problems (FAQ: files not opening after instrument software upgrades) [16]. Per-sample cost comparisons: HRM typing about €500 vs about €5,000 MLST vs about €10,000 WGS for a 100-isolate outbreak [64]; an AI-assisted HRM CALR screen is costed under $10 per test [57].

### 1.4 How big is this, and where is it going

- PubMed title/abstract matches for HRM: 3,920 in total; by year 196 (2010), 336 (2015), 256 (2020), 170 (2024). MS-HRM: 323. TaqMan allelic discrimination: 1,200 [86]. **Inference:** bulk HRM publication output peaked in the mid-2010s and has roughly halved since; it has not vanished but is now a mature, cost-driven method in microbiology, plant and food labs, while the research frontier moved to digital melt and ML.
- ML on melt curves 2014–2026: SVM ensembles on uMelt-simulated and real curves (92 serotypes, 99.9 % LOOCV; 100 % with 3 training curves per variant in vitro) [50]; nested one-vs-one SVM for 37 bacteria (100 % LOOCV on isolates, lower on blood-culture samples) [51]; signature-transform features + random forest with open-set "novel genotype" detection (Youden 0.92; sensitivity and specificity 0.96) on 20K-partition digital HRM, code on GitHub, data on request [52][53]; CNNs on recurrence-plot images of yeast HRM (95.2 % vs 86.5 % SVM) [54]; YOLOv8 + CatBoost for CALR mutation screening with open-set recognition of untrained variants (2,667 development samples; 98.1 % multicentre accuracy) [57]; dynamic-time-warping clustering of Salmonella HRM [56]; LDA on multiplex HRM for Fusarium chemotypes (> 99 %, 80 isolates) [63]; ML web app for SARS-CoV-2 variants from duplex qPCR-HRM (167 swabs, 95.2 % sensitivity) [55]; deep learning on melt signatures for 25 of 28 shark/ray species [61]; ML software bundled with a multi-fragment melt kit identifying 254 lactobacilli isolates (18 species; single fragments 59–90 %, combined 100 %) [62].
- Digital/multiplex melt: AMCA (amplification kinetics + melt) reaches 99.33 ± 0.13 % on a 9-plex with > 100,000 events [60]; droplet digital melt quantifies six targets in one channel at 85 % accuracy [59]; a synthetic unamplified oligonucleotide with known Tm is added as a per-chip temperature calibrator to correct non-uniformity [58].
- Commercial status of the digital-HRM spin-off: the Melio Labs domain now redirects to a domain-for-sale page [87] (inference: the company is dormant or renamed; unverified).

### Key question 1 — Vendor software: what it does, what it costs, what is closed

**Takeaway.** Every vendor implements the same five steps (background, normalise, optional shift, difference plot, cluster) but exposes different knobs and undocumented clustering; only Bio-Rad's method is public, via its patent. Licensing is per-PC with dongles or tied to instrument software versions; prices are hidden behind logins; several products (Thermo HRM v2.0, ScreenClust) appear discontinued or unreachable.

**Cited findings.**
- Bio-Rad Precision Melt: two user licences + two HASP keys; works with all CFX systems; v1.3 patch requires CFX Manager 2.0+ or Maestro 1.0+; documents list requires login; price not shown [11]. Defaults: temperature-shift bar 0.20; shape sensitivity 50 %; Tm difference threshold 0.15 °C (range 0.05–1.00); pre/post-melt region changes alter clustering; per-well Percent Confidence from within-cluster SD; manual re-calling with Call Type recorded; Melt Study compares multiple melt files; exports Excel/CSV/XML/HTML [12]. Manual is version 1.0, 2017 [12].
- Bio-Rad's algorithm (patent): second-derivative melt-region detection, two-step normalisation with threshold crossing, 7-segment curve summary, Gaussian-mixture/k-means clustering, cluster score, Tm sub-clustering, sensitivity-controlled distance thresholds; Google lists anticipated expiry 2032-04-30 [14].
- Thermo: HRM Software v2.0 (4397808) is not orderable [15]; the MeltDoctor FAQ ties HRM Software v2.0.1 to 7500 Fast software < 2.0.4 and v3.0.1 to ≥ 2.0.4, requires a three-step dye calibration (one step on ViiA 7/QuantStudio), and says calibration wells cannot be omitted [16].
- TaqMan Genotyper is free, auto-calls with linear boundaries and an "undetermined" region, allows manual edits, and supports only FAM and VIC; supported run files span 7500 to QuantStudio 7 Pro Dx [17][18].
- ScreenClust: supervised discriminant analysis with likelihoods and unsupervised clustering [20]; used in practice for KPC allele discrimination [21]; product pages not found [—].
- Third-party summary of LightCycler 480 Gene Scanning (normalise, shift, difference plot) and the argument that temperature shifting discards homozygote information [19].
- Independent evaluation: custom software beat commercial software (P < 0.002) and homozygote accuracy averaged 70.3 % across 10 configurations [27].

**Inferences.** Vendors' "confidence" numbers are heuristics (within-cluster SD mapping) with no published validation; the user-facing knobs (sensitivity, Tm threshold, normalisation windows, shift level) are exactly the choices that flip calls. Nothing exposes "how many of the reasonable settings agree with this genotype".

**Gaps.** Prices for Bio-Rad/Roche/Agilent/Thermo HRM modules; current Thermo QuantStudio HRM module documentation and its confidence metric; ScreenClust and LightScanner availability; Roche auto-grouping parameters; any forum complaints (sites blocked).

### Key question 2 — Methods literature

**Takeaway.** The maths is published and old (2003–2014): exponential background subtraction, normalisation, overlay by integral least squares, difference plots, hierarchical clustering by curve distance, nearest-neighbour thermodynamic curve prediction including heteroduplexes. The open problems are calibration across runs/instruments, homozygote discrimination, novel-genotype detection and multiplex deconvolution — all of which 2020–2026 papers attack with ML.

**Cited findings.**
- Wittwer 2003: closed-tube genotyping with LCGreen; all six β-globin genotypes distinguished in a 110-bp amplicon; melting acquisition 1–2 min [22]. Reed & Wittwer 2004: sensitivity/specificity by amplicon length as above [23]. Herrmann 2006: Tm SD 0.018–0.274 °C across nine instruments; only the saturating dye detected heterozygotes by shape [24]. Palais & Wittwer 2009: review of signal extraction, clustering/classification, full-curve prediction and duplex-mixture modelling [25]. Erali & Wittwer 2010: heterozygotes appear as atypical shapes; 3 h scan + 3 h sequencing [26]. Li 2014: accuracy figures above [27].
- Patents that encode the algorithms: US 8,296,074 (Utah; priority 2005) claims hierarchical clustering of melting profiles by pairwise distance, exponential background subtraction from two slopes, an integral-least-squares overlay, a difference-plot distance and a minimum-distance clustering function; Google lists anticipated expiry 2026-09-20 and "Active" at fetch time; cited by Canon, Bio-Rad, Life Technologies, Roche, Idaho Technology, Seegene, Cepheid and Johns Hopkins [37]. Its continuation US 8,068,992 (exponential background subtraction) is listed "Active – Reinstated" with anticipated expiry 2029-02-01 [38]. The saturation-dye patent US 7,582,429 (assignees include BioFire Defense) is listed expired as of 2025-12-08 [39].
- Prediction: uMelt computes mean helicity per position with an accelerated partition function and nearest-neighbour stacking, loop entropy, monovalent and Mg²⁺ terms; predicted domain counts and relative temperatures match experiments but absolute Tm depends on parameters, and dyes/rapid ramps are not modelled [28]. uAnalyze compares experimental curves to predictions after exponential or linear background removal, reports "curve spread" and a "2D offset", and found a 0.04 ± 0.48 °C difference at 50 % helicity across 14 CYBB amplicons [29]. uMelt HETS models a heterozygote as four duplexes; heteroduplexes contributed 25.7 ± 6.7 % of the composite curve, mismatch ion effects scaled to 76–96 % of normal [30]. DECIPHER's MeltDNA implements the Tostesen 2003 multi-state model with SantaLucia 1998 parameters [80].
- MS-HRM: bisulphite conversion makes methylated and unmethylated alleles differ in sequence and Tm; unknowns are compared with 0.1/1/10/50 % methylated:unmethylated standards run in every experiment; curves normalised by a line of best fit through pre- and post-transition regions; 0.1 % detection with 94–109 bp amplicons; annealing temperature must be determined empirically to avoid PCR bias; heterogeneous methylation shows as a different curve shape [40]. Protocol under 3 h [41]; H19 imprinting study: 100 % concordance with Southern blot, 33 of 36 samples (92 %) scored unambiguously [42]; sensitivity 0.1–1 % [43].
- Typing and microbiology: Minim typing melting types [44]; HRM reproducibility suffers if template or amplicon concentration varies; detectability falls with fragment length; G+C-neutral changes are harder; multiplexed HRM is difficult because of concentration sensitivity and the need for well-separated Tm [44]. MeltingPlot's rule: isolates linked when all primer-set Tm differ by ≤ 0.5 °C, then edge-betweenness splitting; results from different datasets are not directly comparable, hence reference isolates; peak shape/height considered noisier than Tm [64].
- ML 2020–2026 and digital melt: see 1.4 [50]–[63].
- Multiplex deconvolution: no PubMed title/abstract hits for "melting curve" + "deconvolution/peak fitting" + PCR in my query [86]; the published multiplex approaches instead use kinetics + melt with supervised ML [60] or Tm windows with LDA [63]. The only public mixture model is uMelt HETS's four-duplex composite [30].

**Inferences.** A permissive, deterministic HRM engine can be built entirely from published maths; the Bio-Rad-specific pipeline (7-segment Gaussian mixture, cluster score) should not be copied verbatim while its patent is active. Exponential background subtraction may still be patent-encumbered to 2029 in the US (Google's status is an assumption); the bilinear baseline from 2003 is not. True "deconvolution" of multiplex melts into component amplicons is a genuine open gap in the literature.

**Gaps.** Full texts of Palais 2009, Simko 2016, Druml 2014 and Erali 2010 (paywalled or bot-blocked); claim-by-claim legal status of the Utah patents; any formal HRM reporting guideline (I found none; MIQE does not cover HRM calls).

### Key question 3 — Open tools and what is missing

**Takeaway.** Open code exists for Tm/peak finding (rdmlpython MIT; MBmca and qpcR GPL), for normalisation/overlay/clustering as a browser app (uAnalyze-HRM MIT), for Tm-table typing (MeltingPlot GPL) and for curve prediction (DECIPHER, GPL; uMelt web-only). Nothing open does end-to-end HRM genotyping with confidence, robustness and a record; nothing open does MS-HRM quantification; nothing permissive predicts curves; nothing open calls allelic-discrimination plates deterministically with QC.

**Cited findings.**
- rdmlpython: MIT; CLI `-mca` with `--mcaNormMethod`, `--mcaFluorSource`, `--mcaPeakCutoff`, `--saveDerivative`, `--saveResults` [1]; `meltCurveAnalysis(normMethod="exponential", fluorSource="normalised", truePeakWidth=1.0, artifactPeakWidth=1.0, expoLowTemp=65.0, expoHighTemp=92.0, bilinLowStartTemp=65.0, bilinLowStopTemp=67.0, bilinHighStartTemp=93.0, bilinHighStopTemp=94.0, peakLowTemp=60.0, peakHighTemp=98.0, peakMaxWidth=5.0, peakCutoff=5.0, updateRDML=False, ...)`; peaks are local maxima of the smoothed first derivative checked against second-derivative bounds, width and temperature window; peaks below `peakCutoff` % of total ΔH are dropped; the expected peak is the largest-ΔH peak within `truePeakWidth` of the target's expected Tm; write-back sets `excl`/`note` with texts such as "no product with expected melting temperature", "product with different melting temperatures detected", "product detected in negative control", "several products with different melting temperatures detected", and for saturating dyes a `corrF` = true-peak fluorescence share; results table columns per peak: peak temp, peak width, Fluor, peak correction factor, deltaH, deltaH factor, H, H factor; `--saveDerivative` writes smoothed, normalised, first- and second-derivative TSVs [2]. PyPI release 1.7.2, May 2023 [10]. RDML-Tools web wrapper: a "MeltingCurveAnalysis" tab; reactions with several products are reported and excluded; all web tools GPL, library MIT [3][4].
- MBmca (GPL ≥ 2; 2025) functions and datasets [72][73]; qpcR::meltcurve (GPL; 2025) algorithm [74][75]; chipPCR (GPL-3; 2021) and PCRedux (MIT; Nov 2025) are amplification-curve only [76][77]; RDML R package (MIT; July 2025) imports RDML, no melt mention [78]; CRAN "HRM" is an unrelated repeated-measures package [79].
- uAnalyze-HRM: MIT, features and formats as in 1.3 [34][35][36]; the lab page notes possible bioMérieux sublicensing for commercial use [33]. uMelt Quartz: login required; free for research with citation; no source/API [31][32].
- DECIPHER MeltDNA [80]; MeltR (MIT) fits absorbance melting and fluorescence binding isotherms, not HRM [81]; MeltingPlot GPL, R, igraph [64][65]; Boussina's dHRM notebooks and CSVs on GitHub without a visible licence [53]; SNPman non-commercial [68].

**Inferences.** The permissive building blocks for qPilot are rdmlpython (peaks, normalisation, RDML write-back), uAnalyze-HRM (reference JS implementations of overlay/difference/clustering to port), and RDML itself. Missing and permissively licensable from papers: a partition-function melt predictor (reimplement Tostesen/uMelt from the papers; validate against the CC BY uMelt-simulated curves in Athamanolap 2014's supplementary data), MS-HRM quantification, mixture-model genotype calling for scatter plots (Fujisawa 2004), cross-run Tm alignment with calibrators.

**Gaps.** I could not enumerate PyPI/GitHub for other HRM packages without search; a maintained Python HRM-genotyping package may exist that I did not find.

### Key question 4 — Data access and public datasets

**Takeaway.** Raw melt fluorescence is exportable from all mainstream instruments and is first-class in RDML (`mdp`), with CFX Maestro, LightCycler 96 and Rotor-Gene Q exporting RDML 1.1 natively. Public HRM datasets with known truth are few and small, but several are permissively licensed (CC BY / CC0) and together are enough for acceptance tests.

**Cited findings.**
- RDML `mdp`/`tmp`/`fluor`/`meltTemp`/`meltingTemperature`/`excl`/`note` definitions [5]; example file 7,380 melting points [7]; RDES melt import layout [3]; RDML-compliant instruments and software [8][9]; Bio-Rad exports Raw/Normalised/Difference RFUs [12]; uAnalyze reads LC480, LC96, LS96/CFX96, Rotor-Gene, QuantStudio, HR1, LS32 exports [35].
- Datasets: Athamanolap 2014 supplementary S1–S8 (amplicon sequences and uMelt-simulated curves for 92 serotypes × 9 salt conditions, plus in vitro RASSF1A curves) under CC BY [50]; dHRM-novelty-detection `Data/` with ten species' derivative-melt CSVs and synthetic normalised sets (licence not shown) [53]; Dryad CC0 HRM Tm table for *Amphicarpaea* (8 loci × 90 samples; 14 references, 76 unknowns) [84]; Dryad CC0 MS-HRM age-estimation sets (cat/snow leopard raw CSV + R scripts; dolphin; elephant) and a 2024 Culex multiplex qPCR + HRM record with files unlisted [82]; Zenodo records are mostly papers; a 2026 "Raw RT-qPCR, melting curves and amplification curves" deposit (CC BY 4.0) contains only a Cq spreadsheet and PNG plots [83][85]; an Actinobacillus 19-serovar HRM paper deposit has two supplementary xlsx tables (contents unverified) [83]; MeltingPlot ships an example Tm workbook [65].

**Inferences.** There is no public benchmark of raw HRM curves with sequencing-confirmed genotypes across instruments; the Li 2014 dataset (6,582 calls across 10 configurations) would be ideal but is not deposited. Building and publishing such a benchmark (CC0) would be a first.

**Gaps.** Zenodo API rate-limited two of my queries; figshare's search endpoint returned noise; I could not confirm whether CFX Maestro's RDML 1.1 export includes `mdp`.

### Key question 5 — Communities, volume and pains

**Takeaway.** HRM is a mature mid-volume method (about 170–340 PubMed papers a year, 3,920 total) concentrated in microbiology (432), plant (216), veterinary (166) and food (158) literatures; its documented pains are normalisation-window and sensitivity dependence, homozygote ambiguity, run-to-run Tm drift, dongle-locked software, mandatory calibration plates, and ML models that require data not shared.

**Cited findings.** Counts [86]; pain evidence from [12][16][19][24][27][44][64]; forum evidence: none obtainable (declared gap).

**Inferences.** The declining publication curve argues against a stand-alone HRM product but for a module inside a general qPCR analysis tool that labs already use for expression work, which is where qPilot sits.

**Gaps.** No instrument-installed-base or licence-count numbers were found; no forum quotes.

### Key question 6 — Allelic discrimination (TaqMan/KASP)

**Takeaway.** Vendor callers are free but closed (TaqMan Genotyper: linear boundaries, FAM/VIC only; KlusterCaller: proprietary), the only open implementations are non-commercial (SNPman) or academic methods (model-based clustering, 2004), and the real-world workflow still has a human re-calling "undetermined" wells with no record.

**Cited findings.** TaqMan Genotyper features and limits [17][18]; SNPviewer view-only, KlusterCaller proprietary with "inconclusive" calls [70][71]; SNPman uses whole-run fluorescence, 3,738 samples, free for non-commercial use [68]; Fujisawa 2004 normal-mixture model with penalised likelihood flags unclear genotypes and copes with unknown cluster counts where k-means fails [67]; a 2026 pharmacogenetics programme genotyped 617 patients by TaqMan allelic discrimination with an internal calling/QC pipeline and medical-director review [69]; STAR Protocols 2026 mouse-colony genotyping by allelic-discrimination qPCR [89]; 1,200 PubMed papers mention TaqMan allelic discrimination [86].

**Inferences.** RDML already holds the per-dye amplification data needed for both end-point and whole-run calling, so qPilot can implement SNPman's idea with permissive code.

**Gaps.** Published "undetermined" rates for TaqMan plates; the exact TaqMan Genotyper quality-value algorithm (user guide not reachable).

---

## 2. Pain inventory

| # | Pain (what the scientist experiences) | Evidence | Frequency (estimate) | Who feels it | Severity | What exists today |
|---|---|---|---|---|---|---|
| P1 | Clusters change when I move the pre-/post-melt normalisation sliders; no way to know which setting is "right" | Bio-Rad manual note that changing regions changes clustering [12]; patent describes automated region detection to avoid this [14] | Every HRM plate (estimate) | Anyone calling genotypes | High (flips calls) | Vendor sliders; no robustness report |
| P2 | Homozygotes cannot be told apart reliably; shape-only (temperature-shifted) analysis hides Tm | 70.3 % homozygote accuracy across 10 configurations; custom software better than commercial [27]; shifting removes temperature information [19] | Common for SNP genotyping with homozygous classes | SNP genotyping labs, plant breeders | High | Vendor Tm-difference threshold (default 0.15 °C) [12] |
| P3 | Sensitivity/stringency knob decides how many genotypes exist; vendors tell users to turn it down when there are "false positives" | Bio-Rad shape sensitivity and Tm threshold instructions [12]; Bio-Rad patent CD thresholds [14] | Every plate with unknown number of alleles | Variant scanning, species ID | High | Manual tuning |
| P4 | Ambiguous wells are re-called by right-click with no reason recorded; "confidence %" is an unvalidated heuristic | Percent Confidence defined from within-cluster SD; Call Type Automatic/Manual only [12] | Several wells per plate (estimate) | All | Medium–High (audit, reproducibility) | Spreadsheet export |
| P5 | Runs are not comparable across plates, days or instruments; reference isolates needed in every run; Tm SD varies 15-fold between instruments | MeltingPlot: datasets not directly comparable [64]; Herrmann [24]; Rotor-Gene ΔTm limit about 0.2 °C [44]; chip non-uniformity needs an oligo calibrator [58] | Every multi-plate study | Typing labs, breeders, core facilities | High | Reference controls per run; Bio-Rad Melt Study module compares several melt files, but only inside Precision Melt for CFX data [11][12] |
| P6 | Software is dongle-locked and version-coupled; data files will not open after instrument software upgrades; calibration plates mandatory | HASP keys, 2 licences [11]; Thermo FAQs on calibration and version mismatch [16]; HRM Software v2.0 not orderable [15] | Per lab, per upgrade | Core facilities, shared instruments | Medium | Buy another licence; vendor support |
| P7 | HRM cannot tell me a genotype it has never seen; it forces the sample into a known cluster | Open-set/novelty detection papers [52][57] | Variant scanning, surveillance | Clinical research, microbiology | High (false assignment) | Only in ML research code |
| P8 | Assay design: will my SNP be resolvable on my instrument? Predicted ΔTm vs instrument noise; uMelt is web-only and now login-walled | uMelt limits [28][32]; detectability vs length and G+C-neutral changes [44][23] | Every new assay | Assay developers | Medium | uMelt (web), DECIPHER (GPL), primer-design folklore |
| P9 | Multiplex melts (several amplicons, one dye) are hard to analyse; concentrations shift peaks | Multiplexed HRM "difficult" [44]; multiplex solved only with ML or Tm windows [60][63] | Growing (multiplex assays, dPCR) | Diagnostics R&D, food | Medium | Tm-window assignment by eye |
| P10 | MS-HRM methylation % is read by comparing to standard curves by eye; heterogeneous methylation changes shape | Profile matching to 0.1/1/10/50 % standards [40]; 3 of 36 equivocal [42] | Every MS-HRM run | Epigenetics, forensic age estimation | Medium–High | None open; vendor HRM software not designed for it |
| P11 | Allelic-discrimination "undetermined" wells need manual re-calling; vendor callers closed and dye-limited | TaqMan Genotyper linear boundaries, FAM/VIC only [17][18]; KlusterCaller proprietary [71]; SNPman non-commercial [68] | Every genotyping plate | Breeders (KASP), mouse colonies, PGx research | Medium | Free closed tools; Excel |
| P12 | ML HRM classifiers are published without data; "available on request" | Boussina data on request [52]; most ML papers without repositories [90] | Research community | Method developers | Medium | Athamanolap CC BY data [50] |
| P13 | Melt data is exported but rarely archived with the analysis settings; no reporting standard for HRM calls | RDML has `mdp`/`meltTemp` but example file has no `meltTemp` results [7]; no guideline found (gap) | All | Reviewers, repeat analysts | Medium | RDML (data only) |

---

## 3. Discoveries (ranked by impact × feasibility × fit)

### D1. An open HRM genotyping engine where the vendor's knobs become Decision Cards and a robustness grid

1. **Persona and situation.** A plant-breeding technician or a microbiology research assistant calling SNP/indel genotypes or allele classes from 96/384-well HRM plates on a CFX, LightCycler or Rotor-Gene, several plates a week, with a vendor module that costs extra, lives on one dongle-locked PC, and gives a "confidence %" nobody can explain. Also the clinical-research lab scanning a gene region for variants before sequencing [26].
2. **Evidence of the pain.** P1–P4, P6: normalisation windows change clustering [12]; sensitivity and Tm-threshold tuning is manual and vendor-advised [12]; homozygote accuracy 70.3 % and commercial software worse than custom analysis [27]; temperature shift discards Tm information [19]; dongles and version lock [11][16]. Estimated cost: a wrong homozygote call is a wrong genotype in a mapping or clinical-research dataset; re-running a 96-well HRM plate costs reagents plus a day (estimate).
3. **What exists today.** Vendor modules (closed clustering, one instrument each) [11][14][16][19][20]; uAnalyze-HRM (MIT, browser, k chosen by user, no confidence, no record) [34]; rdmlpython (MIT) finds peaks but does not genotype [2]; MBmca/qpcR (GPL) find Tm only [72][74]; ML research code without data [52]. None reports how many reasonable analysis settings agree with a call, none logs the reason for a manual re-call, none is instrument-agnostic through RDML.
4. **The concrete feature.** *Input:* RDML with `mdp` per reaction (native from CFX Maestro, LightCycler 96, Rotor-Gene Q; via RDES/TableShaper or qPilot's vendor importers for QuantStudio/LightCycler 480 text exports) plus a plate map with known-genotype controls (optional) [5][8][3]. *Deterministic method:* (a) background and normalisation with rdmlpython's `bilinear`, `exponential` and `combined` options and explicit windows [2]; (b) optional overlay at a fluorescence level (the integral-least-squares overlay of Palais & Wittwer [25][37]); (c) difference curves against a chosen reference; (d) genotype clusters by hierarchical clustering on a pairwise curve distance (the Wittwer-lab approach described in its patent [37]; the same lab's custom software outperformed commercial software in Li 2014 [27] — that the custom software was this clustering is my inference) with the number of clusters chosen by a published criterion, and a separate Tm-only step for homozygote classes; (e) per-well confidence as the distance to the assigned cluster relative to within-cluster spread, plus leave-one-out stability (does the well keep its label when any single control is removed). *Robustness grid:* rerun (a)–(d) over normalisation windows × shift on/off and level × cluster stringency × distance metric and report, per well, the fraction of settings that give the same genotype; cards appear only for wells whose call flips. *Decision Cards:* "Normalisation window" (evidence: curves, flip map), "Shift or not" (evidence: homozygote separation lost/gained), "Number of genotypes" (evidence: cluster-separation score across k), "Ambiguous well A7" (options: assign, new cluster, exclude; consequence: per-group genotype frequencies and Hardy–Weinberg check), "Control disagreement" (a known-genotype control landed in the wrong cluster, escalate: human only). *Record:* settings, grid, calls, confidences, manual overrides with reasons, in RDML `meltTemp`/`note`/`excl` plus qPilot's hash-chained log. *Agent:* `qpcr_hrm_genotype(study, assay, settings|"grid")` returning calls with fact ids; `qpcr_hrm_explain(well)`.
5. **Feasibility.** Public maths [22][23][25][27][29]; MIT code to port or call (rdmlpython, uAnalyze-HRM) [2][34]; RDML schema [5]; CC BY in vitro and simulated curves for tests [50]; CC0 Tm table with 14 known references for a Tm-only typing test [84]. Effort: 3–5 weeks for one developer (engine 1–2, grid and cards 1, importers 1, validation 1). Hardest part: a robust, published cluster-count criterion that behaves on plates with 1, 2 or 3 genotypes and on variant scans with one odd well; and avoiding the active Bio-Rad patent's exact pipeline (7-segment means + Gaussian mixture + cluster score) [14] while the Utah clustering patent's anticipated expiry (Sept 2026) and the exponential-background continuation (anticipated 2029) are checked by counsel [37][38].
6. **Why qPilot.** It already has raw curves from RDML, a decision-space/robustness engine, impact-ranked cards, autonomy levels with escalation, and a record; HRM genotyping is the same architecture applied to melt data, and the "study-wide" framing (every plate, same method) is exactly what per-plate vendor modules lack. The domain-agnostic core means the clustering-with-robustness module is reusable for allelic discrimination (D5) and MS-HRM (D4).
7. **Risks.** Patent exposure for commercial users (Apache-2.0 grants cover contributors only); HRM publication volume is declining [86]; instrument-specific Tm precision limits what any software can do (Tm SD up to 0.274 °C [24]); users may lack raw exports if they only kept vendor `.melt` files. Confidence: **high** that the pain is real and the methods are implementable; **medium** on adoption volume.

### D2. Cross-plate, cross-run melt alignment and reference-anchored typing ("melt passports")

1. **Persona and situation.** Hospital or veterinary microbiology research lab typing isolates by multilocus HRM over months; plant breeder genotyping thousands of lines over dozens of plates; core facility comparing a client's new plate to last month's.
2. **Evidence.** HRM clustering results from different datasets are not directly comparable, so reference isolates must be included and clusters are labelled by them [64]; instrument Tm SD ranges 0.018–0.274 °C [24]; robust ΔTm discrimination about 0.2 °C on Rotor-Gene [44]; chip temperature non-uniformity corrected with a synthetic oligo of known Tm [58]; vendor "Melt Study" compares files only inside one vendor's software [12].
3. **What exists.** MeltingPlot (GPL, Tm tables in .xls, 0.5 °C link rule, reference labelling) [64][65]; vendor Melt Study [12]; otherwise Excel.
4. **Feature.** Per-assay "melt passport" in the lab memory: expected Tm and curve from the assay's own history, per instrument and reagent lot. Per-run alignment using designated calibrator wells (reference isolates or a synthetic oligo with known Tm [58]) to estimate a run temperature offset and scale; cards when a run's offset exceeds the passport tolerance or when a calibrator melts outside its band. Cross-run typing: MeltingPlot's deterministic rule (link isolates whose Tm differ ≤ δ for all amplicons; δ default 0.5 °C; split components by edge betweenness) reimplemented in Python under Apache-2.0 from the paper, with δ as a Decision Card informed by the run's calibrator spread, and with robustness over δ. *Record:* offsets, calibrator Tm, δ, cluster memberships, reference labels. *Agent:* `qpcr_melt_align(run, calibrators)`, `qpcr_melt_type(study, delta)`.
5. **Feasibility.** Algorithm fully described in a CC BY paper [64]; graph clustering available in permissive libraries (networkx, BSD); CC0 Tm table with reference samples for testing [84]; RDML `meltTemp` per reaction holds Tm [5]. Effort 2–3 weeks. Hardest: deciding how much of the shape (not just Tm) to carry across runs; MeltingPlot deliberately uses Tm only because shape is noisier [64].
6. **Why qPilot.** Study-level, multi-plate analysis is qPilot's native unit; lab memory and reagent-lot drift alerts are already on the roadmap; the record makes "which reference defined this clone" auditable.
7. **Risks.** Labs without reference isolates every run; mixing instruments may be beyond correction. Confidence: **medium–high**.

### D3. Permissive in-silico melt prediction and heterozygote composites, used as expectations and for mixture fitting

1. **Persona.** Assay developer designing an HRM or multiplex melt assay; microbiologist assigning multiplex peaks.
2. **Evidence.** uMelt is web-only, now behind a login, free for research but closed [31][32]; predicted domain structure and relative Tm are reliable but absolute Tm depends on parameters and dyes are not modelled [28]; experimental vs predicted at 50 % helicity differed by 0.04 ± 0.48 °C across 14 amplicons [29]; heteroduplexes contribute 25.7 ± 6.7 % of a heterozygote curve [30]; detectability depends on amplicon length and whether the change alters G+C [23][44]; multiplex HRM is hard [44] and solved in the literature only with ML on kinetics + melt [60] or Tm windows [63].
3. **What exists.** uMelt/uMelt HETS (web) [31]; DECIPHER MeltDNA (GPL-3, R) [80]; nothing permissive in Python; no open mixture fitter.
4. **Feature.** `qpcr_melt_predict(sequence, Na, Mg)` implementing the multi-state partition-function model (Tostesen 2003) with SantaLucia 1998 nearest-neighbour parameters [80][28] in Python under Apache-2.0, producing helicity, derivative curve and positional stability; heterozygote composite as the HETS four-duplex mixture with the published 25.7 % heteroduplex weight [30]. Uses: (i) a Decision Card at assay import — "predicted ΔTm between alleles 0.12 °C vs your instrument's historical Tm SD 0.09 °C: homozygotes may not be resolvable; consider a smaller amplicon or a snapback/unlabeled probe" [23][24]; (ii) expected `meltingTemperature` auto-filled into RDML targets for rdmlpython's peak check [2][5]; (iii) multiplex deconvolution by non-negative least squares of a well's derivative curve onto predicted or empirically learned component curves after the run-offset of D2 — a deterministic alternative to the ML multiplexing papers, exposed as a card when two components are nearly collinear.
5. **Feasibility.** Model and parameters are published; acceptance test: reproduce the CC BY uMelt-simulated curves for 92 serotypes × 9 salt conditions deposited by Athamanolap 2014 [50]. Effort 3–5 weeks (the partition function with loop entropy in near-linear time is the hard part; validate first on short amplicons where a single transition is expected [80]). Mixture fitting: scipy NNLS (BSD).
6. **Why qPilot.** Predictions become engine facts bound to cards (no naked numbers); the record stores the prediction alongside the observed curve, closing the loop the uAnalyze paper describes [29]; `qpilot plan` already asks "can this study answer the question" and this extends it to "can this assay resolve these alleles".
7. **Risks.** Absolute Tm will be off without instrument/dye calibration (acknowledged by uMelt's authors [28]); reimplementation accuracy must be proven; patents on prediction were not found but not excluded. Confidence: **medium**.

### D4. MS-HRM methylation quantification with standard-curve and heterogeneity cards

1. **Persona.** Epigenetics researcher or forensic/wildlife age-estimation lab running MS-HRM with 0/0.1/1/10/50/100 % methylated standards on every plate, reading methylation level by matching the unknown's curve to standards by eye [40][41]; wildlife and veterinary age-estimation datasets exist for cats, dolphins and elephants [82].
2. **Evidence.** Estimation is by profile similarity to standards [40]; 3 of 36 samples equivocal in a blinded imprinting study [42]; annealing temperature must be empirically tuned to avoid PCR bias [40]; heterogeneous methylation shows as a distinct shape that a Tm-only approach misreads [40]; 323 MS-HRM papers [86]; no open MS-HRM tool found (gap).
3. **What exists.** General HRM vendor software (not designed for % quantification); Excel.
4. **Feature.** Input: RDML `mdp` plus sample annotation of standards (`std` with methylation fraction) [5]. Method: Wojdacz normalisation (line of best fit through pre- and post-transition regions) [40]; per-plate calibration curve of a curve-level statistic (area under the normalised curve between the fully methylated and unmethylated standards, or fitted mixture weight by NNLS onto the two pure-standard curves) vs known methylation %, with a monotonic fit and prediction intervals; cards for "sample outside standard range", "shape not explained by a two-component mixture (heterogeneous methylation)", "standards not monotonic (PCR bias suspected)". Record: standards, fit, intervals, flags. Agent: `qpcr_mshrm_quantify(study)`.
5. **Feasibility.** Methods described in CC-licensed/open papers [40][41][43]; CC0 datasets with R scripts on Dryad for cross-checking age-estimation pipelines [82]. Effort about 2 weeks. Hardest: defining the mixture statistic so it is robust to heterogeneous methylation.
6. **Why qPilot.** Standards, groups and plate effects are already modelled for expression; the robustness grid naturally tests normalisation windows and statistic choice; the GRADE-style confidence maps to "within calibrated range".
7. **Risks.** Smaller community than HRM genotyping; PCR bias is a wet-lab problem software can only flag. Confidence: **medium**.

### D5. Allelic-discrimination (TaqMan/KASP) caller with whole-run evidence, model-based clusters and recorded re-calls

1. **Persona.** Plant breeder running KASP plates, mouse-facility technician genotyping colonies by allelic-discrimination qPCR [89], pharmacogenomics research lab genotyping DPYD-type variants with an in-house pipeline and sign-off [69].
2. **Evidence.** 1,200 PubMed papers mention TaqMan allelic discrimination [86]; vendor caller uses linear boundaries with an undetermined region and supports only FAM/VIC [17][18]; KlusterCaller is proprietary and returns "inconclusive" [71]; SNPviewer cannot change calls [70]; the only open-ish alternatives are non-commercial (SNPman) [68] or a 2004 paper's model-based clustering that flags unclear genotypes and copes with unknown cluster counts where k-means fails [67].
3. **What exists.** TaqMan Genotyper (free, closed), KlusterCaller/Kraken (closed), SNPman (non-commercial), Excel.
4. **Feature.** Input: RDML with per-dye `adp` for both reporter dyes (end point = last cycle, plus whole-run shape) [5]. Method: ROX/passive-reference normalisation (toggle, as KlusterCaller exposes [71]); Gaussian-mixture clustering with penalised likelihood on the end-point angle/amplitude space (Fujisawa 2004) [67]; whole-run consistency check per well (SNPman's idea: does the dye that "won" at the end point also show the earlier exponential rise) [68]; per-plate QC: call rate, Hardy–Weinberg deviation per population group, control concordance, NTC cluster. Decision Cards: "Undetermined wells" (options: assign to nearest cluster with stated posterior, leave undetermined, re-run; consequence: allele frequencies), "Clusters not separated (mixture overlap)", "Control mismatch" (human only). Robustness: calls under 2 vs 3 cluster models, with and without ROX normalisation. Record and agent: `qpcr_snp_call(study, assay)`.
5. **Feasibility.** Mixture models in scikit-learn (BSD); methods published [67][68]; validation data: SNPman demo data on SourceForge (licence check needed), or generate from the team's own plates. Effort 2–3 weeks. Hardest: dye crosstalk differences across instruments; KASP (FAM/HEX) vs TaqMan (FAM/VIC) dye names in RDML.
6. **Why qPilot.** Same engine as D1 (clusters + confidence + grid + cards); end-point genotyping plates are the second-most common qPCR use after expression, so this widens qPilot's audience to breeders and colony managers; the hash-chained log answers the sign-off need described for pharmacogenomics programmes [69].
7. **Risks.** Vendor free tools are "good enough" for many; breeders' plates may live in LGC's Kraken ecosystem. Confidence: **medium–high**.

### D6. An open HRM benchmark and a deterministic "never-seen genotype" card

1. **Persona.** Method developers and reviewers; any lab wanting to know whether a well is a new variant rather than a bad fit to known clusters.
2. **Evidence.** ML HRM papers rarely share data (data on request [52]; Europe PMC records show no repositories [90]); novelty detection reached Youden 0.92 (sensitivity and specificity 0.96) on digital HRM [52] and open-set recognition was needed for 57 of 64 untrained CALR variants [57]; variant scanning's purpose is finding unknowns [26].
3. **What exists.** CC BY simulated and in vitro curves [50]; dHRM CSVs on GitHub without a licence [53]; CC0 Tm tables [84]; RDML example with 7,380 melt points [7]; no cross-instrument benchmark with sequencing truth.
4. **Feature.** (i) Publish a CC0 "qPilot-HRM-bench" assembled from the licensable sets above plus the team's own plates with Sanger-confirmed truth, in RDML with `meltTemp` and genotype annotations; (ii) a deterministic open-set rule in D1: a well is "unassigned/novel" when its distance to every cluster exceeds a threshold calibrated by leave-one-out on the plate's controls, surfaced as a card with the robustness fraction; (iii) a public acceptance test that any future ML method module must pass.
5. **Feasibility.** Mostly data curation; 1–2 weeks initial. Hardest: obtaining sequencing truth for enough homozygous pairs.
6. **Why qPilot.** Already validates publicly against the RDML benchmark and plans an open commons of records; a versioned method module with a public acceptance test is the stated rule for any ML.
7. **Risks.** Small initial dataset; licensing of GitHub data without a stated licence (ask the authors). Confidence: **medium**.

### D7. Melt-informed quantification corrections (lower priority, builds on the existing melt-peak roadmap item)

1. **Persona.** Expression labs using SYBR/EvaGreen whose wells show primer-dimer or secondary peaks.
2. **Evidence.** rdmlpython already computes, for saturating dyes, a per-reaction correction factor `corrF` = fluorescence share of the expected peak and a `corrCq` placeholder, and writes exclusion/note texts for wells with no expected product, products at different Tm, several products, or product in negative controls [2]; RDML-Tools excludes multi-product reactions from further analysis [3].
3. **What exists.** rdmlpython CLI (MIT) and the GPL web tool; vendor software shows peaks but does not correct Cq.
4. **Feature.** Surface `corrF` and the four note types as per-well facts; a Decision Card "exclude or correct wells with secondary products" with the per-gene consequence under both choices in the robustness grid; record the choice.
5. **Feasibility.** Mostly wiring; 1 week. Hardest: verifying how LinRegPCR consumes `corrF` (not confirmed in this session).
6. **Why qPilot.** Uses the same MIT library already in the engine.
7. **Risks.** Overlaps the existing "melt-peak checks" headline; include only as the deeper, concrete version. Confidence: **medium**.

---

## 4. Data, libraries, standards, licences found

| Item | What | Licence | URL |
|---|---|---|---|
| rdmlpython | RDML library + LinRegPCR + `meltCurveAnalysis` | MIT | https://github.com/RDML-consortium/rdmlpython ; https://pypi.org/project/rdmlpython/ |
| RDML-Tools (web) | RDML-Edit/RunAnalysis incl. MeltingCurveAnalysis tab, RDES-TableShaper | GPL-3 | https://github.com/RDML-consortium/rdml-tools ; https://www.gear-genomics.com/rdml-tools/help.html |
| RDML v1.3 schema, example | `mdp`/`tmp`/`fluor`/`meltTemp`/`meltingTemperature` | Open standard | https://rdml.org/files/rdml/RDML_v1_3_REC.xsd ; https://rdml.org/files/rdml/example_1_3.rdml |
| RDML compliant instruments/software lists | CFX Maestro 1.1, LightCycler 96 1.1, Rotor-Gene Q 1.1, MyGo 1.2; Clarida viewer 1.3, Primer3Plus 1.3, LinRegPCR 1.2 | — | https://rdml.org/instruments.html ; https://rdml.org/software.html |
| uAnalyze-HRM | JS HRM normalisation/overlay/difference/clustering; 8 instrument formats | MIT (2026) | https://github.com/zachdwight/uAnalyze-HRM |
| uMelt Quartz / uMelt HETS / uAnalyze (web) | Curve prediction and analysis | Free for research with citation; login now required; no source | https://www.dna-utah.org/ |
| MBmca | Tm/peak functions; melt datasets DMP, DualHyb, MultiMelt | GPL (≥ 2) | https://cran.r-project.org/package=MBmca |
| qpcR | `meltcurve()` | GPL-2/3 | https://cran.r-project.org/package=qpcR |
| chipPCR / PCRedux | Amplification-curve preprocessing / features (no melt) | GPL-3 / MIT | https://cran.r-project.org/package=chipPCR ; https://cran.r-project.org/package=PCRedux |
| RDML (R) | RDML import for qpcR/chipPCR | MIT | https://cran.r-project.org/package=RDML |
| DECIPHER::MeltDNA | Melt-curve simulation (Tostesen 2003; SantaLucia 1998) | Bioconductor (licence not confirmed here) | https://rdrr.io/bioc/DECIPHER/man/MeltDNA.html |
| MeltR | Absorbance melting / binding isotherm fitting (not HRM) | MIT | https://github.com/JPSieg/MeltR |
| MeltingPlot | Graph-based HRM typing from Tm tables | GPL | https://github.com/MatteoPS/MeltingPlot |
| dHRM-novelty-detection | Notebooks + CSV derivative melt curves for 10 species + synthetic sets | No licence shown | https://github.com/aboussina/dHRM-novelty-detection ; https://github.com/lenlan/dHRM-novelty-detection/tree/master/Data |
| Athamanolap 2014 supplementary S1–S8 | Amplicon sequences, uMelt-simulated curves (92 serotypes × 9 conditions), in vitro curves | CC BY | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0109094 |
| Dryad: *Amphicarpaea* HRM Tm table | 8 loci × 90 samples, 14 references | CC0 | https://doi.org/10.5061/dryad.12g7j |
| Dryad: MS-HRM age estimation (cat/snow leopard; dolphin; elephant) | Raw CSV + R scripts | CC0 | https://doi.org/10.5061/dryad.66t1g1k2t ; https://doi.org/10.5061/dryad.9zw3r22kr ; https://doi.org/10.5061/dryad.qjq2bvqnb |
| Dryad: Culex multiplex qPCR + HRM (2024) | Files not listed in API | CC0 | https://doi.org/10.5061/dryad.vt4b8gv2b |
| Zenodo: Actinobacillus 19-serovar HRM tables | Two supplementary xlsx | CC BY 4.0 | https://doi.org/10.5281/zenodo.6045374 |
| SNPman | TaqMan calling from whole-run data | Free for non-commercial use (not permissive) | https://pubmed.ncbi.nlm.nih.gov/21697130/ |
| TaqMan Genotyper v1.7.1 | Closed, free | Vendor EULA | https://www.thermofisher.com/us/en/home/technical-resources/software-downloads/taqman-genotyper-software.html |
| Patents to check | US 8,296,074 (clustering/overlay/exp. background; anticipated expiry 2026-09-20), US 8,068,992 (exp. background; "Active – Reinstated", anticipated 2029-02-01), US 7,582,429 (saturation dyes; expired 2025-12-08), US 8,606,527 (Bio-Rad clustering; to 2032-04-30) | — | https://patents.google.com/patent/US8296074B2/en ; https://patents.google.com/patent/US8068992B2/en ; https://patents.google.com/patent/US7582429B2/en ; https://patents.google.com/patent/US8606527B2/en |

---

## 5. Open questions and what I could not verify

- **Prices** of Bio-Rad Precision Melt (1845025/1845015), Roche Gene Scanning, Agilent AriaMx HRM and current Thermo HRM modules: all behind logins or unreachable.
- **Current Thermo QuantStudio HRM module** (Design & Analysis 2 / Connect) documentation and how its confidence/variant call is defined; whether QuantStudio exports include melt in RDML.
- **ScreenClust, LightScanner and Call-IT** current availability; Qiagen and BioFire pages 404.
- **Roche LightCycler 480 Gene Scanning** auto-grouping parameters and licence model.
- **Whether CFX Maestro / LightCycler 96 / Rotor-Gene RDML 1.1 exports contain `mdp`** (the schema allows it; not confirmed per vendor).
- **Legal status of the Utah HRM analysis patents** (Google's "Active" and expiry dates are stated as assumptions); the uAnalyze page's note about bioMérieux sublicensing suggests a live licensing programme; get counsel before distributing exponential-background or overlay code with commercial users in mind.
- **Forum evidence** of pains (Reddit, Biostars, ResearchGate, Stack Exchange) could not be collected; the pain inventory relies on manuals, patents and papers.
- **Zenodo/figshare coverage** of HRM datasets is incomplete (rate limiting; search endpoint noise).
- **DECIPHER licence** not confirmed on the page fetched.
- **Full texts** of Palais 2009, Erali 2010 (bot-blocked), Simko 2016, Druml 2014, Vossen 2009, Herrmann 2007 (paywalled or not fetched).
- **Any HRM reporting guideline** (none found); whether MIQE 2.0 has melt-specific items.
- **Melio Labs** status (domain for sale; no statement found).

---

## 6. Sources

1. rdmlpython README (MIT; `-mca` CLI options) — https://github.com/RDML-consortium/rdmlpython
2. rdmlpython `rdml.py` source: `meltCurveAnalysis` signature, peak logic, RDML write-back texts, result columns — https://raw.githubusercontent.com/RDML-consortium/rdmlpython/master/rdml.py
3. RDML-Tools help (MeltingCurveAnalysis tab; RDES melt import; licensing statement) — https://www.gear-genomics.com/rdml-tools/help.html
4. RDML-Tools GitHub (GPL-3.0) — https://github.com/RDML-consortium/rdml-tools
5. RDML v1.3 schema (XSD) — https://rdml.org/files/rdml/RDML_v1_3_REC.xsd
6. RDML v1.3 page (REC 26.10.2022; files) — https://rdml.org/rdml_v_1_3.html
7. RDML v1.3 example file (inspected locally: 90 reactions, 3,420 `adp`, 7,380 `mdp`, 0 `meltTemp`, 5 `meltingTemperature`, SYBR Green I) — https://rdml.org/files/rdml/example_1_3.rdml
8. RDML compliant instruments — https://rdml.org/instruments.html
9. RDML compliant software — https://rdml.org/software.html
10. rdmlpython on PyPI (1.7.2, 22 May 2023, MIT) — https://pypi.org/project/rdmlpython/
11. Bio-Rad Precision Melt Analysis Software product page — https://www.bio-rad.com/en-us/product/precision-melt-analysis-software?ID=df190aee-f184-497e-bfb6-b6dd632c99b5
12. Bio-Rad Precision Melt Analysis Software User Guide, 10000080911 Ver A (2017) — https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/10000080911.pdf
13. Bio-Rad Bulletin 5798 (software flier) — https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/Bulletin_5798.pdf
14. US 8,606,527 B2, "SNP detection by melt curve clustering" (Bio-Rad) — https://patents.google.com/patent/US8606527B2/en
15. Thermo Fisher catalog 4397808, High Resolution Melt (HRM) Software v2.0 (not orderable) — https://www.thermofisher.com/order/catalog/product/4397808
16. Thermo Fisher MeltDoctor HRM Master Mix (cat. 4409535) page and FAQs — https://www.thermofisher.com/order/catalog/product/4409535
17. Thermo Fisher TaqMan Genotyper Software page — https://www.thermofisher.com/us/en/home/technical-resources/software-downloads/taqman-genotyper-software.html
18. TaqMan Genotyper v1.7.1 Release Notes (PDF) — https://downloads.thermofisher.com/Taqman_Genotyper/v1.7.1/100121672_RevA_Taqman%20Genotyper_v1.7.1_Release%20Note.pdf
19. gene-quantification.de HRM resource page — https://www.gene-quantification.de/hrm.html
20. Reja V et al. 2010, ScreenClust, Methods (PMID 20146938) — https://pubmed.ncbi.nlm.nih.gov/20146938/
21. Roth AL et al. 2013, KPC variants by HRM + ScreenClust, J Clin Microbiol (PMID 23077125) — https://pubmed.ncbi.nlm.nih.gov/23077125/
22. Wittwer CT et al. 2003, Clin Chem (PMID 12765979) — https://pubmed.ncbi.nlm.nih.gov/12765979/
23. Reed GH, Wittwer CT 2004, Clin Chem (PMID 15308590) — https://pubmed.ncbi.nlm.nih.gov/15308590/
24. Herrmann MG et al. 2006, Clin Chem (PMID 16423901) — https://pubmed.ncbi.nlm.nih.gov/16423901/
25. Palais R, Wittwer CT 2009, Methods Enzymol (PMID 19216933) — https://pubmed.ncbi.nlm.nih.gov/19216933/
26. Erali M, Wittwer CT 2010, Methods (PMID 20085814; PMC2836412) — https://pubmed.ncbi.nlm.nih.gov/20085814/
27. Li M, Zhou L, Palais RA, Wittwer CT 2014, Clin Chem (PMID 24718912) — https://pubmed.ncbi.nlm.nih.gov/24718912/
28. Dwight Z, Palais R, Wittwer CT 2011, uMELT, Bioinformatics (PMID 21300699) — https://pubmed.ncbi.nlm.nih.gov/21300699/
29. Dwight ZL et al. 2012, uAnalyze, IEEE/ACM TCBB (PMID 22889837) — https://pubmed.ncbi.nlm.nih.gov/22889837/
30. Dwight ZL et al. 2014, heterozygote melting curve prediction (uMelt HETS), Hum Mutat (PMID 24375593) — https://pubmed.ncbi.nlm.nih.gov/24375593/
31. DNA Utah (Wittwer lab) tools page — https://www.dna-utah.org/
32. uMelt Quartz login page — https://www.dna-utah.org/umelt/quartz/um.php
33. uAnalyze page (formats, GitHub link, patent note) — https://www.dna-utah.org/uv/uanalyze.html
34. uAnalyze-HRM GitHub repository — https://github.com/zachdwight/uAnalyze-HRM
35. uAnalyze-HRM README — https://raw.githubusercontent.com/zachdwight/uAnalyze-HRM/main/README.md
36. uAnalyze-HRM LICENSE (MIT, 2026 Zachary Dwight) — https://raw.githubusercontent.com/zachdwight/uAnalyze-HRM/main/LICENSE
37. US 8,296,074 B2, "Melting curve analysis with exponential background subtraction" (Utah) — https://patents.google.com/patent/US8296074B2/en
38. US 8,068,992 B2 (Utah; continuation) — https://patents.google.com/patent/US8068992B2/en
39. US 7,582,429 B2, "Amplicon melting analysis with saturation dyes" — https://patents.google.com/patent/US7582429B2/en
40. Wojdacz TK, Dobrovic A 2007, MS-HRM, Nucleic Acids Res (PMC1874596) — https://pmc.ncbi.nlm.nih.gov/articles/PMC1874596/
41. Wojdacz TK et al. 2008, MS-HRM, Nat Protoc (PMID 19180074) — https://pubmed.ncbi.nlm.nih.gov/19180074/
42. Wojdacz TK et al. 2008, H19 imprinting MS-HRM, Hum Mutat (PMID 18473334) — https://pubmed.ncbi.nlm.nih.gov/18473334/
43. Hussmann D, Hansen LL 2018, MS-HRM, Methods Mol Biol (PMID 29224163) — https://pubmed.ncbi.nlm.nih.gov/29224163/
44. Tong SY, Giffard PM 2012, J Clin Microbiol (PMC3486245) — https://pmc.ncbi.nlm.nih.gov/articles/PMC3486245/
45. Simko I 2016, Trends Plant Sci (PMID 26827247) — https://pubmed.ncbi.nlm.nih.gov/26827247/
46. Druml B, Cichna-Markl M 2014, Food Chem (PMID 24731338) — https://pubmed.ncbi.nlm.nih.gov/24731338/
47. Osathanunkul M et al. 2015, Bar-HRM Acanthaceae, PLoS One (PMID 26011474) — https://pubmed.ncbi.nlm.nih.gov/26011474/
48. Osathanunkul M et al. 2018, Bar-HRM soursop tea, Sci Rep (PMID 30139965) — https://pubmed.ncbi.nlm.nih.gov/30139965/
49. Osathanunkul M et al. 2019, Bar-HRM ginseng, PeerJ (PMID 31579587) — https://pubmed.ncbi.nlm.nih.gov/31579587/
50. Athamanolap P et al. 2014, trainable HRM ML classifier, PLoS One (CC BY; data in supplementary) — https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0109094
51. Fraley SI et al. 2016, nested ML HRM genotyping, Sci Rep (PMID 26778280) — https://pubmed.ncbi.nlm.nih.gov/26778280/
52. Boussina A et al. 2024, ML melt-curve profiling with novel genotype detection, BMC Bioinformatics (PMC11088152; CC BY 4.0; full text via Europe PMC) — https://pmc.ncbi.nlm.nih.gov/articles/PMC11088152/
53. dHRM-novelty-detection code and data — https://github.com/aboussina/dHRM-novelty-detection ; https://github.com/lenlan/dHRM-novelty-detection/tree/master/Data
54. Ozkok FO et al. 2021, CNN on recurrence plots for HRM, Comput Methods Programs Biomed (PMID 34029831) — https://pubmed.ncbi.nlm.nih.gov/34029831/
55. Promja S et al. 2023, ML-assisted qPCR-HRM SARS-CoV-2 variants, Anal Chem (PMID 36633573) — https://pubmed.ncbi.nlm.nih.gov/36633573/
56. Wisittipanit N et al. 2020, ML + modified HRM Salmonella subtyping (PMID 32613458) — https://pubmed.ncbi.nlm.nih.gov/32613458/
57. Zhang Q et al. 2026, AI-based HRM for CALR screening, Int J Lab Hematol (PMID 42151105) — https://pubmed.ncbi.nlm.nih.gov/42151105/
58. Traylor A et al. 2024, oligonucleotide temperature calibration for digital melt, Anal Chim Acta (PMID 38438240) — https://pubmed.ncbi.nlm.nih.gov/38438240/
59. Dai X et al. 2025, digital melting curve analysis on ddPCR, Biosensors (PMID 39852087) — https://pubmed.ncbi.nlm.nih.gov/39852087/
60. Moniri A et al. 2020, high-level multiplexing in dPCR with intercalating dyes (AMCA), Anal Chem (PMID 32954724) — https://pubmed.ncbi.nlm.nih.gov/32954724/
61. Prasetyo AP et al. 2023, closed-tube barcoding of sharks and rays, iScience (PMID 37389182) — https://pubmed.ncbi.nlm.nih.gov/37389182/
62. Kesmen Z et al. 2020, MFMAS lactobacilli identification, J Microbiol Methods (PMID 32890569) — https://pubmed.ncbi.nlm.nih.gov/32890569/
63. Singh L et al. 2024, multiplex HRM Fusarium chemotypes, Sci Rep (PMID 39738214; CC BY) — https://pubmed.ncbi.nlm.nih.gov/39738214/
64. Perini M et al. 2021, MeltingPlot, BMC Bioinformatics (PMC7891011; CC BY; full text via Europe PMC) — https://pmc.ncbi.nlm.nih.gov/articles/PMC7891011/
65. MeltingPlot GitHub — https://github.com/MatteoPS/MeltingPlot
66. MeltingPlot web tool — https://skynet.unimi.it/index.php/tools/meltingplot/
67. Fujisawa H et al. 2004, SNP genotyping by model-based clustering, Bioinformatics (PMID 14751987) — https://pubmed.ncbi.nlm.nih.gov/14751987/
68. Konopac M et al. 2011, SNPman, Bioinformatics (PMID 21697130) — https://pubmed.ncbi.nlm.nih.gov/21697130/
69. Virk H et al. 2026, in-house DPYD genotyping programme, Am J Clin Pathol (PMID 42803377) — https://pubmed.ncbi.nlm.nih.gov/42803377/
70. LGC Biosearch SNPviewer — https://www.biosearchtech.com/support/tools/genotyping-software/snpviewer
71. LGC Biosearch KlusterCaller — https://www.biosearchtech.com/support/tools/genotyping-software/klustercaller
72. CRAN MBmca — https://cran.r-project.org/package=MBmca
73. MBmca function index (rdrr.io) — https://rdrr.io/cran/MBmca/
74. CRAN qpcR — https://cran.r-project.org/package=qpcR
75. qpcR `meltcurve` documentation — https://rdrr.io/cran/qpcR/man/meltcurve.html
76. CRAN chipPCR — https://cran.r-project.org/package=chipPCR
77. CRAN PCRedux — https://cran.r-project.org/package=PCRedux
78. CRAN RDML — https://cran.r-project.org/package=RDML
79. CRAN HRM (unrelated: high-dimensional repeated measures) — https://cran.r-project.org/package=HRM
80. DECIPHER `MeltDNA` documentation — https://rdrr.io/bioc/DECIPHER/man/MeltDNA.html
81. MeltR GitHub (MIT) — https://github.com/JPSieg/MeltR
82. Dryad API search for HRM datasets — https://datadryad.org/api/v2/search?q=%22high%20resolution%20melting%22%20HRM&per_page=25
83. Zenodo API search for HRM datasets — https://zenodo.org/api/records?q=HRM%20melting%20curves%20genotyping&size=25
84. Dryad dataset: *Amphicarpaea bracteata* HRM Tm table (CC0) — https://datadryad.org/api/v2/datasets/doi%3A10.5061%2Fdryad.12g7j
85. Zenodo record 10.5281/zenodo.22134778 (Cq spreadsheet + PNG plots; CC BY 4.0) — https://zenodo.org/api/records?q=doi%3A%2210.5281%2Fzenodo.22134778%22
86. PubMed E-utilities counts (17 Oct 2026), e.g. total HRM: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=%22high+resolution+melting%22%5BTitle%2FAbstract%5D+OR+%22high-resolution+melting%22%5BTitle%2FAbstract%5D+OR+%22high+resolution+melt%22%5BTitle%2FAbstract%5D&rettype=count ; the same term AND 2010[dp] / 2015[dp] / 2020[dp] / 2024[dp]; MS-HRM: ("methylation-sensitive high resolution melting" OR "MS-HRM"); subject counts with (plant OR cultivar OR crop OR breeding), (food OR adulteration OR authentication), (bacteria OR bacterial OR fungal OR parasite OR "species identification" OR typing), (veterinary OR canine OR bovine OR livestock OR cattle OR dog OR pig OR poultry); allelic discrimination: ("allelic discrimination" AND TaqMan); ML: HRM/melt terms AND ("machine learning" OR "deep learning" OR "neural network" OR convolutional) AND 2020:2026[dp] (33 hits, triaged by title); deconvolution: melt-curve terms AND (deconvolution OR deconvolve OR "peak fitting") AND PCR (0 hits)
87. Melio Labs domain (redirects to a domain-for-sale page) — https://meliolabs.com/
88. Bruzzone CM et al. 2013, HRM optimisation with synthetic templates, Genet Test Mol Biomarkers (PMID 23790024) — https://pubmed.ncbi.nlm.nih.gov/23790024/
89. Mansoori B et al. 2026, allelic discrimination qPCR genotyping of Winnie mice, STAR Protoc (PMID 41966827) — https://pubmed.ncbi.nlm.nih.gov/41966827/
90. Europe PMC records for licence/data flags of PMIDs 38730317, 36633573, 34029831, 39738214, 42151105, 32613458, 20085814, 26827247 — https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:38730317%20OR%20EXT_ID:34029831%20OR%20EXT_ID:36633573&resultType=core&format=json ; https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:39738214%20OR%20EXT_ID:42151105%20OR%20EXT_ID:32613458%20OR%20EXT_ID:20085814%20OR%20EXT_ID:26827247&resultType=core&format=json
91. Osathanunkul M et al. 2018, Bar-HRM Ophiocordyceps, Sci Rep (PMID 30143746) — https://pubmed.ncbi.nlm.nih.gov/30143746/
92. Osathanunkul M et al. 2016, Bar-HRM Uvaria, Genet Mol Res (PMID 26909907) — https://pubmed.ncbi.nlm.nih.gov/26909907/
