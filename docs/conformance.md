# Which instrument files qPilot reads

qPilot is tested on real files that labs published, not only on the demo study. This page lists
every set of the public corpus in [`tests/fixtures/corpus/`](../tests/fixtures/corpus/README.md)
(each file byte-identical to its public source, with its licence and SHA-256 in a `MANIFEST.yaml`)
and what happens when a person drops it on the page's **Open**.

The tables below are generated, not written by hand: `python scripts/conformance.py` drops each
set on `POST /api/workspaces` exactly as the page does (the whole folder; then each RDML file and
workbook alone), over a throwaway study store with no model, lets qPilot's rules propose the
design, and prints what it found. Re-run it after changing a reader and paste its output here.
`tests/web/test_intake_corpus.py` checks the same plates and wells on every test run.

Last generated on 28 Oct 2026 (qPilot 0.2.0).

## How to read the tables

* **Opens as**: the reader that took the files. An RDML file opens as it is (RDML 1.0 to 1.4; a
  zipped `.rdml` or `.lc96p` whatever its member's name). An instrument export is read by content,
  never by its file name, and written once into deterministic RDML. A refusal is quoted in
  qPilot's own words.
* **Plates · wells · samples · targets**: what the page's Design section then shows.
* **Curves**: Open's raw-ness check of an export's amplification curves.
  * *raw*: the curves as the instrument measured them; LinRegPCR fits each well.
  * *normalised to a passive reference (Rn)*: the ground phase is kept, so LinRegPCR still fits
    each well; no card.
  * *baseline-subtracted* or *could not tell*: the study is analysed with every gene's confidence
    capped at Moderate until a person decides the **Import Trust** card on Results (re-export the
    raw curves, analyse them as they are, or use the instrument's Cq values only).
  * *Cq values only*: there are no curves to fit; the Cq values are analysed as they are
    ([cq-tables.md](cq-tables.md)).
  * An RDML file does not go through this check; the Evidence Ledger says so.
* **Melt curves**: wells whose melt curve `qpilot melt` reads (G-MELT in Controls, the melt panel
  in Curves). "none in the files" means the files hold no melt data.
* **Design proposals**: how many design proposals qPilot's rules made with no model and no sample
  sheet. A file that names its samples and types gives the rules something to read; one that
  does not (`0`) is set on the page by a person instead ([design-editor.md](design-editor.md)).

## Every set, dropped as a folder

| Set | Instrument / software | Opens as | Plates · wells · samples · targets | Curves | Melt curves | Design proposals |
|---|---|---|---|---|---|---|
| `biorad/covmatic-cfx-maestro-4.0-simulated-4plex` (instrument simulator) | CFX96 simulator; NOT a physical run; CFX Maestro 4.0.2325.0418 | Bio-Rad CFX Manager / Maestro export | 1 · 96 · 96 · 4 | could not tell: Import Trust card | none in the files | 2 |
| `biorad/hsieh2016-cfx-manager-3.1-sybr` | CFX96; CFX Manager 3.1.1517.0823 | Bio-Rad CFX Manager / Maestro export | 3 · 209 · 209 · 1 | baseline-subtracted: Import Trust card | 113 wells | 3 |
| `biorad/urtecho-cfx-tsv-baseline-subtracted` | CFX (model not stated in the file); CFX Manager/Maestro (version not stated; no Run Information file deposited) | Bio-Rad CFX Manager / Maestro export | 1 · 95 · 95 · 1 | could not tell: Import Trust card | none in the files | 0 |
| `rdml/cfx-manager-3.0-rdml-1.1-nonstandard-member` | CFX96; CFX Manager 3.0.1224.1015 | RDML (opened as it is) | 2 · 60 · 5 · 4 | not checked (RDML) | 60 wells | 4 |
| `rdml/cfx-manager-3.0-rdml-1.2-rpa` | CFX96; CFX Manager 3.0.1224.1015 (Culture pt-PT) | RDML (opened as it is) | 1 · 90 · 3 · 10 | not checked (RDML) | 90 wells | 5 |
| `rdml/lightcycler96-lc96p-hmuy` | LightCycler 96; LightCycler 96 1.01.01.0050 | RDML (opened as it is) | 1 · 96 · 7 · 3 | not checked (RDML) | 96 wells | 10 |
| `rdml/lightcycler96-rdml-1.1` | LightCycler 96; LightCycler 96 1.01.00.0045 | RDML (opened as it is) | 1 · 96 · 12 · 8 | not checked (RDML) | none in the files | 14 |
| `rdml/linregpcr-rdml-1.3-lc480-kphaffii` | LightCycler 480 II; LinRegPCR (RDML 1.3 with LinRegPCR result elements) | RDML (opened as it is) | 6 · 432 · 24 · 6 | not checked (RDML) | 432 wells | 4 |
| `rdml/quantstudio7pro-rdml-1.2-edna` | QuantStudio 7 Pro System; not stated in the RDML | refused: Open one RDML file at a time (SupplementaryMaterials2_qPCR_ConcentrationStandardCurve.rdml, SupplementaryMaterials2_qPCR_Plate1.rdml); one RDML file can hold many plates. | — | — | — | — |
| `rdml/rdml-1.2-cq-only-soybean` | not stated; not stated | RDML (opened as it is) | 17 · 1428 · 60 · 10 | not checked (RDML) | none in the files | 13 |
| `rdml/stepone-2.3-rdml-1.0` | StepOne; StepOne Software v2.3 | RDML (opened as it is) | 1 · 24 · 8 · 1 | not checked (RDML) | none in the files | 7 |
| `roche/mendeley-diras2-lc480-raw-and-cp` | LightCycler 480 (instrument named '29892'), 384-well; LightCycler 480 Software 1.5.1.62 | Roche LightCycler 480 text export | 1 · 384 · 4 · 1 | raw | none in the files | 0 |
| `roche/nomads-lc480-raw-isothermal-not-pcr` | LightCycler 480; LCS480 1.5.1.62 | refused: The export could not be read: evIC50_1_plate1_07APRIL2026.txt: every reading was taken at about 37 °C, with no heating step, so this is not a PCR run (it looks like an isothermal plate read); qPilot reads qPCR runs only. | — | — | — | — |
| `roche/sanger-lc480-cp-table` | LightCycler 480 (384-well); LightCycler 480 Software (version not in file) | Roche LightCycler 480 text export | 1 · 384 · 176 · 1 | Cq values only | none in the files | 8 |
| `synthetic/cfx-manager-raw-vs-baseline-subtracted` (synthetic) | none (synthetic); none; CFX Manager 3.x export layout | Bio-Rad CFX Manager / Maestro export | 2 · 160 · 95 · 3 | baseline-subtracted: Import Trust card | none in the files | 8 |
| `synthetic/quantstudio-design-analysis-rn-drn` (synthetic) | none (synthetic; header says QuantStudio 5 and SYNTHETIC); none; Design & Analysis 2.7 CSV layout | Thermo Fisher QuantStudio / Applied Biosystems export | 1 · 80 · 15 · 2 | normalised to a passive reference (Rn) | none in the files | 8 |
| `thermofisher/allotropy-quantstudio-rtpcr-txt` | QuantStudio 6 Flex, QuantStudio 7 Flex, ViiA 7 (per file header); QuantStudio Real-Time PCR Software 1.x / ViiA 7 Software (version not in header) | Thermo Fisher QuantStudio / Applied Biosystems export | 6 · 216 · 79 · 8 | Cq values only | none in the files | 52 |
| `thermofisher/opentrons-7500-design-analysis-csv` | 7500 System, 96-well 0.2 mL block; QuantStudio-family CSV export (software name/version not in header; Amp Score/Cq Confidence columns as in Design & Analysis) | Thermo Fisher QuantStudio / Applied Biosystems export | 1 · 51 · 10 · 3 | raw | none in the files | 1 |
| `thermofisher/securebio-qs3-design-analysis-2.7` | QuantStudio 3 System, 96-well 0.1 mL block; Design & Analysis Software v2.7.0 (Primary Analysis v1.8.0, Standard Curve v1.7.0) | Thermo Fisher QuantStudio / Applied Biosystems export | 2 · 186 · 36 · 2 | normalised to a passive reference (Rn) | none in the files | 9 |
| `thermofisher/zamanian-stepone-plus-sybr-sections` | StepOnePlus (inferred: 4 raw filters named BLUE/GREEN/YELLOW/RED, StepOne result flags AMPNC/HIGHSD); StepOne Software v2.x (inferred; the per-section exports carry no '*' header) | Thermo Fisher QuantStudio / Applied Biosystems export | 1 · 57 · 6 · 3 | normalised to a passive reference (Rn) | 57 wells | 4 |

| File, dropped alone | Opens as | Plates · wells | Curves |
|---|---|---|---|
| `rdml/cfx-manager-3.0-rdml-1.1-nonstandard-member/BioRad_qPCR_melt.rdml` | RDML (opened as it is) | 2 · 60 | not checked (RDML) |
| `rdml/cfx-manager-3.0-rdml-1.2-rpa/rpa.rdml` | RDML (opened as it is) | 1 · 90 | not checked (RDML) |
| `rdml/lightcycler96-lc96p-hmuy/hmuy_cq_values.xlsx` | Tidy table (long amplification data or a Cq table) | 1 · 36 | Cq values only |
| `rdml/lightcycler96-lc96p-hmuy/hmuy_hm_vs_dip_r123.lc96p` | RDML (opened as it is) | 1 · 96 | not checked (RDML) |
| `rdml/lightcycler96-rdml-1.1/lc96_bACTXY.rdml` | RDML (opened as it is) | 1 · 96 | not checked (RDML) |
| `rdml/linregpcr-rdml-1.3-lc480-kphaffii/12934_2025_2809_MOESM5_ESM.rdml` | RDML (opened as it is) | 6 · 432 | not checked (RDML) |
| `rdml/quantstudio7pro-rdml-1.2-edna/SupplementaryMaterials2_qPCR_ConcentrationStandardCurve.rdml` | RDML (opened as it is) | 1 · 42 | not checked (RDML) |
| `rdml/quantstudio7pro-rdml-1.2-edna/SupplementaryMaterials2_qPCR_Plate1.rdml` | RDML (opened as it is) | 1 · 96 | not checked (RDML) |
| `rdml/rdml-1.2-cq-only-soybean/VPZ_raw_data.rdml` | RDML (opened as it is) | 17 · 1428 | not checked (RDML) |
| `rdml/stepone-2.3-rdml-1.0/stepone_std.rdml` | RDML (opened as it is) | 1 · 24 | not checked (RDML) |

## What these results do and do not say

* **Opening is not validation.** A file that opens has been read into qPilot's model of plates,
  wells, samples and targets, and its numbers then go through the same engine as the demo study.
  Curve analysis itself (N0, Cq, efficiency) is validated against a published benchmark on one
  instrument platform only (LightCycler 480, SYBR Green I; see the README's Validation section).
* **Cq values only.** A file without curves (a Cq table, `rdml-1.2-cq-only-soybean`, the
  QuantStudio `.txt` results) is analysed from its Cq values, with an efficiency from the plate's
  dilution series or assumed, and a confidence cap ([cq-tables.md](cq-tables.md)).
* **Truncated and simulated sources.** The allotropy QuantStudio files are truncated parser
  fixtures (few wells or 3 cycles), the CFX Maestro set comes from Bio-Rad's instrument
  simulator, and the two `synthetic/` sets are generated from the vendors' documented layouts
  with known ground truth. They test reading, not numbers.
* **Refusals are on purpose.** An isothermal plate read is not a PCR run. Two RDML files dropped
  together are refused because one RDML file can hold many plates: open each alone (the second
  table shows both open).
* **Not read yet:** vendor project files (`.eds`, `.pcrd`, `.ixo`; the page says how to export
  them; `qpilot instrument inspect` reads an `.eds` file's run information only) and CFX "Melt
  Curve Derivative Results" without the melt RFU file.
