# Run Gate acceptance numbers, re-measured independently (Vermeulen demo)

Command (from a qPilot checkout; ~2 s with a warm curve cache):

```bash
python validation/scientist/gate_acceptance.py      # writes validation/scientist/out/{gate_plates,grep_ds380}.csv
```

Inputs: the pinned `data_vermeulen_raw.rdml` through qPilot's LinRegPCR wrapper (`qpilot.qpcr.curves.analyse_study`),
experiments `biomarker_set` (64 plates × 384 wells) and `technical_datasets` (`380_replicates_set`). No Gate code is
used; the definitions are those of `agent-bus/contracts/scientist-spec-gate.md`. Cq = LinRegPCR TD0.

## G-NTC-1 (MIQE 2.0 5-cycle rule; earliest amplifying NTC per plate; no melt data → "unclassified")
| quantity | value |
|---|---|
| NTC wells with an engine Cq | **23 of 192**, on **11** of 64 plates |
| unknown wells within 5 cycles of their plate's earliest amplifying NTC (tainted) | **21**, on **7** plates |
| plate verdicts | pass 53 · warn 4 (NTC amplified, nothing tainted: CAMTA1, FYN, GNB1, NM23A) · fail 7 (ALUsq, CAMTA2, DPYSL3, MAP2K4, MCM2, PAICS, WSB1) |

ALUsq's NTCs amplify at Cq 23.9: an Alu-repeat assay detects traces of human DNA, so NTC signal is expected there.
The rule still fires; the consequence test decides whether it matters.

## G-STD (OLS Cq ~ log10 copies over amplified std wells; 5 levels 15–150,000 copies in triplicate per plate)
| quantity | value |
|---|---|
| plate verdicts (E 90–110 %, R² ≥ 0.980) | pass **57** · fail **7** |
| fails | ALUsq (slope −1.31, R² 0.694); six plates with E 1.873–1.890 (87–89 %): CAMTA1, CDKN3, MCM2, NTRK1, PMP22, TYMS — every one of these six has a 95 % CI that reaches 1.90, so the evidence line must show the CI |
| standard-curve E, median over plates | 1.947 |
| mean LinRegPCR per-well E of the same std wells, median | 1.918 (gap 0.030; standard-curve E higher, the direction MIQE 2.0 and Hastings 2021 describe) |

## G-REP false-flag rate on `380_replicates_set` (one sample, 380 wells; Cq SD 0.192; E 1.853)
Tolerance = q₀.₉₅(range of n) × 0.15 / ln E, copies unknown at Cq ≈ 19 (pipetting term only). 10,000 random groups.

| replicates n | tolerance (cycles) | false-flag rate | the fixed 0.5-cycle rule on the same groups |
|---|---|---|---|
| 2 | 0.674 | **1.1 %** | 4.3 % |
| 3 | 0.806 | **1.3 %** | 9.5 % |
| 4 | 0.884 | **1.7 %** | 14.3 % |

Acceptance (add_plan §3.12: ≤ 5 % false flags on ds_380) is met. The W2 formula `2.1/ln E × √(0.15² + 1/N)` (0.49
cycles, independent of n) would flag ~17 % of triplicates by simulation at this SD; it was replaced in the spec.
Adjacent wells along a row (a pipetting-like grouping) gave 1.1 % / 2.4 % / 3.2 % for n = 2 / 3 / 4 in the scratch run
(`agent-bus/scratch/scientist/val/grep_ds380.py`).

## DRIFT / LATE (from the plate-artefact prototype, definitions in the spec)
DRIFT 4 wells (AKR1C1 A11, ALUsq C23, CDKN3 A8, MTSS1 M2); LATE 58 wells on 9 plates; plate warning at ≥ 5 % of
evaluable wells → 1 plate (QPCT, 30/320 = 9.4 %; next ALUsq 3.4 %). Re-measured from
`proto_plate_qc/s03_well_features.csv`; the Gate's own implementation must reproduce these counts.

Research use only. These are acceptance oracles for the Gate, not statements about the quality of the original study.
