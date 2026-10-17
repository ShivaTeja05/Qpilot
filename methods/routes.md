# Method card: the usual route from the instrument to Prism

**What it answers.** How many conclusions would change if the same plates went the usual way, ΔΔCq in a spreadsheet and a t test in GraphPad Prism, instead of through qPilot's engine? The routes are reported next to the engine's results; they never decide a conclusion.

**Reference.** Livak KJ, Schmittgen TD. *Analysis of relative gene expression data using real-time quantitative PCR and the 2^-ΔΔCT method.* Methods 25(4): 402–408 (2001).

**Implementation.** `qpilot/qpcr/routes.py::compare_routes`, deterministic engine code; called by `qpilot/qpcr/study.py` when the settings ask for the Studio facts (any design other than the legacy default).

| Step | Definition |
|---|---|
| Input | The engine's Cq (LinRegPCR's TD0) of the study wells; technical replicates averaged per biological unit (mean Cq). Wells a person excluded or called not amplified are left out; wells without a Cq are skipped |
| Samples, groups, control genes | The engine's own: the units of its matrix, its groups fixed from the primary analysis, its primary control genes |
| ΔCq | `Cq(gene) − mean(Cq of the control genes)` per unit; units missing a control gene are skipped |
| `ddcq` | Efficiency assumed 2.0: log2 relative quantity = −ΔCq; Welch's t test on that log2 scale; log2 fold change = difference of the group means |
| `linear_welch` | 2^-ΔΔCq per unit, with the calibrator = mean ΔCq of the comparison group ("rest"); Welch's t test on that linear scale; fold change = ratio of the group means |
| `linear_student` | The same with Student's equal-variance t test (Prism's default before version 10) |
| Conclusion | The engine's call rule: up or down only if p < 0.05 and at least two-fold; fewer than two values in a group gives "none" |
| Differs | A gene's route conclusion differs from its conclusion in the engine's primary cell |

Facts: `f_n_differ_route_ddcq`, `f_n_differ_route_linear_welch`, `f_n_differ_route_linear_student` and the gene lists `f_genes_differ_route_<route>`.

**On the demo study.** Of 58 genes, `ddcq` differs for 4 (CAMTA2, IGSF4, PAICS, PRKACB_bis), `linear_welch` for 14 and `linear_student` for 21 (`docs/studio-measured.md`). The only change in `ddcq` is the assumed efficiency; the linear routes also test on a skewed scale.

**What is not claimed.** These are three common ways, not every way a lab works; other tests Prism offers (for example a test on log-transformed values) are not computed here. No route applies a Cq cut-off; that choice is the `amp_call` dimension ([`amp_call.md`](amp_call.md)).

**Validation.** `tests/engine/test_routes.py` (hand-computed toy values; the demo counts and gene list).

**Licence.** Apache-2.0 (qPilot's own code).
