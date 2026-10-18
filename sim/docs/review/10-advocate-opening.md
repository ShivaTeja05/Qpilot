# ADVOCATE: qPilot's Decision Simulator is a working simulator, and it targets the step where qPCR conclusions most often go wrong

## 1. Defining "simulator", and how qPilot meets the definition

**The definition statisticians use.** Simulation studies follow the ADEMP standard (Morris, White & Crowther 2019, https://doi.org/10.1002/sim.8086). Each study has five parts:
- an **A**im;
- a **D**ata-generating mechanism;
- a known **E**stimand, meaning the true value;
- the **M**ethods under test;
- **P**erformance measures.

Engineers add one condition: it must be an executable copy of the real system that reproduces its output and is checked against known answers.

**What qPilot simulates** is the chain from raw amplification curves to a reported call.

- **Executable copy.** The engine is vendored LinRegPCR (rdmlpython). The simulator's baseline reproduces the qPilot engine to 1e-12. Every run logs the input SHA-256, a grid hash and a seed.
- **Controlled inputs**, at three levels:
  - **Analysis decisions.** All 3x3x3x31x3x3x3 = 22,599 combinations are run.
  - **Samples and wells.** These are varied by 3 vs 3 and 6 vs 6 subsampling, exact leave-one-out and drop-k.
  - **The data itself.** Faults of known size and position are planted.
- **Truth and performance.** Detection is scored against the planted faults.

**What it is not** is a model of PCR chemistry. It is a stress test that replays a real plate under scenarios. Change 5 below adds the chemistry.

## 2. Five strongest pieces of evidence

All figures come from results/summary.json and benchmark.csv.

**1. Every analysis is run, not a sample of them.**
- All 22,599 analyses run in 14.8 s on one core, so there is no sampling error over the decision space.
- Where running everything is impossible, a 98-run pairwise covering array (0.43% of the space) finds 47 of the 54 genes that ever change call.

**2. It catches the faults that change conclusions (a known-answer test).**
- 220 faults were planted in the real Vermeulen plates. 46 changed a call, and 39 of those 46 were detected (85%).
- Reference gene shifted with group by 0.3 or 0.6 cycles: changed a call in 40 of 40 trials, detected in 34.
- Contaminated NTC: detected 20 of 20.
- Edge effect of 1.5 cycles: detected 18 of 20.
- Row offset of 2 cycles: detected 17 of 20.
- What it misses (single wells off by 3 to 5 cycles, sample swaps) never changed a call.

**3. At bench scale, it reproduces the failure the literature ranks first.**
- **At 3 vs 3:** every baseline call (about 8) changes when only the reference genes change, and no call holds in 95% of analyses.
- **At 6 vs 6:** the reference genes alone change 10 of 11 calls.
- **Outside evidence agrees.** The average reference gene was differentially expressed in about 42% of 986 studies (https://pmc.ncbi.nlm.nih.gov/articles/PMC7473940). When the reference gene moves with treatment, the 2^-ΔΔCq false-positive rate reaches 93.2% (https://pmc.ncbi.nlm.nih.gov/articles/PMC12666847/).
- qPilot measures this per gene, on the user's own plate.

**4. It finds changes that one-at-a-time checks cannot see.**
- 19 genes change call only when two or more defensible choices change together.
- Every existing what-if feature varies one thing at a time:
  - Clarida's geNorm checkboxes;
  - AnnealIQ's exclude-and-re-run;
  - Auto-qPCR's sweep of the SD cut-off (https://pmc.ncbi.nlm.nih.gov/articles/PMC8556264/).
- Clarida's founders co-authored the 2013 benchmark on this dataset (https://pubmed.ncbi.nlm.nih.gov/22975077/). It varied only curve analysis and found the results robust.
- That benchmark held reference genes and grouping fixed. Those two explain 27% and 52% of the fold-change variance.

**5. It says why a call is fragile and what to fix before seeing results.**
- **Significance itself is robust.** A max-T permutation test over 936 defensible analyses finds 57 of 58 genes associated (BH q < 0.05). The fragility comes from the 2-fold claim and the group definition.
- **What to lock in advance:**
  - Fixing the reference genes and the cut protects all 4 headline calls.
  - Also fixing efficiency and flagged-well handling protects every call.
- **How much a call depends on a few samples or wells:**
  - Removing one tumour changes 4 genes.
  - 148 of 1,745 single reference-well removals change a gene.
  - 15 of 40 calls can be overturned by removing 5 or fewer tumours.
- **Verdicts in plain words:** 16 solid, 8 fragile, 14 "depends on your choices", 2 "check data first", 18 no call.
- **It flagged a design confound by itself.** Groups cluster by plate row (p = 9e-5).

## 3. Why it beats Clarida, and why nobody has built it

- **Clarida has no live preview.** Its methods page says so directly: "There is no live preview that updates as you nudge a parameter" (https://clarida.bio/resources/methods/exploration-and-stored-analyses).
- **Its comparison shows settings, not results.** "Compare with…" lists two settings sets side by side (https://clarida.bio/resources/methods/settings-sets).
  - Clarida records which of its 74 settings you chose.
  - qPilot shows whether the conclusion survives the alternatives.
- **Its homepage promises what qPilot computes.** A demo card there says "excluding 4 of 378 flagged wells" does not change significance. That card is mock UI. qPilot computes such statements for real, from leave-one-out up to 1,745 single-well removals.
- **Its own authors argue by simulation.** Ruijter and van den Hoff simulated efficiencies of 1.7 to 2.0 and showed that ΔΔCq can reverse an effect (https://clarida.bio/blog/why-use-the-real-pcr-efficiency). They do not ship that as a tool.
- **Why nobody has built it:**
  - Instrument software outputs one Cq per well.
  - Re-running every analysis needs raw curves.
  - MIQE 2.0 is only now pushing vendors to export raw data.
  - A targeted search for qPCR multiverse analysis turned up nothing.
- **On p-hacking we take Clarida's side.**
  - There is one locked primary analysis, and the multiverse is a robustness report attached to it.
  - Decision Cards and the hash-chained Analysis Record make any switch to another analysis visible.

## 4. The problem, rated

**The problem:** a published qPCR call can change under choices a reviewer would accept, and nobody checks.

| Rating | Score | Basis |
|---|---|---|
| Severity | **8/10** | 42% reference-gene failure rate across studies; at 3 vs 3 every call changes on reference genes alone |
| Detects dependence on decisions, samples and wells (raw curves, two groups) | **8/10** | Every analysis run, exact influence measures |
| Says which answer is true | **3/10** | No known-answer validation yet |
| Covers the decisions practitioners argue about | **5/10** | Missing: threshold and baseline, late-Cq cut-off, standard curve, replicate handling, ΔΔCq order |
| **Overall today** | **6/10** | |
| **With the changes below** | **8.5/10** | |

**Concede these before the other side raises them:**
- **Mann-Whitney at 3 vs 3** has a smallest exact two-sided p of 2/20 = 0.1. Call it "cannot detect anything at n = 3", not fragility.
- **Multiple-testing changes** scale with panel size (58 genes here).
- **Assuming 100% efficiency and setting non-detects to Cq 40** are "common but biased". The headline uses defensible options only: 46 of 58 genes change somewhere.
- **The MYCN cut** is our own contrast, and it is the biggest driver of changes.
- **A multiverse misleads when its options are not equally defensible** (Del Giudice & Gangestad 2021, https://arts.units.it/retrieve/514d5b20-e3e5-4c08-af56-0a95170bfcb1/del-giudice-gangestad-2021-a-traveler-s-guide-to-the-multiverse-promises-pitfalls-and-a-framework-for-the-evaluation-of.pdf). That is why the defensible split exists.
- **The 85% detection rate is mostly reference-gene shifts**, which are 40 of the 46 call-changing trials. The false-alarm rate on clean data is not measured yet.

## 5. Changes that would make the case undeniable

**1. Run the known-answer test on Untergasser data, with dPCR copy numbers as truth.**
- The data is already in data/untergasser: large_DNA_dilutions.rdml with the dPCR TSVs, plus amplicon_primer_mix.rdml.
- Pass if the preferred efficiency option has median |bias| ≤ 0.15 log2.
- Pass if the truth falls inside the range of defensible analyses in ≥ 90% of comparisons.
- Source: https://github.com/RDML-consortium/rdmlpython/tree/main/experiments/untergasser

**2. Test on data where the answer is "no difference".**
- In Ruijter ds_380, all 380 replicates share one concentration, so any call is false. Pass if ≤ 1% of split × analysis cells make a call and none is labelled solid (https://patterninstitute.r-universe.dev/ruijter/doc/manual.html).
- Then show that fragility predicts wrong calls, with AUROC ≥ 0.70 on ds_94_4 subsamples.

**3. Add the decisions practitioners actually argue about.**
- **Cq threshold and baseline.** Across machines and volumes, Untergasser Cq ranged from 11.6 to 24.9 while TD0 stayed at 24.76 to 25.16 (https://pmc.ncbi.nlm.nih.gov/articles/PMC13026326/).
- **Late-Cq cut-off** at 35, 38 or 40.
- **Standard-curve efficiency.**
- **Replicate aggregation.** Applied strictly, the 0.5-cycle rule rejected 39% of reactions, against 7% for a Poisson-based rule (https://www.econferences.de/?p=3963).
- **ΔΔCq order of operations.**
- **Paired t-test and ANOVA.**

**4. Report in MIQE units.**
- ΔCq and log2 fold change, with intervals.
- A scenario table in the style of de Ronde's A to E (https://pmc.ncbi.nlm.nih.gov/articles/PMC5393188/).
- Sobol interaction indices from SALib, which is MIT-licensed.
- "Ask" on a local model, qwen2.5:7b via Ollama, so the data stays on the laptop. The existing validator rejects any number the engine did not produce.

**5. Build PlateSim, a generator of plates with a known true answer.**
- **How it works:** Poisson loading of molecules, Jagers–Klebaner branching kinetics (https://research.chalmers.se/en/publication/77540) and noise from Lievens 2012, with Cq SD about 0.12 and camera noise SD 1.75 (https://pmc.ncbi.nlm.nih.gov/articles/PMC3506646/).
- **Calibration:** fit on Untergasser, then test on a held-out instrument.
- **Outputs:**
  - error against truth for each analysis;
  - detector ROC curves by fault size;
  - a design planner giving P(call holds in ≥ 95% of analyses) for each mix of biological and technical replicates.

**6. Recruit a wet-lab advisor**, then use NIST SRM 2373 as a physical known-answer standard (certified HER2 ratios of 1.3 to 17.7).

Sources: https://doi.org/10.1002/sim.8086 · https://pmc.ncbi.nlm.nih.gov/articles/PMC7473940 · https://pmc.ncbi.nlm.nih.gov/articles/PMC12666847/ · https://clarida.bio/resources/methods/exploration-and-stored-analyses · https://clarida.bio/resources/methods/settings-sets · https://clarida.bio/blog/why-use-the-real-pcr-efficiency · https://pubmed.ncbi.nlm.nih.gov/22975077/ · https://pmc.ncbi.nlm.nih.gov/articles/PMC8556264/ · https://arts.units.it/retrieve/514d5b20-e3e5-4c08-af56-0a95170bfcb1/del-giudice-gangestad-2021-a-traveler-s-guide-to-the-multiverse-promises-pitfalls-and-a-framework-for-the-evaluation-of.pdf · https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12875576/

Files: /Users/gaddamshivateja/Wheel-hack/qpilot-simulator/results/summary.json, /Users/gaddamshivateja/Wheel-hack/qpilot-simulator/results/benchmark.csv, /Users/gaddamshivateja/Wheel-hack/qpilot-simulator/results/REPORT.md, /Users/gaddamshivateja/Wheel-hack/qpilot-simulator/data/untergasser/