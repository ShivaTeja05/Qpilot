# Method card: which efficiency turns Cq into quantity (the `efficiency` choice)

**What it answers.** Does a conclusion depend on which amplification efficiency is used to turn each well's Cq into a starting quantity? qPilot uses LinRegPCR's mean efficiency of each assay on each plate, as the LinRegPCR authors recommend. Other choices are defensible or common: each well's own efficiency, one efficiency per assay over all its plates, an efficiency assumed to be 2.0 (the 2^−ΔΔCq assumption), or the efficiency of a dilution series. None of them is the correct one by default; this choice makes the dependence visible instead of hiding it in preprocessing.

**Opt-in.** The choice is tested only when a person asks for it: in Studio, Results → "Also test efficiency models" proposes it (the rule proposes, the engine checks it with `D-AXIS`, a person accepts); on the command line, `qpilot run --efficiency all` (or a list such as `per_well,assumed_2`). The request is part of the confirmed design (`StudyDesign.axes`, saved as `study_design.json`), so the study id names it, `qpilot verify` checks the proposal that asked for it and `qpilot rerun` reproduces it. Without the request the analysis, its grid and every locked demo number are exactly as before.

**References.** Ruijter JM et al. Amplification efficiency: linking baseline and bias in the analysis of quantitative PCR data. *Nucleic Acids Res* 2009;37(6):e45 (LinRegPCR, N0 = Nq / E^Cq, mean efficiency per amplicon). Livak KJ, Schmittgen TD. *Methods* 2001;25(4):402–408 (the 2^−ΔΔCq method, E = 2). Standard curve: E = 10^(−1/slope). Science spec: `agent-bus/contracts/scientist-spec-numbers.md` §1.

**Implementation.** `qpilot/qpcr/axes/efficiency.py` (`universe`, `standard_curves`, `unavailable`, `variance_of_e`, `METHOD_CARD`); the axis registry `qpilot/qpcr/axes/__init__.py`; the dimension in `qpilot/qpcr/space.py::QpcrSpace` (matrix stage, memoised per option); screening, the card and its facts in `qpilot/qpcr/study.py`; the Studio proposal in `qpilot/studio_service.py::Studio.propose_axis` and its check in `qpilot/qpcr/design_checks.py::axis_check`.

| Option | Efficiency used for a well | Notes |
|---|---|---|
| `linregpcr` (primary) | LinRegPCR's mean efficiency of the assay on that plate | the per-well table's quantity is passed through untouched, never rebuilt |
| `per_well` | the well's own efficiency | a study well whose own efficiency is not finite or outside LinRegPCR's valid range (1.0, 2.3) is **left out** (not counted as a non-detect), and counted (`f_n_eff_excluded_per_well`) |
| `amplicon_mean` | the assay's LinRegPCR mean over all its plates, weighted by study wells | not applicable when every assay is on one plate (it would be LinRegPCR's own) |
| `assumed_2` | 2.0 | common practice, not measured |
| `standard_curve` | 10^(−1/slope) of Cq against log10 quantity over the plate's standards | needs at least three levels with a Cq; assays without a curve keep the primary and are named (`f_eff_std_fallback`) |

| Step | Definition |
|---|---|
| Rebuild | log2 N0 = log2 Nq − Cq · log2 E, where log2 Nq is the median over the plate's wells of the assay of log2(N0 · E_mean^Cq) (LinRegPCR's common threshold; CV 0.07 % on the demo). No curve is analysed again |
| What stays | A well without a quantity under LinRegPCR has none under any option: the model changes how much was there, never whether something amplified |
| Screening | Each option is tried alone from the primary analysis. The choice enters the grid only if some option flips a conclusion or moves a log2 fold change by more than 0.5; otherwise it is held at the primary and reported (`f_axis_efficiency`, `f_screen_efficiency*`) |
| Card | `numbers.efficiency_model`: one option per tested model, recommended = LinRegPCR's mean; human-only when an option flips a call. Flip count per option: genes whose call changes when only this choice changes (`f_n_flipped_eff_<option>`) |

**On the demo study** (all options requested; `amplicon_mean` does not apply: one assay per plate): the grid grows from 186 to 744 analyses (2 976 in Studio, with the amplification-call rules). Each well's own efficiency changes 5 of 58 calls (CAMTA2, DPYSL3, PAICS, PRKACB_bis, SLC25A5) and leaves out 9 study wells; E = 2.0 changes 4 (CAMTA2, IGSF4, PAICS, PRKACB_bis); the dilution series changes 3 (DPYSL3, PAICS, SLC25A5); 6 genes in all. NTRK1's fold change moves ×0.39 (per well) and ×0.47 (E = 2.0) without changing its call. Every flip sits near the 2-fold line (fold change 1.9–2.1 or 0.49–0.52).

**What is not claimed.** That any efficiency is "correct", or that a gene whose call changes is wrong: the card says what the answer depends on. The delta-method widening of the confidence interval for the uncertainty of the efficiency itself (`variance_of_e`, spec §2) is computed by the engine but not shown yet.

**Validation.** `tests/numbers/test_efficiency.py` (the primary is passed through; the rebuild is exact on a toy table; options that do not apply), `tests/numbers/test_efficiency_demo.py` (the demo flips above, the card and its facts, determinism), `tests/numbers/test_design_axes.py` (the design, the Studio proposal and its check, `qpilot verify` / `qpilot rerun`, the CLI flag).

**Licence.** Apache-2.0 (qPilot's own code).
