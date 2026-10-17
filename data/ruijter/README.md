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
