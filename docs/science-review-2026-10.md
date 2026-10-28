# Science review of the October 2026 analysis features

*Reviewer: agent `science` (excellence round, wave 3), 28 October 2026, branch `ex/science` (from
`ui/excellence` @ 5171854, merged again @ 5b429cf after compare2 landed).*

qPilot's promise is that every number is right and every judgement call is a person's. This
round added a lot of statistics (several comparisons with Holm, Dunnett and Tukey; paired
designs; Welch's ANOVA; melt curves; absolute quantification; NormFinder, the global mean and
correction between plates; replicate rules in the audit; a "different groups" verdict in the
Claim Auditor). This review reads each against its source and recomputes it with an independent
oracle on real lab files. It is written for the person who decides: section 3 lists what was
fixed, section 4 the judgement calls that are yours, each with a recommendation.

## 1. Summary

| Area | Verdict |
|---|---|
| Several comparisons: Welch, paired t, Holm, BH q, Welch's ANOVA | **Correct.** Equal to first-principles numbers to 1e-15 on a real 8-condition study |
| Dunnett and Tukey (compare2) | **Correct.** Dunnett equals an adaptive-quadrature integral to 3e-11 (scipy's quasi-Monte Carlo to 2e-4); Tukey equals `scipy.stats.tukey_hsd` to 2e-14 |
| "The corrected p decides the call" | Grid, Decision Cards, Results: consistent. **Trace was not** for paired designs (fixed here, B1); the gene Trace and Holm were fixed by compare2. **The Claim Auditor was not** (fixed here, B3) |
| Replicates in the audit (mean, median, one outlier left out) | **Correct**, units never counted as n. Two small points (J10) |
| Melt (−dF/dT, peaks, Tm, calls) | **Correct and well sourced.** qPilot's derivative *is* CFX Manager's own; Tm within 0.06 °C of a spline. One rule to tighten (J5) |
| Absolute quantification (curve, efficiency CI, inverse PI, LOD, LOQ) | **The arithmetic is correct.** On a real file, wells LinRegPCR calls "no amplification" enter the curve and give 154 % efficiency, R² 0.41 (J1, the most important call in this review); the interval formula is fine for good curves only (J2) |
| NormFinder | **Correct** (Andersen 2004 rewritten: equal to 2e-15). Two notes (J11) |
| Global mean | Arithmetic correct; the gene set should exclude genes missing in some units (J7) |
| Inter-run calibration, factor correction | **Correct** (Hellemans 2007, Ruijter 2015 rewritten: equal to 1e-12, known offsets recovered, a gap filled through a third plate) |
| Claim Auditor "different groups" | **Two bugs fixed** (B2, B3): 9 of 20 sentences about other groupings came back "Supported"; now 1 of 20 |
| Thresholds set by builders | Listed with a recommendation each (section 4, table J0) |

## 2. How it was checked

Independent oracles live in `validation/excellence/` and are compared with the engine by
`tests/science/` (34 tests, about 20 s). An oracle never calls qPilot's arithmetic: it is written
from the paper, mostly as explicit loops (qPilot is vectorised numpy), with scipy and statsmodels
where a library implements the method. The input is either the file itself (read with `lxml` or
`csv`) or qPilot's per-well table (the data, not a statistic); everything downstream is the
oracle's own.

| Oracle | Method | Real data | Agreement |
|---|---|---|---|
| `stats_oracle`, `comparisons_oracle` | Welch 1947; paired t; Holm 1979; BH 1995; Welch 1951 ANOVA; pooled t; Dunnett 1955 by nested adaptive quadrature; Tukey–Kramer via `scipy.stats.studentized_range` | K. phaffii LinRegPCR RDML (Büchner et al. 2025): 8 conditions × 3 cultures, triplicate wells, 4 UPR genes, ACT1 + TFC1 | log2fc 0, p ≤ 1.1e-16, Holm ≤ 3.3e-16, q ≤ 1.1e-16, ANOVA p ≤ 2.2e-16 (5 plans, paired and 8 groups among them); Dunnett ≤ 3.4e-11; Tukey ≤ 2.4e-14 |
| `normfinder_oracle` | Andersen et al. 2004, supplementary equations, element by element | K. phaffii, 6 genes, 8 groups / ungrouped / 3 genes | ≤ 1.9e-15 (stability, pairs, γ²) |
| `absolute_oracle` | statsmodels OLS; Miller & Miller eq. 5.9 inverse interval and the exact (Fieller) one; statsmodels Logit for the 95 % LOD; Forootan 2017 log-normal CV | StepOne RNase P curve (5 levels × 3); QuantStudio 7 Pro eDNA curve (9 levels × 4) | slope, intercept, R², efficiency CI, LOD, logistic LOD, every level's CV, every interval: ≤ 1e-12 relative |
| `replicates_oracle` | mean / median / G-REP outlier of each unit's wells, then Welch | K. phaffii D20 vs 20 through the audit engine (`qsim`), as filed and with 6 outlier wells added | ≤ 7.4e-15; with the outliers the drop-outlier rule moves the result, without them it does not |
| `melt_oracle` | the instrument's own −dF/dT (CFX "Melt Curve Derivative Results") and a cubic smoothing spline of the raw RFU (GCV smoothing) | CFX Manager 3.1 gapdh plate, 96 SYBR wells | qPilot's −dF/dT equals CFX's own values (ratio 1.000 away from the ends; Tm identical); vs the spline: mean −0.018 °C, SD 0.009, max 0.062 °C |
| `interrun_oracle` | Hellemans 2007 calibration factor; Ruijter 2015 factor correction (pairwise geometric means, two rounds of gap filling, column means) | K. phaffii ACT1/HAC1i wells spread over 3 plates with offsets +0.7 / −0.4 log2, with and without a gap | ≤ 1e-12; offsets recovered exactly |

Also checked by reading against the sources: the planner's formulas (section J4), G-REP's
tolerance (`range_quantile` values are the 95th percentile of the range of n normals: 2.772,
3.314, 3.633 …, correct), rdmlpython's `interRunCorr` (qPilot uses every pair of replicate wells,
as it does), and the melt rule's provenance (rdmlpython's `truePeakWidth` 1.0 °C and
`peakCutoff` 5 %).

