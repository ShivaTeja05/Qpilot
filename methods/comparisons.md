# Method card: several comparisons, multiple-comparison correction and paired designs

**What it answers.** With three or more groups (treatments, time points, genotypes), is a gene
higher or lower in each comparison a person asked for, by how much, and how sure, once the
number of comparisons is taken into account? With a paired design (one donor, animal, passage or
batch in every group), the same questions within each pair.

**Implementation.** `qpilot/qpcr/space.py` (`ComparisonSpec`, `QpcrSpace.evaluate_all`,
`paired_arrays`, `comparison_grid`), `qpilot/qpcr/contrast.py` (`holm`, `bh`, `paired_t`),
`qpilot/qpcr/study.py` (`_design_comparisons`, `_comparison_outcomes`); the plan is
`StudyDesign.comparisons` (`qpilot/schemas_studio.py::ComparisonPlan`), the result
`StudyResult.comparisons`.

| Step | Definition |
|---|---|
| Comparisons | A person's plan: each group against one control group (`vs_control`), every pair (`all_pairs`) or a list (`chosen`); the first is the primary (the Decision Cards describe it) |
| Input per unit | As for one comparison: `log2(n0_gene) − mean(log2(n0_controls))` per biological unit, technical replicates averaged first |
| Unpaired test | Welch's t-test per comparison (no equal-variance assumption, no pooled variance across groups) |
| Paired test | Pairs from `SampleDesign.pair`; the one-sample t-test of the within-pair differences (ΔΔCq within the pair), n = complete pairs, df = n − 1; a pair with a missing value for a gene is left out of that gene only |
| Refusals | Every group needs two units (two complete pairs when paired); a paired design needs each pair key once in each group of a comparison and every unit to have a key; otherwise the design is refused with the key and group named |
| Correction within a gene | Holm's step-down method across the gene's comparisons (family = the comparisons with a p-value); the call uses the corrected p; `none` is a person's choice |
| Across genes | Benjamini–Hochberg q-values over the genes of each comparison; shown, never used for a call |
| Conclusion rule | **up** if corrected p < 0.05 and fc ≥ 2; **down** if corrected p < 0.05 and fc ≤ 0.5; otherwise **no call** |
| Robustness | Every grid cell evaluates every comparison from the same relative quantities and applies the correction inside the cell; each comparison gets its own "holds" share, flip map and grade |
| Not measured | A unit with no well of a gene is kept for the genes it has and left out of that gene only (`f_not_measured_*` facts); it is never treated as undetermined (never capped) |

**Checked against.** `scipy.stats.ttest_ind(equal_var=False)` and `ttest_rel` on the engine's own
per-unit values; `statsmodels.stats.multitest.multipletests` (`holm`, `fdr_bh`)
(`tests/engine/test_comparisons.py`).

**What is not claimed.** No ANOVA or Welch-ANOVA omnibus test; no Dunnett or Tukey procedure
(Holm is valid for any family and conservative for each-vs-control); confidence intervals are
for each comparison alone (not simultaneous); no mixed model for repeated measures beyond the
paired difference; the robustness audit (`sim/`), Trace and the Run Review describe the primary
comparison only.

**Citations.** Welch BL (1947) Biometrika 34:28–35. Holm S (1979) Scand J Stat 6:65–70.
Benjamini Y, Hochberg Y (1995) J R Stat Soc B 57:289–300.

**How to ask for it.** In Studio, accept the groups: with three or more, a rule proposes each
group against the one control-like group name (control, vehicle, untreated, WT, mock, 0 h, day 0
…) or, without one, every pair (up to five groups), Holm-corrected; a sheet column naming donors,
animals or patients that spans groups is proposed as a pairing. A person edits or accepts. From
the command line (`qpilot run FILE --design study.yaml --samples sheet.csv`, sheet column `pair`):

```yaml
mode: groups
comparison: {group_a: Drug A, group_b: Control}
comparisons:
  pattern: vs_control
  control: Control
  correction: holm        # or: none
  pair_by: donor          # optional: a paired design (the sheet's 'pair' column)
  comparisons:
    - {group_a: Drug A, group_b: Control}
    - {group_a: Drug B, group_b: Control}
```
