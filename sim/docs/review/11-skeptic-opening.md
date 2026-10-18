# Skeptic's case: qPilot's Decision Simulator is a sensitivity analysis on one unusual dataset, not a simulator that solves the problem

## Scores (0–10)
- **How serious the problem is: 6.** Analysis choices do change qPCR conclusions. Using one reference gene gives "erroneous normalization up to 3.0- and 6.4-fold in 25% and 10% of the cases" ([Vandesompele 2002](https://pmc.ncbi.nlm.nih.gov/articles/PMC126239)). The average reference gene was differentially expressed in about 42% of 986 studies ([Hampton 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7473940)). But the variation bench scientists feel most comes before analysis (RNA, reverse transcription) and from n=3. Analysis choices are a latent problem that labs don't feel.
- **How much the tool solves today: 3.** It measures how sensitive the analysis is on one atypical dataset. It has no ground truth, gives no prescriptive answer, and leaves out the decisions practitioners actually touch.
- **After the fixes listed under each weakness: about 6–7.**

## Weaknesses: evidence, and what would overturn each

**1. It is not a simulator.**
- **Evidence:**
  - Nothing is generated. It re-analyses fixed data across 7 options (a multiverse in the sense of [Steegen 2016](https://doi.org/10.1177/1745691616658637) or [Simonsohn 2020](https://www.doi.org/10.1038/s41562-020-0912-z)) plus jackknife-style removals.
  - The only planted element, fault injection, edits Cq and N0 values directly. `benchmark.py` `_shift` divides N0 by E^d, which is the engine's own model, not raw fluorescence.
  - Ruijter-school reviewers will say "call it a sensitivity analysis."
- **What would overturn it:**
  - A generative plate model: Poisson sampling of molecules into wells, branching-process kinetics, baseline and optics noise.
  - Calibrated on the [Untergasser dPCR data](https://pmc.ncbi.nlm.nih.gov/articles/PMC13026326/).
  - Passing KS tests against held-out instruments on Cq SD versus input amount, non-detect fraction at ≤10 copies, efficiency spread and plateau CV.

**2. "No call holds in 95% at 3 vs 3" is built in.**
- **Evidence:**
  - The exact two-sided Mann-Whitney test at 3 vs 3 has a minimum p of 2/C(6,3) = 2/20 = 0.1, so it can never reach significance.
  - With equal weighting, one third of all cells can never make a call. The most any call can hold is therefore 66.7%, before BH or Holm cut it further.
  - Multiplicity flips 11 of 11 calls at 6 vs 6 only because the panel has 58 genes. On a 5-gene panel BH barely changes anything.
- **What would overturn it:** drop options that cannot detect anything at the given n, and adjust multiplicity for panel size. Then show that fragility persists.

**3. The forks are not all defensible, and how many options each decision has sets the headline.**
- **Evidence** (`decisions.py`):
  - **Questionable options in the "defensible" tier:**
    - Per-well efficiency: [Ruijter 2009](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=PMCID:PMC2665230&resultType=core&format=json) shows the per-assay mean is better.
    - "Drop wells below 10 copies": censors low values that are not missing at random.
    - Mann-Whitney at n=3: cannot detect anything (weakness 2).
  - **The baseline uses no multiple-testing correction across 58 genes,** which a statistician would call the indefensible arm.
  - **Option counts are lopsided.** Reference genes contribute 26 defensible options (10 pairs, 10 triples, 5 quads, 1 of all five); every other decision contributes 2 or 3. "Holds in X%" depends on how many options get listed.
  - **The 52% variance share for the group cut comes from the range the authors chose (10–20%).** A 14–16% range would give about 0%.
- **What would overturn it:**
  - Weight each decision equally, however many options it has.
  - Get the option tiers signed off by an outside qPCR methods expert before running.
  - Report Sobol total-effect indices ([SALib](https://github.com/SALib/SALib)) and show the ranking survives different option ranges.

**4. The demo dataset is unusual and its groups come from the data.**
- **Evidence:**
  - **Groups come from the panel itself.** They are the top X% of MYCN expression measured in the same panel, and headline gene ODC1 is a direct MYCN target ([PMC8069650](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8069650/)). The contrast is close to circular.
  - **The cut decision doesn't exist on the bench.** In a designed treated-versus-control experiment there is no cut, so the decision that drives most of the variance (52%) does not apply there.
  - **The baseline is favoured.** Groups are fixed using the baseline reference genes (`engine.py`, lines 12–13), so alternative reference sets are scored on groups the baseline defined.
  - **The data has no technical replicates.** Each tumour sits in the same well on every plate.
  - **Primary human tumours vary far more than cell-line triplicates.** So the "3 vs 3" fragility overstates what happens in bench experiments.
- **What would overturn it:** reproduce the flip rates on designed contrasts. Candidates:
  - MAQC C vs D, with known mixing ratios (C = 75% A + 25% B, D = 25% A + 75% B); needs a Cq-only import first.
  - Untergasser dilution groups.
  - Random 3 vs 3 and 6 vs 6 splits of Ruijter ds_380, where any call is false.

**5. "Fragile" has not been shown to mean "wrong".**
- **Evidence:**
  - The tool's own max-T test finds 57 of 58 genes associated with the group, and 7 of 40 calls sit within one SE of the 2-fold line.
  - Flips mostly measure distance to qPilot's own p < 0.05 and ≥2-fold rule. That is an artefact of turning a continuous effect into a yes/no call, not error.
  - No comparison against a known answer has been run.
- **What would overturn it:**
  - Run the planned truth test (protocol step V3): fragility score predicting wrong calls on MAQC C vs D and ds_94_4 subsamples. Pass if AUROC ≥ 0.70 with a lower confidence bound above 0.55, and if fragile calls are wrong at least twice as often as robust ones.
  - Lead with effect sizes and intervals, not flip counts.

**6. The decisions practitioners argue about are missing.**
- **Evidence:**
  - Threshold and baseline: most users accept the instrument default ([Bioconductor thread](https://support.bioconductor.org/p/37399)).
  - Replicate aggregation and the 0.5-cycle rule: applied strictly to 20,016 reactions it rejects 39%, versus 7% for a Poisson-based rule ([Ruijter 2017](https://www.econferences.de/?p=3963)).
  - Late-Cq cut-off at 35, 38 or 40 ([de Ronde 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5393188/)).
  - ddCq order of operations ([Lixiang 2025](https://www.biorxiv.org/content/10.1101/2025.07.16.665089v1)).
  - Global-mean normalisation, the standard choice for large panels ([Mestdagh 2009](https://genomebiology.biomedcentral.com/articles/10.1186/gb-2009-10-6-r64)), which Clarida already offers.
  - Paired designs and ANOVA.
  - RNA integrity and reverse transcription, the dominant sources of variance, which no re-analysis can capture.
- **What would overturn it:** add Cq method and threshold, replicate rules, late-Cq cut-off, global-mean normalisation and paired/ANOVA designs. Then show that reference genes still dominate.

**7. The benchmark is circular.**
- **Evidence** (`benchmark.py`, `troubleshoot.py`):
  - **The 100% NTC score is guaranteed.** The fault adds an amplifying no-template control to a plate that was clean, and `detect_ntc` fires on any amplified control, whatever the planted size.
  - **The reference-shift fault and its detector use the same groups.** The fault uses the same 15% group mask that the detector tests.
  - **Every fault type was paired with a detector written for it.**
  - **Few faults mattered, and the headline number is loose.** Only 46 of 220 faults (21%) changed a call. The 85% detection rate is 39 of 46, with a Wilson 95% interval of 72–92%.
  - **The false-alarm rate is unknown.** There is no truth on the clean data, and 116 of 128 queued issues show "no demonstrated effect".
  - **The 1e-12 match is self-consistency.** It shows the simulator matches qPilot, not that either is accurate.
- **What would overturn it:** score the detectors on real faults (protocol step V5), with no simulator-specific detector tuning:
  - Positives: competimer ≥ 20%, the top inhibitor levels in lievens2/lievens3, testdat FX.3/FX.4, and Untergasser control and artefact wells.
  - Pass: sensitivity ≥ 80% and false alarms ≤ 2% of clean wells.

**8. The finding is not new, and the data belongs to the competitor.**
- **Evidence:**
  - "Reference genes drive calls" is the reason geNorm was created in 2002, by Clarida's founders.
  - Vermeulen is their own data, Vandesompele is its corresponding author, and Clarida's blog already demos on it.
- **What would overturn it:** show a new and useful result on data they didn't produce, such as the coverage test (protocol step V2): the truth falls within the min–max range of defensible analyses in at least 90% of known-truth comparisons.

**9. Labs may not use it.**
- **Evidence:**
  - It needs raw curves, and too few publications share raw data ([RDML authors](https://econferences.de/?p=1078), [HEROIC 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10158759)).
  - Output is CLI + CSV in statistics jargon.
  - At n=3 the actionable message is "add replicates", which labs already know.
  - Nobody pays to be told their result is fragile.
- **What would overturn it:**
  - A Cq-only import.
  - A plain-language report: "the result is not robust to the reference-gene choice".
  - Letters of intent from three core facilities or journals that would require a robustness report.

**10. Clarida could copy it in a sprint.**
- **Evidence:**
  - Clarida already has 74 locked, versioned settings, LinRegPCR, 8 tests and native file import (since 2026.9), and an MCP server is on its planned list ([settings sets](https://clarida.bio/resources/methods/settings-sets), [changelog 2026-9](https://clarida.bio/changelog/2026-9)).
  - The simulator is 3,734 lines, built in one day, and Apache-2.0, so Clarida can simply vendor it.
  - Their "no live preview" principle does not stop a batch robustness report attached to a locked run.
- **What would overturn it:** a moat a vendor can't easily copy:
  - independence (a vendor cannot audit its own pipeline);
  - truth-calibrated validation results (V1–V5) and a calibrated generative plate model;
  - local-first deployment for regulated labs.

## The one fix to make before the debate
Run the known-answer tests V2 to V4 on Untergasser, ds_94_4/ds_380 and MAQC, and show three results:
- the range across defensible analyses contains the truth in at least 90% of comparisons;
- fragile calls are wrong at least twice as often as robust ones;
- fewer than 1% false calls on null data.

Without these, "this is fragile" can't be told apart from "this sits near your own 2-fold line."

Files checked:
- sim/src/qsim/decisions.py
- sim/src/qsim/engine.py
- sim/src/qsim/benchmark.py
- sim/src/qsim/troubleshoot.py
- sim/results/REPORT.md