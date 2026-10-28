# Method card: melt curves of DNA-binding-dye assays (−dF/dT, peaks, the product's Tm, G-MELT)

**What it answers.** For SYBR Green, EvaGreen and other dyes that bind double-stranded DNA: did each well make one product, at the temperature where this assay's product melts? A product loses its dye when it melts, so a well's fluorescence falls most steeply at the product's melting temperature (Tm): the peak of the negative derivative −dF/dT. A second, lower peak is usually a primer-dimer; a peak elsewhere is another product; a peak at the product's Tm in a no-template control means template reached it. The Run Gate's rule G-MELT turns these calls into verdicts and, where they point at study wells, asks the consequence test whether leaving those wells out would change a conclusion; a person decides. A melt peak is a class, never an identification: *a single peak at the correct Tm does not guarantee identification of the intended amplicon* (MIQE 2.0), and nothing in qPilot says "specific" from a melt.

**References.** Ririe KM, Rasmussen RP, Wittwer CT. Product differentiation by analysis of DNA melting curves during the polymerase chain reaction. *Anal Biochem* 1997;245:154–160 (−dF/dT peaks at each product's Tm; primer-dimers melt lower). Untergasser A, Ruijter JM, Benes V, van den Hoff MJB. Web-based LinRegPCR: application for the visualization and analysis of (RT)-qPCR amplification and melting data. *BMC Bioinformatics* 2021;22:398, and its library rdmlpython (MIT, vendored in `qpilot/vendor/rdmlpython`), `Run.meltCurveAnalysis`: the expected-Tm window (`truePeakWidth` 1.0 °C) and the peak cut-off (`peakCutoff` 5 % of the summed peak heights) that G-MELT's defaults take; its exclusion text "no product with expected melting temperature". Bustin SA et al. MIQE 2.0. *Clin Chem* 2025;71:634–651 (item 5.19, specificity). Scientist spec `agent-bus/contracts/scientist-spec-gate.md` (G-MELT and G-NTC-1's melt class).

**Implementation.** `qpilot/qpcr/melt.py` (`read_melt`, `analyse_curve`, `judge`, `judge_assay`, `target_summaries`, `study_melt`); rule G-MELT of the pack `research-default` 1.2.0 (`packs/research-default.yaml`; evaluator `melt_products` and G-NTC-1's `ntc_melt_class` in `qpilot/qpcr/gate_rules.py`); the page's route `GET /api/{studies/{id},sessions/{sid}}/melt` (`qpilot/web/routers/melt.py`); MIQE 2.0 item 5.19 in `qpilot/report/miqe.py`.

**Where the readings come from.** The study's RDML file, `<mdp>` (temperature, fluorescence) under each well's `<data>`. Every connector writes them there: CFX Manager / Maestro "Melt Curve RFU Results" (one column per well; the "Melt Curve Derivative Results" sheet is CFX's own derivative and is not read; "Melt Curve Peak Results" is CFX's own Tm list, used only to check qPilot, below), QuantStudio / ViiA 7 / StepOne "Melt Curve Raw Data" (`Temperature`, `Fluorescence`), LightCycler 480 and 96 melt programs, RDES melt tables, and RDML files that carry melt data. A file without any `<mdp>` is recognised by a streaming scan of its XML and never parsed (0.13 s on the demo's 60 MB XML). Wells, samples and targets are named exactly as the per-well table names them (`run_id/well`; the target with its date token removed), and the sample types are the confirmed design's.

**Per well** (`analyse_curve`; the analysis settings are `MeltSettings`, not pack thresholds).

| Step | What qPilot does |
|---|---|
| Readings | finite pairs only, sorted by temperature; readings at one temperature averaged |
| Enough readings | at least 15, at most 1.0 °C apart (median step); else `too_few_points` or `coarse`, and the well is not judged (a peak cannot be placed to within the tolerance) |
| Even grid | the readings interpolated (linearly) onto a grid at their median step |
| −dF/dT | a Savitzky–Golay derivative: a cubic fitted over a 2 °C window (at least five readings), `scipy.signal.savgol_filter(deriv=1)`, sign reversed. A cubic keeps a peak's height and width; a straight-line slope over the same window would flatten them (on a synthetic peak of known width: width 1.93 °C against 1.88 °C true, height within 1 %) |
| Peaks | the local maxima (`scipy.signal.find_peaks`), each with its prominence (its height above its own local background, the higher of the two minima either side) and its full width at half prominence; maxima within half a window of either end (smoothing edge effects), below 1 % of the well's tallest, or below a millionth of the curve's fluorescence range per reading (rounding in a flat stretch) are dropped; at most eight are kept |
| Tm | the top of the parabola through the peak's reading and its two neighbours (between readings) |

**Per assay** (one target on one plate, `judge_assay`; thresholds are G-MELT's `params`).

| Quantity | Rule |
|---|---|
| Reference wells | the target's amplified unknowns on the plate with a peak (LinRegPCR's call: amplification and a Cq); fewer than `min_wells` (3): amplified unknowns, positives and standards together |
| Expected Tm | the target's `meltingTemperature` declared in the RDML file (20–100 °C), else the median main-peak Tm of the reference wells (with at least `min_wells` of them, a qPilot convention), else not known |
| Spread | lowest and highest main-peak Tm of the reference wells |
| Noise floor | `noise_share` (0.05) × the median main-peak prominence of the reference wells; an assay none of whose study wells amplified (a plate's unused wells) takes the median of the plate's other assays' instead, so its wells are measured against a real product, not their own noise. A peak below the floor is not counted |
| A study well's product | the most prominent counted peak within `tm_tolerance_c` (1.0 °C) of the expected Tm (rdmlpython's true peak); without one, the most prominent counted peak is its main peak |
| Extra peak | a counted peak besides the product carrying at least `extra_peak_share` (0.05) of the well's summed counted prominences |

| A study well that amplified (`unkn`, `pos`, `std`) | Call | G-MELT |
|---|---|---|
| its product within the tolerance, no extra peak | `one_product` | pass |
| its product within the tolerance and an extra peak | `extra_peak` (a mixture: a primer-dimer below the product, another product above it) | warn |
| no counted peak within the tolerance | `tm_off` ("no product with expected melting temperature") | fail |
| no counted peak at all | `no_peak` | fail |

| A no-template control (`ntc`, `ntp`) | Call | G-MELT |
|---|---|---|
| no counted peak | `no_product` | pass (`ntc_clean`) |
| a counted peak (main or extra) within the tolerance of the product | `product` (contamination candidate) | warn (`ntc_product`) |
| peaks only below the product | `dimer` (primer-dimer candidate) | pass (`ntc_dimer`) |
| a main peak above the product | `other_product` | warn |
| a peak, product Tm not known | `unclassified` | not applicable (`no_expected_tm`) |

Study wells that did not amplify are not judged (one "not applicable" per plate × target says how many samples); no-RT and no-amplification controls are not judged by their melt (G-NRT and G-NAC weigh them). A G-MELT verdict is given per study sample × target × plate (the worst of its amplified wells: `tm_off`, then `no_peak`, then `extra_peak`) and per no-template sample. The flagged study wells are the consequence test's option `exclude_flagged`; a control is not a study sample, so its finding has no option of its own. Without melt curves G-MELT is "not applicable: no_melt_data" (once for the study, or once per plate without them); for a target whose dye the file declares a probe chemistry, "probe_chemistry"; for readings too far apart, "coarse_melt".

**G-NTC-1.** When a plate has melt curves, G-NTC-1 (no-template control amplification near the study samples) uses the class of the no-template wells that amplified: every one a primer-dimer candidate → `tainted_dimer` (warn: "primer-dimers are more likely than template"); a product, another product, or a well that cannot be classified → `tainted` (fail), as without melt data. A plate without melt curves gets exactly the reason and verdict it got before (scientist spec: unclassified is treated as contamination).

**Checked on real files** (`tests/qpcr/test_melt.py`, `tests/gate/test_gate_melt.py`, `tests/web/test_melt_routes.py`).

| File (corpus) | What was measured |
|---|---|
| CFX Manager 3.1 SYBR export, gapdh plate (`biorad/hsieh2016-cfx-manager-3.1-sybr`, 96 wells, 0.5 °C steps) | qPilot's Tm is within one reading (0.5 °C) of CFX Manager's own "Melt Curve Peak Results" for all 96 wells, mean difference −0.18 °C (CFX reports the reading at the top, 83.5 °C; the parabola's top is at about 83.3 °C); one peak per well, as CFX lists |
| the same export, inhibition plate (17 wells, 3 typed NTCs) | the two NTCs that amplified late (CFX Cq 36.3 and 35.9) melt at the product's Tm (83.4 °C, the median of 14 wells): contamination candidates; the third shows no peak. G-NTC-1 says "amplified, every study sample at least five cycles earlier" with the class |
| rdmlpython's melt test file (`tests/fixtures/test_mca_1_raw_data.rdml`, target CRE declared at 85.34 °C, 50 wells, 0.21 °C steps) | the declared Tm is used; rows H–J mix a second product near 79.5 °C into CRE's (larger than CRE's in row J): 27 `extra_peak`; row K has the second product only: 10 `tm_off`; 13 `one_product` |
| CFX Manager 3.0 RDML, ten SYBR assays on one plate (`rdml/cfx-manager-3.0-rdml-1.2-rpa`) | ten product Tm (75.8–84.5 °C); HoxB9P4 F4 and F6 (86.0 and 88.4 °C against 80.9 °C) and LMNAP1 H5 and H6 (76.4 and 87.0 °C against 81.7 °C) have no product at the expected Tm; HoxB1P1 A4 an extra peak at 74.8 °C (20 %) |
| LightCycler 96 experiment file (`rdml/lightcycler96-lc96p-hmuy`, 0.2 °C steps), walked through Studio with the depositors' groups | hmuY 82.0 °C and 16S rRNA 87.1 °C, 18 wells each one product; its 60 unused wells (typed no-template): nothing melted |

Synthetic curves (an error-function melt of known Tm, so −dF/dT is a Gaussian centred on it) check the Tm to 0.05 °C at steps 0.1–1.0 °C, the width and height, noise, unsorted and repeated readings, a falling start without a product, and every call.

**What we changed from the published method.** rdmlpython normalises each curve (an exponential background, optionally bilinear) and smooths with Friedman's super-smoother before differentiating; qPilot differentiates the readings directly with one Savitzky–Golay filter and measures each peak above its own local background (its prominence), which needs no background model and is the same for every instrument. rdmlpython's "deltaH" is a peak's height above the mean of the derivative at its two inflection points; qPilot's share is of prominences. The expected Tm falls back to the median of the plate's study wells when the file declares none (rdmlpython then has no expected peak), and the noise floor is relative to the assay's typical product peak (rdmlpython's cut-off is relative to the well's own peaks only, which counts noise in an empty no-template well as peaks). The demo study (Vermeulen 2013) has no melt curves: G-MELT is "not applicable" there and every earlier verdict is unchanged.
