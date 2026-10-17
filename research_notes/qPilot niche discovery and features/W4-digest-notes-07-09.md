# Digest of wave-1 notes 07, 08, 09 for qPilot

Conventions: `[n]` citations in the notes are resolved to the URL from that note's §6. "(uncited in note)" marks numbers with no inline citation. "Estimate" / "inference" labels are the notes' own. Ranks and confidence levels are the notes' own.

---

# NOTE 07 — Turning qPCR amplification curves into conclusions: methods, statistics, malpractice, and what a robustness engine should sweep, model and refuse

Method caveat stated by the note: search budget ran out after 12 searches; forums (Stack Exchange, Biostars, ResearchGate) were blocked; evidence comes from published audits and primary papers fetched directly. Rieu & Powers 2009 and Pfaffl 2001 could not be fetched and are cited only through other sources.

## A. How this corner works

A qPCR run yields one fluorescence curve per well (96 or 384 wells, typically 40–45 cycles — uncited in note); instrument software subtracts a baseline, applies a threshold and reports Cq. MIQE 2.0 lists baseline method, threshold policy (shared vs per-run) and smoothing as steps that silently change Cq, and states that Cq/ΔCq/ΔΔCq are "intermediate data" on which statistical tests "should be avoided" (https://doi.org/10.1093/clinchem/hvaf043). Converting Cq to starting quantity needs efficiency E: N0 = Nq/E^Cq (https://www.gene-quantification.de/ruijter-et-al-variation-multi-plate-pcr-bdq-2015.pdf). Two schools estimate E: dilution-series standard curves (Svec: 95% CI of E is 42.5% from single replicates, 3.3% with 15 replicates; one careful curve per assay, never one per run — https://www.gene-quantification.de/svec-et-al-pcr-efficiency-bdq-2015.pdf) and per-well LinRegPCR (Ruijter: dilution steps were actually 8–9.9-fold instead of 10 in a 69-gene reanalysis — https://europepmc.org/article/PMC/PMC12733170). MIQE 2.0 adopts the per-assay mean of per-well efficiencies with a common threshold.

Multi-plate studies differ by a near-constant factor (6-fold between two runs of the same samples — https://www.gene-quantification.de/ruijter-et-al-variation-multi-plate-pcr-bdq-2015.pdf); a single inter-run calibrator inflates error ~70% (ratio 1.68) (https://europepmc.org/article/PMC/PMC1852402). Non-detects are missing-not-at-random; Cq = 40 substitution turned observed ΔΔCq of −0.16 and −1.54 into ~−2.5 (https://europepmc.org/article/PMC/PMC4133581).

Money: no price data found for GenEx or qbase+; qbaseplus.com showed a "domain may be for sale" placeholder on 17 Oct 2026 (https://www.qbaseplus.com/). Time: manual review of a 384-well TaqMan Array Card (up to 768 amplifications) is "time-consuming and subjective" (https://gatesopenresearch.org/articles/9-1). Malpractice: a 355-article audit found efficiency reporting fell from 13% (2019) to 1% (2024), reference-gene validation 13%→5%, RNA integrity 22%→11% (https://doi.org/10.1093/clinchem/hvaf176); validity was adequately assessable in only 3% (6/179) of colorectal-cancer qPCR papers (https://europepmc.org/article/PMC/PMC5528534).

## B. Pain inventory (top 8 of 10)

| # | Pain | Who feels it | Frequency/severity as stated | What exists today | Evidence URL(s) |
|---|---|---|---|---|---|
| P1 | Fold changes reported without uncertainty; 1.2–1.5× treated as real | PhD students, PIs, reviewers | Typical reported changes 1.5–5×; **estimate**: a large share of published claims sit below the credible floor at their Cq | Vendor software/Excel give point FC; qbase+ propagates error but is closed; no tool computes a Cq-dependent floor | https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/ ; https://doi.org/10.1111/eci.12801 ; https://europepmc.org/article/PMC/PMC12387016 |
| P2 | Efficiency unknown or assumed 100% | Nearly everyone | 99% of general 2024 papers; 20–40% FC distortion; FPR 7.3% vs 5% when E uncertainty ignored | LinRegPCR gives per-well E; vendor curves need extra wells per run; no tool propagates E uncertainty into p-values | https://doi.org/10.1093/clinchem/hvaf176 ; https://pmc.ncbi.nlm.nih.gov/articles/PMC4827196/ ; https://www.gene-quantification.de/svec-et-al-pcr-efficiency-bdq-2015.pdf |
| P3 | Cq depends on threshold/baseline/well position | Anyone comparing runs or instruments | Every run on CFX96/384 and StepOne blocks; efficiencies 1.79–2.19 from periodic Ct; ratio 0.7–9.5 under 2% baseline error | Instrument software hides the choice; LinRegPCR fixes one method; no tool shows method-dependence | https://europepmc.org/article/PMC/PMC5154181 ; https://pmc.ncbi.nlm.nih.gov/articles/PMC2665230/ |
| P4 | Multi-plate: plates differ by a constant factor; calibrator failures bias everything | Any study >1 plate (most) | 6-fold between-run difference; single IRC inflates error ~70% | Factor-qPCR (Windows, no licence); qbase+ IRCs (closed); vendor software ignores plates | https://www.gene-quantification.de/ruijter-et-al-variation-multi-plate-pcr-bdq-2015.pdf ; https://europepmc.org/article/PMC/PMC1852402 |
| P5 | Non-detects substituted with 40 or dropped | Low-expression genes, miRNA, pathogen panels | 1.2–2.8% of values in McCall's datasets; far higher in miRNA/low-input work (**estimate**) | nondetects (GPL-3, R); UCNR scripts (GPL-3); vendor substitutes/blanks | https://europepmc.org/article/PMC/PMC4133581 ; https://pmc.ncbi.nlm.nih.gov/articles/PMC5560691/ |
| P6 | Pseudoreplication: technical triplicates used as n | Students, small labs | 46% pseudoreplication in animal studies; **estimate**: common wherever n = 3 wells is the design | GraphPad/Excel accept any numbers; no tool infers experimental unit from layout | https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.2005282 ; https://doi.org/10.1093/clinchem/hvaf043 |
| P7 | Reference genes picked by habit or by RefFinder on raw Cq | Plant/animal/microbiology labs | 95% of 2024 general papers do not validate; ignoring E changed geNorm rankings in 71% of comparisons | RefFinder (PHP, raw Cq); geNorm in qbase+ (closed); NormqPCR (LGPL-3) | https://doi.org/10.1093/clinchem/hvaf176 ; https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0122515 ; https://pmc.ncbi.nlm.nih.gov/articles/PMC6650036/ |
| P8 | Reviewers cannot check the analysis | Reviewers, editors, core managers | Essentially all submissions; validity assessable in 3% of papers | MIQE checklist is self-reported; no machine-derived statistics statement | https://doi.org/10.1093/clinchem/hvaf176 ; https://europepmc.org/article/PMC/PMC5528534 |

Remaining two: P9 (R packages unmaintained/GPL; `pcr` archived 2025-11-07; only 3 of 27 tools read RDML — https://cran.r-project.org/package=pcr ; https://europepmc.org/article/PMC/PMC5129434) and P10 (low-copy targets: LLOQ ≈ 10 copies ≈ Cq 35 at 90% E; ≥5 replicates above Cq 30; **estimate**: a large share of cytokine/TF targets — https://doi.org/10.1093/clinchem/hvaf043 ; https://europepmc.org/article/PMC/PMC12387016).

## C. Discoveries

### §3.0 Design derivation (the note's evidence-backed sweep/model/refuse list)
**Sweep axes (each with fetched evidence that it moves conclusions):** (1) baseline method — Ruijter 2009 ratio 0.7–9.5 under 2% baseline error (https://pmc.ncbi.nlm.nih.gov/articles/PMC2665230/); (2) Cq method/threshold — Spiess 2016 periodicity (https://europepmc.org/article/PMC/PMC5154181); (3) efficiency model {per-well, per-assay mean, per-plate mean, dilution series, assumed 2.0} — Bilgrau p 5×10⁻⁴ → 0.31 (https://pmc.ncbi.nlm.nih.gov/articles/PMC4827196/); Bustin 11.3–23.0 at ΔCq 4 (https://doi.org/10.1093/clinchem/hvaf176); (4) E-uncertainty plug-in vs delta method — FPR 0.073 vs 0.053; (5) reference set and algorithm input (geNorm vs NormFinder; E-corrected vs raw Cq) — 71%/50% ranking changes; plus "no reference, ΔCt-only" universe (https://pmc.ncbi.nlm.nih.gov/articles/PMC11844642/); (6) plate model {none, Factor-qPCR, IRC, random intercept}; (7) non-detect rule {censor at LOD, EM/MI, substitute LOD, substitute 40, drop} — Pipelers censoring-tolerance 0.90 vs 0.34–0.79 (https://pmc.ncbi.nlm.nih.gov/articles/PMC5560691/); (8) replicate aggregation; (9) test {LMM on log quantities, t on ΔCq, Wilcoxon, randomisation}; (10) kinetic outlier rule (roadmap item, not re-researched).

**Model (default engine):** y = log N0, N0 = Nq/E^Cq; fixed effects condition × target; random intercepts for plate and biological sample (and RT replicate); right-censoring at assay LOD; delta-method E-uncertainty (Ruijter 2015 Eq. 9–11; Bilgrau); inference per biological unit; prediction intervals; MIQE 2.0 fold-difference definition. Optional Bayesian variant following Matz's Poisson-lognormal structure (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0071448).

**Refuse / downgrade to "cannot conclude" (number still visible, reason logged):** p-values on uncorrected Cq/ΔCq/ΔΔCq; group tests with <2 biological units per group; fold-change claims below the Cq-dependent credible floor — **<2× at Cq <25, <3× at Cq 25–30, <4× at Cq >30** (Bustin 2025, https://europepmc.org/article/PMC/PMC12387016) or when the CI includes 1; interpreting <2× changes or ΔCq ≥3 under "assumed 100%" efficiency; fixed-Cq substitution when >~30% of a group is censored without sensitivity analysis; inter-run correction needing >2 rounds of substitution ("run another plate"); conclusions that differ across reference-set universes when a reference pair's ratio shifts (Hampton's 93.2% FPR).

### D1. Efficiency-uncertainty-aware inference and the efficiency-model sweep — rank 2 of 8
- **Persona:** any scientist comparing groups where target and reference assays differ in E (4 of 11 assays deviated >10% in De Spiegelaere's panel); daily.
- **Pain evidence:** 1% of 2024 papers report E; FC 11.3–23.0 across 92–110% E at ΔCq 4 (https://doi.org/10.1093/clinchem/hvaf176); ignoring E uncertainty → FPR 0.073 at nominal 0.05 and p-value flip 5.35×10⁻⁴ → 0.313 (https://pmc.ncbi.nlm.nih.gov/articles/PMC4827196/); single-replicate standard curves carry 32–42.5% CIs (https://www.gene-quantification.de/svec-et-al-pcr-efficiency-bdq-2015.pdf).
- **Exists / why fails:** qbase+ propagates slope error but is closed and of uncertain status; LinRegPCR reports per-assay mean E without carrying its SE into group tests; Cq-input tools assume E; Bilgrau's delta-method code is an unlicensed knitr repo (https://github.com/AEBilgrau/effadj).
- **Feature:** inputs = per-well E and Cq from rdmlpython plus Nq. Method: per-assay mean E with SE pooled over plates (Ruijter 2015 Eq. 7–11, https://www.gene-quantification.de/ruijter-et-al-variation-multi-plate-pcr-bdq-2015.pdf); per-well y = log Nq − Cq·log E with Var(y) ≈ (Cq/E)²·Var(E) + Var(Cq-residual); contrasts with combined variance (Bilgrau EC&VA1); five-universe sweep over the efficiency model. Decision Card "Efficiency model" with per-gene FC/CI/p table; recommendation = per-assay mean with propagation unless inhibition flags suggest per-well (MIQE 2.0 clinical clause). Record: E_mean, SE(E), method, universe results, chosen universe + reason. MCP: `qpcr_robustness(axis="efficiency_model")`, `qpcr_decide`.
- **Feasibility:** numpy/scipy; 3–5 days incl. tests reproducing Bilgrau's 0.073/0.053 and Svec's CI widths. Hardest: variance of Cq residuals when technical replicates are absent.
- **Why qPilot:** only a raw-curve tool has per-well E and its spread; grid, cards and record exist.
- **Risks/confidence:** delta method is first-order; at very low copies Poisson dominates, so include a bootstrap as second estimator. **Confidence: high.**

### D2. Study-level model: plate-aware, censored, log-scale mixed model with prediction intervals — rank 1 of 8
- **Persona:** PhD student or core analyst with 4–12 plates, 6–40 biological samples, 3–8 targets, some undetermined wells; once per study plus every revision.
- **Pain evidence:** between-run factors up to 6×; single-IRC error inflation ~70%; non-detects MNAR with Cq = 40 substitution creating spurious effects (https://europepmc.org/article/PMC/PMC4133581); single imputation anti-conservative (https://europepmc.org/article/PMC/PMC7693525); pseudoreplication 46% (https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.2005282); MIQE 2.0 asks for prediction intervals no mainstream tool produces; only 5 of 27 tools propagate error (https://europepmc.org/article/PMC/PMC5129434).
- **Exists / why fails:** Factor-qPCR (Windows binary, licence unstated); qbase+ IRCs (closed); MCMC.qpcr (GPL-3); nondetects (GPL-3); UCNR (GPL-3 R scripts); ad hoc lme4 scripts (Bilgrau, Hampton). None combine plates, censoring, E propagation and prediction intervals; none permissive or callable.
- **Feature:** input = qPilot per-well table plus per-assay LOD quantity (from NTC/negative-control Cq and MIQE 2.0's ≥5-cycle rule, or via Forootan — https://europepmc.org/article/PMC/PMC5496743). Model y = μ + α_target + β_group×target + u_sample + v_plate + ε; undetermined wells enter the likelihood as Φ((y_LOD − mean)/σ) as in UCNR (https://pmc.ncbi.nlm.nih.gov/articles/PMC5560691/); E variance by delta method. Estimation: ML with scipy.optimize over the marginal likelihood (Gauss–Hermite/Laplace); statsmodels MixedLM for uncensored balanced designs plus a censored EM step; deterministic, versioned. Outputs: contrasts (log FD, CI, p), per-sample quantities with prediction intervals, plate factors with SE (comparable to Factor-qPCR), ICC per level feeding `qpilot plan`. Sweep axes 6–9; refusals (biological n <2, >2 substitution rounds, censor-vs-drop flips). Cards: "Plate correction", "Undetermined wells", "What counts as n". MCP: `qpcr_study(model="lmm_censored")`, `qpcr_robustness(axis="plate_model"|"nondetect_rule")`.
- **Feasibility:** numpy/scipy/statsmodels (BSD-3). Reference results to test against: Ruijter 2015 Fig. 2 run factors (1.186, 0.514, 1.305, 0.652, 2.672, 0.722); Hellemans Table 2; Pipelers' ordering; Hampton's FPRs; Bilgrau's FPR. **3–4 weeks** first validated version; Bayesian PyMC variant (Apache-2.0) adds 1–2 weeks as separate module. Hardest: censored LMM with Laplace over two crossed random effects.
- **Why qPilot:** already has whole-study per-well data, plate identity, grid and record; Cq-input competitors cannot propagate E or build PIs; GPL packages cannot be embedded.
- **Risks/confidence:** over-complex for 1-plate 3-vs-3 — degrade gracefully; surface convergence failures. **Confidence: high on need, medium on effort.**

### D3. The "claim floor": Cq-range-aware minimum credible fold change with replicate-level bootstrap — rank 3 of 8
- **Persona:** every biologist about to write "X was upregulated 1.6-fold (p < 0.05)"; PIs; reviewers.
- **Pain evidence:** "fold-changes of 1.2 to 1.5 are reported as biologically meaningful ... without measurement uncertainty" (https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/); "fold changes less than three- to fivefold are likely to be unreliable" (https://doi.org/10.1111/eci.12801); Bustin 2025 empirical 95% CI widths 2.2–4.0 (Cq <25), 1.4–2.7 (Cq 25–30), 0.71–14.74 around 4.56 above Cq 30; floors **2×/3×/4×** by Cq range; ≥5 replicates above Cq 30; 6 replicates to detect 1.5× at SD 0.5 Cq with 80% power (https://europepmc.org/article/PMC/PMC12387016).
- **Exists / why fails:** Bustin's paper gives rules and a bootstrap, no software; GraphPad gives p-values on anything; qPilot's GRADE-style confidence not tied to a Cq floor.
- **Feature:** per target compute group mean Cq and the floor; bootstrap FC from biological-unit-level quantities 10,000× with E ~ N(E_mean, SE); label "below credible floor" when |log FC| < log(floor) or CI includes 1; equivalence-style statement from the CI (TOST logic; Lakens 2017 not fetched — treated as inference). Card only when the headline would change. Record: floor, CI, seed, replicate counts. `qpilot plan` tie-in. MCP: `qpcr_study` returns `claim_floor` and `ci` per gene; AI layer may not state an FC without them.
- **Feasibility:** 2–4 days; numpy; acceptance test reproduces 11.3/16.0/23.0 at ΔCq 4 and CI bands.
- **Why qPilot:** "no naked numbers" and confidence machinery exist; floor becomes a fact id.
- **Risks/confidence:** thresholds are "context-specific and should be determined empirically for each assay" — present as overridable defaults, never hard refusals. **Confidence: high.**

### D4. Curve-analysis multiverse: baseline, Cq-method and threshold universes from raw curves — rank 4 of 8
- **Persona:** labs mixing instruments; cores asked "why does your Cq differ from ours"; anyone on CFX96/384 or StepOne.
- **Pain evidence:** well-position periodicity; efficiencies 1.79–2.19 and copies 28–86 at Ct 30; SDM/Cy0/5PSM immune (https://europepmc.org/article/PMC/PMC5154181); baseline error → N0 error "an order of magnitude larger" than E error (https://pmc.ncbi.nlm.nih.gov/articles/PMC2665230/); 2013 benchmark "large differences between methods" (https://doi.org/10.1016/j.ymeth.2012.08.011).
- **Exists / why fails:** one method per tool — LinRegPCR, vendor auto-threshold, Cy0 (subscription web, http://www.cy0method.org/), qpcR (GPL), chipPCR (GPL-3). None runs several and reports agreement.
- **Feature:** from rdmlpython baseline-corrected curves implement FDM/SDM (5-point stencil), Cy0 via Richards fit (scipy curve_fit; https://europepmc.org/article/PMC/PMC2533027), 5-parameter sigmoid Cq, per-run vs common threshold; well-position periodicity check (autocorrelation of plateau fluorescence) raising a card recommending scale-insensitive universes. Sweep Cq method × threshold policy; report per-gene sign/CI agreement. MCP: `qpcr_robustness(axis="cq_method")`.
- **Feasibility:** 2–3 weeks incl. validation on `ruijter` CC BY 4.0 dilution sets (https://rmagno.eu/ruijter/) and Brintz CC0 curves (https://github.com/bbrintz/qPCR-amp-call). Hardest: robust Richards/sigmoid fits on noisy/late curves.
- **Why qPilot:** only possible with raw curves; Cq-input competitors (Clarida, AnnealIQ, Auto-qPCR, SATqPCR) structurally cannot.
- **Risks/confidence:** reimplementations must be tested against originals' published outputs; Cy0 reference tool behind login. **Confidence: medium-high.**

### D5. Replicate-structure guard and variance components ("what is your n?") — rank 5 of 8
- **Persona:** students/small labs with 3 wells × 1 cDNA × 2 groups; core managers asked to "do the stats".
- **Pain evidence:** 46% pseudoreplication, 32% unclear (https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.2005282); MIQE 2.0 per-sample statistics; Tichopad: sampling noise dominates for tissue/single cells, RT noise for blood (https://doi.org/10.1373/clinchem.2009.126201); Kitchen: pilot variance components → power (https://doi.org/10.1016/j.ymeth.2010.01.025).
- **Exists / why fails:** powerNest (availability/licence unverified); GraphPad takes any n; `qpilot plan` lacks lab-specific variance components.
- **Feature:** infer hierarchy well ⊂ cDNA ⊂ extraction ⊂ biological unit ⊂ group from RDML annotations; ambiguous → Decision Card ("Are wells A1–A3 one cDNA or three animals?") with consequence (n per group, whether a p-value is allowed). Variance components (ICCs) from D2 written into the record as a per-assay "noise passport"; `plan` allocates replicates to the largest component. Refuse group tests with <2 biological units.
- **Feasibility:** 1 week on top of D2; metadata handling; RDML carries what's needed when filled (hard part: often not).
- **Why qPilot:** cards with impact ranking fit "this choice changes whether you have a p-value".
- **Risks/confidence:** over-prompting on messy layouts. **Confidence: high on need, medium on metadata availability.**

### D6. Methods paper: "A specification-curve (multiverse) framework for qPCR, from raw curves to conclusions" — rank 6 of 8 (deliverable, not feature)
- **Persona:** qPilot team; reviewers/editors wanting a citable justification; method-minded cores.
- **Evidence:** no qPCR multiverse exists; many-analysts variability in neuroimaging (70 teams — https://doi.org/10.1038/s41586-020-2314-9) and ecology (174 teams, ~a third of effects crossing significance either way — https://doi.org/10.1186/s12915-024-02101-x); specification-curve methodology published (https://doi.org/10.1177/1745691616658637 ; https://doi.org/10.1038/s41562-020-0912-z).
- **Exists:** Boba (BSD-3, https://github.com/uwdata/boba); Ruijter 2013 as only benchmark.
- **Deliverable:** (i) specification space with reasonableness tiers (tier 1 MIQE-recommended, tier 2 published alternative, tier 3 common-but-discouraged); (ii) qPCR-tailored joint inference (fraction of universes with CI excluding 1 same sign; median/range; most influential axis), avoiding p-value vote counting; (iii) validation on `ruijter` sets, simulated studies (Ruijter & van den Hoff simulator), re-analysis of public datasets (nondetects' three, UCNR, MCMC.qpcr, Hampton, 2013 biomarker set if terms allow), Brintz amplification-call agreement. Deposit code (Apache-2.0), RDML, REPLICATE.json, hash-chained records.
- **Feasibility:** 6–10 weeks on top of D1–D4; venues BMC Bioinformatics, Bioinformatics, Methods, NAR Methods; bioRxiv. Hardest: obtaining raw curves for published studies (most deposit Cq only — itself a finding).
- **Why qPilot:** the robustness engine is the method; record is the artefact.
- **Risks/confidence:** Ruijter/Vandesompele-school reviewers will scrutinise reimplementations. **Confidence: medium-high publishable; medium on timeline.**

### D7. Reference-gene decisions on efficiency-corrected inputs with NormFinder-from-the-model and an "algorithms disagree" card — rank 7 of 8
- **Persona:** plant, veterinary, microbiology, cancer labs validating reference genes (84% efficiency reporting in reference-gene-titled papers); every new tissue/condition.
- **Evidence:** RefFinder raw-Cq input and rank averaging (https://doi.org/10.1007/s10142-023-01055-7 ; https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0122515 ; https://pmc.ncbi.nlm.nih.gov/articles/PMC6650036/); geNorm co-regulation blind spot (https://europepmc.org/article/PMC/PMC126239); NormFinder inter-group term (https://doi.org/10.1158/0008-5472.CAN-04-0496); 95% don't validate.
- **Exists:** RefFinder (PHP, raw Cq); geNorm in qbase+; NormqPCR (LGPL-3); NormFinder official code forbids redistribution.
- **Feature:** geNorm (existing) + NormFinder reimplementation from Andersen 2004 on E-corrected log quantities; co-regulation screen (flag Gapdh/Tbp-type pairs); NormFinder inter-group variation alongside existing guard; one card when top-k sets disagree; global-mean normalisation universe when ≥~10 targets (https://europepmc.org/article/PMC/PMC2718498).
- **Feasibility:** 1 week; numpy; validate against De Spiegelaere and Sundaram tables.
- **Why qPilot:** per-well E makes E-corrected inputs automatic.
- **Risks/confidence:** NormFinder subtleties (small n; >8 recommended). **Confidence: medium** (overlaps roadmap "NormFinder reimplementation").

### D8. Machine-derived MIQE 2.0 "Data analysis" statement and statistics paragraph from the record — rank 8 of 8
- **Persona:** authors at submission; reviewers; journals embedding the checklist (Clinical Chemistry does).
- **Evidence:** MIQE 2.0 Table 1 Section 5 items (https://doi.org/10.1093/clinchem/hvaf043); audits show these are least reported; Bustin & Wittwer call for MIQE modules "within electronic laboratory notebooks or data repositories" (https://doi.org/10.1093/clinchem/hvaf176).
- **Exists:** Clarida's MIQE score/methods text (Cq-input, closed); self-reported checklists.
- **Feature:** generate Section-5 rows with values and fact ids (raw-data hash, baseline/Cq method + versions, E ± SE, quantity method, replicate counts per level, repeatability/reproducibility from D2 variance components, LOD, dynamic range, reference-gene validation, normalisation formula, model/test, power/MDE); rows that can never be auto-filled marked "author to supply" (standards identity, control identities, specificity, lot details).
- **Feasibility:** 1 week once D1–D5 exist; hard part is honesty about "not derivable".
- **Why qPilot:** record holds versions/hashes/decisions.
- **Risks/confidence:** overlaps roadmap "auto-filled MIQE 2.0 checklist" and another researcher's scope. **Confidence: medium.**

## D. Data / libraries / standards / licences (12 of 33 rows)

| Name | What | Licence (as read 17 Oct 2026) | URL |
|---|---|---|---|
| rdmlpython | RDML reader/writer with LinRegPCR + melt | MIT; PyPI 1.7.2 (2023-05-22) | https://github.com/RDML-consortium/rdmlpython ; https://pypi.org/project/rdmlpython/ |
| rdml-tools | Web apps around rdmlpython | GPL-3.0 (do not vendor) | https://github.com/RDML-consortium/rdml-tools |
| Amsterdam UMC downloads | LinRegPCR, Factor-qPCR, "qPCR data with Methods paper" | Not stated | https://www.medischebiologie.nl/files |
| `ruijter` R package | Ruijter 2013 technical datasets (ds_94_4, ds_380, ds_competimer) | CC BY 4.0 | https://rmagno.eu/ruijter/ |
| qPCR-amp-call (Brintz 2025) | 165,214 TAC curves with expert calls | CC0-1.0 (GitHub); Zenodo says CC BY 4.0 — verify | https://github.com/bbrintz/qPCR-amp-call ; https://zenodo.org/records/13798821 |
| effadj (Bilgrau 2016) | Data + R for E-uncertainty paper | No licence file (article CC BY 4.0; data CC0 per article) | https://github.com/AEBilgrau/effadj |
| UCNR (Pipelers 2017) | Censored-regression simulations/case studies | GPL-3.0 | https://github.com/CenterForStatistics-UGent/UCNR |
| MLM-for-qPCR (Hampton 2025) | R Markdown companion | No licence file | https://github.com/DartCF/MLM-for-qPCR |
| MCMC.qpcr | Bayesian GLMM for qPCR | GPL-3; 1.2.4 (2025-11-08) | https://cran.r-project.org/package=MCMC.qpcr |
| nondetects | EM/MI for non-detects | GPL-3; 2.42.0 | https://www.bioconductor.org/packages/nondetects/ |
| boba | Multiverse DSL + visualiser | BSD-3-Clause | https://github.com/uwdata/boba |
| MIQE 2.0 | Reporting standard, Table 1 | Journal copyright; checklist downloadable | https://doi.org/10.1093/clinchem/hvaf043 ; https://www.multid.se/publications/MIQE-ver2.pdf |

Also noted: PCRedux MIT (https://cran.r-project.org/package=PCRedux), RDML (R) MIT (https://cran.r-project.org/package=RDML), qpcR GPL-2|3, chipPCR GPL-3, pcr archived 2025-11-07, HTqPCR Artistic-2.0, NormqPCR LGPL-3, Python qpcr GPL-3 (https://github.com/NoahHenrikKleinschmidt/qpcr), ISO 20395:2019 paid (https://www.iso.org/standard/67893.html), numpy/scipy/statsmodels BSD-3 and PyMC Apache-2.0 "not re-verified in this session".

**Specifically requested anchors (note 07):**
- Bustin 2025 claim-floor tiers 2×/3×/4× by Cq <25 / 25–30 / >30; CI widths 2.2–4.0, 1.4–2.7, 0.71–14.74; ≥5 replicates above Cq 30; 6 replicates for 1.5× at SD 0.5 Cq: https://europepmc.org/article/PMC/PMC12387016
- Bilgrau 2016 efficiency uncertainty (FPR 0.073 vs 0.053; p 5.35×10⁻⁴ → 0.313; lme4 model): https://pmc.ncbi.nlm.nih.gov/articles/PMC4827196/ ; code https://github.com/AEBilgrau/effadj
- Ruijter 2009 baseline error (ratio 0.7–9.5 under 2% baseline error; 30% baseline error moves Ct ~0.3; N0 error ~an order of magnitude larger than E error): https://pmc.ncbi.nlm.nih.gov/articles/PMC2665230/
- Steibel 2009 mixed model ("more powerful" than comparative CT): https://doi.org/10.1016/j.ygeno.2009.04.008
- Hampton 2025 mixed models (ΔΔCt FPR 14.9/32.9/93.2% at ρ 0/0.5/0.9 when reference shifts 1 SD; ANCOVA 5.0/12.7/75.5%; ΔCt 4–5%; power 72–76% vs 48–53%): https://pmc.ncbi.nlm.nih.gov/articles/PMC11844642/ ; code https://github.com/DartCF/MLM-for-qPCR
- Pipelers 2017 censoring (UCNR; censoring tolerance LOD-substitution 0.69, MNV+1 0.79, KNN 0.34, UCNR 0.90): https://pmc.ncbi.nlm.nih.gov/articles/PMC5560691/ ; https://github.com/CenterForStatistics-UGent/UCNR
- McCall 2014 non-detects (MNAR, P from 2.6×10⁻⁶ to <2×10⁻¹⁶; Cq = 40 substitution → ~−2.5): https://europepmc.org/article/PMC/PMC4133581 ; package https://www.bioconductor.org/packages/nondetects/
- Pseudoreplication 46% (Lazic 2018: 22% genuine, 46% pseudo, 32% unclear; across animal studies, not qPCR-specific): https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.2005282
- Vandesompele geNorm (single-gene error 3.0-fold at 75th pct, 6.4-fold at 90th; V cut-off 0.15; "minimal use of the three most stable"): https://europepmc.org/article/PMC/PMC126239
- Hellemans 2007 qBase (single IRC error ratio 1.68 max 10.98; two IRCs 1.37–1.49; three 1.40 max 5.28; delta-method E error): https://europepmc.org/article/PMC/PMC1852402
- Efficiency reporting audits: 355 articles, 13%→1% (P = 0.004), reference-gene validation 13%→5%, RNA integrity 22%→11% (P = 0.039), MIQE-citing 2024 31%/47%/40%, PMC "PCR efficiency" mentions 3% (2007) → <1% (2025): https://doi.org/10.1093/clinchem/hvaf176 ; 24–30% of 461 Arabian-region papers, median 6/15 MIQE criteria, 2% cite MIQE: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0088266 ; "none of ten papers" / 20-paper repeat: https://doi.org/10.1111/eci.12801
- Patent note: CqMAN (Zhang 2021) web-only, "patents pending": https://pmc.ncbi.nlm.nih.gov/articles/PMC8596907/

## E. Open questions / unverified
- Per-method bias/precision/resolution tables of Ruijter 2013 (paywalled); whether medischebiologie.nl's "qPCR data with Methods paper" includes the Vermeulen biomarker set, and under what terms.
- Whether qbase+ is still sold and its price (domain placeholder; Biogazelle 404); GenEx actual features (vendor page returned navigation only).
- Any peer-reviewed Stan/brms/PyMC use for qPCR; Sherina 2019's implementation.
- Practitioner-forum evidence (blocked) — would strengthen P1, P5, P6.
- Retractions involving qPCR analysis errors — not searchable.
- No formal audit of statistical tests used in qPCR papers found.
- Equivalence testing / effect-size reporting in qPCR — no source.
- GEO/ArrayExpress RT-qPCR series not enumerated.
- Rieu & Powers 2009 and Pfaffl 2001 not fetched.
- Brintz data licence conflict (CC0 vs CC BY 4.0).
- Whether MIQE 2.0's supplemental "Recommendations" contains replicate-number rules beyond the main text.
- Chainy site unreachable; Cy0 behind login; UC Davis QA/QC guidance PDF's original URL not recorded.

## F. Strongest verbatim quotes
1. MIQE 2.0: "statistical tests on Cq values should be avoided because these values are not efficiency-corrected and are not normalized" — https://doi.org/10.1093/clinchem/hvaf043
2. Bustin & Nolan 2017: "fold changes less than three- to fivefold are likely to be unreliable" — https://doi.org/10.1111/eci.12801
3. Bustin & Wittwer 2026: "reviewers seldom assess methodological adequacy, and journals rarely require compliance documentation" — https://doi.org/10.1093/clinchem/hvaf176
4. Bustin 2025 editorial: "fold-changes of 1.2 to 1.5 are reported as biologically meaningful, even at low expression, without measurement uncertainty or technical variance" — https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/
5. Sundaram 2019 on RefFinder rank averaging: "not scientifically sound" — https://pmc.ncbi.nlm.nih.gov/articles/PMC6650036/

---

# NOTE 08 — eDNA, wastewater epidemiology, pathogen/microbial load, GMO: the absolute-quantification and detection corners

Method caveat stated by the note: search budget ran out after 12 searches; forums unreachable; pain evidence comes from systematic literature surveys and agency documents. Five PDFs extracted locally (Klymus 2020, Thalinger 2021, ENGL 2015/2023, EURL validation report, WOAH chapter, EPA 1609.1/1696.1, USFWS 2025 QAPP).

## A. How this corner works

Four communities share one thing: the number that matters is absolute (copies per reaction/litre/gram, or a copy ratio) or binary (detected/not), and it drives a decision outside the lab — close a beach, declare a river invaded, label a lot as GM, report a virus trend (uncited in note). Standard curves, LOD/LOQ, inhibition and contamination controls and multi-lab agreement are first-class, and today live in R scripts, Excel and instrument software.

**eDNA:** the USFWS Whitney Genetics Laboratory processes ~9,000–10,000 eDNA samples/year for invasive carp under a 2025 QAPP (https://www.fws.gov/office/whitney-genetics-laboratory ; https://www.fws.gov/sites/default/files/documents/2025-03/edna_qapp_2025.pdf). The LOD/LOQ standard is Klymus 2020: 7 labs, 36 assays, 20–96 replicates per standard; LOD = lowest concentration with ≥95% positives, LOQ = lowest with CV <35%; discrete LODs 4–250 copies/reaction, modelled 2.19–260; model choice alone moves LOD 1.07–8.72-fold; 8 replicates lowered effective LOD a mean 11.1-fold (https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download). Literature size: 546 single-species assays in 327 papers to April 2019; 30% "incomplete"; none reached the top validation level (https://researchonline.ljmu.ac.uk/id/eprint/14455/). NatureMetrics claims 600+ clients in 126 countries (https://www.naturemetrics.com/).

**WBE:** 32 labs ran 36 SOPs; 80% of recovery-corrected results within ±1.15 log10; recovery and LOD spanned 7 log10 (https://pubs.rsc.org/en/content/articlehtml/2021/ew/d0ew00946f). NWSS public dataset: 211,035 rows, archived 12 Sep 2025 (https://data.cdc.gov/Public-Health-Surveillance/NWSS-Public-SARS-CoV-2-Concentration-in-Wastewater-/g653-rqe2). WastewaterSCAN: ~150 locations, 40 states, >39 million people (https://www.wastewaterscan.org/).

**EPA/EMMI:** Method 1696.1 requires R² ≥0.98, E 0.90–1.10 (https://www.epa.gov/system/files/documents/2022-01/draft_method-1696.1-hf183_01052022_508.pdf); EMMI found only ~a quarter of 100 papers reported Cq method, slope and R² (https://pubs.acs.org/doi/10.1021/acs.est.1c01767).

**GMO:** 228 validated methods in GMOMETHODS (https://gmo-crl.jrc.ec.europa.eu/gmomethods/); ENGL slope −3.1 to −3.6, R² ≥0.98, trueness ±25%, RSDr ≤25% (https://gmo-crl.jrc.ec.europa.eu/doc/MPR%20Report%20Application%2020_10_2015.pdf); compliance at 0.9%/0.1% on C − U with k = 2 (https://gmo-crl.jrc.ec.europa.eu/doc/MU-guidance-document-3rd-edition.pdf). Money: no market-size source found; time: a failed LOD panel costs a plate of 20–96 replicates per standard and a week (**estimate**).

## B. Pain inventory (top 8 of 15)

| # | Pain | Who feels it | Frequency/severity as stated | What exists today | Evidence URL(s) |
|---|---|---|---|---|---|
| P1 | LOD/LOQ not determined/reported or defined differently lab to lab; same raw result = detection in one lab, non-detection in another | Every assay developer; every adopting lab | High: management decisions on invasive/endangered species | USGS R script (provisional, 26 stars, 1 open issue); manual checklist site | https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download ; https://researchonline.ljmu.ac.uk/id/eprint/14455/ ; https://pubs.acs.org/doi/10.1021/acs.est.1c01767 |
| P2 | LOD depends on model chosen (1.07–8.72-fold) and which standards tested; outliers flagged but left to user with no record | Every LOD determination | Medium-high | Script picks by AIC; user reruns after manual outlier removal | https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download ; https://github.com/cmerkes/qPCR_LOD_Calc |
| P4 | "What counts as a detection" undefined (replicates, Cq cut-offs, below-LOD positives, control amplification) | Every eDNA survey; agencies monthly | High: false positives trigger costly action | SOP rules applied by hand in Excel; ROC in R by a few groups | https://www.usgs.gov/centers/upper-midwest-environmental-sciences-center/science/standards-and-validation-resource ; https://link.springer.com/article/10.1007/s12686-017-0817-y ; https://www.frontiersin.org/articles/10.3389/fevo.2020.609973/full |
| P5 | Inhibition untested/unreported; IPC shifts interpreted ad hoc | All environmental matrices | High for negatives and quantities; EMMI: ~40% tested | Rules in spreadsheets and SOPs | https://pubs.acs.org/doi/10.1021/acs.est.1c01767 ; https://www.epa.gov/sites/default/files/2015-08/documents/method_1609-1-enterococcus-iac_2015_3.pdf |
| P6 | Controls absent, lab-only or unreported; field contamination undetected | Majority of published studies | High; 49% of targeted studies lab-only controls; 46/100 ran NTC, 13 reported results | None | https://www.frontiersin.org/articles/10.3389/fevo.2020.609973/full ; https://pubs.acs.org/doi/10.1021/acs.est.1c01767 |
| P8 | Per-plate standard curves drift across months; composite curves need pooling decisions | Weekly, every WBE and beach-monitoring lab | Medium-high (trend artefacts) | EPA Excel workbook (Method C), lab spreadsheets | https://www.mdpi.com/2073-4441/12/3/775 ; https://link.springer.com/article/10.1186/1471-2105-9-120 ; https://pubs.rsc.org/en/content/articlehtml/2021/ew/d0ew00946f |
| P11 | Inter-lab spread: 7 log10 range of recovery and LOD across 36 SOPs | Programme level | High for comparability | QAPPs, proficiency panels | https://pubs.rsc.org/en/content/articlehtml/2021/ew/d0ew00946f |
| P12 | Standards amplify differently from samples (clone vs environmental DNA; circular plasmid; reference organism) → systematic bias | Microbial ecology, WBE, food | High (bias); 5/6 assays; up to 8-fold | None; per-well efficiency only in LinRegPCR-type tools | https://eprints.ncl.ac.uk/191379 ; https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3526484/ ; https://academic.oup.com/clinchem/article/67/6/829/6247760 |

Others: P3 standard-stock degradation (TE + tRNA fix); P7 occupancy modelling rarely done; P9 non-detect/range rules differ; P10 recovery/normalisation arithmetic by hand (100-field submissions); P13 GMO GM% + CF + MU assembled in Excel, one of 12 labs could not fill the template; P14 verification documentation (≥3 labs WOAH, 12 labs EURL); P15 open tooling decays (WES removed from CRAN 2024-08-19; PHES-ODM in maintenance Sept 2026; qPCR_LOD_Calc provisional since 2019; edna-validation.com static since 2021).

## C. Discoveries (note's order = its ranking by impact × feasibility × fit)

### D1. "Assay LOD/LOQ passport": Klymus-2020 curve-fitting from raw plates, with model-choice robustness grid and a recorded, re-runnable definition — rank 1
- **Persona:** eDNA assay developer (USGS/USFWS/Canadian ministry, university, consultancy) validating or re-verifying an assay; also wastewater/food-micro labs. Once per assay per lab, repeated at reagent/instrument changes; for Whitney this sits in front of ~10,000 samples/year.
- **Pain evidence:** "rarely report" LOD/LOQ; model choice moves LOD up to 8.72-fold; outliers flagged but handled manually (https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download); 30% of assays Level 1 and LOD is the Level 4 gate (https://researchonline.ljmu.ac.uk/id/eprint/14455/); provisional 5-input R script with an open issue since Jan 2025 (https://github.com/cmerkes/qPCR_LOD_Calc/issues). Cost (**estimate**): a failed LOD panel costs a plate of 20–96 replicates per standard and a week.
- **Exists / why fails:** qPCR_LOD_Calc: Cq-only, no raw curves, no record of outlier or precision-threshold choices, single model by AIC, `drc` dependency (GPL on CRAN; verify), provisional. edna-validation.com: manual, no computation, all rights reserved. Vendor software: standard curves only.
- **Feature:** input RDML of LOD plates with standards annotated by nominal copies; negatives from the engine's own amplification call. Method per Klymus 2020 and Forootan 2017 (https://pmc.ncbi.nlm.nih.gov/articles/PMC5496743/): (a) binary detection per standard; (b) fit the log-dose sigmoid family (Weibull II, asymptotic regression, log-logistic, Michaelis–Menten, Weibull I, 2–4 parameters) by ML, select by AIC/lack-of-fit, LOD at p = 0.95 with bootstrap CI, effective LOD for n = 1…12 via p = 1 − 0.05^(1/n); (c) LOQ from CV-vs-concentration model with CV from E and SD(Cq), threshold default 35% but exposed; LOQ ≥ LOD enforced; (d) discrete-threshold values alongside; (e) outlier candidates (Cq outside 90–110% of median) as a Decision Card with LOD/LOQ under both choices; (f) standard-stock drift check against previous passports. Robustness: all solvable models × outlier in/out × CV 25/30/35% → LOD spread. Record: Klymus reporting minimum + GBIF `pcr_primer_lod`/`pcr_primer_loq` (https://rs.gbif.org/extension/gbif/1.0/dna_derived_data_2022-02-23.xml). MCP: `qpcr_lod(assay, plates)`.
- **Feasibility:** USGS public-domain release 10.5066/P9AKHU1R with raw multi-lab Cq for 36 assays and script outputs for regression tests (https://data.usgs.gov/datacatalog/data/USGS:5d36fbfce4b01d82ce8a6cbf); paper's Table 1 gives expected values per assay. scipy/statsmodels (BSD). **2–3 weeks.** Hardest: matching `drc` model-selection closely enough to pass regression on Comparison-Data.csv; defining "positive" from raw curves consistently with instrument calls (report both).
- **Why qPilot:** raw curves let the engine make the call and catch late, low-plateau curves; robustness turns model choice into a reported spread; cards log outlier/threshold choices; record = assay passport ("lab memory" roadmap).
- **Risks/confidence:** `drc` fits may be hard to reproduce bit-for-bit; eDNA labs' Bio-Rad CFX/ABI exports need vendor capture; small per-lab user base (validation once per assay). **Confidence: high on pain and method; medium-high on adoption.**

### D2. Detection-call and control-negation engine for eDNA surveys, with occupancy-ready export — rank 2
- **Persona:** eDNA processing lead / QA specialist calling hundreds of samples per week against a QAPP; the resource manager receiving calls. USFWS: ~10,000 samples/year with field blanks, hood controls, extraction negatives, 8 PCR replicates per sample.
- **Pain evidence:** definition of a positive must be negotiated with managers (https://www.usgs.gov/centers/upper-midwest-environmental-sciences-center/science/standards-and-validation-resource); threshold rationales "rarely reported" (https://link.springer.com/article/10.1007/s12686-017-0817-y); only ~6% of targeted studies/year report NTC amplification (https://www.frontiersin.org/articles/10.3389/fevo.2020.609973/full); negation rules are prose in a 61-page QAPP ("samples 12–32 will be negated"). Cost (**estimate**): a mis-negated range can mean re-sampling a river reach.
- **Exists / why fails:** SOP prose + Excel; ROC by a few groups; occupancy packages expect a hand-built matrix; nothing connects plate, controls, rule and record.
- **Feature:** input RDML with well roles + versioned YAML "rule pack" encoding the QAPP: positive-call rule (k of n; Cq ≤40; optional ROC Cq threshold per Serrao); control rules (field-blank range negation; hood-control batch negation; extraction-negative batch negation; positive-control minimums 1/8 and 1/2 per USFWS — https://www.fws.gov/sites/default/files/documents/2025-03/edna_qapp_2025.pdf); inhibition from IPC shift (EPA 3 Ct SPC / 1.5 Ct IAC or Pecson 1.0); multi-assay confirmation and resample logic. Outputs: per-sample call (positive/negative/negated/inhibited/below-LOD positive), per-site summary with effective LOD, Thalinger interpretation sentence. Cards for every negation and below-LOD positive; autonomy "human decides" for negations. Export: eDNAoccupancy/msocc matrices and Darwin Core archive with DNA-derived extension (https://docs.gbif.org/publishing-dna-derived-data/en/). MCP: `qpcr_call(study, rule_pack)`.
- **Feasibility:** QAPP is public and precise; GBIF XML public. Validation data scarce: Klymus release has standards only; a March 2026 Zenodo oyster assay record has environmental Cq (https://zenodo.org/records/18833966); likely need a partner lab's plates. Occupancy inside qPilot optional later (PyMC/NumPyro Apache-2.0). **3–4 weeks.** Hardest: well-role capture from vendor layouts.
- **Why qPilot:** decision space is explicit and conclusion-flipping; robustness answers "how many reasonable call rules agree"; hash-chained record is the audit trail when a detection is challenged; roles/rules/cards carry to wastewater and food QC.
- **Risks/confidence:** agencies may not run third-party software without a validation exercise; rule packs must never silently change a call. **Confidence: medium-high on pain; medium on agency adoption, higher for consultancies/universities.**

### D3. Composite (master) standard curve and absolute-quantification engine with published acceptance criteria and standard-matrix checks — rank 3
- **Persona:** WBE labs (weekly for months), EPA recreational-water labs (1609.1/1696.1/Draft C), microbial-ecology 16S labs, veterinary/plant-pathogen labs. Every plate; composite rebuilt at each new lot/run.
- **Pain evidence:** per-plate curves required (https://pubs.rsc.org/en/content/articlehtml/2021/ew/d0ew00946f); Bayesian master curves abandoned for an Excel WLR workbook (21 labs, 91 curves; https://www.mdpi.com/2073-4441/12/3/775); EPA 1696.1 Table 2 criteria exist only in a PDF and spreadsheet; EMMI: a quarter report slopes/R²; 7 log10 inter-lab spread; standards amplify unlike samples in 5/6 16S assays (https://eprints.ncl.ac.uk/191379); dilution error 4–9% biases standard-curve E (https://academic.oup.com/clinchem/article/67/6/829/6247760); WES removed from CRAN (https://cran.r-project.org/web/packages/WES/index.html).
- **Exists / why fails:** vendor software: one curve per plate, no pooling/windows; EPA workbook (Method C only); WinBUGS code 2008; nothing from raw curves with per-well E.
- **Feature:** (a) per-run WLR (weights ∝ 1/variance) and composite curve after ANCOVA homogeneity test (Lane 2020), optional hierarchical model (REML in statsmodels or PyMC/NumPyro) reproducing Sivaganesan (https://link.springer.com/article/10.1186/1471-2105-9-120); (b) switchable "method cards": EPA 1696.1 (R² ≥0.98, E 0.90–1.10, LLOQ = 95% prediction upper limit at lowest standard, NTC/MB undetermined, IAC SD ≤1.16 Cq, SPC SD ≤0.62 Cq — https://www.epa.gov/system/files/documents/2022-01/draft_method-1696.1-hf183_01052022_508.pdf); Draft Method C (intercept 36.66–39.25, slope −3.23 to −3.74, ANCOVA); ENGL (slope −3.1 to −3.6, R² ≥0.98, ≥5 runs, trueness ±25%, RSDr ≤25%); (c) per-well E from curves compared standards vs unknowns as a matrix-mismatch test, with one-point calibration shown as alternative; (d) unit chain copies/reaction → copies/volume with CDC/NWSS conversion, recovery correction, normalisation markers (https://archive.cdc.gov/www_cdc_gov/nwss/reporting.html); (e) non-detect policies as explicit choices. Robustness grid → distribution of each sample's copies/L and trend slope. Cards: drop a standard point; accept a failing run; declare lot drift; dilute an inhibited sample. MCP: `qpcr_quantify(study, method_card)`.
- **Feasibility:** EPA Method C multi-lab Ct data (https://catalog.data.gov/dataset/epadata_mls_paper2) and Lane 2020 data (https://catalog.data.gov/dataset/epa-data-for-lane-et-al-2020-water) under "EPA Science Hub licence" (terms to check); USGS standards; NIST RGTM 10169 no longer distributed (https://www.nist.gov/programs-projects/sars-cov-2-research-grade-test-material). statsmodels/scipy; optional PyMC/NumPyro. **3–5 weeks** incl. three method cards. Hardest: validating against Lane's published intercept/slope comparisons; unit metadata without a LIMS.
- **Why qPilot:** only candidate already computing per-well E from raw curves; multi-plate is native; robustness answers the regulator's "would the trend change under another calibration"; record meets EPA/ENGL "document the verification" (research use).
- **Risks/confidence:** WBE moving to dPCR; NWSS dataset archived 2025; composite curves can hide run failures if windows are loose. **Confidence: high on method and data; medium on which segment adopts first.**

### D4. NWSS/PHES-ODM-ready wastewater run packet — rank 4
- **Persona:** state/academic WBE lab submitting weekly to a health department, DCIPHER, or PHES-ODM instance; programme epidemiologist.
- **Pain evidence:** ~100-field NWSS dictionary v5.2.3 incl. quantification method, recovery, inhibition, LOD, normalisation marker; CDC trend method (half-LOD substitution, log10 regression on ≥3 points, optional WLS) (https://archive.cdc.gov/www_cdc_gov/nwss/reporting.html); PHES-ODM in 23 countries but QA/QC "being developed" and in maintenance mode (https://github.com/Big-Life-Lab/PHES-ODM); WES archived; 36 SOPs/7 log10 spread.
- **Exists:** DCIPHER CSV templates; PHES-ODM Excel/SQL (licence inconsistent); commercial pipelines closed; wwinference downstream (https://github.com/CDCgov/ww-inference-model).
- **Feature:** on D3, a "run packet" exporter mapping engine facts to NWSS fields and PHES-ODM `measures` long format; computes flow-population and marker normalisation and CDC trend classification with non-detect policy and regression weights as recorded choices. Cards: inhibition dilution, recovery exclusion (<0.01%), marker-vs-flow normalisation. MCP: agent assembles weekly packet and lists open cards.
- **Feasibility:** field lists public; no raw-curve public WBE dataset (gap) → partner lab. **2–3 weeks** on top of D3. Hardest: dictionary versions and dPCR share of inputs.
- **Why qPilot:** decision log holds provenance fields; agents can run the weekly packet; local-first suits health-department IT.
- **Risks/confidence:** funding/platform shifts; CDC templates may change; many labs dPCR-only. **Confidence: medium.**

### D5. GM% module to ENGL/ISO 21570 rules with conversion factors, expanded uncertainty and the compliance decision — rank 5
- **Persona:** GMO method developers, NRL/EURL researchers, food-science labs comparing qPCR and dPCR, students; routine official control out of scope.
- **Pain evidence:** collaborative-trial raw data on an EURL-designed Excel sheet; one of 12 labs could not fill it; results "over not rounded data" create inconsistencies (https://gmo-crl.jrc.ec.europa.eu/summaries/EURL-VL-01-22-VR.pdf); cp/cp → m/m needs per-CRM factors with uncertainty (https://gmo-crl.jrc.ec.europa.eu/doc/Application%20note%20v1.0%20-%20conversion%20factor.pdf); MU top-down and decision on C − U (https://gmo-crl.jrc.ec.europa.eu/doc/MU-guidance-document-3rd-edition.pdf).
- **Exists:** instrument software; Excel; GMOMETHODS lookup; no open tool.
- **Feature:** two standard curves → copies → GM% = event/taxon × 100; ENGL acceptance method card; dPCR inhibition test (within 25%); CF conversion with u_comb = √(u_m² + u_CF²); U = k·u_c with k = 2; compliance vs 0.9%/0.1% on C − U (https://eur-lex.europa.eu/eli/reg/2011/619/oj); ISO 5725-2 Cochran/Grubbs outlier screening as cards. Record: WG-MV verification structure (https://gmo-crl.jrc.ec.europa.eu/doc/WG-MV-Report-version-2.pdf). MCP: `qpcr_gm_percent(study, event, crm)`.
- **Feasibility:** all formulas in CC BY 4.0 JRC documents; CF table published (https://gmo-crl.jrc.ec.europa.eu/doc/CF-CRM-values.pdf); no downloadable raw Cq (gap); CRMs cost money; ISO texts paid. **2 weeks.** Hardest: test data.
- **Why qPilot:** dual-curve ratio with uncertainty is a small extension of D3.
- **Risks/confidence:** small research user base; official labs won't switch; EU-specific. **Confidence: medium on usefulness, high on feasibility.**

### D6. FAIR export and assay-transfer verification: Thalinger checklist items, GBIF Darwin Core archive, "same assay, new lab" card — rank 6
- **Persona:** assay developer publishing; adopting lab; data manager publishing to GBIF/OBIS.
- **Pain evidence:** 20–76% of 122 validation variables reported; details "often spread across different sections … or ambiguously displayed" (https://researchonline.ljmu.ac.uk/id/eprint/14455/); LOD must be re-quantified on transfer; ENGL verification designs; WOAH ≥3 labs/≥20 samples (https://www.woah.org/fileadmin/Home/eng/Health_standards/tahm/1.01.06_VALIDATION.pdf).
- **Exists:** edna-validation.com manual entry; GBIF IPT manual mapping; Excel.
- **Feature:** emit machine-checkable subset of Thalinger's checklist and Klymus's three reporting items; list "human must attest" items; Darwin Core archive with DNA-derived extension; transfer-verification card comparing new-lab LOD/efficiency/intercept with the published passport (D1).
- **Feasibility:** Thalinger checklist/data on Figshare 10.6084/m9.figshare.12184860.v1; GBIF XML public; **1–2 weeks** after D1. Hardest: deciding which of 122 variables are machine-checkable from RDML.
- **Why qPilot:** record has the facts; "no naked numbers" binds each entry.
- **Risks/confidence:** checklists alone "not a discovery" per brief; value is the specific mapping and transfer card. **Confidence: medium.**

**Domains to serve first (note's own ranking):** (1) targeted eDNA (D1, D2, D6) — highest; (2) environmental-microbiology absolute quantification (D3, later D4); (3) GMO (D5), after D3.

## D. Data / libraries / standards / licences (12 of ~45 rows)

| Name | What | Licence | URL |
|---|---|---|---|
| USGS LOD/LOQ data release 10.5066/P9AKHU1R | Raw multi-lab Cq for standards (36 assays, 7 labs) + calculator outputs (`GEDWG_LOD_DATA3.csv`, `Comparison-Data.csv`) | Public domain (US Gov) | https://data.usgs.gov/datacatalog/data/USGS:5d36fbfce4b01d82ce8a6cbf |
| cmerkes/qPCR_LOD_Calc | R script, LOD/LOQ curve fitting (DOI 10.5066/P9GT00GB) | USGS public domain; "provisional" | https://github.com/cmerkes/qPCR_LOD_Calc |
| Klymus et al. 2020 | Method definition | CC BY 4.0 | https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download |
| Thalinger et al. 2021 + Figshare | Validation scale, 122-variable checklist, 546-assay database | CC BY-NC (paper) | https://researchonline.ljmu.ac.uk/id/eprint/14455/ |
| eDNAoccupancy | R multiscale occupancy | USGS public domain | https://github.com/RobertDorazio/eDNAoccupancy |
| GBIF DNA-derived data extension | Darwin Core terms incl. qPCR fields | Guide CC BY-SA 4.0 | https://rs.gbif.org/extension/gbif/1.0/dna_derived_data_2022-02-23.xml ; https://docs.gbif.org/publishing-dna-derived-data/en/ |
| USFWS 2025 QAPP + SOPs | Control/negation rules, standard-curve minima | US Gov public document | https://www.fws.gov/sites/default/files/documents/2025-03/edna_qapp_2025.pdf |
| CDC NWSS reporting + data dictionary v5.2.3 | Submission fields, trend method | US Gov | https://archive.cdc.gov/www_cdc_gov/nwss/reporting.html |
| EPA Method 1696.1 | HF183 qPCR, Table 2 acceptance criteria | US Gov | https://www.epa.gov/system/files/documents/2022-01/draft_method-1696.1-hf183_01052022_508.pdf |
| EPA Method C multi-lab Ct data (Aw 2019) | Ct of reference materials and blinded samples | EPA Science Hub licence (check terms) | https://catalog.data.gov/dataset/epadata_mls_paper2 |
| ENGL MPR 2015 | Acceptance criteria, qPCR | CC BY 4.0 (JRC) | https://gmo-crl.jrc.ec.europa.eu/doc/MPR%20Report%20Application%2020_10_2015.pdf |
| EURL VL-01/22 validation report | Worked GM% validation, 12 labs | CC BY 4.0 | https://gmo-crl.jrc.ec.europa.eu/summaries/EURL-VL-01-22-VR.pdf |

Licence cautions stated by the note: `drc` (R) and `occumb` are GPL (reimplement, do not vendor); `msocc` has no licence; EPA Science Hub terms not retrievable; WastewaterSCAN data CC BY-NC; PHES-ODM licence internally inconsistent (CC BY 4.0 README vs CC-BY-SA-4.0 sidebar); WES CC BY 4.0 per r-universe but archived; ISO 20395/21570/16140-2 paid; CSA W214:21 paid.

**Specifically requested anchors (note 08):**
- Klymus 2020 LOD/LOQ method: LOD = lowest standard with ≥95% positive replicates; LOQ = lowest with CV <35% of back-calculated copies (CV from E and SD(Cq) via Forootan); discrete-threshold and curve-fitting (15 `drc` log-dose sigmoids; best by log-likelihood/AIC/lack-of-fit/residual variance; LOQ via exponential-decay/linear/polynomial CV models); effective LOD p = 1 − 0.05^(1/n); results discrete LOD 4–250, modelled 2.19–260, discrete LOQ 10–1,920, modelled 6–839; model sensitivity 1.07–8.72-fold; Weibull II and 3-parameter asymptotic regression solved 35/36; outliers flagged at <90%/>110% of median Cq but not removed — https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download ; USGS record https://pubs.usgs.gov/publication/70205435
- USGS public-domain dataset 10.5066/P9AKHU1R (published 2019-07-23, metadata updated 2022-04-28) — https://data.usgs.gov/datacatalog/data/USGS:5d36fbfce4b01d82ce8a6cbf
- eDNA literature size: 546 single-species assays in 327 papers to April 2019; ~60% qPCR, ~35% endpoint PCR; 227 fish, 74 amphibians; >40% COI, ~23% cytb; >80% of assays in only one paper — https://researchonline.ljmu.ac.uk/id/eprint/14455/

## E. Open questions / unverified
- Forum-level pain evidence not collected (budget); a follow-up should search complaints about qPCR_LOD_Calc, IPC interpretation and NWSS submissions.
- Lesperance 2021 and Langlois 2021 (the eDNA "MIQE") blocked by Wiley; Goldberg 2016, Hunter 2017, Burian 2021 unread; no "MIQE 2.0 for eDNA" found.
- UK great crested newt scheme specifics (12 replicates, positive rule, proficiency operator) not readable.
- Inter-lab ring trials beyond Klymus not located.
- No reliable market-size source for eDNA or wastewater testing.
- Pecson 2021 per-method-group LODs beyond abstract (page truncated).
- Ahmed 2022, Kantor 2021 blocked; Dutch standard-curve-drift preprint not readable (claim omitted).
- WastewaterSCAN/Verily platform (dPCR vs qPCR) not verified.
- NWSS lab/site counts not stated; reason for 2025 archive not verified.
- ISO 16140-2 statistics and allergen PCR (EN 15634) not read.
- drc, MDPI, mare, EPA Science Hub licences to be checked.
- Whether eDNA labs can export raw amplification data at scale (Whitney instruments/formats unidentified) — determines whether D1–D2 start from raw curves or Cq tables.

## F. Strongest verbatim quotes
1. Klymus 2020: "eDNA studies rarely report these parameters and the methods used to measure them" — https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download
2. USGS toolbox: "You must test for PCR inhibition … an internal positive control (IPC) must be added" — https://www.usgs.gov/centers/upper-midwest-environmental-sciences-center/science/standards-and-validation-resource
3. Serrao 2018: "threshold rationales are rarely reported in eDNA studies" — https://link.springer.com/article/10.1007/s12686-017-0817-y
4. Pecson 2021: "the same SOP or laboratory should be selected to track SARS-CoV-2 trends at a given facility" — https://pubs.rsc.org/en/content/articlehtml/2021/ew/d0ew00946f
5. Lane 2020 on dropping the Bayesian master curve: it "requires specialized statistical software and expertise" — https://www.mdpi.com/2073-4441/12/3/775

---

# NOTE 09 — Genetics and therapy applications of qPCR beyond mRNA expression

Method caveat stated by the note: WebSearch budget exhausted before the first query; built entirely from direct fetches; no forum evidence; some papers abstract-only (marked); community-size numbers exist for CGT, telomere, MRD but not SNP/ChIP/mtDNA-CN.

## A. How this corner works

Telomere qPCR (T/S ratio) is a very large epidemiological community — the 2002 founding paper had 839 PubMed citations by 2018 (https://trn.tulane.edu/wp-content/uploads/sites/72/2020/08/1-s2.0-S0306453018307789-main.pdf) — running thousands of samples in triplicate on 384-well plates. A critical appraisal screened 5,427 records to 25 method-comparison studies: 51% reporting completeness, only 2 of 25 used ICC (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0245582). Inter-lab CV is 20.70% for qPCR vs ~9.20% for Southern/STELA (https://academic.oup.com/ije/article/44/5/1673/2594545); ICC 0.81 vs 0.93, so a 1,000-person qPCR study has less longitudinal power than 250 by Southern (https://academic.oup.com/aje/article/190/7/1406/6132159). Extraction method shifted T/S ~40% and flipped a CVD association (OR 1.22, p = 0.0005 vs OR 1.07, p = 0.469) (https://europepmc.org/article/PMC/PMC4853716). The NIH-funded Telomere Research Network (NIA/NIEHS, 2019, one U24 + four U01) sets norms; its only public pipeline, NCI's `cgrtelomeres`, "emulates" manual steps (https://github.com/NCI-CGR/cgrtelomeres).

miRNA: normaliser choice changed "up" miRNAs from 43 to 74 in one plasma study (https://europepmc.org/article/PMC/PMC6367481); hemolysis raises individual miRNAs up to 13-fold (https://europepmc.org/article/PMC/PMC3663194).

Gene/cell therapy is the growth engine: 2,217 gene therapies in development (4,487 all therapies; 59 Phase III; 46 approved) (https://www.asgct.org/uploads/files/general/Final-ASGCT-Citeline-Q2-2026.pdf); FDA expects a biodistribution LOQ <50 copies/µg gDNA at 95% confidence with triplicates and a spiked replicate (https://www.fda.gov/media/113768/download); ITR qPCR titres up to 8-fold high (https://europepmc.org/article/PMC/PMC4813604); qPCR 64× above ddPCR in crude AAV samples (https://europepmc.org/article/PMC/PMC6650692). EuroMRD (69 labs, 26 countries) publishes fully numeric replicate-level rules (https://euromrd.org/). mtDNA-CN by qPCR stays common at under $2/sample (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0228166). Time/cost for ICC re-runs: ~200 samples × triplicate × 2 targets on a 2,000-sample cohort (**estimate**).

## B. Pain inventory (top 8 of 15)

| # | Pain | Who feels it | Frequency/severity as stated (estimate unless cited) | What exists today | Evidence URL(s) |
|---|---|---|---|---|---|
| P1 | T/S ratios not comparable across labs; inter-lab CV 20.7% qPCR vs 9.2% gel | Telomere labs, cohort PIs | Every multi-site/meta-analysis; High | Z-scoring by hand; no tool | https://academic.oup.com/ije/article/44/5/1673/2594545 ; https://europepmc.org/article/PMC/PMC6973063 |
| P2 | Only 8% of telomere method papers report ICC; 51% completeness; CV misused | Authors, reviewers, TRN | Every publication; High | TRN R script (lme4/rptR) run manually | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0245582 ; https://trn.tulane.edu/wp-content/uploads/sites/72/2020/10/How-to-calculate-repeatability.pdf |
| P3 | Plate, well-position and extraction effects change associations (40% T/S shift; CVD association lost) | Cohort analysts | Every study mixing batches/kits; High | Ad hoc mixed models; method-specific calibrator by hand | https://europepmc.org/article/PMC/PMC4853716 ; https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0184098 ; https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0164046 |
| P5 | miRNA normaliser choice changes which miRNAs are significant (43 vs 74 up) | Biomarker researchers | Every panel study; High | GeneGlobe, ExpressionSuite 2019, HTqPCR | https://europepmc.org/article/PMC/PMC6367481 ; https://europepmc.org/article/PMC/PMC2718498 |
| P6 | Hemolysis inflates plasma miRNAs up to 13-fold; spike-ins don't correct | Liquid-biopsy labs | Every plasma/serum cohort; High | Qiagen ΔCq >7 rule applied manually | https://europepmc.org/article/PMC/PMC3663194 |
| P7 | Biodistribution/VCN runs must meet numeric acceptance rules and be reported per animal | CGT bioanalysis groups, CROs, vector cores | Every plate of every study; High (regulatory) | Instrument software + Excel + SOPs | https://www.fda.gov/media/113768/download ; https://europepmc.org/article/PMC/PMC7786041 |
| P8 | Standard topology/choice shifts AAV titres up to 8× and VCN calibrator type changes copy numbers | Vector cores, CMC analysts | Every titration; High | Lab SOPs; no cross-standard view | https://europepmc.org/article/PMC/PMC4813604 ; https://europepmc.org/article/PMC/PMC6650692 ; https://europepmc.org/article/PMC/PMC5628571 |
| P14 | Rare-target positivity below quantitative range is a grey zone needing replicate-level rules | Research MRD/ctDNA labs | Every follow-up sample; High | Rules by hand under EuroMRD QA | https://euromrd-public.s3.nl-ams.scw.cloud/Guidelines_for_RQ-PCR_MRD_data_interpretation-Leukemia2007_%2021_604-611.pdf ; https://europepmc.org/article/PMC/PMC11147754 |

Others: P4 per-plate mean efficiency substituted for per-well; informal outlier rules; P9 VCN per transduced cell needs flow data + risk-justified limit; P10 CNV/genotype calls rounded by closed Windows tools; P11 ChIP-qPCR fold enrichment despite advice; P12 mtDNA-CN weak associations; P13 single-cell tooling GPL/abandoned (Low-Medium); P15 CRISPR qPCR imprecise <15%/>85% (Low-Medium).

## C. Discoveries (note's order = its ranking by impact × feasibility × fit)

### D1. "Telomere Study Mode": cohort-scale T/S with repeatability, plate models and the TRN checklist — rank 1
- **Persona:** technician/postdoc in a population-health or ageing lab (e.g. TRN member) measuring T/S on 500–5,000 samples, triplicates on 384-well plates, 1–3 QC DNAs and a standard curve per plate, re-running a subset for repeatability; weekly to monthly.
- **Pain evidence:** 51% completeness, 2/25 ICC (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0245582); inter-lab CV 20.7%; ICC 0.81 vs 0.93 and 1,000-vs-250 power; extraction 40% shift deleting a CVD association; TRN Recommendations 1–2 (https://trn.tulane.edu/wp-content/uploads/sites/72/2021/12/Recommendation-1-FINAL.pdf ; https://trn.tulane.edu/wp-content/uploads/sites/72/2021/12/Recommendation-2-FINAL.pdf); TRN ICC script requires long-format reshaping and lme4/rptR; NCI pipeline "Plots and testing not implemented". Cost **estimate**: ICC re-run of 10% of a 2,000-sample cohort ≈ 200 samples × triplicate × 2 targets (inference from 8% ICC reporting rate).
- **Exists / why fails:** vendor Cq; LinRegPCR per-well E averaged per plate; Excel T/S; R ICC scripts; cgrtelomeres (MIT). Nothing computes ICC from the record, models plate/well/extraction as TRN asks, or shows which choices change ranking.
- **Feature:** input RDML for all plates + sample sheet (sample id, individual, extraction method/lot, plate, well, run, role; MMqPCR acquisition steps as two targets). Methods: per-well E via rdmlpython with per-plate mean as robustness alternative; T/S by (a) standard-curve interpolation (https://academic.oup.com/nar/article-lookup/doi/10.1093/nar/gkn1027), (b) efficiency-corrected ratio (https://europepmc.org/article/PMC/PMC1852402), (c) ΔΔCq; replicate rules (Cq SD <1 per aTL — https://europepmc.org/article/PMC/PMC3047434; CV >5% single-outlier deletion); plate QC via QC DNAs; well-position/plate effects in an LMM per TRN how-to; method-specific calibrator (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0164046) or protocol-as-fixed-effect with Z-scoring; ICC (one-way, batch-adjusted); Z-scored T/S (https://europepmc.org/article/PMC/PMC6973063). Cards: "Replicate C of sample 1143 is 0.9 Cq off… 14 samples cross the tertile boundary"; "Plate 7 QC 12% high"; "Two extraction kits detected; calibrate (23 bridging samples) or Z-score within kit?"; "Per-well vs per-plate efficiency changes 31 T/S by >5%". Record: ICC with CI, plate/well model, outlier log, % repeated/excluded, auto-filled TRN checklist (https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0245582.s001&type=supplementary). MCP: `qpcr_study` with `telomere` method card.
- **Feasibility:** Nettle 2019 dataset1/2.csv + simulation code CC BY 4.0 (https://zenodo.org/record/1994386); Dagnall 2017 S1–S4 PLOS CC BY; Seeker 2016 (no licence; ask — https://github.com/LASeeker/DNAextractionTelomeres); TRN example.xls. ICC via statsmodels (BSD), no GPL. **2–3 weeks** + 1 week MMqPCR mapping. Hardest: two-temperature acquisition in RDML across instruments; validating ICC/LMM against the TRN script.
- **Why qPilot:** per-well E the field knows it should use and doesn't; robustness answers "would my cohort ranking change"; record carries ICC and QC percentages; MCP for unattended cohort pipelines.
- **Risks/confidence:** labs attached to Excel/in-house R; TRN may publish its own tooling; aTL/MMqPCR variants multiply formats. **Confidence: high pain is real and unserved; medium on adoption speed.**

### D2. "Run-acceptance rule packs" for standard-curve absolute quantification in gene/cell therapy research (biodistribution, VCN, AAV titre) — rank 2
- **Persona:** bioanalytical scientist in an academic vector core, biotech process-development group or CRO method-development team; 384-well plates against an 8–9-point curve with QC sets, NTCs, spiked replicates; several plates/study, weekly; results into a study report or CoA.
- **Pain evidence:** FDA LOQ/triplicate/spike/BLOQ expectations (https://www.fda.gov/media/113768/download); industry points-to-consider with dozens of numeric criteria and "repeat run, escalate on second failure" (https://europepmc.org/article/PMC/PMC7786041); EMA units (https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-quality-non-clinical-and-clinical-aspects-gene-therapy-medicinal-products_en.pdf); ICH S12 spike-and-recovery and non-GLP sample analysis (https://database.ich.org/sites/default/files/ICH_S12_Step4_Guideline_2023_0314.pdf); FDA VCN per CAR-positive cell (https://www.fda.gov/media/156896/download); AAV titre bias up to 8×; 64× qPCR-vs-ddPCR; 2,217 gene therapies. Cost **estimate**: a failed plate costs a day plus reagents; an undetected inhibited well changes a tissue's positivity call.
- **Exists / why fails:** QuantStudio DA2 "Standard curve" module, CFX Maestro compute quantities; acceptance checks, spike recovery, BLOQ policy, per-animal tables in Excel under SOPs; no open tool encodes the rules.
- **Feature:** input RDML/vendor export + study sheet (animal/lot, tissue, DNA ng, replicate role incl. spike copies, standard copies, QC nominal). Versioned "method card": curve acceptance (≥6–7 passing non-zero standards, E 90–110%, R² ≥0.980), QC (%CV ≤25%, %RE ±25%, ±45% at lowest), spike recovery <55% = inhibition with 1/4–1/10 re-run, LOD/LLOQ logic, BLOD/BLOQ labelling, copies/µg gDNA or per diploid cell (×2 albumin convention — https://europepmc.org/article/PMC/PMC3130191), per-animal/tissue tables. Robustness: end standards dropped vs kept; Cq cut-off 38/40; BLOQ as 0 vs LOQ/2 vs censored; per-plate vs pooled curve; plasmid vs gDNA calibrator (https://europepmc.org/article/PMC/PMC5628571). Cards: "Standard 25 copies failed in one replicate…"; "Spike recovery 48% in liver #3"; "Kidney positivity flips if BLOQ = LOQ/2". Record: rule-pack version, every pass/fail, escalations, `validation summary` export. MCP: `qpcr_study` with `rulepack=fda_ltfu_2020`.
- **Feasibility:** rules public; no raw-curve public dataset (gap) → synthetic plates + RDML benchmark standard-curve plates; ATCC VR-1616/VR-1816 purchasable for demo. **2 weeks** engine + 1 week per extra rule pack. Hardest: declarative, auditable, versioned rule packs; avoiding any GLP/Part 11 claim.
- **Why qPilot:** multi-plate study with hash-chained record is the bioanalyst's audit trail even outside GLP; same machinery serves ELISA later; BLOQ policy becomes a tested sensitivity.
- **Risks/confidence:** regulated users will ask for Part 11; CROs have LIMS; ddPCR displacing qPCR for VCN/titre. Position as method-development/academic-core tool and "second opinion" next to ddPCR. **Confidence: medium-high.**

### D3. Full-curve allelic discrimination with cluster-confidence cards (TaqMan, rhAmp, KASP endpoint) — rank 3
- **Persona:** genetics core or breeding lab calling SNPs on 96/384 plates or OpenArray, dozens of plates/week, technician overriding edge calls.
- **Pain evidence:** operator-threshold endpoint analysis wrong in 12 of 84 sequenced calls vs 0 for full-curve BCGA (https://academic.oup.com/nar/article-lookup/doi/10.1093/nar/gkl185); vendor tools call by NTC angle/distance, user-drawn boundaries, or proprietary rules with "inconclusive"/"unconfirmed" points (https://www.biosearchtech.com/support/tools/genotyping-software/klustercaller); overrides recorded only as "Manual"; one 0-star GPL notebook on GitHub.
- **Exists:** TaqMan Genotyper (Windows 10), CFX Maestro, DA2 Genotyping, KlusterCaller/SNPviewer; closed, no API, no cross-method agreement.
- **Feature:** two-dye raw curves from RDML (or endpoint RFU for KASP); BCGA best-cycle difference + PAM clustering + silhouette, and endpoint polar-coordinate method as grid members; control-anchored calling optional. Per sample: call, silhouette, method agreement, distance to alternative cluster. Cards only for disagreements/low silhouette, impact-ranked (Hardy–Weinberg, allele frequency). MCP: `qpcr_genotype`.
- **Feasibility:** BCGA fully described; PAM/silhouette in scikit-learn (BSD); no public multi-dye raw datasets (gap). **1–2 weeks.** Hardest: dye cross-talk and ROX normalisation across instruments in RDML.
- **Why qPilot:** only open tool with per-well raw curves across the study; record logs overrides as decisions.
- **Risks/confidence:** flat application, migrating to arrays; KASP users have endpoint only. **Confidence: medium.**

### D4. miRNA panel normalisation robustness plus biofluid QC cards — rank 4
- **Persona:** biomarker researcher running miRCURY or TaqMan Advanced panels (84–179 miRNAs) on plasma/serum from 20–200 subjects; one study/month.
- **Pain evidence:** 43 vs 74 "up" miRNAs by normaliser, spike-ins inverting trend (https://europepmc.org/article/PMC/PMC6367481); global mean valid only for large panels (https://europepmc.org/article/PMC/PMC2718498); hemolysis up to 13-fold; Qiagen ΔCq(miR-23a-3p − miR-451a) >7 rule by hand (https://www.qiagen.com/us/products/discovery-and-translational-research/pcr-qpcr-dpcr/qpcr-assays-and-instruments/mirna-qpcr-assays-and-panels/mircury-lna-mirna-focus-pcr-panels); chemistry cross-reactivity up to 122.47% (https://academic.oup.com/nar/article-lookup/doi/10.1093/nar/gkx588); tools are a 2019 Windows app, a web portal, or Artistic-licensed R.
- **Exists:** GeneGlobe, ExpressionSuite, HTqPCR, Excel.
- **Feature:** panel presets (plate maps for spike-in, IPC, hemolysis, candidate references); expressed threshold Cq ≤35; global mean in log space; NormFinder/geNorm sets; spike-in normalisation; IPC calibration (geometric mean); hemolysis flag. Grid: normaliser family × threshold × hemolysis exclusion × IPC on/off; per-miRNA "stable under n of m" badge. Cards: "Sample 17 hemolysis ΔCq 8.4: exclude (changes 6 miRNAs) or keep"; "Spike-in and endogenous disagree on direction for 12 miRNAs".
- **Feasibility:** methods published; Faraldi data in supplements (licence to check); no raw-curve public set. **1–2 weeks** on top of geNorm. Hardest: TLDA/OpenArray import; pre-amp uniformity checks.
- **Why qPilot:** robustness engine built for "which normaliser"; miRNA is where there's no agreed answer and the biggest effect.
- **Risks/confidence:** Clarida may cover miRNA normalisation; vendor tools are free. **Confidence: medium-high on pain, medium on differentiation.**

### D5. Objective copy-number calls with propagated error (CNV and mtDNA-CN) — rank 5
- **Persona:** human-genetics or mitochondrial lab calling copy number (TaqMan Copy Number Assays, RNase P reference) or mtDNA-CN (ND1/RPPH1) on hundreds of samples in quadruplicate.
- **Pain evidence:** CopyCaller (Windows .exe, 264 MB) describes its algorithm only as "confidence in copy number calls" (https://www.thermofisher.com/us/en/home/technical-resources/software-downloads/copycaller-software.html); qPCR mtDNA-CN associations ~5.6 orders of magnitude less significant and 5.8× less extreme than WGS (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0228166); error propagation and IRC in qBase only (https://europepmc.org/article/PMC/PMC1852402).
- **Exists:** CopyCaller, qbase+, Excel.
- **Feature:** ΔΔCq with geometric-mean references, delta-method SEs, IRCs; copy number = 2 × ratio with CI; plate random effect and pipetting-order covariate; "distance to nearest integer"; card only when CI spans two integers; robustness across reference and calibrator.
- **Feasibility:** formulas public; D'haene calling criteria paywalled (gap); no public dataset. **1 week.** Hardest: duplex wells in RDML and Crt-vs-Ct import.
- **Why qPilot:** error propagation + robustness = honest "confidence".
- **Risks/confidence:** niche, flat; ddPCR dominates new CNV. **Confidence: medium.**

### D6. ChIP-qPCR percent-input module with background shown, not subtracted — rank 6
- **Persona:** chromatin lab, 5–20 loci with input dilutions and IgG, several times/month.
- **Pain evidence:** reference paper recommends %input or relative-to-control with ≥4 replicates and advises against fold enrichment (https://europepmc.org/article/PMC/PMC2077865); open tools are an unlicensed script (https://github.com/sccallahan/WARPqpcr) and a 2026 agent "skill" (https://github.com/wanleyu2000/chip-qpcr).
- **Feature:** samplesheet (well, plate, sample, locus, role, input %, extra dilution); %input with dilution correction; relative-to-control; background displayed; efficiency check; replicate CV. Cards: "IgG Cq within 1 cycle of ChIP at locus X"; "input dilution factor missing".
- **Feasibility:** days; no public datasets (gap).
- **Why qPilot:** generalises samplesheet/role model; the 2026 "skill" shows agent-era demand.
- **Risks/confidence:** low impact. **Confidence: medium.**

### D7. Research "rare-target interpretation" rule pack (EuroMRD-style QR, sensitivity, positive-below-QR) — rank 7
- **Persona:** research lab quantifying a rare target (ASO-qPCR research protocols, residual plasmid, vector persistence, ctDNA research) in triplicate with background controls.
- **Pain evidence:** rules validated on >1,400 assays (https://euromrd-public.s3.nl-ams.scw.cloud/Guidelines_for_RQ-PCR_MRD_data_interpretation-Leukemia2007_%2021_604-611.pdf) and 1,262 samples (https://europepmc.org/article/PMC/PMC11216996) but applied by hand under QA (https://europepmc.org/article/PMC/PMC11147754); FDA persistence judged against LOQ with triplicates/spikes; CML Poisson 3-copy floor (https://europepmc.org/article/PMC/PMC4430701).
- **Feature:** QR/sensitivity definitions (ΔCq ≤1.5, ≥3 Cq from background, 2.6–4.0 Cq per 10-fold, slope −3.1 to −3.9, R² ≥0.98, ≥3 points, ≥2 logs), 2024 "low positive <QR" criteria, Poisson floor, one-significant-figure reporting; robustness over thresholds; grey-zone cards; explicit "research use only; not for patient reporting" banner.
- **Feasibility:** rules public; **1 week**; no public dataset.
- **Risks/confidence:** clinical adjacency; must never be presented as diagnostic. **Confidence: medium.**

### D8. Biomark/single-cell import with Fano-factor LoD and detection-failure culling — rank 8 (lower priority)
- **Persona:** remaining Biomark HD/X9 users.
- **Evidence:** LoD by Fano factor, culling at 3× median detection-failure score, melt flags (https://europepmc.org/article/PMC/PMC3562442); hurdle-model QC in a GPL package (MAST); Biomark CSV Pass/Fail; vendor software Windows-only; GitHub scripts unlicensed/old.
- **Feature:** Biomark CSV importer (2,304/9,216 rows), LoD/Fano, Log2Ex, culling, melt flags, robustness over LoD; no hurdle model unless reimplemented.
- **Feasibility:** days; HTqPCR example CSV documents format.
- **Risks/confidence:** shrinking community. **Confidence: low-medium.**

Growth ranking (note's **estimate**): CGT VCN/titre/biodistribution > circulating miRNA/cfDNA > telomere (large, flat) > CNV/mtDNA-CN (flat) > SNP genotyping (flat, migrating) > single-cell qPCR (declining).

## D. Data / libraries / standards / licences (12 of 29 rows)

| Name | What | Licence/status | URL |
|---|---|---|---|
| Nettle 2019 code + data | dataset1.csv (81.4 kB), dataset2.csv (2.1 kB), simulation.functions.r; Cq replicates for T and S | CC BY 4.0 | https://zenodo.org/record/1994386 |
| Dagnall 2017 S1–S4 | 576-result reproducibility set; extraction/storage T/S | PLOS CC BY | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0184098 |
| TRN example.xls + ICC R script | Long-format id/TL/batch example; lme4/rptR | Not stated | https://trn.tulane.edu/resources/study-design-analysis/ |
| Lindrose S1 TRN reporting checklist | 35 items with E/D importance | PLOS CC BY | https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0245582.s001&type=supplementary |
| cgrtelomeres (NCI-CGR) | Telomere qPCR pipeline from Excel plate reports; "Plots and testing not implemented"; 1 star | MIT | https://github.com/NCI-CGR/cgrtelomeres |
| rptR | ICC/repeatability; used by TRN script | MIT | https://cran.r-project.org/web/packages/rptR/index.html |
| tidyqpcr | LightCycler Cq/raw import; ΔCq/ΔΔCq | Apache-2.0 | https://github.com/ewallace/tidyqpcr |
| FDA LTFU guidance (2020) | <50 copies/µg LOQ, triplicates, spikes | Public domain | https://www.fda.gov/media/113768/download |
| FDA CAR-T guidance (2024) | VCN per CAR+ cell on CoA; risk-justified limit | Public domain | https://www.fda.gov/media/156896/download |
| ICH S12 (2023) | qPCR/dPCR standard; non-GLP analysis acceptable | ICH | https://database.ich.org/sites/default/files/ICH_S12_Step4_Guideline_2023_0314.pdf |
| Ma, Bell, Loker 2021 points to consider | Numeric validation/acceptance criteria | CC (Mol Ther MCD) | https://europepmc.org/article/PMC/PMC7786041 |
| EuroMRD 2007 guideline; 2024 update; grey-zone study | Replicate-level rules | Publisher / OA | https://euromrd-public.s3.nl-ams.scw.cloud/Guidelines_for_RQ-PCR_MRD_data_interpretation-Leukemia2007_%2021_604-611.pdf ; https://europepmc.org/article/PMC/PMC11147754 ; https://europepmc.org/article/PMC/PMC11216996 |

Licence consequences stated by the note: nothing GPL/LGPL/Artistic (MAST, qpcR, NormqPCR, HTqPCR) may be vendored; ICC, PAM/silhouette, delta-method, mixed and hurdle models re-implementable with numpy/scipy/statsmodels/scikit-learn (BSD); rdmlpython (MIT) remains the curve engine; `pcr` archived 2025-11-07; ASGCT/Citeline report is copyrighted; BCGA code (2006 university URL) licence not stated and availability unverified.

**Specifically requested anchors (note 09):**
- **Telomere TRN consortium:** NIA/NIEHS-sponsored, established 2019 via one U24 and four U01 awards; no member/lab count found — https://trn.tulane.edu/ ; resources https://trn.tulane.edu/resources/study-design-analysis/ ; Recommendation 1 (assay precision, ICC into power/sample size, per cohort) https://trn.tulane.edu/wp-content/uploads/sites/72/2021/12/Recommendation-1-FINAL.pdf ; Recommendation 2 (one extraction method per cohort; re-extract 20–30 samples to estimate protocol effect) https://trn.tulane.edu/wp-content/uploads/sites/72/2021/12/Recommendation-2-FINAL.pdf ; ICC how-to https://trn.tulane.edu/wp-content/uploads/sites/72/2020/10/How-to-calculate-repeatability.pdf ; Lin 2019 critical factors https://trn.tulane.edu/wp-content/uploads/sites/72/2020/08/1-s2.0-S0306453018307789-main.pdf
- **Gene/cell therapy run-acceptance — Ma 2021:** the note cites the criteria to [36] (https://europepmc.org/article/PMC/PMC7786041) without naming a table number ("Table 4" does not appear in the note). Criteria as listed: LOD = lowest standard positive in all replicates across five runs, ≥3 copies (Poisson); LLOQ duplicate Cq %CV ≤2.0%, back-calculated %RE ±45%, inter-assay Cq %CV ≤3.0%; E 90–110% (slope ≈ −3.1 to −3.6), R² ≥0.980; standards 10^8 down to 50, 25, 10, 5 and blank, ≥8 non-zero levels in duplicate, ≥75% of levels and minimum seven pass per run (six in sample analysis); QC sets 10^2/10^3/10^5/10^7 with ≥50% per level and ≥67% overall at %CV ≤25% / %RE ±25% (±45% lowest); triplicates with one spiked (e.g. 200 copies); spike recovery <55% = inhibition → re-run at 1/4 or 1/10; matrix DNA 1,000 ng per 50 µL; naive DNA from ≥3 individuals below LOD; five runs over ≥3 days, two operators, two lots; BLOD/BLOQ reporting; failed curve/QC → repeat, second failure → Study Director; supercoiled plasmid standards shift Cq 2.65–4.38 cycles; FDA has not required qPCR validation while EMA has.
- **FDA LTFU (2020):** LOQ <50 copies/µg gDNA at 95% confidence; triplicates with one spiked replicate; individual-animal data; below-LOQ categorisation method must be specified — https://www.fda.gov/media/113768/download
- **ValidPrime:** not mentioned anywhere in note 09 (nor in 07 or 08).
- **Patent notes:** none in note 09. (The only patent mention across the three notes is note 07's CqMAN "patents pending", https://pmc.ncbi.nlm.nih.gov/articles/PMC8596907/.)
- Note 09 §5 item 10: the oft-quoted FDA "≤5 copies per cell" VCN figure does not appear in the 2024 CAR-T guidance read; treat as folklore unless a primary source is found.

## E. Open questions / unverified
1. No practitioner complaint evidence (budget).
2. TRN membership/lab count not stated; EuroMRD counts explicit (69–71 labs).
3. Hays 2024 (AAPS J) and Global CRO Council 2022 abstract-only (bot-walled).
4. WHO lentiviral integration standard: 2017 paper describes a plan; NIBSC site did not resolve.
5. D'haene 2010, Eisenberg 2015 well-position, Picard 2021, Morinha 2020, Schwarzenbach 2015, Mestdagh 2014: paywalled/abstract-only.
6. No public raw-curve datasets for VCN, biodistribution, AAV titre, CNV, SNP, ChIP-qPCR or miRNA panels; Cq-level public data only for telomere and single-cell; Faraldi 2019, Lu 2020, Dobnik 2019 supplements not checked.
7. No formal "MIQE for miRNA" found.
8. BCGA code availability and licence unverified.
9. GeneGlobe and Thermo Connect features unreadable (JavaScript).
10. FDA "≤5 copies per cell" VCN figure not in the guidance read.
11. No community-size numbers for SNP, ChIP-qPCR, CNV, mtDNA-CN.
Also: CFX Maestro and QuantStudio DA2 user-guide PDFs obtained but exact URLs not captured (sources 57, 58).

## F. Strongest verbatim quotes
1. FDA LTFU: "The assay should have a demonstrated limit of quantitation of <50 copies/μg genomic DNA, so that your assay can detect this limit with 95% confidence" — https://www.fda.gov/media/113768/download
2. TRN ICC how-to: "the coefficient of variation (CV) is an invalid statistic for TL measurement and should not be used" — https://trn.tulane.edu/wp-content/uploads/sites/72/2020/10/How-to-calculate-repeatability.pdf
3. Lin 2019: labs adopting LinRegPCR "have routinely calculated the average PCR efficiency of all samples from each assay plate and applied this average efficiency to individual samples" — https://trn.tulane.edu/wp-content/uploads/sites/72/2020/08/1-s2.0-S0306453018307789-main.pdf
4. Verhulst 2020: T/S values "are not comparable across assays, laboratories, or sometimes runs within a lab" — https://europepmc.org/article/PMC/PMC6973063
5. NCI cgrtelomeres README: built to "emulate the current series of tools and manual steps used by lab personnel to analyze their telomere qPCR data" — https://github.com/NCI-CGR/cgrtelomeres

---

**Cross-note observations for the report writer (digest author's synthesis, not from the notes):** all three notes independently converge on the same architecture — (i) rule packs / method cards encoding published numeric acceptance criteria (Bustin claim floors, EPA/ENGL windows, FDA/Ma criteria, EuroMRD rules, USFWS negation), (ii) a robustness grid over conclusion-flipping analysis choices, and (iii) Decision Cards + hash-chained record as the audit trail; all three flag the same licence wall (GPL R packages, closed vendor tools) and the same validation-data gap (raw curves rarely public; Cq-only datasets common). Note 07's D2 study-level model is the shared engine that notes 08 D3 (composite curves) and 09 D1/D2 (telomere LMM, biodistribution rule packs) would build on.
