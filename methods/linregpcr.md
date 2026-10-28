# Method card: LinRegPCR curve analysis (amplification curve → starting quantity)

**What it answers.** For every well: how much template was there at the start (N0), read from the whole amplification curve and the amplification efficiency measured on the plate, instead of assuming that every cycle exactly doubles the product.

**References.**
- Ruijter JM, Ramakers C, Hoogaars WMH, et al. *Amplification efficiency: linking baseline and bias in the analysis of quantitative PCR data.* Nucleic Acids Research 37(6): e45 (2009).
- Ruijter JM, Pfaffl MW, Zhao S, et al. *Evaluation of qPCR curve analysis methods for reliable biomarker discovery: bias, resolution, precision, and implications.* Methods 59(1): 32–46 (2013).
- Untergasser A, Ruijter JM, et al. *Web-based LinRegPCR: application for the visualization and analysis of (RT)-qPCR amplification and melting data.* BMC Bioinformatics 22: 398 (2021).

**Implementation.** Not ours. The method is `Run.linRegPCR` in `qpilot/vendor/rdmlpython/rdml.py`, the RDML consortium's rdmlpython (MIT), copied unchanged at commit `fce7a44`. A test fails if the file's SHA-256 changes. `qpilot/qpcr/curves.py::analyse_run` calls `run.linRegPCR(updateRDML=False, saveResultsCSV=True)` once per plate with the library's default settings, then reads the result table **by column name**.

| Step | What LinRegPCR does (from the vendored source) | qPilot column |
|---|---|---|
| Baseline | Estimates each well's background fluorescence and subtracts it; wells where this fails are flagged | `baseline` |
| Cq | **TD0**: the cycle where the third derivative of the fluorescence curve crosses zero, interpolated between cycles. It is a point on the curve's own shape, not the crossing of a fluorescence threshold | `cq` |
| Individual efficiency | 10^slope of log10(baseline-corrected fluorescence) over the window of linearity in the exponential phase (at most 9 cycles); `R2` is the quality of that fit | `eff_indiv`, `r2` |
| Mean efficiency per gene and plate | Mean of the individual efficiencies, leaving out negative controls, wells without amplification, wells without a plateau, and outliers (while the efficiencies are significantly skewed, the most extreme one is removed by Grubbs' test, α = 0.05) | `eff_target`, `eff_target_sd` |
| Starting quantity | `Ncopy = nAmpli / E_mean^TD0`, where `nAmpli` is the amplicon amount LinRegPCR derives from the reaction's limiting reagent and volume. Uses the gene's **mean** efficiency, not the well's own, as the method recommends; set only when 1.0 < E < 2.3 | `n0` |
| Quality flags | *Amplification*: fluorescence rises over the four cycles before TD0 and the well's efficiency is > 1.4. *Plateau*: the final fluorescence is at least 5× below what unbroken exponential growth would have reached | `amplification`, `plateau` |

**Settings (the library defaults; recorded in every cache key).**

| Setting | Value | Effect |
|---|---|---|
| `excludeEfficiency` | `"outlier"` | Skewness test + Grubbs' test, as above |
| `excludeNoPlateau` | `True` | Wells without a plateau do not count towards the mean efficiency |
| `maxCycExpPhase` | `9` | Longest window of linearity, in cycles |
| `pcrEfficiencyExl` | `0.05` | Only used by the `"mean"` exclusion mode, so inactive with these defaults |
| `ignoreExclusion` | `False` | Exclusion marks already in the RDML file are respected |

**What qPilot adds around it (not part of LinRegPCR).** A hardened loader (no XML entities, no network, size caps) opens the file. Results are parsed by column name, and names are checked at the boundary. The `_20YYMMDD` date token is stripped from gene names (`target_raw` keeps the original). A well with no TD0, or with N0 ≤ 0, becomes *undetermined* (`NaN`); downstream it is either dropped or capped, and that choice is one dimension of the robustness grid. The per-well table is cached by the input file's SHA-256 plus these settings, so 64 plates take seconds once and a fraction of a second after that.

**Multiplex plates (several dyes in one well).** LinRegPCR, as vendored, gives each reaction's volume only to the *first* curve of a well (`reactVol` is filled once per reaction but read once per curve), so `nAmpli`, and with it `Ncopy`, is 0 for every other dye of a multiplex well: the HEX/VIC reference of a TaqMan duplex came out *undetermined*. qPilot does not edit the vendored code: `curves.analyse_run` analyses each dye of a multiplex plate as a plate of its own (`curves.channels`: the dye's curves in a copy of the run, with the file's declarations; a dye that still has two curves in one well is split by target) and puts the rows back in the file's order. Each curve then gets its own baseline, efficiency, Cq, N0 and amplification call, exactly as LinRegPCR gives them on that dye's export alone: fluorescence in different dyes is on different scales, and LinRegPCR shifts every curve of a plate by the plate's brightest curve before it fits a baseline. A plate with one curve per well (the demo) takes the old path, unchanged. Measured on the corpus (curves with an N0 before → after): LightCycler 96 bACTXY X/Y/IPC 0/0/0 → 12/12/14; QuantStudio 7 Pro IPC 0 → 95; CFX Maestro 4-plex IEC and N_covid 0 → 96; 7500 nCoV 0 → 21. A test (`tests/engine/test_multiplex.py`) fails if an upstream update fixes the volume, so the two can be compared again. See [docs/multiplex.md](../docs/multiplex.md).

**What we changed from the published method.** Nothing in the method. We vendor the commit rather than `pip install rdmlpython`, because the last PyPI release (1.7.2) cannot read RDML 1.4. On a multiplex plate qPilot calls the method once per dye (above).

**Validation.** `qpilot validate` compares this step with the RDML consortium's own published results for the demo study's dilution standards, in three lines: N0 against RDML-Tools, the dilution-series bias against LinRegPCR 2013, and Cq against LinRegPCR 2013. The numbers are in [`validation/validation_table.md`](../validation/validation_table.md), which the script generates. The Cq line shows a near-constant shift of about one cycle. LinRegPCR 2013 reported Cq where each curve crossed a common fluorescence threshold; the current code reports TD0, a different point on the same curve. qPilot's comparisons use N0, never Cq.

**Limits.**
- Needs the raw amplification curves in the RDML file. A file that holds only Cq values or melt curves cannot be re-analysed.
- One mean efficiency per gene per plate. On the demo, each plate holds one gene, so each mean comes from a whole plate; a plate with few wells per gene gives a noisier mean.
- Melt curves are not analysed, and there is no kinetic outlier test.
- Validated on one published study from one instrument platform (LightCycler 480, SYBR Green I).
- Research use only.
