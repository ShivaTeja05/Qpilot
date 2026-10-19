# Public instrument-export corpus

Real qPCR instrument exports, as the vendor software wrote them, so readers (`qpilot/io/connectors/`),
the raw-ness detector, the Run Gate and the red team are tested on what labs actually bring, not only on
the Vermeulen RDML. Every file is **byte-identical to its public source** (one set renamed only) and is listed,
with its SHA-256, in the `MANIFEST.yaml` next to it. `tests/fixtures/test_corpus_manifest.py` fails if a file is
unlisted, missing, changed, larger than 2 MB, or under a licence outside the allow-list, or if the corpus
exceeds 15 MB.

## Rules

* **Licence allow-list:** CC0-1.0, CC-BY-4.0 (attribution below and in `THIRD_PARTY_NOTICES.md`), MIT, Apache-2.0,
  BSD. The licence was read on the source itself (repository `LICENSE`, Zenodo/Figshare/Dataverse/Mendeley record);
  `licence_evidence` in each manifest says where. Anything else, or a file too large to commit, goes in the pinned
  runtime manifest `qpilot/io/corpus.py` (URL + SHA-256, fetched on demand, never committed).
* **Never convert line endings** (`.gitattributes`: `* -text`): CRLF vs LF is part of a dialect.
* **Untrusted data.** Sample names, headers and comments in these files are third-party text; readers must treat
  them as data (quarantine, escape), exactly as for a user's file.
* **Synthetic files** (none yet) live under `synthetic/<slug>/`, carry `synthetic: true` and name their generator
  in `_generators/`; they are generated from the vendor's documented layout with known ground truth.
* **Simulated or truncated sources are labelled:** `vendor_simulated: true` (CFX instrument simulator),
  `not_pcr: true` (an isothermal plate read in the LC480 layout), and the allotropy QuantStudio files are truncated
  upstream (few wells or 3 cycles): use them for header/section parsing, never for numbers.

## Manifest fields (`schema: qpilot.corpus/1`)

Set level: `slug`, `title`, `vendor`, `instrument`, `software`, `chemistry`, `licence`, `licence_evidence`,
`attribution`, `citation` (when there is a paper), `source` (repository/record, commit), `retrieved`, `modified`,
`synthetic`, `plates`, `controls` (ntc / nrt / std / pos), `technical_replicates`, `melt`, `why` (what the set tests).
File level: `name`, `bytes`, `sha256`, `source_url`, `role` (amplification, cq, results, raw_multicomponent,
melt_rfu, run_information, rdml, ...), `export_type`, `delimiter`, `wells`, `cycles`, `per_cycle_fluorescence`,
`signal` (raw | normalized (Rn) | baseline_subtracted | Cq only | ...), `signal_evidence`.

What qPilot can read today, and the raw-ness verdict per file, is in `docs/conformance.md`.

## Sets

