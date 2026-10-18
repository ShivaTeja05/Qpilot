# qPilot Studio: numbers measured on the demo before building

Measured on 17 Oct 2026 from the cached Vermeulen RDML (`data_vermeulen_raw.rdml`,
sha256 `bc1d233e…`) with qPilot's own engine (LinRegPCR per plate, primary analysis: all five
reference genes, MYCN-high = top 15 %, undetermined wells dropped, Welch on log2, call rule
p < 0.05 and at least two-fold). These are the acceptance oracles for the Studio build; every
gate in `qPilot-STUDIO-PRISM-PLAN.md` is checked against this table, not against the plan's
prose. Where the plan's number did not reproduce, the measured number wins and the difference
is stated.

| Plan step | What | Plan says | Measured | Status |
|---|---|---|---|---|
| 2.7 | ΔΔCq in Excel (E = 2.0, engine Cq), Welch on log2: conclusions that differ from the engine (of 58) | 4 (CAMTA2, IGSF4, PAICS, PRKACB_bis) | 4, same genes | reproduces |
| 2.7 | 2^-ΔΔCq per sample (calibrator = mean ΔCq of the "rest" group), Welch on the linear scale, fold = ratio of group means | 14 | 14 | reproduces |
| 2.7 | the same with Student's (equal-variance) t test | 21 | 21 | reproduces |
| 4.1 | "Cq > 35 = not detected" (engine Cq; n0 set to undetermined; then the primary analysis) | 10 | 10: CLSTN1, EPN2, MRPL3, NTRK1, PAICS, PLAT, PRKACB_bis, PTPRF, PTPRH, SLC25A5 | reproduces |
| 4.1 | Cq > 38 | 7 | **3**: CLSTN1, EPN2, PLAGL1 | does not reproduce |
| 4.1 | Cq > 40 | 2 | **1**: CLSTN1 | does not reproduce |
| 2 | STD_15 wells (15-copy standard, by label) with Cq > 35 | 90 of 192 | 90 of 192 | reproduces |
| 6.2 | Exclude ODC1's highest sample (1496, MYCN-high) | 3.59× → 3.32×, ODC1 stays up, 0 of 58 change | 3.590× → 3.319×, p 2.3e-8 → 2.1e-8, stays up | reproduces |
| 3.3 | `comp_XX_conc_Y` (technical_datasets / competimer_set): R² of Cq vs log10 dilution, levels 0.0625–16 | 0.983–0.999 at six of seven competimer levels | 0.983–0.999 at six (comp 00, 05, 10, 20, 30, 40); comp 50 = 0.707 | reproduces |
| 3.3 | Top level (conc 64): wells with a Cq | 0 of 21 | 0 of 21 called amplified by LinRegPCR; 7 of 21 carry a late TD0 (39.9–42.0) with `amplification = False` | reproduces when "with a Cq" means "amplified" |
| 3.3 | Efficiency from the slope of each competimer level | — | 1.86, 1.80, 1.76, 1.64, 1.47, 1.40, 1.38 (comp 00 → 50): all outside 90–110 % | warning, not a contradiction (plan rule) |
| 3.2 | Samples declared in the file | 425 (409 unknown, 9 NTC, 7 standards) | **427** (409 unkn, 9 ntc, 9 std): STDA15…STDA15000 (4) + STD_15…STD_150000 (5) | does not reproduce; 427 is the file's own count |
| — | competimer_set NTC wells | — | 21; LinRegPCR notes "TD0 found in negative control" on the 3 comp_50_NTC wells | for the NTC check |
| — | Unknown wells with `amplification = False` but an n0 (biomarker set) | — | 11 of 23,424 | the `linregpcr` rule keeps today's behaviour (n0 present) |

Definitions used above, which the engine code must follow exactly:

- **"Differs from the engine"** compares each gene's conclusion (up / down / none) under the
  route with its conclusion in the engine's primary cell; groups are always the engine's fixed
  MYCN-high / rest split.
