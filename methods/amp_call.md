# Method card: which curves count as amplified (the `amp_call` choice)

**What it answers.** Does the conclusion depend on which wells are counted as amplified? LinRegPCR decides this from the shape of each curve; many labs apply a Cq cut-off on top ("Cq above 35 = not detected") before any further calculation. qPilot makes that cut-off a visible choice, one dimension of the robustness grid, instead of a silent preprocessing step.

**References.** LinRegPCR's own call: Ruijter et al., *Nucleic Acids Research* 37(6): e45 (2009); Untergasser et al., *BMC Bioinformatics* 22: 398 (2021) (see [`linregpcr.md`](linregpcr.md)). The Cq cut-offs are common laboratory practice, not a published method; MIQE asks that the cut-off be reported, not that one be used.

**Implementation.** `qpilot/qpcr/amp_call.py` (`RULES`, `apply_rule`, `well_calls`, `disagreements`, `screen_amp_call`, `METHOD_CARD`); the dimension lives in `qpilot/qpcr/space.py::QpcrSpace` and the card in `qpilot/qpcr/study.py`.

| Rule | A well counts as amplified when | Label |
|---|---|---|
| `linregpcr` (recommended, default) | LinRegPCR gives it a starting quantity (`n0`); exactly the engine's behaviour before the dimension existed | LinRegPCR's own call |
| `linregpcr_call` (offered, not the default) | LinRegPCR gives it a quantity **and** calls it amplified: a study well it notes "no amplification" (or a standard it excludes as "no amplification in positive control") is undetermined even though it has a quantity and a Cq (a flat curve). Negative controls are left as they are (their quantity is the contamination signal G-NTC-1 weighs); a file without LinRegPCR's call (Cq values only) falls back on the quantity | LinRegPCR's call, its "no amplification" respected |
| `cq_le_40` | it has a quantity **and** its engine Cq (LinRegPCR's TD0) is at most 40 | — |
| `cq_le_38` | the same with 38 | — |
| `cq_le_35` | the same with 35 | "common, not recommended" |

| Step | Definition |
|---|---|
| Applying a rule | Every well that does not count gets `n0` = NaN (undetermined), for **every** target, control genes included. No row is removed, so the samples in the analysis never change; then the analysis runs unchanged (the `undetermined` choice then drops or caps those wells) |
| A person's call | `StudyDesign.well_calls["<run_id>/<well>"]`: `false` makes the well undetermined under every rule; `true` keeps its quantity under every rule. A well without a quantity never counts |
| Groups | Fixed from the primary analysis (primary control genes, primary rule); changing the rule changes only which wells count |
| Flip count per rule | Genes whose conclusion differs from the primary cell when only this choice changes (facts `f_n_flipped_amp_<rule>`) |
| Screening (W3 §4.2) | Each rule is tried alone from the primary cell. The dimension enters the grid only if some rule flips a conclusion or moves a log2 fold change by more than 0.5; the screening result is reported as facts either way (`f_screen_amp_*`) |
| Options | The legacy default offers `linregpcr` only (no dimension; the demo grid stays 186 cells). Studio offers all four (`STUDIO_AMP_CALLS`), 744 cells on the demo |

**On the demo study (all four rules, primary = `linregpcr`).** Cq ≤ 35 changes 10 of 58 conclusions (CLSTN1, EPN2, MRPL3, NTRK1, PAICS, PLAT, PRKACB_bis, PTPRF, PTPRH, SLC25A5); NTRK1 loses its "down" call. Cq ≤ 38 changes 3 (CLSTN1, EPN2, PLAGL1) and Cq ≤ 40 changes 1 (CLSTN1). 90 of the 192 wells of the 15-copy standard (STD_15) have a Cq above 35. The plan's prose said 7 and 2 for the 38 and 40 lines; those did not reproduce, and the definitions were not tuned to hit them (`docs/studio-measured.md`). The 744-cell sweep takes about a third of a second.

**LinRegPCR's own "no amplification" (science review J1, applied 29 Oct 2026).** rdmlpython's LinRegPCR returns a starting quantity and a TD0 Cq for some wells it marks *no amplification* (note "no amplification; baseline error", "only 3 values in log phase"). The default rule counts them (it is the engine's behaviour from before the dimension existed, and the demo's locked numbers rest on it); the `linregpcr_call` rule does not. It is offered, not switched on: Studio's curves stage lists it as an alternative of the call-rule proposal whenever the file has such a well, with how many there are ("LinRegPCR calls 11 wells of this file 'no amplification' …"), and the Curves view shows each well's call under it. A person who chooses it makes it the analysis's rule (primary); the grid then tests LinRegPCR's quantity alone and the three Cq lines against it, so whether it matters is shown, not assumed. Measured: on the QuantStudio 7 Pro eDNA sample plate (corpus) 7 unknown wells are such wells (one at Cq 19.1 with 2.5 × 10⁶ copies); on the demo 11 of 24 576 wells (most at Cq > 39 with fewer than ten copies; one MTSS1 well at Cq 23.8 with its own efficiency 1.20), and counting them as undetermined changes **no** call, the largest fold-change move being 0.069 log2 (CDH5), so the screen keeps the axis out of the legacy grid (186 cells). Absolute quantification applies LinRegPCR's call to standards and unknowns always ([`absolute_quantification.md`](absolute_quantification.md)): a standard curve is never fitted through a well its own curve analysis calls flat. The review's option (b), making this the default and regenerating the demo's locks, is left to the next planned regeneration. A person's well call has the last word under every rule.

**What is not claimed.** A Cq cut-off is not a limit of detection: it is not derived from a dilution series, and the same Cq means different amounts for assays of different efficiency. No rule here uses melt curves or a kinetic outlier test. The learned call (the Curve Judge) is not part of this card: `register_learned` is the hook for it, to be called only after its transfer validation passed; nothing registers it today.

**Validation.** `tests/engine/test_amp_call.py` (rules on a hand-built table; the demo flip counts, the NTRK1 call and the STD_15 count; grid size and sweep time; the card's template passes the "no naked numbers" validator; the strict rule on a hand-built table, on the eDNA sample plate's 7 wells and on the demo's 11, no call changed); `tests/studio/test_service_demo.py` (the curves stage offers it on the demo).

**Licence.** Apache-2.0 (qPilot's own code).
