# 02 — Primer/probe (assay) design, validation and lifetime management for qPCR

Researcher notes for the qPilot niche-discovery effort. Written 17 Oct 2026 for two software/AI developers; biology terms are defined on first use. Citations are `[n]` → numbered Sources list at the end (URLs there). Where a number is an estimate I say so. Where I could not verify something I put it in Open questions.

Method note: ~35 web searches (the shared search budget then ran out), ~70 page fetches, and local text extraction of three PDFs (MIQE 2.0 full text, Bio-Rad PrimePCR validation bulletin 6262, Svec 2015, Bio-Rad Real-Time PCR Applications Guide). ResearchGate, Reddit and Biostars pages returned 403/blocked, so forum evidence is thinner than I wanted; vendor pages (IDT PrimeTime, Sigma KiCqStart, OriGene qSTAR, Benchling) partly failed to load. These gaps are listed in section 5.

---

## 1. How this corner of the niche works

### 1.1 Vocabulary (minimum needed to read the rest)

- **Assay** = one primer pair (forward + reverse, ~18–24-nt DNA oligos) plus optionally a fluorescent **probe**, which together amplify one short **amplicon** (50–200 bp) from one **target** (a gene/transcript). "Assay", "primer pair" and "primer set" are used interchangeably at the bench.
- **Tm** = melting temperature of an oligo or amplicon; **ΔG** = free energy of an unwanted structure (hairpin, primer-dimer). Lower (more negative) ΔG = more stable = worse.
- **Efficiency (E)**: how much product doubles per cycle. Written as 1.9 (fold/cycle) or 90 %. Textbook acceptance window 90–110 % [1][20]. Measured two ways: from a **standard curve** (10-fold dilution series; E = 10^(−1/slope) − 1) or from the slope of each individual amplification curve (LinRegPCR "window of linearity", which qPilot already uses) [1].
- **LOD / LLOQ / ULOQ**: limit of detection (smallest amount reliably detected, usually at 95 %), lower/upper limits of quantification [1]. Poisson statistics mean LOD can never be below 3 copies and LLOQ of a good assay is ~10 copies; at 90 % efficiency that is Cq ≈ 35 (LLOQ) and 37 (LOD) [1].
- **Cq**: quantification cycle (older "Ct"). **NTC** = no-template control (water instead of sample). **No-RT / NRT** = sample without reverse transcriptase, to detect genomic DNA (gDNA) contamination.
- **Melt curve / dissociation curve**: after amplification the product is heated and fluorescence drop recorded; the negative first derivative shows a peak at the amplicon Tm. "Single peak" is the usual (and insufficient, see 1.6) evidence of specificity for SYBR-type dyes.
- **Exon–exon junction spanning / intron spanning**: designing the primer pair so it only amplifies spliced mRNA (cDNA) and not gDNA. **Isoform / splice variant**: alternative transcripts of the same gene; a pair may amplify only some. **Processed pseudogene**: an intron-less genomic copy of a gene; intron-spanning primers do not protect against it [1][63].
- **SNP / MAF**: single-nucleotide polymorphism and its minor-allele frequency. A SNP under a primer makes a **mismatch** between primer and template in some samples.
- **Context sequence**: for commercial assays whose oligo sequences are secret (Thermo TaqMan), the vendor gives the amplicon or probe-centred sequence instead [14]. **Assay ID**: vendor catalogue identifier; Thermo states the oligo sequences behind an Assay ID never change [14].
- **Lot / batch**: each synthesis of an oligo is a new lot. **Resuspension**: dried oligo dissolved (typically to 100 µM stock in TE buffer) then diluted to working stocks (e.g. 10 µM) and aliquoted [22][23].

### 1.2 Roles and a typical assay's life