- **Cq cut-off rule `cq_le_X`**: a well whose engine Cq is greater than X becomes undetermined
  (n0 = NaN) for every target, reference genes included; then the analysis runs unchanged.
  The flip count varies only this choice from the primary cell (the engine's `impact`).

## Measured while building (17 Oct 2026)

| What | Measured | Where it is checked |
|---|---|---|
| Curve Judge, held-out accuracy on Brintz et al.'s curves (n = 33,043) | 0.9968 (sensitivity 0.9932, specificity 0.9979); the paper reports 0.996 | `qpilot/models/curve_judge/metrics.json` |
| Curve Judge transfer to the demo (LightCycler 480, SYBR, no ROX), pre-registered gate committed before any demo prediction (`94f2b48`) | standards 960 / 960 called amplified; agreement with LinRegPCR at Cq < 30 = 99.32 % (16,043 / 16,153); NTCs: model 17, LinRegPCR 23 of 192 | `qpilot/models/curve_judge/transfer.json` |
| Where the Curve Judge disagrees with LinRegPCR on the demo's study wells | 166 wells; only ALUsq's (110 early curves, Cq 9.5–13.5, a reference gene) could change a conclusion; LinRegPCR fitted a complete curve in every one, so `D-CURVE` marks all 110 `contradicted` | `tests/studio/test_service_demo.py` |
| The declared standard series per plate (`STD_*`) | consistent on 63 of 64 plates; contradicted on the ALUsq plate (R² 0.694) | `tests/engine/test_design_checks.py` |
| `water` NTC wells of the biomarker set that amplify | 23 of 192, all late (closest 11.6 cycles after the plate's unknowns) | `tests/engine/test_design_checks.py` |
| The demo entered as a confirmed **groups** design (MYCN-high / rest named per tumour) | identical fold changes and p-values to the expression-defined preset (ODC1 3.590×) | `tests/prism/test_designed_export.py` |
| Studio's grid with the amplification-call axis | 744 cells (186 × 4 rules), the full sweep in about 0.35 s | `tests/engine/test_amp_call.py` |
| The Curve Judge's calls applied to every study well **without a person** (what Studio never does) | 3 of 58 conclusions change (CLSTN1, EPN2, IGSF4), all through the ALUsq blind spot: without the ALUsq wells, 0 change. Each of those wells reaches the scientist as a proposal the engine check marks `contradicted` | measured with `Studio._primary_conclusions` on the confirmed demo design |

## Does a bigger model help? Measured on a Kaggle GPU (18 Oct 2026)

The full harness (`qpilot harness run --studio`: 30 "Ask your data" items and 21 Studio items, typing over the demo's 427 samples twice) was run with the model on the same machine as qPilot: the laptop (Apple M3 Pro, Ollama) for qwen2.5:7b, and a private Kaggle notebook (NVIDIA Tesla T4 ×2, Ollama 0.40.6, per-call timeout raised to 600 s so the model is never cut off) for the larger models. Same code snapshot for the larger models (`f652bca`); only the public demo dataset was used.

| Profile | Typing accuracy | Control recall | Ban violations / false accepts / invented citations | Injection effect | Ask items correct (by the model alone) | Harness time |
|---|---|---|---|---|---|---|
| Rules only (no model) | 839/854 (98.2 %) | 18/18 | 0 / 0 / 0 | 0 | 30/30 (—) | 45 s |
| qwen2.5:7b, laptop | 834/854 (97.7 %) | 18/18 | 0 / 0 / 0 | 0 (re-run after the harness fix) | 30/30 (17/20) | about 70 min |
| qwen2.5:14b, Kaggle T4 | 839/854 (98.2 %) | 18/18 | 0 / 0 / 0 | 1 (a model proposal that differed between the clean and planted runs; never applied) | 27/30 (14/20) | 74 min |

What this says, without overreading three runs on one dataset:

- **The deterministic rules carry the typing accuracy.** Neither model raises it above the rules on this file; the 7B lowers it slightly (it proposed some unknowns as NTCs, which a person sees as contradicted proposals), the 14B leaves it unchanged.
- **Safety held for every model**: no control was missed, nothing forbidden got through, nothing was accepted without a person, no citation was invented.
- **The 14B was worse at saying "not in this study"** (3 refusal items failed) and found a gap: for the amplification-call card it produced an explanation that passed the number validator while leaving out the very counts the card is about, where the 7B's failed validation and the template answered. Explanations must now cite the card's key counts or the template is used.
- **Where a model can still add value** is reading what rules cannot: free-text sentences and messy sheets that name groups and units. The demo's design is expression-defined, so it does not exercise that; a lab file with a group sheet would.
