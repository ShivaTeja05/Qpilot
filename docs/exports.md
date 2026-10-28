# Exports: your numbers, figures and a journal supplement

qPilot's numbers leave it as numbers: a workbook you can calculate with, tidy CSV tables, a figure
per gene and one zip for a journal. Every file is written from the study's own engine output
(`qpilot/report/tables.py`); nothing is typed in, rounded into text or recomputed elsewhere.

## Which analysis

Every export follows **the options chosen on the Decision Cards** ("As decided"): the engine
evaluates the study's decision space at the chosen cell (`qpilot.qpcr.export.Reanalysis`), the
same numbers the Results page shows "at your choices". A card still open counts at its recommended
option, and the file says so. When a chosen option is not the recommended one, the **recommended
analysis** comes too, in tables and sheets marked "recommended", so a reader sees both. The About
table names the analysis, the input file's and the design's SHA-256, and the decision chain head
the Analysis Record carries.

## The files

| Export | What it holds |
|---|---|
| **Excel workbook** (`xlsx`) | Sheets *Results* (per comparison and gene: call, fold change, 95 % CI low and high as two numeric columns, log2 fold change, p, q and Holm-adjusted p when the engine gives them, n per group in biological units, the share of qPilot's choice grid with the same call, confidence, Trace's first place to look), *Per unit* (per biological unit: wells used, mean Cq of the gene and of the reference genes, ΔCq, log2 RQ, RQ), *Per well* (plate, well, sample, unit, group, role, target, Cq, N0 of the curve fit and N0 in use, the well's and the assay's efficiency, the amplification call, left out by a person and why), *Where to look*, *Decisions* (who, what, why, when, hash), *Settings*, *Methods*, *About*. Numbers are number cells with number formats; headers name units; header rows are frozen, columns sized and filtered. |
| **CSV tables** (`csv`, zip) | The same tables, one tidy CSV each, UTF-8, exact floats, `TRUE`/`FALSE`, empty = no value; text a spreadsheet would read as a formula starts with an apostrophe. Plus the MIQE 2.0 checklist. |
| **Figures** (`figures`, zip) | For each headline gene (or the genes asked for): `<gene>.svg` (editable text), `<gene>.png` (300 dpi, 85 mm wide), `<gene>_source.csv` (the dots and each group's mean and CI as drawn), `<gene>_caption.txt`; a panel of them side by side. |
| **Journal supplement** (`supplement`, zip) | The workbook, every table as CSV (and per gene), the MIQE 2.0 checklist, the figures, the study's RDML file with qPilot's results written back (`data/<name>-qpilot.rdml`: `cq` always, `N0` and `ampEff` from RDML 1.3, `excl` with the person's reason for every well left out; checked against the RDML schema of its version, otherwise the original file and the per-well CSV, and the README says which), and the Analysis Record (its id on every About table; `qpilot verify` checks it). |

## The figure

Each dot is one **biological unit's** log2 relative quantity (technical replicates are averaged
within the unit by the engine first and are never dots); the bar is each group's mean with its
95 % confidence interval (Student's t on the units' values, as GraphPad Prism draws it); above the
groups the engine's call as a shape and a word (▲ up, ▼ down, ○ no call), the fold change and p of
the engine's test. Colours are Okabe–Ito (safe for colour-blind readers) and each group is named
under its column with its n. The caption is built from the engine's facts: n per group, the test,
the correction for many genes (none, or the engine's), the reference genes, the efficiency model,
the call rule and the call, and which analysis it is. The SVG and the PNG are drawn from one layout,
so they show the same figure. The Gene section's **Figure** panel previews it and downloads SVG,
PNG and CSV.

## Several comparisons

Every per-gene table and figure iterates over the study's comparisons through one adapter
(`tables.comparisons` / `tables.stored_comparisons`): today the study's two groups; with a design
that compares several pairs (`StudyResult.comparisons`), each comparison gets its rows, its q
(Benjamini–Hochberg across genes) and Holm-adjusted p, and its own per-unit rows.

## Names

Groups, units, samples and genes keep the names the lab gave them (`LPS + inhibitor`,
`IL-6/ctrl`, `Day 3 (50 µM)`, `KO#2`, `α-syn`) in every table, figure, report and Prism project:
the workbook writes them as text cells, every CSV a person opens defuses a formula start with an
apostrophe, SVG and HTML escape them. A name never becomes a path: a file named after a gene is
the name itself when it is a plain ASCII file name (`SDHA(1).svg`), else its ASCII slug and the
first 8 hex digits of its SHA-256 (`syn_efb8d4c7.svg`), so two names never share a file
(`qpilot/core/names.py`). A name is refused, in words, only when it is empty, longer than 64
characters, starts or ends with a space, or carries a tab, a line break or an invisible character;
the Prism tables (whose CSVs Prism reads back as they are) also refuse a group or unit that starts
with `=`, `+` or `@`.

## Where

* Page: **Report → Export** (each file is a job; the files written since qPilot started stay
  listed) and **Gene → Figure**.
* CLI: `qpilot export xlsx|csv|figures|supplement --out FILE [--study ID] [--genes A,B]
  [--basis recommended]` (`--format` names the same thing; `export excel` still works).
* API: `POST /api/studies/{id}/report/export {format, expected_head, basis?, genes?}`;
  `GET /api/studies/{id}/report/figure/info?gene=` and `GET …/report/figure?gene=&format=svg|png|csv`.

## Measured

On the demo (64 plates, 24 576 wells, 58 genes, 28 Oct 2026, a shared laptop): workbook ~25 s
(Trace of 58 genes included), CSV ~10 s, figures of the four headline genes ~12 s, supplement
~50 s (it writes the 60 MB RDML and checks it against the schema). On the real LightCycler 96
hmuY file (Hm vs DIP, 3 units of 3 wells each): every export under 15 s.

For research use only. Not for clinical or diagnostic use.
