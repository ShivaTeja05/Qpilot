# Clarida and other qPCR tools: competitive analysis for qPilot's Decision Simulator (17 Oct 2026)

## 1. Bottom line

- **Clarida doesn't simulate anything in its product.** It doesn't simulate plate layouts, offer power or sample-size tools, re-run analyses across choices, or measure how much each sample drives a result. It gives one locked analysis configuration and computes statistics on demand, and it has made that a stated anti-p-hacking principle. On its methods page, Clarida says statistics have "no live preview that updates as you nudge a parameter" ([exploration methods](https://clarida.bio/resources/methods/exploration-and-stored-analyses)).
- **Clarida already exposes the same decision axes qPilot varies.** Its "settings sets" are named, versioned and locked bundles of 74 settings, including Cq method, baseline method, Cq aggregation, normalization mode and efficiency mode. "Compare with…" compares two sets' setting values; no comparison of results is described ([settings sets](https://clarida.bio/resources/methods/settings-sets)). qPilot's pitch is simple: Clarida records which choices you made, and qPilot shows whether the conclusion survives the other choices.
- **Raw curves no longer set qPilot apart.** Since release 2026.9 (7 Sep 2026), Clarida reads native .pcrd, .eds, .ixo/.xml and .rex/.qrex files and shows raw amplification and melt curves. It calls Cq by threshold, SDM or LinRegPCR per-well efficiency ([changelog 2026-9](https://clarida.bio/changelog/2026-9)).
- **qPilot's benchmark dataset belongs to Clarida's founders.** In the Vermeulen 2009 study, Vandesompele is the corresponding author and Hellemans a co-author ([em-consulte](https://em-consulte.com/article/362377/predicting-outcomes-for-children-with-neuroblastom), [CRAN vermeulen](https://cran.r-project.org/web/packages/vermeulen/index.html)). Their 2013 benchmark on the same data compared curve-analysis methods and found most performed reasonably well for biomarkers ([Europe PMC record](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:22975077%20AND%20SRC:MED&resultType=core&format=json)). Clarida's own blog uses this data for a 4 vs 4 demo ([efficiency blog](https://clarida.bio/blog/why-use-the-real-pcr-efficiency)).

## 2. What Clarida does at each stage

| Stage | What it does | Simulates anything? |
|---|---|---|
| Define | Research question, hypothesis, references, protocol, completeness checklist. Suggests 8–12 candidate reference genes ([home](https://clarida.bio/), [ref-gene use case](https://clarida.bio/use-cases/reference-gene-validation)) | No |
| Design | Plate layout in Auto, Assisted or Manual mode, with four settings: block by, orientation, block style, replicate placement. No randomization, NTC/IRC placement or layout scoring is described ([blog](https://clarida.bio/blog/plate-layout-generation), [algorithm](https://clarida.bio/resources/methods/plate-layout-algorithm)) | No; no power or sample size |
| Execute | Pipetting guidance. The Porta connector watches export folders and reads a finished LC480 run straight from its database ([Porta](https://clarida.bio/resources/methods/connecting-instruments-with-porta)) | No |
| Analyze | qBase NRQ, standard-curve efficiency, auto-exclusion by replicate ΔCq, late Cq or undetermined ([2026-4](https://clarida.bio/changelog/2026-4)). Sample and assay QC, OLS inter-run calibration, global mean normalization. Eight confirmatory tests: Welch, Student, paired t, Wilcoxon, Mann-Whitney, one-way ANOVA with post-hoc, Pearson, Spearman ([2026-6](https://clarida.bio/changelog/2026-6)). Detection cut-offs with per-target override; unmeasured wells are not counted as negative ([2026-9](https://clarida.bio/changelog/2026-9)) | No. Tests are computed on click and each saved run is frozen |
| Report | Figures, methods text, MIQE score (demo shows 47/51 essential, 14/17 desirable), proposed conclusions with Accept/Edit buttons. Exports PDF, PPT, Excel, RDML and an ELN record ([home](https://clarida.bio/), [2026-7](https://clarida.bio/changelog/2026-7)) | See below |
| Free tools | geNorm finder with on/off checkboxes per sample and gene and a recalculate step, no account needed ([genorm](https://clarida.bio/tools/genorm)). Plate homogeneity: Cq SD, missing values, share of wells near the median Cq, heatmap ([blog](https://clarida.bio/blog/functional-qpcr-instrument-validation)) | Manual what-if on reference-gene ranking only |

**Business facts**
- Pricing: free (2 experiments a month), €15 per experiment pay-as-you-go, €8–10 per experiment on the Lab plan, custom Center plan ([pricing](https://clarida.bio/pricing)).
- Cloud SaaS on Next.js, FastAPI, Supabase and Fly.io. MVP targeted Q2 2026, full release end of 2026. The founders say they direct Claude Code ([job post](https://clarida.bio/jobs/founding-engineer)).
- LinkedIn: founded 2025 in Ghent, 254 followers ([LinkedIn](https://www.linkedin.com/company/clarida)).
- The planned list on the geNorm page includes an "API and MCP server", NormFinder, missing-data handling and multi-experiment analysis ([genorm](https://clarida.bio/tools/genorm)).

**Closest things to simulation at Clarida**
1. A blog post by Ruijter and van den Hoff (1 Oct 2026) simulates efficiencies from 1.7 to 2.0 and shows that ddCq can reverse the direction of an effect ([blog](https://clarida.bio/blog/why-use-the-real-pcr-efficiency)). This is marketing content, not a product feature.
2. The geNorm checkbox toggles.
3. A homepage demo conclusion card says that excluding 4 of 378 flagged wells does not change significance ([home](https://clarida.bio/)). This is mock UI; it does not appear in the methods pages or changelog.

**Inconsistency in Clarida's own docs:** the import-methods page still says raw curves are not re-read ([import](https://clarida.bio/resources/methods/importing-instrument-data)), which looks like it predates 2026.9.

## 3. Other tools

| Tool | What it does | Simulation or what-if |
|---|---|---|
| CFX Maestro 2.3 | Biological groups, reference-gene selector (geNorm M), t-test and one-way ANOVA, volcano plots ([Bio-Rad](https://www.bio-rad.com/en-ie/product/cfx-maestro-software-for-cfx-real-time-pcr-instruments?ID=OKZP7E15), [Bioradiations](https://www.bioradiations.com/reference-gene-selection-using-primepcr-plates-and-cfx-maestro-software/)) | None listed |
| Thermo Design & Analysis 2 / Connect RQ | Correlation, volcano and cluster plots. Cq above the maximum is either capped or treated as undetermined ([modules](https://www.thermofisher.com/us/en/home/cloud/all-analysis-modules.html), [RQ guide](https://qa1-assets.thermofisher.cn/TFS-Assets/LSG/manuals/MAN0018747_RelativeQuantificatAnalysisModule_QSDASWv2_UG.pdf)) | None listed |
| GenEx | Pre-processing, missing data, t-test, ANOVA, PCA, SVM, nested ANOVA ([TN](https://www.technologynetworks.com/tn/product-news/tataa-and-multid-launch-genex-6-223502), [gene-quantification](https://gene-quantification.de/genex.html)) | Design planning only (the only prospective one). Sample-size and design-optimization editions UNVERIFIED (from a search snippet). Based on Kitchen et al. 2010; the related powerNest tool is unmaintained, last release v0.5.7 in 2009 ([powerNest](https://groups.inf.ed.ac.uk/nesc-research/powernest.html)) |
| qbase+ (legacy) | geNorm, NRQ, statistical wizard. Deprecated after the CellCarta acquisition ([Bio-Rad](https://www.bio-rad.com/webroot/web/html/lsr/products/amplification_pcr/product_overlay/global/qbasec_cfx_touch.html), [Clarida](https://clarida.bio/what-happened-to-qbase-plus)) | None found |
| LinRegPCR web / RDML-Tools | Raw fluorescence through to group statistics, per-well efficiency, outlier detection, RDML-TestStat ([PMC8386043](https://pmc.ncbi.nlm.nih.gov/articles/PMC8386043), [RDML-Tools](https://www.gear-genomics.com/rdml-tools/)) | None |
| VoilaPCR | Browser-based ΔΔCt, Pfaffl and geNorm, "8 diagnostic checks" ([site](https://voilapcr.com/)) | UNVERIFIED: the page didn't render, so features come from a search snippet |
| ProntoPCR (JOSS 2026) | R Shiny tool for ΔΔCq and fold change ([JOSS](https://joss.theoj.org/papers/10.21105/joss.09949)) | None |
| AnnealIQ (beta) | LLM-driven chat analysis that **picks the statistical test automatically**, Grubbs outlier test, MIQE 2.0 checklist ([site](https://www.annealiq.ai/), [guide](https://www.annealiq.ai/guides/miqe-compliance-guide)) | Exclude a replicate and re-run, one case at a time |
| SATqPCR | Automatic geNorm reference selection, t-test, ANOVA ([FAQ](https://satqpcr.sophia.inrae.fr/cgi/help.cgi)) | None |
| Auto-qPCR (Sci Rep 2021) | Iterative replicate removal at SD > 0.3, FDR-corrected statistics ([PMC8556264](https://pmc.ncbi.nlm.nih.gov/articles/PMC8556264/)) | The paper swept the SD cut-off against manual analysis: the only single-choice sensitivity check I found |
| PCR.AI | Clinical diagnostic curve calling, Westgard rules, CE-IVDR/MHRA registration ([BusinessWire](https://www.businesswire.com/news/home/20250528880805/en)) | Not gene-expression research |
| Theoretical simulators | chipPCR AmpSim (Richards-curve generator with noise, missing values and photobleaching) and qpcR pcrsim ([AmpSim](https://rdrr.io/cran/chipPCR/man/AmpSim.html)) | Generate curves; could drive a generative layer for qPilot |

## 4. Clarida's workflow vs qPilot's Decision Simulator

| Feature | Clarida (runs the experiment workflow) | qPilot Decision Simulator |
|---|---|---|
| Define, design, bench guidance | Yes | No |
| Power or sample size | No | Empirical only (3 vs 3 and 6 vs 6 subsampling) |
| Raw-curve Cq method choice | 3 methods, you pick one | LinRegPCR only; no threshold or baseline axis yet |
| Efficiency | Per-well LinRegPCR, standard curve or library value, you pick one | Assay mean, per-well and 100% all run |
| Reference genes | geNorm with toggles, global mean | geNorm plus all 31 subsets run |
| Tests | 8, one per saved run | 3, all run at once; no paired test or ANOVA |
| Multiple testing | Correction named only for correlations | None, BH and Holm all run |
| Analysis configuration | 74 locked, versioned settings | 7 axes, 22,599 analyses in 14 s |
| Do conclusions survive other choices? | Not computed | Flip maps, variance share per choice, interaction flips |
| Sample and well influence | Flags outliers; one demo exclusion claim | Exact leave-one-out, drop-k-to-flip, 1,745 reference-well removals |
| Detector validation | Nothing published | 220 planted faults, 85% of call-changing faults detected |
| Traceability | Frozen snapshots; audit log on Center plan | Hash-chained Analysis Record |
| AI | MCP server planned | MCP server built; local model planned |
| Deployment and price | Cloud, €0–15 per experiment | Local, Apache-2.0 |

## 5. Why nobody has built this

- I found no qPCR multiverse tool. My searches turned up only general multiverse work ([Wikipedia](https://en.wikipedia.org/wiki/Multiverse_analysis)) and many-analyst studies in ecology ([Gould 2025](https://research.vu.nl/en/publications/same-data-different-analysts-variation-in-effect-sizes-due-to-ana/)). A failed search is not proof that none exists.
- The field's reference evidence, the 2013 benchmark, varied one choice (curve analysis) and found results robust. It held reference genes and grouping fixed, and qPilot finds those two explain 52% and 27% of fold-change variance.
- Inference, not sourced: workflow and instrument vendors sell a single trusted answer, and a tool that exposes fragility hurts that pitch. Clarida also treats live re-computation as a p-hacking risk.

## 6. What qPilot should copy

1. Map its axes onto Clarida's settings vocabulary (Cq method, baseline, aggregation, efficiency mode) and add the missing ones: Cq method, baseline, late-Cq/detection cut-off with per-target override.
2. One primary pre-declared configuration, frozen, with the multiverse attached as a robustness report rather than as alternative answers.
3. Proposed-conclusion cards in plain language with Accept/Edit buttons, of the form "excluding these N wells does not change this call", backed by real computation.
4. Native instrument file readers, plus paired tests and ANOVA.
5. Free, no-account single tools as a funnel, for example "Does my call survive?" on one uploaded file.
6. Content written by credible authors, plus a MIQE checklist score.

## 7. Arguments Clarida's team would use, with rebuttals

| Their argument | qPilot's answer |
|---|---|
| A multiverse is a p-hacking machine | qPilot never lets you choose a branch. It reports the distribution and requires a Decision Card for any choice that can flip a conclusion, which makes p-hacking visible instead of easy. |
| Your "defensible" options aren't defensible: 100% efficiency and Cq 40 contradict our own blog and MIQE 2.0 | Agreed. Lead with the 46/58 defensible-only result and drop the indefensible arms from the headline. |
| Your MYCN top-X% cut is a contrast you made up on our data | This is the weakest point: grouping is the biggest driver of flips. Validate on studies with a designed contrast, such as Untergasser dilution series with known copy numbers. |
| Fragility comes from your own 2-fold rule (your permutation test finds 57/58 genes associated) | Present it as sensitivity of the reported claim, which is what papers publish. Offer an effect-size view without the threshold. |
| Prevention beats autopsy: design and validate up front | Make the two complementary. Pitch qPilot as an MCP/plug-in check that runs on top of Clarida's RDML export. |
| We now read raw files and run LinRegPCR | Concede it. qPilot's moat is robustness and influence analysis, not file import. |
| Two-group Welch only; no paired designs, ANOVA, IRC or multiplex | True gap; add them. |
| MIQE authors versus a hackathon team with no wet-lab scientist | Point to the 220-fault benchmark, exact reproduction to 1e-12, and open code. Recruit a wet-lab advisor. |

## UNVERIFIED and gaps

- GenEx edition table (sample size, design optimization): search snippet only.
- VoilaPCR features: page did not render.
- Clarida's MIQE score and homepage conclusion cards are demo UI, not documented features.
- No Clarida webinar found. The only Hellemans webinar found is a 2024 talk given as COO of pxlence ([Bioradiations](https://www.bioradiations.com/qpcr-and-ddpcr-assay-validation-in-regulated-environments-624/)).
- I did not open MIQE 2.0's checklist structure.
- No 2025–2026 LLM qPCR paper found.