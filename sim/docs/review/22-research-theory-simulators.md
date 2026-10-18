# Research: simulators that could turn qPilot's Decision Simulator into a real simulator

## Bottom line
- Today the tool replays real data under different analysis choices. To become a simulator in the full sense, it needs a **generative layer**: a model that produces fake but realistic plates where we know the true answer. All the pieces exist in published work: Poisson sampling of molecules into wells, efficiency that falls as product builds up, stochastic branching processes, and measured noise sizes.
- Every simulator I found works on **one curve at a time** (qpcR `pcrsim`, chipPCR `AmpSim`) or on dPCR partitions (dpcR). None simulates a whole plate with planted faults and a known true answer for testing QC detectors. That is a gap qPilot can claim, but it is based on my searches, not proof (searches: [1](https://doaj.org/article/0a55d63c2e434606ba55fc97bf6e811b), [2](https://rdrr.io/github/michbur/chipPCR/man/AmpSim.html)).
- **Licences:** qpcR, chipPCR, dpcR, MCMC.qpcr and propagate are all GPL. Reimplement their published equations in qPilot's Apache-2.0 code rather than vendoring the GPL code. SALib is MIT and safe to use.

## Inventory

| Model / tool | What it simulates | How it plugs into qPilot | Maturity / licence |
|---|---|---|---|
| **qpcR `pcrsim`** | Noisy sigmoid curves from a fitted model. Noise can be constant or depend on fluorescence (e.g. `1/y`, more noise at low signal). Used for Monte Carlo model selection. [doc](https://search.r-project.org/CRAN/refmans/qpcR/html/pcrsim.html) | A quick baseline for curve noise. It is not mechanistic. | CRAN 1.4-2, 2025-06-10, GPL-2/3. [CRAN](https://cran.r-project.org/package=qpcR) |
| **chipPCR `AmpSim`** | 5-parameter Richards curve. Noise can be constant, decreasing or increasing over the run. Supports in-silico dilution (3.32 cycles ≈ 10-fold). Its own docs point to mechanistic models elsewhere. [doc](https://search.r-project.org/CRAN/refmans/chipPCR/html/AmpSim.html) | Same use as `pcrsim`. | CRAN 1.0-2, 2021, GPL-3. [CRAN](https://cran.r-project.org/package=chipPCR) |
| **MAK2** mass-action model (Boggy & Woolf 2010) | Cycle-by-cycle product with 2 parameters (starting amount D0, constant k). Efficiency falls monotonically as DNA concentration rises. Assumes primers and enzyme are in excess, so it covers early cycles only. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2930010/) | Gives the shape of efficiency decay for the generator. | Code is in Mathematica; no code licence stated. |
| **Cobbs 2012** stepwise equilibrium model | Annealing equilibrium with primer depletion; efficiency changes every cycle. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3519511) | Possible kinetics for the plateau phase. Heavier than needed. | Code is SAS (proprietary software). |
| **Rutledge & Stewart 2008 (LRE)** | Amplification rate falls linearly with amplicon quantity; efficiency per reaction. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2397388) | A simple decay law: E_n = Emax·(1 − F_n/Fmax). | Implemented in qpcR. [LRE doc](https://search.r-project.org/CRAN/refmans/qpcR/html/LRE.html) |
| **Carr & Moore 2012** global fit | Recursive model with a capacity term (max) and an inhibitor-affinity term (Kd). Efficiency falls from 100% toward 0. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3365123) | Could simulate inhibition. | Paper only. |
| **Lievens et al. 2012, PLoS ONE** | A simulator built by adding error terms until simulated technical repeats matched real ones (details below). [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3506646/) | **The best published parameter set for a well-noise model.** | Algorithm in supplement (S1); no repository found. |
| **Lievens 2012 (FPK-PCR)** | Full chain of per-cycle efficiencies. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3258155) | Alternative decay law. | Seen via search abstract only; full text not opened. |
| **Branching processes: Sun 1995** | PCR and mutations as a branching process (J Comput Biol 2:63–86). [dblp](https://dblp1.uni-trier.de/db/journals/jcb/jcb2.html) | Theory background. | **UNVERIFIED**: dblp and Sage pages blocked. |
| **Peccoud & Jacob 1996** | Branching-process confidence intervals for starting copies from one curve. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC1233461) | Theory background. | Seen via search abstract. |
| **Jagers & Klebaner 2003** | Efficiency from Michaelis–Menten kinetics gives a size-dependent branching process: exponential growth, then linear. [Chalmers](https://research.chalmers.se/en/publication/77540) | **The core of the stochastic generator.** | Opened. |
| **Lalam, Jacob & Jagers 2005** | Size-dependent branching with a saturation phase; per-cycle replication probability. [CRAS](https://comptes-rendus.academie-sciences.fr/mathematique/articles/10.1016/j.crma.2005.09.029/) | Supports the same generator. | Seen via search. |
| **Chigansky, Jagers & Klebaner 2018** | When replication is imperfect (v < 1), the starting copy number is hidden behind a "veil of uncertainty". [Chalmers](https://research.chalmers.se/en/publication/504249) | Theoretical reason why technical replicates are needed at low copy numbers. | Opened. |
| **DeJaco et al. (NIST) 2023, Bull Math Biol** | Two-type (strand-specific) branching plus a fluorescence version of Beer's law. Splits variance into liquid transfer, imperfect amplification and strand effects. [Springer](https://link.springer.com/article/10.1007/s11538-023-01182-z), [AIChE](https://aiche.org/conferences/aiche-annual-meeting/2023/proceeding/paper/296h-reducing-bias-and-quantifying-uncertainty-fluorescence-produced-pcr) | A citable recent basis for a variance budget. | Paywalled; abstract only. |
| **Chigansky, Klebaner, Mrksa & Sagitov, arXiv Mar 2026** | Multitype Michaelis–Menten branching: several templates compete. [arXiv](https://arxiv.org/html/2603.29549v1) | Would let the generator simulate gDNA contamination or off-target product. | Opened; no code. |
| **Velikanov & Kapral 1999** | Markov model of primer extension; distribution of strand lengths. | Low value for qPilot. | **UNVERIFIED**: page returned 404. [link](https://sites.chem.utoronto.ca/rkapral/node/1270) |
| **Poisson at low copy numbers** | LOD ≈ 3 copies; at 10 copies the CV is about 33% and Cq about 35; efficiency 1.7–1.9 spreads 10 copies over Cq 35–42; assuming 100% efficiency can bias results up to about 100-fold. [Ruiz-Villalba et al. 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8229287/) | Sets the non-detect and late-Cq behaviour in the generator. | Opened. |
| **Tellinghuisen & Spiess 2015** | Cq variance at low copy numbers is Poisson-driven. Above about 100 copies, pipetting (>3%) and efficiency variation dominate. Single-curve exponential methods can be off by 4-fold or more in N0. [1](https://fis.uke.de/portal/en/publications/absolute-copy-number-from-the-statistics-of-the-quantification-cycle-in-replicate-quantitative-polymerase-chain-reaction-experiments(fa358c66-226e-4718-9b34-8c5505076b0a).html), [2](https://fis.uke.de/portal/en/publications/bias-and-imprecision-in-analysis-of-realtime-quantitative-polymerase-chain-reaction-data(fa4170d1-25c1-407e-96c5-0c0b21bc3680).html) | Variance budget for the generator. | Seen via search abstracts. |
| **Pipetting** | ISO 8655 limits for a 2–20 µL pipette: ±10% systematic and 5% CV at 2 µL; ±2% and 1% at 10 µL. [Gilson chart](https://www.gilson.com/pub/media/docs/Pipette_Specs_Chart_LT380069-12.pdf) | Volume noise in the generator. | From a vendor table via search; the 2022 revision may differ. |
| **Plate temperature (von Kanel 2011)** | Well temperature measured by melting analysis, correlated with Cq. [BORIS](https://boris.unibe.ch/8343) | Row/edge fault model. | Effect sizes **UNVERIFIED** (page returned 503). A contrary study found no fixed position effects. [link](https://www.mediray.co.nz/media/15474/ja_xxpress_pcr_broadway-et-al-2014_comparison-rtpcr-paper.pdf) |
| **Technical vs biological variance (Tichopad 2009; Kitchen 2010, powerNest)** | Nested ANOVA over subject, sample, RT and qPCR. The dominant level depends on tissue type. powerNest computed cost-optimal replicate plans. [Tichopad](https://www.labgenexp.eu/publications/design-and-optimization-of-reverse-transcription-quantitative-pcr), [Kitchen](https://pubmed.ncbi.nlm.nih.gov/20109551) | The variance structure for a design planner. | powerNest's page is marked unmaintained. [Edinburgh](https://groups.inf.ed.ac.uk/nesc-research/powernest.html) |
| **MCMC.qpcr (Matz 2013)** | Poisson-lognormal GLMM on molecule counts; no control genes needed. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3747227/) | Could be an extra analysis option, run as a separate R process. | GPL-3. |
| **Bilgrau et al. 2016** | Ignoring efficiency uncertainty gave a false-positive rate of 0.073 at nominal 0.05; delta-method correction gave 0.053. In a real example with 3 dilution steps, p went from 5×10⁻⁴ to 0.31. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4827196/) | Propagating efficiency uncertainty. | Code on GitHub, no licence stated, so reimplement. |
| **propagate (Spiess)** | Error propagation by Taylor expansion and Monte Carlo. [CRAN](https://cran.r-project.org/package=propagate) | Same purpose. | 1.2-0, 2026-07-27, GPL. |
| **dpcR `sim_dpcr` / dPowerCalcR** | dPCR partition simulation; dPCR power calculation. [doc](https://rdrr.io/github/michbur/dpcR/man/sim_dpcr.html), [dPowerCalcR](https://documentserver.uhasselt.be/handle/1942/33742?mode=full) | Only relevant if dPCR is added later. | dpcR 0.6, GPL-3. [CRAN](https://cran.r-project.org/package=dpcR) |
| **"Digital twin" of PCR instruments** | Nothing found for qPCR. Only thermal-design tools, e.g. Laird's Thermal Wizard. [Laird](https://lairdthermal.com/thermal-technical-library/press-releases/lts-offers-online-thermoelectric-modeling-tool-for-pcr) | Avoid the term. The honest equivalent is a per-instrument noise profile fitted to the user's own plates. | Not established. |
| **ML trained on simulated curves** | SARS-CoV-2 curve-anomaly classifiers trained on simulated curves, then applied to lab data. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7793083/) | Shows simulated curves are accepted for training detectors. | Seen via search. |
| **Multiverse and sensitivity theory** | Steegen 2016 (multiverse) [link](https://www.psychologicalscience.org/journals/perspectives/1745691616658637/). Simonsohn 2020 (specification curve with joint inference) [doi](https://www.doi.org/10.1038/s41562-020-0912-z). Gould 2025 *BMC Biology*: spread between analysts far exceeds sampling error [pdf](https://escholarship.org/content/qt0rd2q3sz/qt0rd2q3sz.pdf). R `multiverse` 0.6.2 (2024) [link](https://cran.r-universe.dev/multiverse). SALib Sobol/Morris [GitHub](https://github.com/SALib/SALib). | qPilot's method is mainstream methodology applied to qPCR. Its max-T permutation test plays the role of Simonsohn's joint inference. | SALib: MIT. |

**Lievens 2012 parameters (for the well-noise model).** Starting copies are Poisson. True Emax SD is below 1%. Baseline is linear with random slope (mean 0.7, SD 0.2) and intercept (mean 200, SD 70). Camera noise SD is 1.75 fluorescence units. Primers are lost to side reactions each cycle; this loss drives plateau variability (simulated plateau CV about 0.02 without it, observed about 0.09). Observed Cq SD is about 0.12.

## Recommendation 1 (highest value): PlateSim, a generative plate simulator with known truth
**Why:** right now qPilot can show that a call is fragile, but not which analysis branch is *correct*. With planted truth it can do both. This is also the direct answer to "is your simulator right?"

**Generator (Python/numpy, writes RDML so plates go through the real engine):**
1. **Biology.** log2 expression = gene mean + group effect β_g (known) + a low-rank sample factor (reuse the detectors' co-expression model) + residual. Reference genes have β = 0 unless the "reference shifts with group" fault is planted.
2. **Sampling.** Copies N0 ~ Poisson(λ·V·(1+δ)), with δ ~ N(0, CV_pip) and CV_pip between 1% and 5% ([Gilson chart](https://www.gilson.com/pub/media/docs/Pipette_Specs_Chart_LT380069-12.pdf)).
3. **Kinetics.** Hybrid branching: while N < 10⁴, N_{n+1} = N_n + Binomial(N_n, p_n), with p_n = Emax·K/(K+N_n) ([Jagers & Klebaner](https://research.chalmers.se/en/publication/77540)). Above that, use the deterministic mean. Emax per assay has SD 0.01 between repeats; side-reaction primer loss as in [Lievens](https://pmc.ncbi.nlm.nih.gov/articles/PMC3506646/).
4. **Optics and plate.** Fluorescence = a·N + linear baseline with random parameters + N(0, 1.75). Row, column and edge effects are Emax shifts with a size parameter, since published effect sizes are unverified.
5. **Faults.** Reuse the existing 220-fault injector.

**Validating the simulator itself.** Fit about 6 hyperparameters to the Untergasser dilution series. Then test on held-out instruments and on the Ruijter `ds_94_4`, `ds_380` and `competimer` sets ([README](https://ftp.fau.de/cran/web/packages/ruijter/readme/README.html); no licence stated, citation required). Pass criteria compare simulated and observed values for:
- Cq SD across input amounts.
- Non-detect fraction at ≤ 10 copies.
- Spread of LinRegPCR efficiency estimates.
- Plateau CV.

Use quantile/KS tests. The competimer set lets us test the efficiency-modulation behaviour.

**What it produces:**
- Detector ROC curves against true fault size. The current benchmark on real data cannot rule out faults that were already in the data.
- Error against truth for each branch of the multiverse. This turns "fragile" into "fragile, and these options are closest to the truth".

## Recommendation 2: robust-call design planner
**Why:** answers "how many replicates do I need for a robust call?", which the 3 vs 3 results make urgent.
- Estimate nested variance components (subject / sample / RT / qPCR, as in [Tichopad](https://www.labgenexp.eu/publications/design-and-optimization-of-reverse-transcription-quantitative-pcr)) by REML from a pilot study, or use defaults from Vermeulen.
- Simulate each candidate design (biological × technical replicates) through PlateSim and the 98-run covering array.
- Report P(correct call), P(the call holds in ≥ 95% of defensible analyses), and cost per design. This replaces the role of the unmaintained [powerNest](https://groups.inf.ed.ac.uk/nesc-research/powernest.html).
- Add a Poisson rule: when expected Cq > 35, technical replicates are required ([Ruiz-Villalba](https://pmc.ncbi.nlm.nih.gov/articles/PMC8229287/)).

## Recommendation 3: continuous uncertainty and interaction-aware sensitivity analysis
- Treat efficiency as a distribution (bootstrap or delta method, per [Bilgrau](https://pmc.ncbi.nlm.nih.gov/articles/PMC4827196/)) instead of a three-way choice.
- Report fold-change prediction intervals, which MIQE 2.0 asks for ([Bustin 2025](https://www.gene-quantification.de/bustin-et-al-miqe-2.0-clinical-chemistry-2025.pdf), seen via search).
- Replace the variance-share numbers (52% / 27%) with SALib Sobol first-order and total-effect indices. Total minus first-order measures the interaction-only flips (the 19–22 genes that flip only when 2+ choices change).

## Rating (my assessment)
- **Does the current tool solve "can I trust this qPCR conclusion?"** Partly. It is strong evidence of analysis fragility on real data, but it cannot say which call is true or what to do next. My rating: 6/10.
- **With Recommendations 1 and 2:** about 8/10. It would show truth recovery, detector accuracy and design advice, validated against dilution series with known copy numbers.

**Still open:**
- Plate-effect sizes are unverified.
- There is no RT-step kinetics model.
- PlateSim's realism outside the instruments it is calibrated on is unproven until the held-out tests are run.