## 3. Bugs fixed on `ex/science`

Each has a test that fails before the fix and passes after.

**B1. Trace's what-ifs on a paired study were an unpaired Welch update** (`qpilot/qpcr/trace.py`,
commits 21e4477, fe0620e; `tests/science/test_trace_exact.py`). Trace scores each sample by
"what if it were set aside" and each reference well by "what if it read as expected" with a
closed-form one-comparison Welch update. A paired comparison tests within-pair differences, and
setting a unit aside takes its pair with it, so the closed form gave other fold changes: up to
1.06 log2 on K. phaffii paired by replicate (3 groups), 0.59 with 2 groups. With Holm's
correction it also read the raw p (a "changes the call" verdict could be wrong); compare2 fixed
that case independently, but only when a correction is set, so **paired + no correction stayed
wrong on `ui/excellence`**. Now one switch, `_closed_form(space)`, sends a paired comparison, or
any correction over several comparisons, through the exact unit-by-unit evaluation
(`QpcrSpace.evaluate_arrays`). One-comparison studies (the demo) keep the closed form, unchanged.

**B2. A phrase naming another grouping lost to the study's group inside it**
(`qpilot/claims/lexicon.py`, c85d643; `tests/claims/test_claims_other_groups.py`). The review
wrote 20 sentences about groupings the demo study does not compare and 15 about its own groups
in new words. 9 of the 20 came back **Supported**: "tumours with a high MYCN copy number" was
read as the group "high MYCN"; "ALK mutations" (plural), "1p-deleted", "11q loss", "older than
18 months", "unfavourable histology", "died of disease" and "hypoxia" were not recognised. Now a
longer phrase that names another grouping wins over the study's group it contains ("MYCN-high"
itself still is the study's group), and those groupings are known. 19 of 20 are now "Not
supported: different groups"; all 15 own-group sentences stay Supported; the 40-claim corpus is
unchanged. The one left is "MNA tumours", the field's abbreviation of MYCN amplification (see O2).