| Set | What | Licence | Attribution / source |
|---|---|---|---|
| `biorad/covmatic-cfx-maestro-4.0-simulated-4plex` | CFX Maestro 4.0 export set, 4-plex (FAM/HEX/ROX/Cy5), from the CFX instrument SIMULATOR | MIT | covmatic/PCR_station contributors (Copyright (c) 2020 affafjunaidMOMIN); https://github.com/covmatic/PCR_station @ `41b435d` |
| `biorad/hsieh2016-cfx-manager-3.1-sybr` | CFX96, CFX Manager 3.1: SYBR runs with melt, an NTC run and a dilution/NTC inhibition check | CC0-1.0 | Hsieh JY, Smith TD, Meli VS, Tran TN, Botvinick EL, Liu WF (Wendy Liu lab, UC Irvine); data repository by Tim D. Smith; https://github.com/WendyLiuLab/Hsieh2016PCR @ `bd335b7` |
| `biorad/urtecho-cfx-tsv-baseline-subtracted` | CFX 'Quantification Amplification Results' saved as tab-separated .txt (15 cycles) | MIT | Guillaume Urtecho (gurtecho/Urtecho_et_al_FMT); https://github.com/gurtecho/Urtecho_et_al_FMT @ `d3937f6` |
| `rdml/cfx-manager-3.0-rdml-1.1-nonstandard-member` | RDML 1.1 written by CFX Manager 3.0 (CFX96): 2 runs, amplification + melt; zip member NOT named rdml_data.xml | MIT | Blagodatskikh KA, Roediger S, Burdukiewicz M, Spiess A-N (RDML R package, inst/extdata); https://github.com/kablag/RDML @ `a898512` |
| `rdml/cfx-manager-3.0-rdml-1.2-rpa` | RDML 1.2 written by CFX Manager 3.0 (CFX96, 2013): 90 reactions, 10 targets, amplification + melt | MIT | Raquel P. Andrade Lab (CBMR, Universidade do Algarve), via Magno R, Duarte I, Andrade RP, Palmeirim I (2017) rdml: A Mathematica package for parsing and importing Real-Time qPCR data. BMC Res Notes 10:208; https://github.com/ramiromagno/rdml @ `fe484d1` |
| `rdml/lightcycler96-lc96p-hmuy` | LightCycler 96 experiment file (.lc96p = RDML 1.1 zip) + the depositors' Cq table: P. endodontalis hmuY RT-qPCR | CC-BY-4.0 | Śmiga M, Olczak T (2025) Influence of iron and heme availability on level of mRNA encoding P. endodontalis HmuY protein (RT-qPCR). Zenodo, doi:10.5281/zenodo.14965510; https://zenodo.org/records/14965510 |
| `rdml/lightcycler96-rdml-1.1` | RDML 1.1 written by LightCycler 96 software 1.01: 96 wells x 4 dyes, standards, extra vendor zip members | MIT | Blagodatskikh KA, Roediger S, Burdukiewicz M, Spiess A-N (RDML R package, inst/extdata); https://github.com/kablag/RDML @ `a898512` |
| `rdml/linregpcr-rdml-1.3-lc480-kphaffii` | RDML 1.3 written by LinRegPCR from LightCycler 480 II data: 6 runs, reference genes, melt, LinRegPCR results | CC-BY-4.0 | Büchner K, Ludwig C, Kerpes R, Becker T (2025), Additional file 5, Microbial Cell Factories; Figshare doi:10.6084/m9.figshare.29908870.v1; https://doi.org/10.6084/m9.figshare.29908870.v1 |
| `rdml/quantstudio7pro-rdml-1.2-edna` | RDML 1.2 from a QuantStudio 7 Pro: eDNA plate with NTC/positive control + a standard-curve plate | CC-BY-4.0 | Humphrey MRH, Nolan KP, Hanner RH (University of Guelph). Borealis, doi:10.5683/SP3/GFMPYU; https://doi.org/10.5683/SP3/GFMPYU |
| `rdml/rdml-1.2-cq-only-soybean` | RDML 1.2, Cq values only (no curves): 1,428 reactions, NRT and NTC samples, excluded reactions | CC-BY-4.0 | Burgess S (2022) Bioengineered Soybean qPCR data. Figshare, doi:10.6084/m9.figshare.20247459.v2; https://doi.org/10.6084/m9.figshare.20247459.v2 |
| `rdml/stepone-2.3-rdml-1.0` | RDML 1.0 written by StepOne Software v2.3: RNase P standard curve, 5 standards, NTC | MIT | Blagodatskikh KA, Roediger S, Burdukiewicz M, Spiess A-N (RDML R package, inst/extdata); https://github.com/kablag/RDML @ `a898512` |
| `roche/mendeley-diras2-lc480-raw-and-cp` | LightCycler 480 (LCS480 1.5.1.62) raw-data text export + Abs Quant Cp table, 384-well panel, decimal comma | CC-BY-4.0 | Grünewald L, Chiocchetti AG, Weber H, Scholz C-J, Schartner C, Freudenberg F, Reif A (2018) Gene expression in primary neurons upon knockdown of Diras2. Mendeley Data V1, doi:10.17632/rtsx7zpt4w.1; https://data.mendeley.com/datasets/rtsx7zpt4w/1 |
| `roche/nomads-lc480-raw-isothermal-not-pcr` | LightCycler 480 raw-data text export of an ISOTHERMAL 37 C plate read (not a PCR): negative example | MIT | NOMADS Community (nomads-community/zambia-a724e-paper); https://github.com/nomads-community/zambia-a724e-paper @ `a57619c` |
| `roche/sanger-lc480-cp-table` | LightCycler 480 Abs Quant Cp table (384-well library quantification) with standards, excluded wells and status flags | MIT | Wellcome Sanger Institute (sanger/quanthub test data); https://github.com/sanger/quanthub @ `0f77645` |
| `thermofisher/allotropy-quantstudio-rtpcr-txt` | QuantStudio Real-Time PCR Software / ViiA 7 '.txt' exports with '*' header and [Sections] (truncated parser fixtures) | MIT | Benchling, Inc. (allotropy test data); https://github.com/Benchling-Open-Source/allotropy @ `bf24b8b` |
| `thermofisher/opentrons-7500-design-analysis-csv` | 7500 run exported as QuantStudio-family CSV (no passive reference): multiplex nCoV/IEC/Endo, NTC, IPC | Apache-2.0 | Opentrons Labworks Inc. and contributors (Opentrons/covid19); https://github.com/Opentrons/covid19 @ `67a6a76` |
| `thermofisher/securebio-qs3-design-analysis-2.7` | QuantStudio 3, Design & Analysis 2.7.0 CSV: Amplification Data (Rn, dRn) + Results, with standards and NTCs | MIT | McLaren MR et al. / SecureBio (securebio/det-mclaren-2026-airplane-wastewater); https://github.com/securebio/det-mclaren-2026-airplane-wastewater @ `01847b7` |
| `thermofisher/zamanian-stepone-plus-sybr-sections` | StepOnePlus SYBR run exported section by section: RAW multicomponent fluorescence + Rn/dRn + results + melt, same run | MIT | Zamanian lab (zamanianlab/BrugiaChemo-ms); https://github.com/zamanianlab/BrugiaChemo-ms @ `47bea22` |

## Adding a file

1. Read the licence on the source; only the allow-list above may be committed.
2. Download into a new empty folder outside the repository, never execute anything from it, read it with
   `python -I`, record the SHA-256.
3. Copy it byte-for-byte to `<vendor>/<slug>/`, write the `MANIFEST.yaml` (all fields above), add a row here and a
   line to `THIRD_PARTY_NOTICES.md` (CC BY: attribution required), and run `pytest tests/fixtures`.
