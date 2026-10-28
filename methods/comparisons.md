# Method card: several comparisons, multiple-comparison correction and paired designs

**What it answers.** With three or more groups (treatments, time points, genotypes), is a gene
higher or lower in each comparison a person asked for, by how much, and how sure, once the
number of comparisons is taken into account? With a paired design (one donor, animal, passage or
batch in every group), the same questions within each pair.

**Implementation.** `qpilot/qpcr/space.py` (`ComparisonSpec`, `QpcrSpace.evaluate_all`,
`paired_arrays`, `pooled_arrays`, `comparison_grid`, `QpcrSpace.focus`),
`qpilot/qpcr/contrast.py` (`holm`, `bh`, `paired_t`), `qpilot/qpcr/multiplicity.py`
(`dunnett_adjusted`, `tukey_adjusted`, `pooled`), `qpilot/qpcr/study.py`
(`_design_comparisons`, `_comparison_outcomes`, `_card_views`); the plan is
`StudyDesign.comparisons` (`qpilot/schemas_studio.py::ComparisonPlan`), the result
`StudyResult.comparisons`.

| Step | Definition |
|---|---|
| Comparisons | A person's plan: each group against one control group (`vs_control`), every pair (`all_pairs`) or a list (`chosen`); the first is listed first everywhere |
| Input per unit | As for one comparison: `log2(n0_gene) − mean(log2(n0_controls))` per biological unit, technical replicates averaged first |
| Unpaired test | Welch's t-test per comparison (no equal-variance assumption, no pooled variance across groups) |
| Paired test | Pairs from `SampleDesign.pair`; the one-sample t-test of the within-pair differences (ΔΔCq within the pair), n = complete pairs, df = n − 1; a pair with a missing value for a gene is left out of that gene only |
| Refusals | Every group needs two units (two complete pairs when paired); a paired design needs each pair key once in each group of a comparison and every unit to have a key; otherwise the design is refused with the key and group named |
| Correction within a gene | A person's choice. **Holm** (any pattern): the step-down method across the gene's comparisons (family = the comparisons with a p-value), each comparison keeping its own Welch (or paired) test. **Dunnett** (each group against one control, unpaired): one variance per gene pooled over every compared group, a t-test per comparison with df = N − G, and the single-step adjusted p = P(max\|T\| ≥ \|t\|) of the multivariate t with correlations λᵢλⱼ, λ = √(n/(n + n₀)). **Tukey** (every pair, unpaired): the same pooled t-tests and p = P(Q ≥ \|t\|√2) of the studentized range of the G groups (Tukey–Kramer). **None**. Dunnett's and Tukey's probabilities are integrated with fixed Gauss rules (deterministic, ≤ 1e-7 from a high-order rule); a comparison a gene cannot test is not in its family. The call uses the corrected p |
| Across genes | Benjamini–Hochberg q-values over the genes of each comparison; shown, never used for a call |
| Conclusion rule | **up** if corrected p < 0.05 and fc ≥ 2; **down** if corrected p < 0.05 and fc ≤ 0.5; otherwise **no call** |
| Robustness | Every grid cell evaluates every comparison from the same relative quantities and applies the correction inside the cell; each comparison gets its own "holds" share, flip map and grade |
| Decision Cards | A card's choice applies to every comparison; its impact counts a changed call in any comparison (a card that changes a call only in a later comparison waits for a person like any other), and each option shows its effect per comparison |
| Trace | Follows the comparison picked; every what-if (a sample set aside alone, two together, a reference read as expected) recomputes every comparison of the samples' groups and the correction, so Trace's call is the engine's corrected call; it shows the corrected p (named) and q, and the uncorrected p only as "p before correction". A paired comparison is not traced (a sample counts only with its pair) |
| Audit | The robustness audit (`sim/`) audits the first comparison alone, and runs only when the correction changes none of its calls at the planned analysis (so its baseline reproduces qPilot's); it refuses a paired comparison or a pooled-variance correction in words |
| Any difference | Welch's one-way ANOVA per gene across the plan's groups (three or more, unpaired designs), at the planned analysis; for orientation, never a call |
| Not measured | A unit with no well of a gene is kept for the genes it has and left out of that gene only (`f_not_measured_*` facts); it is never treated as undetermined (never capped) |

**Checked against.** `scipy.stats.ttest_ind(equal_var=False)`, `ttest_rel` and
`f_oneway(equal_var=False)` on the engine's own per-unit values; `statsmodels.stats.multitest.multipletests` (`holm`, `fdr_bh`)
(`tests/engine/test_comparisons.py`); `scipy.stats.dunnett` (quasi-Monte Carlo, within 1e-3),
`scipy.stats.tukey_hsd` and `studentized_range` (1e-8) (`tests/engine/test_multiplicity.py`),
also on a real study (`tests/web/test_compare_real_lab.py`, K. phaffii UPR, Dunnett against one
condition).

**What is not claimed.** The omnibus ANOVA gates nothing (no "ANOVA first, then post hoc" rule);
Dunnett and Tukey assume equal variances on the log2 scale (Holm with Welch tests does not), and
neither is offered for a paired design; confidence intervals are for each comparison alone (not
Dunnett's or Tukey's simultaneous intervals); no mixed model for repeated measures beyond the
paired difference; the robustness audit audits the first comparison only, and Trace does not
follow a paired comparison.

**Citations.** Welch BL (1947) Biometrika 34:28–35. Holm S (1979) Scand J Stat 6:65–70.
Benjamini Y, Hochberg Y (1995) J R Stat Soc B 57:289–300. Dunnett CW (1955) J Am Stat Assoc
50:1096–1121. Tukey JW (1953) The problem of multiple comparisons (Princeton); Kramer CY (1956)
Biometrics 12:307–310.

**How to ask for it.** In Studio, accept the groups: with three or more, a rule proposes each
group against the one control-like group name (control, vehicle, untreated, WT, mock, 0 h, day 0
…) or, without one, every pair (up to five groups), Holm-corrected; a sheet column naming donors,
animals or patients that spans groups is proposed as a pairing. A person edits or accepts, or
sets the comparisons themself on the Design page (Comparison → Several comparisons: the pattern,
the control, the correction and the pairing). From the command line (`qpilot run FILE --design study.yaml --samples sheet.csv`, sheet column `pair`):

```yaml
mode: groups
comparison: {group_a: Drug A, group_b: Control}
comparisons:
  pattern: vs_control
  control: Control
  correction: holm        # or: dunnett (vs_control), tukey (all_pairs), none
  pair_by: donor          # optional: a paired design (the sheet's 'pair' column)
  comparisons:
    - {group_a: Drug A, group_b: Control}
    - {group_a: Drug B, group_b: Control}
```