**B3. In a study with several comparisons, every claim was checked against the first one**
(`qpilot/claims/check.py`, `lexicon.py`, 48e72f4; `tests/claims/test_claims_comparisons.py`).
The record's contrasts are the first comparison's. On the three-group test file (Drug A, Drug B,
Control; Holm), "MYC was up-regulated in Drug B compared with Control" came back **Overstated**
(the study calls it up there, corrected p 0.028) and "IL6 was higher in Drug B than in Drug A"
**Contradicted** (a pair the plan does not compare). A claim naming a group of another comparison
is now **Unchecked**, in words that say the auditor checks the first comparison only and where
the numbers are; a claim naming no group gets a note that it was read against the first
comparison; "significant" is judged by the corrected p, the one the call uses (it used the raw
p); a numeric group label (K. phaffii's `20`, `28`) no longer matches inside `p = 0.20`.
Checking a claim against the comparison it names is the better end state (O2).

Found and already fixed by compare2 before it merged (confirmed here): the gene Trace
(`qpilot/trace/`) reported IL6 "up" where the Holm-corrected engine said "no call"; it now
evaluates every comparison with the correction (`Family`).

## 4. Judgement calls for you

Nothing below was changed. Each says what, why it matters, the options, a recommendation and
the sources.

### J0. The thresholds builders set without a source, at a glance

| Threshold | Where | Recommendation |
|---|---|---|
| A non-amplifying sample is a repeat candidate only if the gene amplified in ≥ 90 % of the other compared samples | `qpcr/repeat.py` `EXPECTED_SHARE` | **Change**: count within the sample's own group (J3); keep 90 %, make it lab-editable |
| Poisson noise floor `1 / (ln 2 · √N)` | `qpcr/plan.py` | **Keep, cite** Ståhlberg & Kubista 2014 (already cited); say "lower bound" below 3 copies (it is) |
| One copy crosses at Cq 35 (`--cq-one-copy`) | `qpcr/plan.py` `CQ_ONE_COPY` | **Keep as default, take it from the study's standard curve when there is one** (the intercept at 1 copy, now computed by `absolute.py`) |
| Plan for 2.5× (1.25 × the 2-fold line) | `qpcr/plan.py` `default_fold` | **Keep, but headline the n that gives 80 % *calls*** (J4) |
| Melt: product within 1 °C; extra peak ≥ 5 % of summed prominence; noise floor 5 %; ≥ 3 wells | G-MELT params | **Keep, cite rdmlpython** (as the card does); **add a minimum distance for "primer-dimer"** (J5) |
| LOQ: log-normal CV ≤ 35 % | `absolute.py` `LOQ_CV` | **Keep, cite** Forootan 2017 and Klymus 2020 (both use 35 %); already lab-editable (`loq_cv`) |
| LOD: detected in ≥ 95 % of wells | `absolute.py` `LOD_RATE` | **Keep** (MIQE's definition); **say that with < 20 wells per level it means "all wells"** (J6) |
| Global mean from 50 genes | `axes/normaliser.py` | **Keep, lab-editable; restrict the gene set** (J7) |
| A group of capped values only is never compared ("detected only in X") | `qpcr/space.py` | **Keep; add the detection counts' own test as orientation** (J8) |
| Standard curve warnings: efficiency 90–110 %, R² ≥ 0.98 "(MIQE)" | `absolute.py`, G-STD | **Cite Taylor et al. 2010** (Methods 50:S1–S5), where these numbers are; MIQE 2009 asks for them to be reported, not for these limits |
| Trace robust z 3.5 | `qpcr/trace.py` | Keep (Iglewicz & Hoaglin 1993, cited) |

### J1. Wells LinRegPCR says did not amplify still count, because they have a quantity (most important)

**What.** rdmlpython's LinRegPCR returns a starting quantity (`Ncopy`) and a TD0 Cq for some
wells it marks *no amplification* (`amplification` false, note "no amplification; baseline
error", or for a standard "excluded: no amplification in positive control"). qPilot's
`linregpcr` amplification rule counts a well as amplified when it has a quantity
(`amp_call.amplified`: "has `n0`"), and the absolute module counts a standard as detected when
it has a Cq and "LinRegPCR's call **or** a quantity" (`absolute.detected_wells`).

**Why it matters (measured).**
* QuantStudio 7 Pro eDNA standard curve (corpus): wells A7, A8 and D9 (4.8, 2.4 and 1.2 copies)
  are flat (fluorescence 0.44 → 0.50), the instrument reports them Undetermined, LinRegPCR says
  no amplification, yet they enter the curve with Cq 24.7, **9.9** and 25.6. The fit becomes
  efficiency **154 %** (95 % CI 90–449 %), R² **0.41**; without those three wells it is **87 %**
  (84–90 %), R² **0.996**. The LOQ and every quantity read from that curve move with it.
* The eDNA sample plate: 7 unknown wells with "no amplification" carry quantities (one at Cq 19.1,
  2.5 × 10⁶).
* The demo: 11 of 24 576 wells (mostly Cq > 39, Ncopy < 10; one MTSS1 well at Cq 23.8 with
  efficiency 1.20). Counting them as undetermined changes **no** call; the largest fold-change
  move is 0.069 log2.

**Options.** (a) Keep (documented as "exactly the engine's behaviour before the dimension
existed"). (b) Count LinRegPCR's "no amplification" as undetermined everywhere (changes the
demo's locked numbers, not its calls; regenerate the locks). (c) Add an amplification rule
"LinRegPCR's call, its no-amplification notes respected" to the `amp_call` axis, so the grid
shows whether it matters, and make it the default for new studies. (d) In the absolute module
only, require LinRegPCR's amplification call for a standard to be detected.

**Recommendation.** (d) now (a standard curve should never be fitted through a well its own
curve analysis says is flat; it does not touch the demo's relative numbers), and (c) for the
relative engine; (b) at the next planned lock regeneration. In every case a person keeps the last
word through `well_calls`.

### J2. Standard wells outside the series, and the interval when a curve is poor

**What.** The absolute module never drops a standard well ("a person does"), which is right, but
nothing *proposes* it either: a standard whose Cq is earlier than the wells of a ten-fold higher
level (A8 above: Cq 9.9 at 2.4 copies, 9 cycles before the 965 000-copy wells) is physically
impossible and only surfaces as a low R². Separately, the classical inverse prediction interval
(Miller & Miller eq. 5.9, `Fit.inverse`) is an approximation that is excellent when the curve is
good and poor when it is not: on StepOne's curve it equals the exact (Fieller) interval to
2 × 10⁻⁴ log10; on the eDNA curve with the flat wells (g = t²s²/(m²Sxx) = 0.2) it is
[−0.20, 5.80] against the exact [−0.56, 6.17] at the mean Cq — too narrow and centred wrongly.

**Options / recommendation.** Propose a `curve.exclude_well` card (the decision kind exists) for
a detected standard that breaks the order of the series or whose studentized residual is beyond
±3.5, with the consequence for efficiency and LOQ shown, for a person to accept or reject. Report
g with each curve and use the exact interval when g > 0.05 (the usual rule of thumb accepts the
approximation below g = 0.1; 0.05 keeps a margin).

### J3. "No amplification where one was expected" counts across groups

**What.** `repeat.py` flags a non-amplifying sample when the gene amplified in ≥ 90 % of the
*other compared samples*, regardless of group. **Why.** A gene that is truly off in a small group
(2 of 20 samples, as in a knockout or a sex-specific gene) passes 90 % (18 of 19) and every
sample of that group is put on the repeat plate as a technical failure. **Recommendation.** Count
the share within the sample's own group (with at least three other samples there; otherwise do
not flag), keep 90 % as a lab-editable default, and say in the reason which group's share it is.

### J4. The planner: which n to headline

**What.** The headline "you need n per group" is the normal approximation plus one,
`2(z₁₋α/₂ + z₁₋β)² σ² / δ² + 1` (the +1 approximates Guenther's 1981 t correction). Against the
exact non-central t (Student, equal n) it is the same in 15 of 24 settings and one sample short in
9 (all at n ≤ 11; e.g. 2-fold, σ 0.5: 5 vs 6). The planner already simulates qPilot's own rule and
says so honestly (at 2.5×, σ 1 log2: n 10 gives p < 0.05 in 80 % of runs but a *call* in 74 %,
because the call also needs the measured change past 2-fold; 14 per group give 80 % calls,
`n_for_call`). **Recommendation.** Headline `n_for_call` (what a scientist wants is the call), show
the test-only n beside it, and compute the test-only n from the non-central t (scipy) instead of
the normal approximation. Keep 2.5× as the starting fold (no published source; it is a sensible
"aim above the line" heuristic, now explained in `fold_words`). Take `cq_one_copy` from the study's
own standard curve when there is one (J0).

### J5. Melt: when is an NTC peak a primer-dimer?

**What.** A no-template control whose peaks are all below the product's Tm is a "primer-dimer
candidate" and **passes** (G-MELT `ntc_dimer`, and G-NTC-1 then grades its amplification
`tainted_dimer`, a warning instead of a failure). Any distance counts: a peak 1.1 °C below the
product does. **Why.** Primer-dimers melt well below most products (often in the 70s °C; Ririe et al.
1997 show the separation), but a shorter non-specific product or a variant
amplicon can melt a degree or two below the intended one; passing it as "dimer" hides a
contamination candidate. **Recommendation.** Add a lab-editable `dimer_min_below_c` (default 3 °C)
to G-MELT: closer peaks are `other_product` (warn). The other melt thresholds are well chosen and
sourced (rdmlpython's 1.0 °C true-peak window and 5 % cut-off; the noise floor relative to the
assay's typical product, which avoids counting noise in an empty NTC as peaks).

### J6. LOD with few replicates

**What.** The empirical LOD is the lowest level detected in ≥ 95 % of its wells with every higher
level too (MIQE's definition). With fewer than 20 wells per level that means *all* wells (3 of 3,
4 of 4), so the "95 % LOD" of a triplicate series is really "the lowest level where none failed";
the logistic LOD (Forootan 2017) is the better estimate and is shown. **Recommendation.** Keep
both; say in the curve's words how many wells per level stand behind the empirical limit, and
recommend ≥ 10 replicates at the levels around the LOD (Forootan 2017; Klymus et al. 2020). The
log-normal CV for the LOQ is exactly Forootan's formula (checked).

### J7. The global mean's gene set

**What.** The global mean (Mestdagh 2009) centres each gene on its own mean over the units, then
averages, per unit, the genes that have a value there. **Why.** Values are not missing at random:
a gene is undetermined in a unit because it is *low* there. Leaving it out raises that unit's
mean: a unit missing the lowest tenth of its genes has its normaliser raised by about
0.2 residual-SD (φ(1.28)/0.9 ≈ 0.195), of the order of 0.2 log2, and every gene of that unit falls
by as much. **Options.** (a) Keep. (b) Use only genes with a value in every compared unit (the
common set; this is what "expressed in all samples" normalisation does). (c) Keep the per-unit
mean but flag units missing more than, say, 5 % of the genes. **Recommendation.** (b), with the
count of genes used in the card's words, and keep 50 genes as the lab-editable minimum of the
*common* set. The 50 is not from Mestdagh et al. (they profiled 366–448 genes and give no
minimum), as the code already says; qbase+'s documentation is often quoted as "more than about
50 genes": verify that source before citing it.

### J8. "Detected only in X"

**What.** A gene detected in no unit of one group is withheld with the group's ΔCq and no fold
change (a ratio to nothing), and any grid cell where a group's values are all capped is not
tested. **This is right**: no fold change should be invented from a cap. **Recommendation.** Keep,
and add as orientation (never a call) the detection counts' own test, Fisher's exact test on
"detected / not detected" by group (6 of 6 against 0 of 6 is p = 0.002), so a presence/absence
difference is not mistaken for "nothing found".

### J9. Several comparisons: smaller points

* **BH family.** q-values are Benjamini–Hochberg over the genes of one comparison, from raw p,
  shown and never used for a call. That is the standard per-contrast FDR (as limma reports it) and
  the words say so. With many comparisons the whole table's FDR is not controlled; offer a
  table-wide q only if screens with many comparisons become common.
* **Welch per comparison** uses each comparison's own two groups (no pooled variance), robust to
  unequal variances but with few degrees of freedom at n = 3. Dunnett and Tukey pool (more power,
  equal-variance assumption). Both are a person's choice: right.
* **"Any difference" (Welch's ANOVA)** drops a group with fewer than two values for that gene;
  the note names all the plan's groups. Say per gene when a group was left out (df1 shows it).
* **Dunnett/Tukey under the "cap" rule** (robustness cells only): a group whose values are all
  capped is not tested itself, but its identical values still add n − 1 degrees of freedom and no
  spread to the pooled variance, which shrinks the SD of the other comparisons in those cells.
  Leave such a group out of the pooled variance too.

### J10. Technical replicates

* **Several samples of one unit.** A unit's value is the flat mean over all wells of all its
  samples, so a sample with three wells weighs three times one with one well. When the samples
  are biological sub-replicates (two RNA preparations of one animal), the mean of the sample means
  is the usual choice. Recommendation: mean of sample means when a unit has several samples (no
  change for one sample per unit, the common case and the demo).
* **G-REP's outlier with ties.** With three wells spread symmetrically (20.0, 20.5, 21.0) the
  "well farthest from the median" is a tie and the first in well order is proposed. Propose no
  single well then (say "the spread is not one well's").
* **Audit vs G-REP.** The audit's drop-outlier tolerance never uses the standard curve's copy
  number (pipetting term only), while G-REP adds the Poisson term when the plate has a curve: at
  low copy numbers the audit may leave out a well G-REP accepts. Use G-REP's tolerance.

### J11. NormFinder

* A candidate whose unbiased within-group variance comes out negative is counted as 0 (documented;
  the paper is silent). With small groups this happens often (4 of 6 genes on K. phaffii's groups
  of three) and makes those genes look steadiest. The warning "fewer than 8 per group, rough" is
  shown; also name the clamped genes in it.
* Without groups the stability value is the standard error of the gene's mean (the paper's
  equation with γ² = 0). The ranking is NormFinder's; if a lab compares the *values* with the
  NormFinder program's ungrouped output, check that program's scale first.

### J12. The "cap" rule for wells that never amplified (legacy, not new)

Capping at the lowest amount detected for the gene is conservative (it shrinks a fold change
towards none for the group with non-detects) and is one option of the grid, not the default.
Model-based alternatives exist (McCall et al. 2014, non-detects as missing not at random); not
needed now, worth a sentence in the method card.

## 5. Observations for other owners

* **O1. qPilot's curve re-analysis and the depositors' LinRegPCR differ on K. phaffii.** qPilot's
  per-gene efficiencies are 0.014–0.028 higher than the ones LinRegPCR wrote into the file (ACT1
  1.930 vs 1.916, HRD1 1.959 vs 1.931); per-well log2 N0 differ with SD 0.08–0.14 within a plate;
  fold changes up to 0.23 log2 apart. Every call agrees (`tests/science/test_oracles.py`). Worth a
  look by the curves owner (LinRegPCR version and settings: window of linearity, baseline).
* **O2. The Claim Auditor's group lexicon is a closed list.** Recognising more phrases (B2) helps,
  but any grouping it does not know falls back to "the study's groups" and can be Supported.
  Safer end state: a claim that names a qualifier the auditor does not recognise ("in MNA tumours")
  is Unchecked with "check that these are the study's groups". And for several comparisons,
  route a claim to the comparison whose two groups it names (B3 makes it Unchecked today).
* **O3.** Dunnett's fixed quadrature is accurate to 1e-11 here; its own docstring limits that to
  groups up to nine times the control's size. Above that it should fall back to scipy or say so.

## 6. Not checked

The curve analysis itself (LinRegPCR port), the Curve Judge, the Run Gate rules other than G-REP,
G-MELT and G-STD's thresholds, and the efficiency axis were outside this review. No real file in
the corpus has a gene split over plates, so the inter-run oracle used real values on constructed
plates.

## 7. References

Andersen CL, Jensen JL, Ørntoft TF. Normalization of real-time quantitative RT-PCR data: a
model-based variance estimation approach. *Cancer Res* 2004;64:5245–5250.
Benjamini Y, Hochberg Y. Controlling the false discovery rate. *J R Stat Soc B* 1995;57:289–300.
Bustin SA et al. The MIQE guidelines. *Clin Chem* 2009;55:611–622; MIQE 2.0, *Clin Chem*
2025;71:634–651.
D'haene B, Mestdagh P, Hellemans J, Vandesompele J. miRNA expression profiling: from reference
genes to global mean normalization. *Methods Mol Biol* 2012;822:261–272.
Draper NR, Smith H. *Applied Regression Analysis*, 3rd ed. Wiley 1998 (inverse prediction, §3.2).
Dunnett CW. A multiple comparison procedure for comparing several treatments with a control.
*J Am Stat Assoc* 1955;50:1096–1121.
Fieller EC. Some problems in interval estimation. *J R Stat Soc B* 1954;16:175–185.
Forootan A et al. Methods to determine limit of detection and limit of quantification in
quantitative real-time PCR (qPCR). *Biomol Detect Quantif* 2017;12:1–6.
Guenther WC. Sample size formulas for normal theory t tests. *Am Stat* 1981;35:243–244.
Hellemans J et al. qBase relative quantification framework and software. *Genome Biol*
2007;8:R19.
Holm S. A simple sequentially rejective multiple test procedure. *Scand J Stat* 1979;6:65–70.
Iglewicz B, Hoaglin DC. *How to Detect and Handle Outliers.* ASQC 1993.
Klymus KE et al. Reporting the limits of detection and quantification for environmental DNA
assays. *Environmental DNA* 2020;2:271–282.
Kralik P, Ricchi M. A basic guide to real time PCR (definitions and parameters). *Front
Microbiol* 2017;8:108.
Kramer CY. Extension of multiple range tests to group means with unequal numbers of
replications. *Biometrics* 1956;12:307–310.
McCall MN et al. On non-detects in qPCR data. *Bioinformatics* 2014;30:2310–2316.
Mestdagh P et al. A novel and universal method for microRNA RT-qPCR data normalization.
*Genome Biol* 2009;10:R64.
Miller JN, Miller JC. *Statistics and Chemometrics for Analytical Chemistry*, 6th ed. 2010, eq. 5.9.
Ririe KM, Rasmussen RP, Wittwer CT. Product differentiation by analysis of DNA melting curves
during the polymerase chain reaction. *Anal Biochem* 1997;245:154–160.
Ruijter JM et al. Removal of between-run variation in a multi-plate qPCR experiment. *Biomol
Detect Quantif* 2015;5:10–14.
Ruiz-Villalba A, Ruijter JM, van den Hoff MJB. Use and misuse of Cq in qPCR data analysis and
reporting. *Life* 2021;11:496.
Ståhlberg A, Kubista M. The workflow of single-cell expression profiling using quantitative
real-time PCR. *Expert Rev Mol Diagn* 2014;14:323–331.
Taylor S et al. A practical approach to RT-qPCR — publishing data that conform to the MIQE
guidelines. *Methods* 2010;50:S1–S5.
Untergasser A et al. Web-based LinRegPCR. *BMC Bioinformatics* 2021;22:398.
Welch BL. The generalization of "Student's" problem. *Biometrika* 1947;34:28–35; On the comparison
of several mean values. *Biometrika* 1951;38:330–336.
