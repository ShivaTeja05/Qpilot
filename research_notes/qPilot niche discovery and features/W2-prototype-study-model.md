# W2 — Prototype: does a study-level statistical model change qPilot's conclusions on real data?

Date: 2026-10-17. Timebox: ~40 min. Data: `~/.cache/qpilot/data_vermeulen_raw.rdml` (Vermeulen neuroblastoma panel, 64 plates, 366 tumours, 64 assays, CC BY 4.0), analysed through qPilot's own modules (`qpilot.qpcr.curves/quant/design/refgenes/contrast/space`, imported, not re-implemented). Scripts and CSV outputs live in `scratchpad/proto_stats/` (`common.py`, `s1`…`s6`). `statsmodels 0.15.0` (BSD-3) was pip-installed into the repo venv for the mixed models (it was not present; `patsy`/`formulaic` came with it). The repo itself was not modified (`git status --porcelain` in `qpilot/` at the end of the session printed nothing).

Tests the three proposed features from note 07: (a) D2 plate-aware censored mixed model with prediction intervals, (b) D1 efficiency-uncertainty propagation and efficiency-model sweep, (c) D3 Cq-tier claim floor with bootstrap.

## 0. What the data allows (read this before any number)

| Fact (from `common.py` exploration) | Consequence |
|---|---|
| Exactly **one gene per plate** (64 plates, 64 assays; 0 genes on >1 plate, 0 plates with >1 gene) | A per-gene **plate random effect is not estimable**: plate ≡ gene, so the plate term is the gene intercept and cancels in the within-plate MYCN-high vs rest contrast. D2's "plate-aware" claim **cannot be tested** here; the fitted "plate variance" (4.81 log2²) in a joint model is just between-gene expression spread (`s2_mixed.py`, plate demo). |
| **One well per sample × gene** (no technical replicates) | No replicate-level variance component; "replicate-level bootstrap" means resampling biological samples. |
| 323 undetermined wells of 23,424 study wells (1.4 %); 19 of the 58 tested genes have ≥1; two genes are heavily censored (NHLH2 87, CPSG3 69, both ~22–28 % of the *rest* group) | Censoring is testable, but mainly on 2–8 genes. |
| Per-assay LinRegPCR efficiency 1.73–1.94, per-well SD 0.020–0.051, n = 366 wells per assay | The SE of the per-assay mean E is ~0.0013 — efficiency uncertainty is tiny on this dataset (this will not be true of a 3-vs-3 study with 12 wells). |
| Nq (threshold fluorescence) constant per plate, CV 0.07 % | `N0 = Nq / E^Cq` holds exactly, so N0 can be rebuilt under any efficiency model from Cq alone. |
| 53 vs 294 samples per group; 56 of 58 genes already p < 0.05 (`s1`) | The study is massively over-powered. "Changes significance" is a weak metric here; **changes of estimate and of the up/down/none call (p < 0.05 and ≥ 2×) are the informative metrics.** |

## 1. Baseline (current method) — `common.py` → `s1_welch_baseline.csv`

Primary normaliser = all five references (geNorm recommends all five); groups = top 15 % by MYCN (53 vs 294); undetermined = drop; Welch on log2 relative quantities.

| Gene | FC | 95 % CI | p | call |
|---|---|---|---|---|
| ODC1 | 3.59 | 2.42–5.33 | <1e-8 | up |
| NM23A | 2.19 | 1.75–2.73 | <1e-8 | up |
| BIRC5 | 4.01 | 2.93–5.49 | <1e-8 | up |
| NTRK1 | 0.066 | 0.032–0.140 | <1e-8 | down |

Across the 58 tested genes: 56 with p < 0.05, 56 with Benjamini–Hochberg q < 0.05, 40 up/down calls. Headline numbers (ODC1 3.6×, NM23A 2.2×) reproduce.

## 2. Mixed model vs Welch — `s2_mixed.py` → `s2_mixed_vs_welch.csv`

Because plate is not estimable, the study-level model fitted is the Steibel 2009 / Hampton 2025 form with a **sample random intercept** that replaces the geometric-mean normaliser:

- **A. Per-target LMM** over {target, 5 refs}: `y_sg = μ_g + β·high_s·[g = target] + u_s + ε_sg`, refs constrained to no group effect (statsmodels `MixedLM`, REML; 58/58 converged).
- **B. Joint LMM** over all 64 genes: `y_sg = μ_g + β_g·high_s + u_s + ε_sg` (global-mean-style normalisation).
- **C.** Pooled-variance t on the current relative values (isolates the Welch-vs-pooled part).

| Comparison vs Welch | sig changes @0.05 | BH changes @0.05 | \|Δ log2FC\| > 0.5 | max \|Δ log2FC\| | median SE ratio |
|---|---|---|---|---|---|
| A per-target LMM | 0 | 0 | 0 | 0.25 | 0.85 |
| B joint LMM (64 genes) | 4 lost (MRPL3, SLC25A5, SLC6A8, SNAPC1) | 4 lost | 0 | 0.40 | 1.39 |
| C pooled t | 0 | 0 | 0 | 0 | — |

Variance components (A): sample random-intercept variance median 1.02 log2², residual median 1.64 log2²; ODC1 0.91/1.58, NM23A 1.01/1.44. Joint model: sample 2.10, residual 2.88. Plate variance: **not estimable** (see §0).

Per-gene detail: ODC1 log2FC 1.84 (Welch) → 1.74 (A) → 1.60 (B); NM23A 1.13 → 1.04 → 0.86 (joint p = 0.0098 rather than <1e-8).

Reading: model A is numerically the current method with a different error model (SEs 15 % narrower because it pools residual variance across the six genes). Model B's shifts are not "the mixed model" at work — they are the normaliser: a sample random intercept estimated from all 64 genes is a global-mean normaliser, and on an MYCN-biased panel it absorbs part of the shared up-shift, so every estimate drops by ~0.2–0.3 log2. Model B also assigns **one SE (0.331) to every gene** because it assumes one residual variance across genes — a known weakness of the naive joint LMM that qPilot must not ship without per-gene residual variances.

**Verdict (a), mixed model: does not change conclusions on this data, and the plate part cannot be tested on it.** The variance components are real and useful outputs (they feed `qpilot plan`), but the claim "plate-aware model flips conclusions" needs a dataset with several genes per plate and samples spread over plates (e.g. the Ruijter 2015 inter-run data, or any 96-well study). Prediction intervals, however, are producible now (§6).

## 3. Censoring — `s3_censor.py` → `s3_censoring.csv`