1. **Design** (PhD student / postdoc, hours to a day): pick the gene and transcript; run NCBI Primer-BLAST (web only) or a vendor tool; or buy a pre-designed assay (Thermo TaqMan, Bio-Rad PrimePCR, IDT PrimeTime, Sigma KiCqStart, OriGene qSTAR; Roche UPL until end-2020 [12]); or copy a pair from a paper, PrimerBank or a colleague's spreadsheet.
2. **In-silico checks** (minutes, often skipped): specificity against transcriptome/genome, exon-junction status, SNPs, hairpins/dimers, isoform coverage. MIQE 2.0 lists all of these as design expectations [1].
3. **Order** (lab manager): oligos from IDT/Sigma/Thermo/Eurofins; delivered dry; a packing slip is signed and filed (one university describes signing, dating and writing the budget number on the slip [69]).
4. **Resuspend, aliquot, store** (student): 100 µM stock, 10 µM working aliquots at −20 °C [22][23]. Tube labels and a spreadsheet are the usual registry ("check the lab primer sheet before designing; name as species-gene-direction-positions, e.g. mm-SREBF1-FWD-127-254" [67]).
5. **Validate** (student, half a day to a week): 10-fold dilution series (≥5 points, ≥3 replicates per point per MIQE 2.0 [1]; "at least 5 dilutions at 1:10, duplicates minimum" per a vendor FAQ [57]); accept 90–110 % (Bio-Rad's 2006 guide said 90–105 % and R² > 0.980 [20]; PrimePCR targets 90–110 %, r² > 0.99 [18]); melt curve single peak; NTC clean; no-RT; sometimes a gel or sequencing.
6. **Use** for months to years across many plates, instruments and people.
7. **Re-order / new lot / resynthesis**; freeze-thaw; new master-mix kit lot; new instrument. MIQE 2.0: "revalidate assays when new batches of reagents, primers, or probes are introduced" and "optimization and validation of assays must be repeated when changing kits or suppliers and verified when changing batches" [1].
8. **Loss**: the student leaves; the spreadsheet, the validation plate and the reason a pair was chosen leave with them. (Direct forum evidence for this is in the Gaps; the lab-protocol pages above are indirect evidence that labs build their own primer sheets and naming rules to survive turnover [67][68].)
9. **Publication**: MIQE 2.0 section 1 asks for bioinformatics tools/versions/settings, gene symbol + accession, amplicon location and length, sequences (or context sequence for commercial assays), modifications, oligo manufacturer, optimisation details [1]. Audits show most of this is not reported (1.5).

### 1.3 Tools used today and what each checks

| Tool | Engine / licence | Checks it does | Checks it does not do / limits |
|---|---|---|---|
| NCBI Primer-BLAST [5][6] | Primer3 2.5.0 inside; BLAST + global alignment; web only | Options verbatim: "Primer must span an exon-exon junction", "Exon junction match (Min 5' match / Min 3' match / Max 3' match)", "Intron inclusion … separated by at least one intron", "Intron length range", "Allow primer to amplify mRNA splice variants", "SNP handling: Primer binding site may not contain known SNP", specificity "Primer must have at least N total mismatches to unintended targets, including at least M mismatches within the last K bps at the 3' end", databases RefSeq mRNA / RefSeq representative genomes / nr / custom, organism, salt/Mg/dNTP Tm settings, "Max primer pairs to screen" | SNP avoidance works only for human RefSeq [7]; no official API (the R package primerTree drives the website and "may break if NCBI changes the site" [8]); no isoform-coverage fraction; no pseudogene flag beyond hits list |
| Primer3 / Primer3Plus [9][10] | C library; **GPL-2.0**; web help: linking or including Primer3 forces GPL2 on your code [10] | Tm (nearest-neighbour), hairpin/homo/heterodimer ΔG (ntthal), 3' end stability, candidate ranking | No genome specificity, no SNP, no isoform |
| primer3-py [11] | Python bindings; **GPL-2.0** (PyPI metadata GPLv2) | calc_tm, calc_hairpin, design | Same licence problem |
| Thermo TaqMan Gene Expression assays [14][15][16][17] | Closed pipeline, "up-to-date annotations" | Vendor shows RefSeq accession, amplicon length, probe location, exon–exon boundary, assay map; context sequence for MIQE; lot-to-lot spec "< 0.6 Ct" (one FAQ says 0.5) [16]; efficiency "90–110 % across 5 logs" claimed [16]; "several hundred" assays tested, "we do not functionally test all" [17] | Oligo sequences withheld ("we don't share the specific oligo sequences" [14]); guarantee page says nothing about efficiency [15]; no public API for assay search |
| Bio-Rad PrimePCR (designed with Biogazelle) [18][19] | Closed; wet-lab validated | Every assay run ≥10 reactions: cDNA, NTC, gDNA, 7-point 10-fold series 20–20 M copies; accept r² > 0.99 and 90–110 %; amplicons verified by massively parallel sequencing; NTC Cq < 35 → redesign; spike-in control on every plate; "a large majority of assays actually fall between 95 and 105 %" [18] | Human/mouse/rat; SYBR; only on Bio-Rad reagents/instruments as validated; validation sheets per assay on bio-rad.com (I did not fetch one) |
| IDT PrimerQuest / PrimeTime (press and product summaries) [24] | Closed web tools (PrimerQuest page did not load) | Claims: designs across exon junctions, "checks each sequence against up-to-date SNP and intron/exon junction locations", cross-react search, 90 % efficiency or free redesign | Human/mouse/rat; claims not independently verified |
| Roche Universal ProbeLibrary (UPL) [12][13] | Discontinued | 165 LNA probes + Assay Design Center | Phased out end-2020, Assay Design Center off 31 Dec 2020; labs stranded ("Our lab is in the same situation, so we have recreated this software as a freely available web app" [13]) |
| Beacon Designer (Premier Biosoft) [71] | Commercial desktop; free online edition needs Flash | Hairpins/dimers; BLAST cross-homology; multiplex cross-compatibility | No SNP/exon statements on product page |
| Geneious [70] | Commercial desktop (engine not named on page) | Tm, hairpins, dimers; "Test with Saved Primers" flags off-target sites; primer database import (FASTA/spreadsheet/GenBank) | Engine not stated; not open |
| Benchling | Could not load help page | — | Unverified here |
| PrimerBank [29] | Web DB, MGH | 306,800 human/mouse primers; mouse set: 26,855 pairs tested by qPCR + gel + sequencing, 82.6 % success | Page "last modified 1 Oct 2006"; no download/API; no efficiency values shown; no licence stated |
| RTPrimerDB [30] | Dead | — | rtprimerdb.org now 301-redirects to a vendor's nursing-omics site with empty statistics |
| qPrimerDB 2.0 (NAR 2025) [28] | Web DB; in-silico | 1,172 organisms; 429.8 M primer pairs; in-silico PCR specificity; 3' ΔG ≥ −9 kcal/mol; hairpin/dimer ΔG; exon count; SNP flags "when variation information is accessible" | No experimental validation counts; no bulk download or licence found; home page content not rendered |
| GETPrime 2.0 (EPFL, NAR 2017) [27] | Web DB + REST API (documented, but host bbcftools.epfl.ch did not resolve on 17 Oct 2026) | Gene- vs transcript-specific pairs; isoform-coverage fraction per pair; dbSNP v145 overlay: **>80 % of human primers overlap a documented variant, ~3 SNPs per primer**; 13 species; TSV download | SNPs for human/mouse only; no licence stated; availability uncertain |
| openPrimeR, rprimer, DECIPHER (Bioconductor) [32][33][34] | **GPL-2 / GPL-3 / GPL-3** | Multiplex/degenerate design; set-cover | Copyleft |
| MFEprimer 3/4 [39] | Binary-only distribution; "free to use" for non-profit and commercial, licence not named | k-mer thermodynamic specificity, dimers, hairpins, pan-genome check | Not open source as far as I could find |
| uMELT Quartz [74] | Web only; "we do not provide source code" | Predicts melt curves/Tm from amplicon sequence; cited by MIQE 2.0 | API "on request"; registration coming |

Permissive building blocks that exist (details and licences in section 4): seqfold (MIT, hairpin MFE, no heterodimers) [35]; `primers` (MIT, simple design on seqfold) [36]; seqkit `amplicon` (MIT, in-silico PCR with mismatch budget, "mismatch location (5' or 3') is not controlled") [37]; ThermonucleotideBLAST (BSD-3, nearest-neighbour Tm/ΔG for primer pairs ± probe against FASTA/BLAST DBs, hetero/homodimer, in-silico PCR with Tm thresholds) [38]; Biopython `MeltingTemp.Tm_NN` (SantaLucia 1998/2004 tables, internal/terminal mismatch and dangling-end tables, Owczarzy salt/Mg corrections, template strand with mismatches) [41].

### 1.4 Standards

- **MIQE 2.0** (Bustin et al., Clin Chem 2025) [1]: design guidance (NN Tm, ΔTm < 3 °C, 18–24 nt, 40–60 % GC, avoid repeats; "review sequence variation at potential primer and probe sites using variant databases or genome browsers"; "Variation at the 3' end of primers will likely hinder amplification"; pseudogenes "usually lack introns, and residual genomic DNA may be amplified even when using intron spanning primers"; exon–exon spanning recommended; design 2–3 alternative primers and test combinations). Validation: efficiency, linearity, dynamic range, LOD, LOQ; standard curve ≥3 replicates per step, 4–5 orders of magnitude, confidence intervals reported; individual-curve efficiency allowed and "the mean efficiency extracted from individual curves … provides the most sensitive and precise efficiency-corrected target quantification"; re-validate on new batches. Controls: positive, negative, NTC, no-RT (no-RT "desirable, but no longer essential" once a sample is shown DNA-free); "an unknown sample should be considered positive only if its Cq precedes that of the negative control by at least 5 cycles". Checklist section 1 (reagent preparation) and section 5 (PCR efficiency estimation and method; LOD calculated?; dynamic range; specificity) — the checklist no longer labels items E/D; footnote c: sequences "highly desirable", and if a vendor withholds them "assay context sequences must be submitted"; footnote j: "Efficiency-corrected target quantity calculation is necessary". Raw data in RDML or RDES.
- **RDML v1.3 / v1.4-CR target element** [47]: `target` has `xRef`, `type` (ref/toi), `amplificationEfficiencyMethod`, `amplificationEfficiency` (1.95 = 95 %), `amplificationEfficiencySE`, `meltingTemperature`, `detectionLimit` (copies/µl), `dyeId`, `sequences{forwardPrimer, reversePrimer, probe1, probe2, amplicon}` each with `threePrimeTag`, `fivePrimeTag`, `sequence` (IUPAC) and (v1.4) `oligoConc` (nM, default 250), and `commercialAssay{company, orderNumber}` "for some commercial assays the primer sequences may be unknown". **No lot number, manufacturer, resuspension date or storage fields exist at target, oligo or reaction level.** Schema and rdmlpython are MIT [47][48].
- **ISO 20395:2019** (qPCR/dPCR performance evaluation) — could not fetch content; see Open questions [81].
- **Clinical lot-to-lot practice** (research labs could adapt): CLSI EP26-style verification with patient samples spanning the range; "no universally agreed acceptance criteria … up to the laboratory"; one 360-lot-change study found QC and patient-sample shifts disagreed in ~7.8 % of events, so real samples are preferred over QC material [64].

### 1.5 What "good" looks like vs what is done (audit evidence)

- Drude et al. 2026 (top-20 genetics journals n = 186, plant-science n = 246, Sept–Oct 2021 papers) [3]: primer sequences reported 88 % / 92 %; target accession numbers 14 % / 31 %; primer specificity checked/reported 8 % / 13 %; **PCR efficiency reported 5 % / 8 %, only half with values**; reference-gene stability (M-value) 0.4 %; no evidence of no-RT controls in the sample; "over 90 % of papers did not mention efficiency or specificity testing"; only 2 papers cited MIQE; "most papers omit transcript accession numbers, placing the responsibility of verifying isoform and spliceform specificity on the readers".
- Abdel Nour et al. 2014 (461 papers, Arabian countries, 2009–13) [4]: compliance with 15 essential MIQE items median 40 %; assay design 12 %; amplification efficiency 30 %; normalisation 3 %.
- Bustin 2025 editorial [2]: "Assay efficiencies are assumed, not measured"; "compliance remains patchy, and in many cases, entirely superficial".
- A secondary blog claims efficiency reporting fell from 13 % (2019) to 1 % (2024) [76] — I could not find the primary study; treat as unverified.

### 1.6 Where assays fail silently (evidence)

- **Mismatches / SNPs under primers.** Stadhouders et al. 2010 (5' nuclease assay, synthetic templates): single 3'-terminal mismatches shift Ct from 0.99–1.91 (A–C, C–A, T–G, G–T; 2–4-fold underestimate) to 8.29–9.09 cycles (A–A, A–G, G–A, G–G, C–C; 320–580-fold); average effect 5.19 Ct at the terminal position, 1.87 at position 2, 0.53/0.71 at positions 3/5; double/triple mismatches in the last three bases abolished amplification; effect size differed up to 7-fold between master mixes [26]. Lefever et al. 2013 (five master mixes): "Single mismatches located > 5 bp from the 3' end have a moderate effect"; reaction fully blocked by ≥4 mismatches in one primer or 3 + 2 [25]; IDT's summary: terminal mismatch "altering Cq by as much as 5–7 cycles"; IDT advises "Recheck previously used primers and probes, since genomic data keeps changing" [21]. GETPrime: > 80 % of human primers overlap a known variant [27] — so a binary "has SNP" flag is useless; position- and MAF-weighted risk is what matters.
- **Isoforms and pseudogenes.** MIQE 2.0 statements above [1]; Bio-Rad's design rules explicitly maximise "fraction of transcript isoforms being detected" and accept 5'-end SNPs "because of the sheer number of SNPs … it is becoming impossible to avoid SNPs in all primers" [18]; forum/vendor explanations of intron-less pseudogenes defeating intron-spanning design [62][63].
- **Melt curve false reassurance.** MIQE 2.0: "a single peak at the correct Tm does not guarantee identification of the intended amplicon" [1]. Bio-Rad: "the sensitivity of these methods is too limited to detect small fractions of nonspecific PCR products … It is also known to sometimes generate more than one peak for assays that are confirmed to be specific" — hence they sequenced every amplicon [18]. CASRAI guide: single peak "consistent with specificity, not proof of it"; sequencing "the only check that closes the same-Tm, same-size loophole" [59]. Primer-dimers in NTC: PrimePCR redesigns any assay with NTC Cq < 35 [18]; MIQE 2.0's 5-cycle rule vs negative controls [1].
- **Efficiency estimates are noisy and instrument-dependent.** Svec et al. 2015 (6 instruments, 1–16 replicates, 2–10 µl transfer volumes): "the estimated PCR efficiency varies significantly across different instruments"; "uncertainty … may be as large as 42.5 % (95 % CI) if standard curve with only one qPCR replicate is used in 16 different plates"; CI 8.3 % with single wells vs 2.3 % with triplicates; "the efficiency is instrument dependent, but reproducibly stable on one platform"; 2 µl transfer volumes lost 31–69 % of replicates at the lowest standard [49]. Rogers-Broadway 2015: same 18S assay, four instruments, Cq spread 1.2–4.5 cycles across the plate [51]. Hastings 2021 (telomere qPCR): standard-curve single-copy-gene efficiency 2.10–2.12 ("inflated beyond 100 %") vs per-reaction LinRegPCR 1.92; the choice changed mean T/S ratio from 5.39 to 0.73 [50]. MIQE 2.0: pipetting errors in serial dilution give slopes below −3.32 (E > 100 %); inhibitors raise standard-curve E but lower individual-curve E [1]. Consequence for a passport: **standard-curve E and LinRegPCR E are different quantities with different biases and must be stored separately with the method label (RDML `amplificationEfficiencyMethod`).**
- **Lots, storage, freeze-thaw: lore vs data.** Vendor FAQ: "Never work under the assumption that primers from different batches will work at the same efficiency … Do this even if you are using primers that you know work well but they are from a new batch" [57]; Thermo lot-to-lot spec < 0.6 Ct [16]. IDT stability study: unmodified DNA oligos stable (ΔCq < 1.5) 24 months at −20 °C dry, in TE or in water; 30 freeze-thaw cycles "no significant effect"; at 37 °C water is least stable but little loss for ~6 weeks; fluorophore-labelled oligos lose ~20 % signal over 24 months [22][23]. An eDNA study (BMC Res Notes 2024): primer–probe mixes stable 5 months at −20 °C with monthly freeze-thaw; standard-curve efficiencies across assays/time 89–117 %, r² 0.994–1 [54]. Forum lore disagrees: "after 4 or 5 freeze-thaw cycles, primers can be fully degraded", "a primer stock kept in water at −20 °C … still fully degraded" (protocol-online/ResearchGate summaries) [55][56]. Inference: most "my primers died" events are probably handling/contamination/dilution errors or lot differences rather than intrinsic degradation — exactly the kind of thing a per-assay history would show, and nothing shows it today. **I found no peer-reviewed study quantifying efficiency drift by oligo lot (Gap).**
- **Cross-lab / cross-assay evidence exists but is one-off.** Vogels et al. 2020 compared nine SARS-CoV-2 primer–probe sets under one protocol: all E > 90 % (slopes 3.1–3.7), but the Charité RdRp set ran 6–10 Ct late because of a degenerate reverse-primer base mismatching 990/992 genomes, and the CDC N3 set was withdrawn after a T→C variant in 39 genomes [72]. Ring trials: four MAP qPCR assays across labs gave Fleiss' kappa 0.15 [73]; a shared-reagent SARS-CoV-2 ring trial gave > 99.5 % concordance [73]. These are exactly the comparisons individual research labs never get for their own assays.

### 1.7 Money and time (estimates, labelled)

- Validation of one assay = one dilution-series plate (≥5 points × 3 replicates + NTC ≈ 18–24 wells) plus reagents and ~half a day; a failed design means a reorder cycle of days to a week. I did not find a citable oligo price; treat cost as "tens of currency units per primer, but the lost week and the irreplaceable samples are the real cost" (vendor guidance makes this latter point [58]).
- Inventory software: Quartzy entry plan ~$159/month for five users [65]; Benchling pricing not public; eLabFTW free/AGPLv3 self-hosted [66].
- Time lost to repeated validation of vendor assays is explicitly called out by Bio-Rad: "assay validation by individual researchers leads to a waste of precious time and resources" [18].

### 1.8 Key sites/communities

MIQE 2.0 [1]; gene-quantification.de efficiency and primer pages [52]; RDML consortium GitHub [47][48]; Primer-BLAST [5]; IDT DECODED articles [21][22][23]; Bio-Rad bulletins [18][20]; CASRAI qPCR guides [59]; protocol-online forums [56]; ResearchGate Q&A (blocked to fetch) [13][55].

---

## 2. Pain inventory

| # | Pain | Who feels it / how often | Severity | Evidence | What exists today and why insufficient |
|---|---|---|---|---|---|
| P1 | Efficiency assumed, not measured; when measured, not recorded with method/CI | Every RT-qPCR user; per assay, per paper | Wrong fold changes; 90 %+ of papers | [1][2][3][4] | Excel standard curves; vendor software per plate; nothing accumulates across plates |
| P2 | Inherited/copied primer pairs never re-checked against current genome/variant data (SNPs at 3' end, isoform subset, pseudogene) | Students reusing lab/paper primers; weekly in any expression lab | Allele-dependent 2–9 Cq bias; wrong isoform conclusions | [25][26][27][21][1][18] | Primer-BLAST (web only, human-only SNP, no API); GETPrime (SNP overlay human/mouse, host down); vendors do it only for their own catalogue |
| P3 | New lot / resynthesis / new kit lot silently changes assay behaviour; re-validation mandated but rarely done | Lab managers, anyone re-ordering; per re-order | Repeated runs; irreplaceable samples spent on a bad lot | [1][57][16][64] | Clinical labs run EP26 bridging; research labs have nothing; no instrument export carries lot info |
| P4 | "Old primers" blamed for failures; lore contradicts data | Everyone; monthly | Unnecessary reorders, or false reassurance | [22][23][54][55][56] | Forum advice; no per-assay history to see whether this tube ever behaved differently |
| P5 | Single melt peak taken as proof; primer-dimer in NTC ignored or over-reacted to | SYBR users; every plate | Off-target counted as target; sensitivity loss | [1][18][59][60] | Vendor software shows peaks; no fingerprint across runs; no NTC-vs-sample rule applied automatically |
| P6 | "Which primer pair / isoform did that paper use?" cannot be answered | Readers, reviewers, students replicating; per paper | Non-reproducible results | [3][14] | 88–92 % give sequences but 14–31 % give accessions; TaqMan sequences withheld (context sequence only) |
| P7 | Inventory tools track tubes, not assay performance; spreadsheets die with the student | Lab managers, PIs; on every departure | Lost validation evidence; duplicate orders | [65][66][67][68][69] | Quartzy/Benchling/eLabFTW/LabArchives hold items; no link tube → runs → evidence |
| P8 | Standard-curve efficiency is imprecise (±8 % single wells; ±42.5 % across plates) and instrument-dependent; E > 100 % from pipetting | Anyone validating; per validation | Wrong E → wrong correction | [49][50][51][1] | Textbook 90–110 % threshold applied blindly; no CI; no comparison with per-curve E |
| P9 | Public validated-primer resources are dead or frozen; UPL design tool gone | Designers; when a design is needed | No living source of measured performance | [29][30][12][13] | PrimerBank (2006/2012), RTPrimerDB (dead), qPrimerDB/GETPrime (in-silico only) |
| P10 | Open design engines are GPL | qPilot specifically | Licence conflict | [9][10][11][32][33][34] | Need permissive reimplementation or process isolation |
| P11 | Efficiency/Tm differ by instrument; labs with 2+ cyclers compare numbers that are not comparable | Core facilities, multi-instrument labs | Cross-plate bias | [49][51] | Nothing tracks per-instrument assay behaviour |
| P12 | Commercial "validated" means different things (all tested + sequenced vs "several hundred tested") | Buyers | Misplaced trust | [17][18] | Marketing pages; no independent evidence base |

---

## 3. Discoveries (ranked by impact × feasibility × fit)

### D1. Assay Passport: a per-primer-pair performance record computed from every RDML run (lab memory, done properly)

1. **Persona and situation.** A postdoc in a 10-person expression lab runs 2–4 plates a week on a CFX384 and a QuantStudio; the lab has ~150 primer pairs in a spreadsheet, half designed by people who have left. Before each study she decides which GAPDH/ACTB/TBP pair to use and whether the IL6 pair "still works". A core-facility manager has the same question for 40 client assays. Frequency: every study start; every re-order; every failed plate.
2. **Evidence of pain.** P1, P3, P4, P8, P11 above. Efficiency reported in 5–8 % of papers [3]; MIQE 2.0 mandates per-assay efficiency with CI, LOD/LLOQ, method and re-validation on new batches [1]; standard-curve E uncertainty up to 42.5 % [49]; instrument dependence [49][51]; forum lore about dead primers vs IDT 24-month/30-freeze-thaw data [22][55]; Thermo's own lot-to-lot spec (< 0.6 Ct) shows what "same assay" tolerance looks like [16]. Cost estimate: one repeated validation plate (~half a day + reagents) per suspicious assay per month per lab is plausible; the bigger cost is studies normalised with an assay whose E had drifted (unquantified; Hastings shows E-method alone changed a ratio 7-fold [50]).
3. **What exists today.** Vendor software reports E per standard-curve plate and forgets it. Clarida/qbase+ take Cq input, so cannot compute per-well E or melt fingerprints. Inventory tools store tubes [65][66]. No tool accumulates per-assay evidence across plates, instruments, lots and years.
4. **The feature.**
   - *Input:* every RDML the lab analyses (qPilot already reads them). Assay identity = SHA-256 of (uppercased forward seq, reverse seq, probe seq) when `target/sequences` is filled; else `commercialAssay{company, orderNumber}`; else target id + a reconciliation Decision Card ("These 3 target names look like one assay — merge?"). Per well: LinRegPCR per-well efficiency and quality flags (rdmlpython, MIT), Cq, melt data points `mdp` → peak Tm/width via rdmlpython MCA; sample type/quantity (RDML `sample` quantity for standards); NTC/no-RT roles from the plate layout; instrument id and run date from RDML `run`.
   - *Registry side-file* (`assays.yaml`, hand-filled once per tube, prompted when a new hash appears): oligo manufacturer, lot/batch, order number, resuspension date and buffer, working-stock concentration, freezer location, design tool/version/settings, accession and amplicon coordinates (these are the MIQE 2.0 section-1 fields [1]). RDML has none of these fields [47], so the side-file is unavoidable; qPilot can write back the expected `amplificationEfficiency`, `amplificationEfficiencySE`, `meltingTemperature`, `detectionLimit`, `amplificationEfficiencyMethod` into the RDML `target` of each record it produces, which makes the passport partly portable in the standard itself.
   - *Deterministic methods:* (a) per-run assay efficiency = mean and SD of per-well window-of-linearity efficiencies of valid wells (MIQE 2.0 endorses this mean for standardised experiments [1]); (b) control charts per assay with segmentation by lot, instrument and master-mix lot: Shewhart/EWMA limits learned from the assay's own first N runs rather than the textbook 90–110 %, because LinRegPCR E is systematically lower than standard-curve E (Hastings: 1.86–1.92 vs 1.89–2.12 [50]) and instrument-specific (Svec [49]); change-point test at each lot boundary (a two-sample comparison of per-well E and of Cq on repeated controls); (c) melt fingerprint per assay per instrument (median Tm, IQR, width) and distance of each new well to it; (d) NTC behaviour: fraction of NTC wells amplifying, their Cq and Tm (dimer Tm usually < product Tm), Cq gap to the lowest sample (MIQE 2.0 ≥ 5-cycle rule [1]; PrimePCR NTC Cq < 35 → redesign [18]); (e) validation events: whenever a plate contains a dilution series for the assay, compute standard-curve E with a confidence interval from replicate resampling (Svec's recommendation of ≥3–4 replicates and reported CI [49][1]), LOD by probit at 95 % and LLOQ by precision criterion, and store them with the method label; also compare std-curve E vs mean per-well E on the same plate — a large gap points at pipetting error or inhibition (MIQE 2.0 mechanism [1]).
   - *Decisions (cards):* "E for IL6 (lot B, since 3 Mar) averages 1.78 vs 1.91 for lot A over 11 plates — re-validate / retire / accept with note"; "GAPDH on QuantStudio shows Tm 83.1 vs 84.6 on CFX — expected instrument offset; no action"; "NTC amplifies in 6/8 recent plates at Cq 33–35 with Tm 74 °C (dimer); lowest sample Cq 31 — within 5 cycles: results below Cq 30 only". Impact ranking uses the existing engine (does the choice flip any per-gene conclusion?).
   - *Record and MCP:* passport JSON (schema versioned) appended to each Analysis Record; `qpcr_assay_passport(assay_hash)` returns the facts; `qpcr_assay_history(assay_hash, since)`; the robustness grid gains an axis "efficiency source = per-plate mean / passport prior / 100 %".
5. **Feasibility.** rdmlpython (MIT) already provides LinRegPCR and MCA [48]; RDML schema fields exist for expected values [47]; control charts are textbook; effort ≈ 2–3 developer-weeks for v1 (identity + charts + cards), +1 week for validation-event detection and LOD/LLOQ. Hardest parts: assay identity across inconsistent target names and files lacking sequences (most vendor exports do not carry sequences — the registry prompt solves it); deciding thresholds without over-alerting (use the assay's own distribution + impact ranking); no instrument export carries lot numbers, so lot segmentation depends on one-time human entry with date ranges.
6. **Why qPilot.** It already has per-well efficiency from raw curves (Cq-input tools cannot do this), melt data, a decision-card framework, a hash-chained record and an MCP surface. A passport is a by-product of what it already computes; competitors would have to change their input model.
7. **Risks / confidence.** Labs that use vendor Cq-only exports give no curves (the roadmap's vendor-capture work addresses this). Alert fatigue if thresholds are textbook rather than learned. Lot data entry may be skipped (make it one field, prompted once). Confidence **high** for value and feasibility; **medium** that labs will enter lot data.

### D2. In-silico pre-flight of existing assays against current genome resources (offline-first, permissive)

1. **Persona.** The same postdoc inherits a primer spreadsheet; a student designs a pair in Primer-BLAST at 7 pm; a reviewer asks "which isoforms does your pair detect?". Frequency: every new or inherited assay; every genome/annotation release.
2. **Evidence.** P2, P6. > 80 % of human primers overlap a known variant, ~3 SNPs/primer [27]; terminal-mismatch Cq shifts 1–9 cycles depending on base pair and position [26][25]; IDT: "Recheck previously used primers … since genomic data keeps changing" [21]; MIQE 2.0 requires checking variant databases and warns about processed pseudogenes and splicing [1]; only 14–31 % of papers give accessions so isoform claims are unverifiable [3]; Primer-BLAST has no API, SNP check human-only [7][8]; GETPrime's API host did not resolve [27]; Vogels shows a single degenerate mismatch cost a widely used assay 6–10 Ct [72].
3. **What exists.** Primer-BLAST (manual, web, no batch), GETPrime/qPrimerDB (precomputed catalogues, not "your pair"), vendor pipelines (their assays only), Geneious/Beacon (desktop, closed, no SNP/isoform in the pages I could read) [70][71].
4. **The feature.** Input: assay hash + sequences (from registry or pasted) + species + a pinned "pre-flight pack" version. Deterministic steps: (i) locate binding sites in the pinned transcript set (Ensembl/RefSeq release id stored) using exact + mismatch-tolerant search (seqkit `amplicon -m`, MIT [37]) and then re-score each hit with 3'-end-aware rules (last 5 nt weighted per Stadhouders/Lefever tables [26][25]) and a nearest-neighbour duplex ΔG/Tm with mismatches (Biopython `Tm_NN` with `c_seq`, or TNTBLAST BSD-3 [41][38]); (ii) isoform coverage: fraction of the gene's transcripts amplified, whether the MANE Select/canonical transcript is included, amplicon length per isoform (GETPrime's metric [27]); (iii) exon-junction / intron-spanning status and predicted gDNA amplicon size; (iv) genome-wide off-targets including processed pseudogenes (same search on the genome; report any amplifiable product ≤ 1 kb with ≤ k mismatches outside the last 5 nt); (v) SNP overlay: variants overlapping each primer with MAF (Ensembl REST `overlap/region?feature=variation` returns dbSNP/gnomAD-sourced variants [44]; or an offline VCF subset shipped in the pack), scored as position × MAF × mismatch class into an expected Cq-bias range quoting [26]; (vi) hairpin/homodimer ΔG (seqfold MIT [35]) and heterodimer ΔG (TNTBLAST or own NN implementation); (vii) predicted amplicon Tm (NN model; note uMELT is web-only [74]) compared with the observed passport Tm (D1). Output: a pre-flight report + cards: "Pair covers 3/7 isoforms (MANE included)"; "rs… MAF 0.21 at reverse primer position −2: expect allele-dependent underestimation of up to ~2 Cq (T–T class) — accept / annotate samples / redesign"; "Intron-less pseudogene GAPDHP1 amplifiable with 0 mismatches — no-RT control mandatory". Record: pack version, every hit, every rule applied; MCP: `qpcr_assay_preflight(assay_hash, pack_id)`.
5. **Feasibility.** Data licences: Ensembl "imposes no restrictions on access to, or use of, the data", code Apache-2.0 [43]; NCBI "places no restrictions" on molecular data, 3 requests/s etiquette [46]; UCSC data free for commercial use but isPcr/Blat need a separate licence [42] — avoid isPcr; Ensembl REST 55,000 requests/h per IP [45]. Tools: seqkit MIT, seqfold MIT, Biopython (Biopython Licence/BSD-3 dual) [41], TNTBLAST BSD-3 [38]; BLAST+ is US-government public-domain software (NCBI policy page states government-created works are public domain [46]; I could not fetch the toolkit LICENSE file). Effort ≈ 3–5 weeks for human/mouse/rat packs (pack builder + search + scoring + cards); additional species = pack builds. Hardest: laptop-speed genome-wide mismatch search (pre-index k-mers per pack; cache per assay hash), correct 3'-mismatch scoring beyond the published tables (publish the rule table and tests), keeping packs small (transcripts + exon map + SNPs with MAF ≥ 0.01 is a few hundred MB per species).
6. **Why qPilot.** The passport (D1) gives the observed Tm/E to compare with predictions; the robustness engine can rerun a study excluding wells/samples from a flagged genotype; the record pins pack versions so a reviewer can reproduce the check; the agent can run it on every assay in a study before analysis.
7. **Risks / confidence.** Non-model species have no SNP data; vendors' secret sequences can only be checked via context sequence (amplicon-level isoform/SNP check still possible). GPL contamination must be avoided (no Primer3/primer3-py, no openPrimeR). Confidence **high** on need and data availability; **medium** on effort (indexing).

### D3. Lot-change gate: a deterministic bridging study for research labs

1. **Persona.** Lab manager receives a resynthesised primer; the PI insists on the MIQE 2.0 line about re-validating on new batches but nobody knows what "re-validate" means in practice. Frequency: every re-order (monthly in an active lab).
2. **Evidence.** MIQE 2.0 re-validation requirement [1]; "Never work under the assumption that primers from different batches will work at the same efficiency" [57]; Thermo's < 0.6 Ct lot-to-lot spec and advice to run a control on both lots in parallel [16]; CLSI EP26 practice, lab-defined acceptance, QC material missing 7.8 % of real shifts [64]. No research-lab tool does this (P3).
3. **What exists.** Clinical SOPs; vendor FAQs; nothing in research software.
4. **The feature.** When the registry records a new lot for an assay with a passport, qPilot proposes a minimal plate layout (both lots × 3 samples spanning the passport's Cq range × 3 replicates + NTC each; optionally a 4-point series), pre-registers the acceptance rule (ΔCq old–new ≤ 0.6 at matched samples by default, per-well E within the passport's learned interval, NTC Tm/Cq unchanged) and, after the run, writes a verdict card: pass / pass-with-offset (store lot offset so the passport's control chart does not alarm) / fail (block the lot in the registry, recommend re-order). Record: layout, rule, verdict, lot ids. MCP: `qpcr_lot_bridge(assay_hash, old_lot, new_lot)`.
5. **Feasibility.** ~1–2 weeks on top of D1 (plate layout assistant exists in roadmap). Hardest: persuading users to spend 20 wells; make the gate optional and show the passport's own drift history as the argument.
6. **Why qPilot.** Uses per-well E (not just Cq), impact ranking (does the lot change flip any conclusion in the current study?), records, autonomy levels (the agent can propose; the human accepts).
7. **Risks / confidence.** Evidence of lot-driven drift in research primers is vendor/anecdotal, not peer-reviewed (Gap) — the feature's value rests on MIQE 2.0's mandate and the asymmetry of costs. Confidence **medium**.

### D4. Melt-identity fingerprint and NTC-artefact model per assay (beyond "single peak")

1. **Persona.** SYBR users on every plate; core facilities asked "why did this well fail?".
2. **Evidence.** P5. MIQE 2.0 and Bio-Rad statements that a single peak proves little and that melt analysis cannot see small off-target fractions [1][18]; CASRAI [59]; multiple peaks can occur for specific assays with GC domains [18]; dyes differ in sensitivity to minor peaks [1]; PrimePCR's NTC Cq < 35 redesign rule [18]; MIQE's 5-cycle rule [1].
3. **What exists.** Instrument software shows derivative peaks per plate; the roadmap names "melt-peak checks" as a headline only. rdmlpython MCA gives peaks per well [48]; a Ruijter-group melt-curve analysis manuscript exists [87].
4. **The feature.** Per assay per instrument, build from the passport a fingerprint of the normalised −dF/dT curve (median curve, Tm, width, shoulder presence). For each new well compute Tm offset, width ratio and a shape distance (e.g. correlation of derivative curves within the main peak window); classify: matches fingerprint / shifted (possible variant amplicon or gDNA) / broad or extra peak (mixture) / low-Tm only (dimer, no product). For NTC wells, model the dimer peak separately and compute the Cq gap to the lowest sample. Cards: "3 wells deviate from the IL6 fingerprint (ΔTm +1.4 °C, width +60 %); excluding them changes group B mean by 0.3 ΔCq — exclude / keep / run a gel". Prediction from D2 (NN Tm of the intended amplicon and of any predicted off-target/pseudogene amplicon) is shown next to the observed Tm. Record: fingerprint version and per-well distances. MCP: `qpcr_melt_identity(study)`.
5. **Feasibility.** 2 weeks; melt data already parsed. Hardest: instrument ramp-rate and dye effects (fingerprint must be per instrument/chemistry), and avoiding over-exclusion (impact ranking helps).
6. **Why qPilot.** Raw melt data + cross-run memory + robustness reruns + record. Cq-input tools cannot do this at all.
7. **Risks / confidence.** Probe-based assays have no melt data (skip gracefully). Confidence **high** on feasibility, **medium** on how often it changes conclusions (unquantified).

### D5. Lab assay registry with sequence-hash identity, MIQE-section-1 autofill and "which pair did that paper use" resolver

1. **Persona.** PI writing methods; student replicating a 2019 paper; reviewer; lab manager deciding whether to reorder a pair that "someone validated once".
2. **Evidence.** P6, P7, P9. 88–92 % of papers give sequences but 14–31 % give accessions; 0.4 % give M-values [3]; TaqMan Assay IDs are stable and come with a context sequence [14]; RTPrimerDB dead, PrimerBank frozen [29][30]; labs invent naming schemes and sheets [67][68]; inventory tools do not hold performance [65][66].
3. **What exists.** Spreadsheets; Geneious primer DB (desktop, closed) [70]; Quartzy/Benchling/eLabFTW items (eLabFTW is AGPLv3 with an API — integration by API call is fine, code linking is not) [66].
4. **The feature.** Registry entries created automatically from RDML targets and vendor order files (Thermo Assay Information File carries context sequence [14]); identity by sequence hash; fields = MIQE 2.0 section 1 + lot/storage; link to passports (D1) and pre-flight reports (D2). Functions: (a) autofill MIQE 2.0 section-1 and section-5 assay items into the templated methods paragraph already on the roadmap, with "cannot be determined from data" stated honestly (e.g. design-tool settings must come from the registry); (b) paper resolver: paste a primer table → hash match to registry (exact or near, e.g. the same pair with one base different), show the lab's passport and the pre-flight result on today's genome; (c) optional push of a one-paragraph passport summary into eLabFTW/Benchling items via their APIs. Record: registry snapshot hash in every Analysis Record. MCP: `qpcr_registry_lookup(sequences|hash|assay_id)`.
5. **Feasibility.** 2–3 weeks; mostly data model + import parsers. Hardest: adoption (keep required fields to lot + date; everything else optional), vendor file formats.
6. **Why qPilot.** Records and MCP make the registry queryable by agents ("is there a validated TBP pair for mouse liver on the CFX?"); the domain-agnostic core can treat antibodies/ELISA reagents the same way later.
7. **Risks / confidence.** A registry without the passport is just another spreadsheet; ship D1 first. Confidence **medium-high**.

### D6. Opt-in cross-lab assay evidence exchange (passport commons)

1. **Persona.** Anyone choosing between three published GAPDH pairs; a core facility benchmarking its instruments.
2. **Evidence.** No living source of measured assay performance exists (P9); vendors withhold sequences; one-off cross-lab comparisons show large, assay-specific differences [72][73]; the roadmap names an "open commons of records", but assays are the natural unit because a sequence hash is a global key.
3. **What exists.** PrimerBank/qPrimerDB/GETPrime (no measured E), vendor sheets (their assays only).
4. **The feature.** Export of anonymised passport summaries (hash, species, chemistry, instrument family, master-mix family, n plates, E distribution by method, Tm, NTC behaviour, pre-flight pack result) under CC0 to a public index; import to show "this pair: 14 labs, median LinRegPCR E 1.91, Tm 84.2 ± 0.4 on CFX, 3'-end SNP risk low". Deterministic aggregation only.
5. **Feasibility.** Schema from D1; a static index (JSON on GitHub Pages) is enough initially; weeks of work. Hardest: critical mass; de-identification; sequence secrecy for commercial assays (use context-sequence hash).
6. **Why qPilot.** Passports exist as a by-product; open licence and local-first default (export is explicit).
7. **Risks / confidence.** Low adoption; conflicting instrument families make pooling noisy. Confidence **low-medium**; do after D1–D5.

---

## 4. Data, libraries, standards, licences found

| Item | Type | Licence / terms | Notes | URL |
|---|---|---|---|---|
| MIQE 2.0 (Bustin et al. 2025) | Standard | © ADLM; text subscription/OA copies | Checklist section 1 and 5 define assay reporting | [1] |
| RDML schema v1.3 REC, v1.4 CR | Schema | MIT | target: sequences, commercialAssay, efficiency, SE, Tm, detectionLimit; no lot fields | [47] |
| rdmlpython | Library | MIT | LinRegPCR (`-lrp`), melt-curve analysis (`-mca`), validation | [48] |
| Primer3 | Engine | GPL-2.0 | Linking forces GPL2 per project help | [9][10] |
| primer3-py | Bindings | GPL-2.0 | — | [11] |
| openPrimeR / rprimer / DECIPHER | R/Bioconductor | GPL-2 / GPL-3 / GPL-3 | Not usable in distribution | [32][33][34] |
| PrimeSpecPCR | Python | MIT but depends on primer3-py | Inherits GPL problem | [80] |
| seqfold | Python/Rust | MIT | DNA MFE folding (SantaLucia 2004); no heterodimers | [35] |
| primers | Python | MIT | Simple design on seqfold; off-target = ≤1 mismatch in last 10 nt within given sequence | [36] |
| seqkit `amplicon` | Go CLI | MIT | In-silico PCR with `-m` mismatches, degenerate bases, BED output; mismatch position not controlled | [37] |
| ThermonucleotideBLAST | C++ | BSD-3 (Triad/LANL) | NN Tm/ΔG for primer pairs ± probe vs FASTA/BLAST DB; heterodimer; MPI/OpenMP | [38] |
| Biopython `Bio.SeqUtils.MeltingTemp` | Python | Biopython Licence / BSD-3 dual | Tm_NN with SantaLucia tables, mismatch/dangling tables, Owczarzy salt/Mg corrections | [41] |
| MFEprimer 3/4 | Binary | "free to use", licence unnamed | Not open source | [39] |
| PrimerROC / PrimerDimer | Web | Unknown (site unreachable) | Cited by MIQE 2.0 | [40] |
| uMELT Quartz | Web | No source provided | Melt prediction; API on request | [74] |
| NCBI Primer-BLAST | Web | US gov; no API | primerTree scrapes it | [5][8] |
| NCBI data / E-utilities | Data/API | Public domain; 3 req/s etiquette | RefSeq transcripts, dbSNP | [46] |
| Ensembl data + REST | Data/API | Data: "no restrictions"; code Apache-2.0; 55,000 req/h | `overlap/region` feature=variation, max 5 Mb | [43][44][45] |
| UCSC Genome Browser data | Data | Free incl. commercial (except liftOver chains) | isPcr/Blat need Kent licence | [42] |
| GETPrime 2.0 | DB/API | Not stated | Host unreachable 17 Oct 2026 | [27] |
| qPrimerDB 2.0 | DB | Not stated | 429.8 M pairs, in-silico | [28] |
| PrimerBank | DB | Not stated (MGH copyright) | 306,800 primers; frozen | [29] |
| Bio-Rad PrimePCR validation sheets | Vendor data | Vendor terms | Per-assay E, r², NTC, NGS specificity | [18][19] |
| Thermo TaqMan Assay Search / AIF | Vendor data | Vendor terms | Context sequence, amplicon length, exon boundary | [14] |
| IDT oligo stability studies | Vendor data | Vendor pages | 24 months at −20 °C; 30 freeze-thaw cycles no effect | [22][23] |
| eLabFTW | ELN/inventory | AGPLv3; has API | Integrate by API only | [66] |
| Quartzy, Benchling | Inventory | Commercial | Quartzy–Benchling sync; ~$159/mo entry | [65] |
| CLSI EP26 (lot-to-lot) | Clinical guideline | Paid | Practice reference for D3 | [64] |
| ISO 20395:2019 | Standard | Paid; not fetched | qPCR/dPCR performance evaluation | [81] |

---

## 5. Open questions and what I could not verify

- **Lot-driven efficiency drift:** no peer-reviewed study found that quantifies E or Cq change between oligo lots in research assays; evidence is vendor specs [16][57] and MIQE 2.0's mandate [1]. D3 rests on this.
- **Forum/community evidence** (Reddit r/labrats, ResearchGate, Biostars) on lost primers when students leave, inventory habits and "primers stopped working" could not be fetched (403/blocked); the protocol-online threads were summarised only via search snippets [55][56]. A follow-up with browser access should collect 5–10 verbatim quotes.
- **Secondary claim** that efficiency reporting fell 13 % → 1 % (2019–2024) [76] is unverified; the primary 2026 audit I read reports 5–8 % for 2021 papers [3].
- **Lefever 2013 full text** (how many published assays overlap SNPs; exact Cq tables) is paywalled; only the abstract and IDT's summary were available [25][21].
- **ISO 20395:2019 content** (acceptance criteria for LOD/LOQ/efficiency) not read [81].
- **Benchling primer design, Sigma KiCqStart, OriGene qSTAR, IDT PrimerQuest** pages failed to load; their design checks are unverified here.
- **GETPrime availability**: NAR 2017 describes a REST API and TSV downloads, but the host did not resolve; status unknown [27]. qPrimerDB download/licence unknown [28].
- **BLAST+ licence text**: NCBI policy says US-government works are public domain [46], but the toolkit LICENSE file URL I tried returned 404; confirm before bundling.
- **MFEprimer licence**: "free to use" but no OSI licence; binary-only [39]. Not safe to bundle.
- **How often melt-identity failures change conclusions** (D4) and **how many lab assays have 3'-end common SNPs** (D2) are unquantified; both are measurable once D1/D2 exist and would make good validation papers.
- **Thermo "efficiency guarantee" terms**: FAQ states 90–110 % across 5 logs and lot-to-lot < 0.6 Ct, but the guarantee page itself does not mention efficiency [15][16]; the exact programme document was not read.

---

## 6. Sources

1. Bustin SA et al. MIQE 2.0: Revision of the Minimum Information for Publication of Quantitative Real-Time PCR Experiments Guidelines. Clin Chem 2025;71(6):634–651. https://academic.oup.com/clinchem/article/71/6/634/8119148 (full text read from https://www.multid.se/publications/MIQE-ver2.pdf)
2. Bustin S. MIQE 2.0 and the Urgent Need to Rethink qPCR Standards. IJMS 2025. https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/
3. Drude N, Baselly C, Gazda MA et al. Reporting quality of quantitative polymerase chain reaction (qPCR) methods in scientific publications. Research Integrity and Peer Review 2026. https://link.springer.com/article/10.1186/s41073-026-00188-0 ; preprint https://www.biorxiv.org/content/10.1101/2024.12.04.626769v1.full
4. Abdel Nour AM et al. Five Years MIQE Guidelines: The Case of the Arabian Countries. PLoS ONE 2014. https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0088266
5. NCBI Primer-BLAST form. https://www.ncbi.nlm.nih.gov/tools/primer-blast/
6. NCBI Primer-BLAST information page (Primer3 2.5.0; Ye et al. 2012). https://www.ncbi.nlm.nih.gov/tools/primer-blast/primerinfo.html
7. NLM Primer-BLAST workshop, interface page (SNP option human RefSeq only). https://www.nlm.nih.gov/ncbi/workshops/2023-09_Primer-BLAST/interface.html
8. primerTree::primer_search (drives the Primer-BLAST website). https://www.rdocumentation.org/packages/primerTree/versions/1.1.0/topics/primer_search
9. primer3-org/primer3 GitHub (GPL-2.0). https://github.com/primer3-org/primer3
10. Primer3 web help, copyright and licence. https://primer3.ut.ee/primer3web_help.htm
11. primer3-py PyPI (GPLv2) https://pypi.org/project/primer3-py/ ; GitHub https://github.com/libnano/primer3-py
12. Sigma-Aldrich/Roche UPL product page: phased out end 2020; Assay Design Center until 31 Dec 2020. https://www.sigmaaldrich.com/US/en/product/roche/upl1thru10
13. ResearchGate: Roche has stopped its Universal Probe primer design service. https://www.researchgate.net/post/Roche_has_stopped_its_Universal_Probe_primer_design_service_does_anyone_know_where_or_how_we_can_design_primers_to_fit_Universal_Probe_Library
14. Thermo Fisher: Publish real-time PCR results (Assay ID, context sequence, AIF). https://www.thermofisher.com/us/en/home/life-science/pcr/real-time-pcr/real-time-pcr-assays/why-choose-taqman-assays/publish-real-time-pcr-results.html
15. Thermo Fisher: Why choose TaqMan assays (guarantee). https://www.thermofisher.com/us/en/home/life-science/pcr/real-time-pcr/real-time-pcr-assays/why-choose-taqman-assays.html
16. Thermo Fisher TaqMan MicroRNA Assay FAQs (lot-to-lot < 0.6 Ct; 90–110 % across 5 logs). https://www.thermofisher.com/order/catalog/product/4440888/faqs
17. Thermo Fisher TaqMan Non-coding RNA Assay FAQs (several hundred assays tested; not all functionally tested). https://www.thermofisher.com/order/catalog/product/4426963/faqs
18. Hellemans J, Vandesompele J et al. PrimePCR Assays: Meeting the MIQE Guidelines by Full Wet-Lab Validation. Bio-Rad Bulletin 6262 (2012). https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/Bulletin_6262.pdf
19. Bio-Rad PrimePCR pathway page (90–110 %, R² > 0.99, NGS specificity). https://www.bio-rad.com/en-us/pathwayhomepage/1455666205169
20. Bio-Rad Real-Time PCR Applications Guide, Bulletin 5279 (90–105 %, R² > 0.980). https://www.bio-rad.com/webroot/web/pdf/lsr/literature/Bulletin_5279.pdf
21. IDT DECODED: Consider SNPs when designing PCR and qPCR assays (2017, updated 2025). https://www.idtdna.com/page/wp-json/wp/v2/posts/832
22. IDT: Storing oligos: 7 things you should know. https://www.idtdna.com/page/support-and-education/decoded-plus/storing-oligos-7-things-you-should-know/
23. IDT: My oligos have arrived: now what? https://www.idtdna.com/page/support-and-education/decoded-plus/my-oligos-have-arrived-now-what/
24. IDT PrimeTime pre-designed assays (press/product summaries). https://www.technologynetworks.com/genomics/product-news/idt-primetime-predesigned-assays-increase-qpcr-accuracy-and-efficiency-218882 ; https://labonline.com.au/content/life-science-clinical-diagnostics-instruments/product/integrated-dna-technologies-primetime-pre-designed-qpcr-assays-1288948807 ; https://eu.idtdna.com/page/?p=850
25. Lefever S, Pattyn F, Hellemans J, Vandesompele J. Single-nucleotide polymorphisms and other mismatches reduce performance of quantitative PCR assays. Clin Chem 2013;59(10):1470–80. PMID 24014836. https://europepmc.org/article/MED/24014836
26. Stadhouders R et al. The effect of primer-template mismatches on the detection and quantification of nucleic acids using the 5' nuclease assay. J Mol Diagn 2010;12(1):109–117. https://pmc.ncbi.nlm.nih.gov/articles/PMC2797725/
27. Gubelmann C et al. GETPrime 2.0: gene- and transcript-specific qPCR primers for 13 species including polymorphisms. NAR 2017. https://pmc.ncbi.nlm.nih.gov/articles/PMC5210624/ ; https://pubmed.ncbi.nlm.nih.gov/28053161/
28. qPrimerDB 2.0 (NAR 2025). https://pmc.ncbi.nlm.nih.gov/articles/PMC11701640/ ; https://qprimerdb.biodb.org/
29. PrimerBank. https://pga.mgh.harvard.edu/primerbank/
30. RTPrimerDB domain (redirects to https://omics.gentaur.com/). https://www.rtprimerdb.org/
31. A comprehensive collection of experimentally validated primers for PCR quantitation of murine transcript abundance. BMC Genomics 2008;9:633. https://bmcgenomics.biomedcentral.com/articles/10.1186/1471-2164-9-633
32. openPrimeR (Bioconductor, GPL-2). https://bioconductor.org/packages/release/bioc/html/openPrimeR.html
33. rprimer (Bioconductor, GPL-3). https://bioconductor.org/packages/release/bioc/html/rprimer.html
34. DECIPHER (Bioconductor, GPL-3). https://bioconductor.org/packages/release/bioc/html/DECIPHER.html
35. seqfold (MIT). https://github.com/Lattice-Automation/seqfold
36. primers (MIT). https://pypi.org/project/primers/
37. seqkit (MIT) https://github.com/shenwei356/seqkit ; amplicon usage https://bioinf.shenwei.me/seqkit/usage/
38. ThermonucleotideBLAST (BSD-3). https://github.com/jgans/thermonucleotideBLAST ; LICENSE https://raw.githubusercontent.com/jgans/thermonucleotideBLAST/master/LICENSE
39. MFEprimer. https://www.mfeprimer.com/ ; https://www.mfeprimer.com/license/ ; https://github.com/quwubin/MFEprimer-3.0
40. Johnston AD et al. PrimerROC: accurate condition-independent dimer prediction using ROC analysis. Sci Rep 2019. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6338771/
41. Biopython Bio.SeqUtils.MeltingTemp docs https://biopython.org/docs/latest/api/Bio.SeqUtils.MeltingTemp.html ; licence https://raw.githubusercontent.com/biopython/biopython/master/LICENSE.rst
42. UCSC Genome Browser licence page. https://genome.ucsc.edu/license/
43. Ensembl legal/disclaimer. https://jun2026.archive.ensembl.org/info/about/legal/disclaimer.html ; https://www.ensembl.org/info/about/legal/index.html
44. Ensembl REST overlap/region documentation. https://rest.ensembl.org/documentation/info/overlap_region
45. Ensembl REST rate limits. https://github.com/Ensembl/ensembl-rest/wiki/Rate-Limits
46. NCBI policies and disclaimers (public domain; request limits). https://www.ncbi.nlm.nih.gov/home/about/policies/
47. RDML-consortium/rdml-schema (MIT) https://github.com/RDML-consortium/rdml-schema ; v1.3 XSD https://raw.githubusercontent.com/RDML-consortium/rdml-schema/master/RDML_v1_3_REC.xsd ; v1.4 CR XSD https://raw.githubusercontent.com/RDML-consortium/rdml-schema/master/RDML_v1_4_CR.xsd
48. RDML-consortium/rdmlpython (MIT). https://github.com/RDML-consortium/rdmlpython
49. Svec D, Tichopad A, Novosadova V, Pfaffl MW, Kubista M. How good is a PCR efficiency estimate: Recommendations for precise and robust qPCR efficiency assessments. Biomol Detect Quantif 2015. https://www.gene-quantification.de/svec-et-al-pcr-efficiency-bdq-2015.pdf
50. Hastings WJ, Eisenberg DTA, Shalev I. Impact of Amplification Efficiency Approaches on Telomere Length Measurement via qPCR. Front Genet 2021;12:728603. https://pmc.ncbi.nlm.nih.gov/articles/PMC8484782/
51. Rogers-Broadway KR, Karteris E. Amplification efficiency and thermal stability of qPCR instrumentation. Exp Ther Med 2015;10:1261–1264. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4578049/
52. gene-quantification.de, PCR efficiency page. https://www.gene-quantification.de/efficiency.html
53. Ruijter JM et al. Efficiency correction is required for accurate quantitative PCR analysis and reporting. Clin Chem 2021;67:829–842. https://researchoutput.csu.edu.au/en/publications/efficiency-correction-is-required-for-accurate-qpcr-analysis-and-/ ; commentary https://www.econferences.de/one-more-time-do-not-ignore-the-amplification-efficiency
54. Effects of storage conditions on the stability of qPCR reagents: implications for environmental DNA detection. BMC Res Notes 2024. https://pmc.ncbi.nlm.nih.gov/articles/PMC11264737/
55. ResearchGate: How long can one store primers? https://www.researchgate.net/post/How_long_can_one_store_primers
56. protocol-online: the storage time for primers http://www.protocol-online.org/biology-forums-2/posts/28871.html ; Primers stopped working!? https://www.protocol-online.org/biology-forums-2/posts/18948.html (404 at fetch time)
57. AAT Bioquest FAQ: What should I consider when I set up a PCR efficiency test for my assay? https://www.aatbio.com/resources/faq-frequently-asked-questions/what-should-i-consider-when-i-set-up-a-pcr-efficiency-test-for-my-assay
58. VoilaPCR: Primer efficiency below 90 %. https://voilapcr.com/blog/primer-efficiency-below-90-what-it-means-and-how-to-fix-it
59. CASRAI guide: qPCR melt curve analysis, peaks, primer dimers. https://www.casrai.org/guides/qpcr-melt-curve-analysis-peaks-primer-dimers
60. Yeasen: Troubleshooting abnormal melt curves. https://www.yeasenbio.com/blogs/molecular-biology/why-does-your-melt-curve-look-so-strange
61. NEB FAQ: Why do I see amplification curves in my NTC samples? https://www.neb.com/en-us/faqs/why-do-i-see-amplification-curves-in-my-ntc-samples
62. Yeasen: Do qPCR primers need to span introns? https://www.yeasenbio.com/blogs/ivd/do-qpcr-primers-need-to-span-introns
63. protocol-online thread on pseudogenes and intron-spanning primers. https://protocol-online.org/biology-forums-2/posts/23040.html
64. Lot-to-lot verification: CLN Bench Matters 2014 https://myadlm.org/cln/articles/2014/july/bench-matters ; CCLM 2022 https://doi.org/10.1515/cclm-2022-1126 ; APHL verification toolkit https://www.aphl.org/aboutAPHL/publications/Documents/QSA-VV-Toolkit.pdf ; Cho et al. 2014 https://journals.sagepub.com/doi/10.1177/0004563214520749
65. Quartzy–Benchling integration guide https://support.quartzy.com/hc/en-us/articles/13448531646491 ; Quartzy pricing https://www.softwareadvice.com.au/software/150604/quartzy
66. eLabFTW documentation (AGPLv3; API). https://doc.elabftw.net/
67. Bridges Lab: Primer Design for qPCR (lab primer sheet, naming). https://bridgeslab.sph.umich.edu/protocols/index.php/Primer_Design_for_qPCR
68. Mullins Lab PrimerDB. https://indra.mullins.microbiol.washington.edu/Primer/primersearch.html
69. UW Biology primer ordering procedure. https://www.biology.washington.edu/sites/default/files/pdf/purchasing/PrimersLSB.pdf
70. Geneious primer design feature page. https://www.geneious.com/features/primer-design
71. Premier Biosoft Beacon Designer. http://www.premierbiosoft.com/qpcr/index.html
72. Vogels CBF et al. Analytical sensitivity and efficiency comparisons of SARS-CoV-2 RT-qPCR primer-probe sets. Nat Microbiol 2020. https://www.nature.com/articles/s41564-020-0761-6
73. Ring trials: MAP qPCR inter-laboratory comparison, Microbiol Spectrum 2023 https://journals.asm.org/doi/full/10.1128/spectrum.02210-23 ; direct RT-qPCR SARS-CoV-2 ring trial, PLoS ONE https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0261853
74. uMELT Quartz. https://dna-utah.org/umelt/quartz/
75. Quantification Revisited: What qPCR Efficiency Models Reveal About Data Analysis Integrity. IJMS 2026. https://www.mdpi.com/1422-0067/27/5/2337
76. Unicorn Lifescience blog on MIQE compliance (secondary, unverified figures). https://unicornlifescience.com/miqe-guidelines-qpcr-reporting-compliance/
77. Gubelmann C et al. GETPrime (2012) original paper copy. https://www.gene-quantification.de/gubelmann-et-al-getprime-2012.pdf
78. Lock et al. Efficiency clustering for low-density microarrays and its application to QPCR. 2010. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2912893/
79. Thermo Fisher: Common TaqMan myths busted. https://www.thermofisher.com/us/en/home/life-science/pcr/real-time-pcr/real-time-pcr-assays/common-taqman-myths-busted.html
80. PrimeSpecPCR (MIT; uses primer3-py). https://github.com/Adv20202/PrimeSpecPCR
81. ISO 20395:2019 Biotechnology — Requirements for evaluating the performance of quantification methods for nucleic acid target sequences — qPCR and dPCR (content not read). https://www.iso.org/standard/67893.html
82. UGENE remote Primer-BLAST documentation. https://ugene.net/docs/extensions/remote-blast/primer-blast/
83. LabArchives Inventory quick-start (University of Kentucky). https://research.uky.edu/sites/default/files/2025-01/inventory_labmember_qsg_1.1.pdf
84. Mountain Scholar thesis on primer mismatches and quantification accuracy. https://mountainscholar.org/items/40777ea2-66bc-4356-a7f9-474889b6cb9b
85. Pitfalls in genetic testing: SNP in primer-annealing region leading to allele dropout in BRCA1. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5511807/
86. Taylor SC et al. The Ultimate qPCR Experiment. Trends Biotechnol 2019. https://www.cell.com/trends/biotechnology/fulltext/S0167-7799(18)30342-1
87. Ruijter et al., melt-curve analysis manuscript (Amsterdam UMC repository). https://pure.amsterdamumc.nl/ws/files/107164215/Ruiter_et_al_Melt_curve_resub.pdf
