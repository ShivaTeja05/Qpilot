# Untergasser validation data

Copied unchanged from the RDML consortium repository, `experiments/untergasser/`
(https://github.com/RDML-consortium/rdmlpython/tree/main/experiments/untergasser), where the
data were created by Andreas Untergasser with Maurice van der Hoff (AMC, Amsterdam) and
Vladimir Benes (EMBL, Heidelberg). Licence: that of the rdmlpython repository (MIT).

Used by `qsim validate`:

- **Round 1 (nominal truth).** The "DNA Dilution - AMC" experiment in `amplicon_primer_mix.rdml`:
  human genomic DNA at 20, 7, 2, 0.7, 0.2 and 0 ng in triplicate, 16 primer pairs, LightCycler 480,
  Roche SYBR, SensiFast and LC Green mixes. `dna_dilution_amc_curves.csv` is qPilot's LinRegPCR
  output for that experiment.
- **Round 2 (dPCR truth, four machines).** See `src/qsim/truth.py` and `src/qsim/known_answers.py`.
  - "dPCR - DKFZ" in `large_DNA_dilutions.rdml` (LightCycler 480 II at DKFZ, 27.08.2025) was
    prepared from the same tubes as the QX200 dPCR in `large_DNA_dilutions_res_dpcr_probe.tsv` and
    `large_DNA_dilutions_res_dpcr_evagreen.tsv`. The qPCR layout is
    `large_DNA_dilutions_pipett_qpcr_for_dpcr.tsv`; the dPCR layout is
    `large_DNA_dilutions_pipett_dpcr.tsv`.
  - `volume_machine.rdml` is the instrument comparison: one FSTL1 primer pair and one DNA dilution
    series on a LightCycler 480 II (AMC, 14.02.2024), then on a QuantStudio 6 Flex and a StepOne
    (EMBL, 06.03.2024), whose reactions were pipetted from the same tubes. The layouts are
    `volume_pipett_AMC.tsv` and `volume_pipett_EMBL.tsv`.

## Files added in round 2

Downloaded on 18.10.2026 from `https://raw.githubusercontent.com/RDML-consortium/rdmlpython/main/experiments/untergasser/<file>`
(repository head `fce7a44`). The SHA-256 values are of the files as committed here.

| File | Last upstream commit | SHA-256 |
|---|---|---|
| `volume_machine.rdml` | `aa378c9` (2025-12-07) | `aeb5fb32711072b351bebd9a11816760686fe1ff26b618b55e8b28eaf5591e6b` |
| `volume_pipett_AMC.tsv` | | `5c1bd8c6044d9ee38aa4e0561c22e5d1e78201431f216972598552d61734de69` |
| `volume_pipett_EMBL.tsv` | | `26302bca4ba3fc3486eebfbf9710ad50937567ea1dc495675d885fa9ae1a139c` |
| `large_DNA_dilutions_pipett_dpcr.tsv` | `da67d8b` (2025-11-16) | `bcf217638f7054e703e2e771a4de6cd8568cec57449bafb0d0a0da6f33e8e742` |

`large_DNA_dilutions.rdml` and `large_DNA_dilutions_res_dpcr_probe.tsv` were checked to be
byte-identical to upstream on the same day.

## How the dPCR wells map to the qPCR samples

`src/qsim/truth.py` implements this mapping and raises an error if any result-file row disagrees
with it.

| dPCR layout | Result-file sample | qPCR sample (DKFZ plate) | Assays measured by dPCR |
|---|---|---|---|
| 20, 7, 2, 0.7, 0.2 | 20, 7, 2, 0.7, 0.2 | genomic DNA 20ng ... 0.2ng | F_109, K_219 (probe) |
| EMBL 20 | EMBL20 | EMBL DNA 20ng | F_109, K_219 |
| 0 | NTC | genomic DNA 0ng | F_109, K_219 |
| 200000, 20000, 2000, 200 (copies in 2 µl) | a20000, a2000, a200, a20 | Dil 1:10 - 10e5 ... 10e2 | F_109, K_219 (probe); H_201, L_412 (EvaGreen) |
| test | FF | not on the qPCR plate | unused |

Notes on the mapping:

- **Assay names.** Assay names in both layout and result files were numbered on by spreadsheet fill: F_109, F_110 ... F_116 along a row. The assay is therefore read from its letter. F, K, H and L each name one primer pair.
- **EvaGreen plate.** The EvaGreen wells ran on their own plate. Its wells A01–A08 are layout row D. Well D1 (H_201 at 10^5) is absent upstream.
- **Which amplicon series.** The qPCR plate holds the amplicon standard twice: the fresh 1:10 series ("Dil 1:10") and aliquots frozen and thawed ten times ("Freeze"). dPCR measured the fresh series, so only that one is scored.
- **Other experiments.** The README upstream says that one genomic dilution series, made in AMC in December 2024, was used for every later experiment. That makes the dPCR truth apply to "DNA Dilution - AMC" too, measured eight months before the dPCR. It does not apply to `volume_machine.rdml`, whose dilutions were made in February 2024.