Rules compared on the 19 genes with non-detects: (i) drop (current primary), (ii) cap at the lowest detected value (qPilot's current alternative) and substitute at the plate's latest detected Cq (N0 = Nq/E^Cq_max) — these two are numerically identical here (max |Δ| < 0.001), (iii) left-censored Tobit normal MLE at the detection floor on the relative scale (53/58 converged; the 5 failures are genes with no censoring where the Hessian is singular in the censoring direction, estimates still equal Welch).

| Rule vs drop (19 genes) | sig changes | up/down/none changes | \|Δ log2FC\| > 0.5 | max \|Δ log2FC\| |
|---|---|---|---|---|
| cap / substitute ceiling | 0 | 0 | 3 | 2.31 |
| Tobit censored | 0 | 0 | 4 | 3.33 |

Where it bites: NHLH2 log2FC 3.90 (drop) → 6.21 (substitute) → 7.23 (Tobit), i.e. 15× → 74× → 150×; CPSG3 4.41 → 6.14 → 6.78 (21× → 70× → 110×); CDH5 −3.32 → −4.15 → −4.16; PLAGL1 −1.18 → −1.55 → −1.60; DDC −1.89 → −2.31 → −2.34. Non-detects are concentrated in one group (NHLH2: 83 of 87 in "rest" = 28 % of that group; CPSG3: 66 of 69 = 22 %), exactly the MNAR pattern McCall describes; "drop" therefore under-estimates these fold changes by 4–10×.

**Verdict, censoring: changes the estimate (not the call) for 4 of 19 genes, by up to 3.3 log2.** On a smaller study the same mechanism would flip calls; the Pipelers ~30 % censoring guard would already trigger a sensitivity card for NHLH2 and CPSG3 here. Worth shipping as a grid axis ("non-detect rule: drop / substitute floor / censored MLE") with a card raised only when the estimate moves > 0.5 log2.

## 4. Efficiency — `s4_efficiency.py` → `s4_efficiency.csv`, `s4_efficiency_assay_stats.csv`

Efficiency-model sweep (Welch on each universe, N0 rebuilt from Cq):

| Universe vs per-assay mean E (current) | FC change > 25 % | sig changes | up/down/none flips | FC ratio range |
|---|---|---|---|---|
| per-well E (LinRegPCR `indiv PCR eff`) | 2 (NTRK1 ×0.39, PRAME ×1.32) | 1 | 5 (CAMTA2, DPYSL3, PAICS, PRKACB_bis, SLC25A5) | 0.39–1.32 |
| assumed 2.0 | 4 (NTRK1 ×0.47, CLSTN1 ×0.76, ECEL1 ×0.78, NHLH2 ×1.27) | 0 | 4 (CAMTA2, IGSF4, PAICS, PRKACB_bis) | 0.47–1.27 |

All flips are genes sitting at the 2× call threshold (FC 1.9–2.1 or 0.49–0.52); the big ratio changes are the late-Cq genes (NTRK1 mean Cq 32.5–37.7, E 1.73; CLSTN1 Cq 34, E 1.73), as Bustin's ΔCq-scaling predicts (NTRK1 ΔCq = 5.4 cycles).

Efficiency-uncertainty propagation (delta method, Bilgrau 2016 / Hellemans 2007 form; E uncertainty is shared by all wells of a plate so it enters the contrast as `Var_E(D) = Σ_k w_k² (ΔCq_k /(E_k ln 2))² Var(E_k)`, added to the Welch variance):

| SE(E) universe | median CI widening | max widening | genes losing p < 0.05 | flips |
|---|---|---|---|---|
| (a) SE of the per-assay mean = sd/√n (≈ 0.0013; bootstrap over wells agrees: ODC1 0.00125 vs 0.00124) | ×1.000 | ×1.000 | 0 of 56 | 0 |
| (b) pessimistic: SE = per-well SD (0.02–0.05, comparable to a dilution-series SE) | ×1.009 | ×1.031 (NTRK1) | 0 of 56 | 0 |

**Verdict (b): the efficiency-model *sweep* changes fold changes by > 25 % for 2–4 genes and flips the up/down call for 4–5 of 58 — it is a real axis. Efficiency-uncertainty *propagation* does not change anything on this data** because 366 wells per assay pin the mean E to ±0.0013. Bilgrau's effect (FPR 0.073, p 5e-4 → 0.31) arises with 6 samples and a 6-point dilution series, where SE(E) is 10–30× larger; the formula is implemented and costs nothing, so ship it, but do not promise it moves conclusions on large studies.

## 5. Claim floor — `s5_claimfloor.py` → `s5_claimfloor.csv`

Thresholds as cited in note 07 §3.0 (Bustin 2025 [9]): minimum credible fold change 2× at Cq < 25, 3× at Cq 25–30, 4× at Cq > 30. Floor taken from the **higher of the two group mean Cqs** of the target (the less precise group; using the overall mean Cq instead moves 6 genes from the 4× tier to the 3×/2× tiers). Bootstrap: 10,000 resamples of biological samples within group, E per assay drawn from N(E_mean, SE_mean), N0 rebuilt, 95 % percentile CI.

- Floor tiers (max group Cq): 2× for 3 genes, 3× for 29, 4× for 26.
- Of the **56 genes with Welch p < 0.05, 39 (70 %) are below their Cq-tier claim floor**; 0 have a bootstrap CI that includes 1.
- Of qPilot's **40 up/down calls (which already require ≥ 2×), 23 (58 %) are below the Cq-tier floor** — e.g. MRPL3 1.78× at Cq 26 (floor 3×), SLC6A8 1.54× at Cq 31 (floor 4×), HIVEP2 0.42× (2.4-fold down) at Cq 32.5 (floor 4×), PLAT 0.29× at Cq 33 (3.4-fold, floor 4×).
- Headlines: ODC1 3.59× at Cq 23–25 (floor 2×, bootstrap CI 2.49–5.36) and NM23A 2.19× at Cq 22 (floor 2×, CI 1.77–2.72) both pass; BIRC5 4.0× at Cq 25–27 passes a 3× floor; NTRK1 15-fold down at Cq 32–38 passes a 4× floor.
- Bootstrap SE / Welch SE median 0.99 — on 53 vs 294 samples the efficiency draw adds nothing; the bootstrap matters only as the small-n estimator.

**Verdict (c): changes conclusions — it would relabel 23 of qPilot's 40 current calls as "below credible floor"** without touching the numbers or p-values. This is the largest conclusion-level effect of the three features on this data, and it is also the one Bustin flags as assay-specific (floors are defaults a lab may override). NM23A, the gene that "flips under some choices", sits at 2.19× against a 2× floor with CI lower bound 1.77: the claim-floor card would say its credible margin is thin even in universes where it holds.

## 6. Prediction intervals — `s6_predint.py` → `s6_prediction_intervals.csv`

Per-group normal PI on the normalised log2 scale, `mean ± t_{0.975,n−1}·s·√(1+1/n)` (empirical coverage 94–98 %):

| Gene | Group | n | mean log2 rel. | SD | 95 % CI of mean (fold width) | 95 % PI for a new sample (fold width) |
|---|---|---|---|---|---|---|
| ODC1 | MYCN-high | 53 | 2.76 | 2.02 | 2.20–3.31 (×2.2) | −1.33 to 6.85 (**×290**) |
| ODC1 | rest | 294 | 0.91 | 1.14 | 0.78–1.04 (×1.2) | −1.34 to 3.16 (×23) |
| NM23A | MYCN-high | 53 | 4.11 | 1.10 | 3.81–4.41 (×1.5) | 1.89–6.33 (×22) |
| NM23A | rest | 294 | 2.98 | 0.90 | 2.88–3.09 (×1.2) | 1.22–4.75 (×12) |

In words a scientist would read: *"ODC1 is on average 3.6× higher in MYCN-high tumours (95 % CI 2.4–5.3×), but a single new MYCN-high tumour's ODC1 level is expected anywhere within a 290-fold range, and the two groups' prediction intervals overlap almost entirely (rest: 23-fold range). The group difference is real; ODC1 alone cannot classify a tumour."* For NM23A: *"2.2× higher on average (CI 1.8–2.7×); a new MYCN-high tumour falls in a 22-fold range that overlaps the 12-fold range of the rest."* The LMM gives the same message on the raw log2 N0 scale (±3.1 log2, ×70, for both genes from sample + residual variance).

**Verdict: does not change the contrast, but changes what the sentence next to it says** — MIQE 2.0 asks for exactly this and no competitor emits it. Cost: one line of code per group.

## 7. Comparison tables (headline genes across all variants)

| Gene | Welch FC (p) | LMM-A FC | joint LMM FC (p) | Tobit FC | per-well-E FC | E = 2.0 FC | floor | passes floor |
|---|---|---|---|---|---|---|---|---|
| ODC1 | 3.59 (<1e-8) | 3.33 | 3.03 (<1e-8) | 3.59 (no ND) | 3.6 | 3.6 | 2× | yes |
| NM23A | 2.19 (<1e-8) | 2.05 | 1.81 (0.0098) | 2.19 (no ND) | 2.2 | 2.2 | 2× | yes |
| BIRC5 | 4.01 (<1e-8) | 3.74 | 3.41 (<1e-8) | 4.01 | 4.0 | 4.0 | 3× | yes |
| NTRK1 | 0.066 (<1e-8) | 0.063 | 0.058 (<1e-8) | 0.047 | 0.026 | 0.031 | 4× | yes |
| NHLH2 | 15.0 | — | — | 150 | — | 19.1 | 4× | yes |

Counts across the 58 tested genes:

| Feature / axis | Significance changes (0.05 / BH) | Call changes (up/down/none) | Estimate moves > 0.5 log2 | Verdict on this data |
|---|---|---|---|---|
| Mixed model, sample RE, refs as targets (A) | 0 / 0 | 0 | 0 | does not change |
| Mixed model, joint 64-gene (B) | 4 / 4 | not computed (SE artefact) | 0 | changes via the normaliser, not the model |
| Plate random effect | — | — | — | cannot tell (plate ≡ gene) |
| Non-detect rule (drop → censored) | 0 | 0 | 4 of 19 | changes estimates, not calls |
| Efficiency model (assay mean → per-well / 2.0) | 1 / 0 | 5 / 4 | 2 / 4 genes FC > 25 % | changes calls |
| Efficiency-uncertainty propagation | 0 | 0 | 0 | does not change (n = 366 wells) |
| Cq-tier claim floor | n/a | 23 of 40 calls relabelled | n/a | **changes conclusions** |
| Prediction intervals | n/a | n/a | n/a | changes the sentence, not the number |

## 8. What to ship, with formula and paper, and how it plugs into the grid

1. **Claim floor + bootstrap (D3) — ship first.** Floor table from Bustin 2025 (2×/3×/4× by Cq tier, from the less precise group's mean Cq, lab-overridable); bootstrap over biological units with `E ~ N(E_mean, SE_mean)`; label = `below_floor` if `|log2 FC| < log2(floor)` or CI ∋ 1; equivalence statement "data rule out changes larger than Y×" from the CI bound. Grid: not an axis but a **post-hoc label on every cell**, so the robustness summary gains "holds and passes floor in x of 186". New facts `f_floor_<gene>`, `f_boot_ci_<gene>`. Effort: 2–3 days (prototype is `s5_claimfloor.py`, 60 lines).
2. **Efficiency-model axis (D1 sweep) — ship second.** `N0 = Nq / E^Cq` with E ∈ {per-assay mean (current), per-well, per-plate mean, assumed 2.0, dilution-series when `std` wells exist}; Nq from the cache (`n0·E^Cq`). Grid: a 4th dimension (×4–5 cells → ~750–930 cells; `QpcrSpace.evaluate` is vectorised so still seconds). Decision Card only when a gene's call differs between per-assay mean and per-well. Effort: 2–3 days.
3. **Delta-method variance (D1 propagation) — ship with 2, zero-cost.** `Var_E(D) = Σ_k w_k² (ΔCq_k/(E_k ln2))² Var(E_k)` (Bilgrau 2016; Hellemans 2007 Eq. for E error), `Var(E_k) = sd_k²/n_k` from LinRegPCR's `STD PCR eff`; added to the Welch variance before the t. Honest statement: no effect at n = 366 wells; it matters at n ≤ 12. Effort: half a day; acceptance test = Bilgrau's FPR 0.073 → 0.053 by simulation.
4. **Non-detect axis (D2 censoring) — ship third.** Replace "cap" with {drop, substitute floor, censored MLE}; censored MLE = Tobit normal on the relative scale with censoring point = plate's detection floor `log2(Nq/E^Cq_max)` (Pipelers 2017 censor rule; McCall 2014 for the MNAR argument), scipy `minimize` + numerical Hessian; raise the sensitivity card when > 30 % of a group is censored or the estimate moves > 0.5 log2. Effort: 3–4 days including the singular-Hessian guard seen here (5/58).
5. **Prediction intervals (D2 output) — ship with 1.** `mean ± t·s·√(1+1/n)` per group on the normalised scale; one sentence template. Effort: half a day.
6. **Mixed model with plate random effect (D2 core) — do not ship on the strength of this data.** The Steibel/Hampton form `y = μ_g + β·high·[g=target] + u_sample + v_plate + ε` is implemented and runs in 8 s on 23k wells with statsmodels `MixedLM`, but on the demo it reproduces Welch (0 changes) and the plate term is unidentifiable. Before committing 3–4 weeks, find a multi-plate-per-gene dataset (Ruijter 2015 inter-run set, or a lab's own 96-well study) and rerun `s2_mixed.py` with `groups = plate`. If shipped later, it needs per-gene residual variances (the joint model's single SE is unacceptable) and should enter the grid as a "plate model" axis {none, random intercept}.

## 9. Things that failed or were not done

- Plate random effect: not fitted per gene (impossible by design); the joint-model "plate" variance is a demonstration of the confound, not an estimate.
- Tobit Hessian singular for 5 genes without censoring (estimates equal Welch; the SE fallback should be Welch's).
- No per-plate-mean or dilution-series efficiency universe (identical to per-assay mean here, since one gene = one plate; `std` wells exist but were not used in the timebox).
- Bilgrau's FPR simulation and Bustin's 11.3/16/23 check were not reproduced (acceptance tests for the shipped version, not for this prototype).
- "Cq = 40 substitution" was not used literally because this run goes to Cq 47; the plate ceiling was used instead.
