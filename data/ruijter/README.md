# Ruijter 2013 ds_380: one template, 380 replicates

`ds_380.csv` is the `ds_380` data set of the R package **ruijter** 0.1.3 by Ramiro Magno
(https://github.com/ramiromagno/ruijter, commit `f9d2df4`; licence CC BY 4.0). It comes from
Ruijter et al. 2013, *Methods* 59:32-46 (https://doi.org/10.1016/j.ymeth.2012.08.011).

- **Source.** Downloaded on 18.10.2026 without R, from the r-universe data endpoint `https://patterninstitute.r-universe.dev/ruijter/data/ds_380/csv`.
- **Content.** 17,280 rows: one row per well and cycle, with raw fluorescence.
- **Plate.** 380 wells contain 150,000 copies of a MYCN amplicon and 4 are no-template controls, on one Bio-Rad CFX384 plate with SYBR Green and 45 cycles.
- **Copy number.** The paper says 15,000 copies. The package manual corrects this to 150,000, on the authors' word.
- **SHA-256.** `95734574de8cc2dd8a80af2a72e8442d4ea55005cac084acde55d741c6748c0b`

`ds_380.rdml` is the same data as RDML, written by `qsim.nodiff.to_rdml()` with rdmlpython's own
table import. qPilot's LinRegPCR analyses it like any instrument export:

```bash
.venv/bin/python -c "from qsim import nodiff; nodiff.to_rdml()"
```

Each rebuild stamps a new creation date into the file, so the file's hash changes (and with it
qPilot's curve cache key), but the curves do not.

## Added 18 Oct 2026: ds_94_4 and ds_competimer

Both come from the same package and endpoint as ds_380 (`https://patterninstitute.r-universe.dev/ruijter/data/<name>/csv`, CC BY 4.0) and were downloaded without R. Both are converted to RDML by `qsim.external`, as ds_380 is.

- **`ds_94_4.csv`** (832,137 bytes, SHA-256 `7d869dfc0230f8f85c1c38987565b7994fb9b3c409f46fdaae400249ed86169c`).
  - **Design.** A MYCN oligo at 15, 150, 1,500 and 15,000 copies × 94 replicates, plus 8 no-template controls, on one CFX384 with SYBR Green and 45 cycles.
  - **Label check.** The original dilution labels were reversed; the package's labels run the right way. More copies amplify earlier: the half-maximum cycle is 26, 29, 32 and 35.
- **`ds_competimer.csv`** (278,704 bytes, SHA-256 `911bca98d46b10543aa0347534aea877bf029fef8cb824c4ff82d257dbaa382e`).
  - **Design.** AluSx on gDNA at 64, 16, 4, 1, 0.25 and 0.0625 ng/µl, plus 0. Each has 0, 5, 10, 20, 30, 40 and 50 % competimer, which lowers efficiency on purpose, in triplicate on a LightCycler 480.
  - **No well IDs.** The CSV has none, so wells are numbered in file order.
