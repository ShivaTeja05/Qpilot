# Method card: NormFinder, and what to normalise each gene to

**What it answers.** How much error would each candidate reference gene bring into the normalisation,
counting both its variation within each group and its shift between the groups being compared?
Which pair of candidates is steadiest? And, as a further choice of the robustness grid, would the
conclusions change if each gene were divided by NormFinder's or geNorm's best pair, or by the mean of
every gene measured, instead of the reference genes chosen for the study?

**References.**
- Andersen CL, Jensen JL, Ørntoft TF. *Normalization of real-time quantitative reverse transcription-PCR
  data: a model-based variance estimation approach to identify genes suited for normalization, applied to
  bladder and colon cancer data sets.* Cancer Res 64(15):5245–5250 (2004). doi:10.1158/0008-5472.CAN-04-0496
- Mestdagh P, Van Vlierberghe P, De Weer A, et al. *A novel and universal method for microRNA RT-qPCR data
  normalization.* Genome Biol 10(6):R64 (2009) — the global mean.
- D'haene B, Mestdagh P, Hellemans J, Vandesompele J. *miRNA expression profiling: from reference genes to
  global mean normalization.* Methods Mol Biol 822:261–272 (2012) — each gene weighted equally.

**Implementation.** `qpilot/qpcr/normfinder.py::normfinder` (reimplemented from the paper's equations;
NormFinder's own R/Excel code and GPL ports such as NormqPCR were not used or read), the normaliser axis
`qpilot/qpcr/axes/normaliser.py`, the reference panel `GET /api/studies/{id}/references`
(`qpilot/web/references_views.py`). Deterministic, numpy only.

## NormFinder

Model (Eq. A): `y_igj = α_ig + β_gj + ε_igj` for the log2 quantity of gene *i* in sample *j* of group *g*
(*k* genes, *G* groups, *n_g* samples in group *g*); β is the amount of mRNA in the sample and cancels.

| Quantity | Definition |
|---|---|
| Intragroup variance (Eq. B) | Residuals of the additive model per group, `r = y − ȳ_ig· − ȳ_·gj + ȳ_·g·`; `s²_ig = Σ_j r² / ((n_g − 1)(1 − 2/k))`; unbiased `σ²_ig = s²_ig − Σ_v s²_vg / (k(k − 1))` |
| Intergroup shift | `z_ig` = mean of gene *i* in group *g*; `d_ig = z_ig − z̄_i· − z̄_·g + z̄_··` (the average of the candidates is assumed not to differ between groups) |
| Spread of true shifts (Eq. D) | `γ² = Σ d² / ((k − 1)(G − 1)) − Σ (σ²_ig / n_g) / (kG)`, set to 0 if negative |
| Stability value (Eq. C) | With `v = σ²_ig / n_g`: `ρ_ig = γ²·|d_ig| / (γ² + v) + √(v + γ²·v / (γ² + v))` — the posterior mean shift plus one posterior SD; `ρ_i` = mean over the groups. Lower is steadier |
| Best pair | The average of two genes has the average of their posterior shifts and a quarter of the sum of their posterior variances: `ρ_ij = mean_g(|d̃_ig + d̃_jg| / 2 + √((p_ig + p_jg) / 4))`; the pair with the lowest value. Genes whose shifts cancel can beat the two individually steadiest genes |

Without groups (one group), `d = 0` and `γ² = 0`: the stability value is `√(σ²/n)` and the best pair is
the two steadiest genes.

**qPilot's choices where the paper is silent** (each reported, never hidden): an unbiased variance estimate
below 0 (sampling noise with few genes) counts as 0 in the stability value and the gene is named
(`clamped`); a unit missing any candidate is left out (NormFinder needs complete data), as is a unit without
a group and a group with fewer than two units. The groups are every group of a confirmed design, or the
expression-defined split's high group and the rest. The paper's own requirements are shown as plain warnings:
at least 8 samples per group, at least 3 candidates (5–10 recommended), candidates with no expected difference
between the groups. The input is `log2 N0` (LinRegPCR's efficiency-corrected quantity), the scale of
NormFinder's own `−Cq` input.

**Tests.** `tests/numbers/test_normfinder.py`: a hand computation (3 genes, 2 groups of 3: σ² = 0, 0, 3;
γ² = 1/6; ρ = 0.5, 0.5, √(8/7); best pair G1 + G2 at 0 because their shifts cancel), the same without groups,
a direct line-by-line transcription of Eqs. A–D on random three-group data (agreement to 1e-10), and
properties: the sample amount and each gene's own level cancel, sample and candidate order do not matter, a
shift between groups moves from intra- to intergroup variation once the groups are known. The paper's
published colon example (NormqPCR reproduces Table 3: TPT1 0.141, UBC 0.161, …) was not reproduced here
because its data set is not redistributed with qPilot.

**On the demo study** (MYCN-high 53 vs rest 294; 347 units, 19 left out for a missing reference value).
NormFinder: ALUsq(Eurogentec) 0.113, HPRT1 0.227, SDHA(1) 0.232, UBC(2) 0.304, HMBS 0.337; γ² = 0.027; best
pair ALUsq(Eurogentec) + HPRT1 (0.119). geNorm's best pair is the same two genes, so the two methods agree
on the best pair, and disagree on the order of the rest (geNorm puts HMBS third, NormFinder last: HMBS's
within-group SD is 1.87 log2 and it shifts by ±0.22 between the groups).

## The normaliser axis (opt-in)

Options (ids stable): `planned` (primary: the reference genes chosen for the study, i.e. the `refs` cell),
`normfinder_pair`, `genorm_pair`, `global_mean`. Absent by default (`StudyDesign.axes` names it only when a
person accepted the rule's `choice.axis` proposal), so every existing design hash, study id and the locked
demo output are unchanged. An option that would repeat another (a best pair that is the set in use, geNorm's
pair equal to NormFinder's) or that the study cannot support is not offered and the reason is reported. The
best pairs and the global mean's genes come from the primary matrix and stay fixed across the grid.

Another normaliser does not read the `refs` choice, so the grid evaluates it only with the primary `refs`;
the other combinations would repeat an analysis (`QpcrSpace.redundant`, skipped by `core.robustness`), so
"holds" counts each distinct analysis once. Screening as for the efficiency models: the axis enters the grid
when an option alone flips a call or moves a log2 fold change by more than 0.5, and then raises its own
Decision Card (`numbers.normaliser`). Choosing an option never changes which reference genes a study uses;
the card is decided by a person.

**Global mean.** Each gene's `log2 N0` is centred on its own mean over the units, and a unit's normaliser is
the mean of its genes that have a value (D'haene et al. 2012: each gene weighs the same even when values are
missing; with no missing value it is Mestdagh's plain mean up to a constant that cancels). **Threshold:**
offered from **50 genes** with values in at least two units. This is qPilot's own default, not a published
number: Mestdagh et al. write that the global mean "is only valid if a large number of" genes is profiled
(they profiled 366–448) and give no minimum. Below it the option is not offered and the reason says so in
plain words. The card also reports whether the global mean itself moves between the groups against the
reference genes in use: a panel chosen for the comparison moves its own mean.

**On the demo study** (asked for with all options): `genorm_pair` is not offered (the same pair as
NormFinder's); NormFinder's pair alone changes 3 of 58 calls (DPYSL3, PAICS, PDE4DIP); the global mean of 64
genes alone changes 19 of 58. Against the five reference genes, the global mean is 0.71× in the MYCN-high group
(p = 6.1 × 10⁻⁶): the panel was chosen for this comparison, which is why the global mean is not a neutral
yardstick here. The grid has 186 + 12 = 198 analyses (no repeated cell).
