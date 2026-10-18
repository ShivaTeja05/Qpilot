# qPilot and GraphPad Prism

Scientists take qPCR results into GraphPad Prism for statistics and figures. qPilot's Prism
bridge hands Prism numbers it cannot misread, carries the record into the project, and notices
what a scientist changed in Prism afterwards. It does the qPCR-specific part that Prism does
not do (raw curves, per-assay efficiency, several reference genes, robustness across reasonable
analyses) and leaves Prism to do what scientists already trust it for: familiar statistics and
publication graphs.

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.

> **Not yet run on a real Prism seat.** There is no Prism installation or licence on the
> development machine. Everything qPilot writes is built from GraphPad's own documentation,
> and every Prism behaviour that documentation does not settle is marked **[R]** below and in
> the code. It stays unverified until plan step 0.1 is done on a real seat.

## What goes into Prism, and why log2

`qpilot export prism` writes one CSV table per gene:

- **Log2 relative quantities**: log2 of the gene's efficiency-corrected starting quantity
  (LinRegPCR N0) minus the mean log2 of the reference genes, per biological unit. These are the
  engine's own numbers (`qpcr.quant.relative`), read back bit for bit (`float.hex` equality is a
  test).
- **One value per biological unit** in the default column layout: first column `Sample` (row
  titles), then one column per group in the design's order. Technical replicates are averaged
  per unit by qPilot and are never written as n. With technical replicates and the nested
  template, each unit is a subcolumn with its replicates as rows, so Prism's nested t test
  counts units, not wells.
- At the analysis choices the study's Decision Cards hold (a decided option, or the
  recommended one while a card is open), with every choice and who made it in the provenance.

Why log2: on the demo study (64 plates, 58 genes, the same groups and the same five reference
genes in every row), the usual route from the instrument to Prism changes conclusions the
engine makes (`docs/studio-measured.md`, measured with qPilot's own engine):

| Route into Prism | Conclusions (of 58) that differ from the engine |
|---|---|
| ΔΔCq in a spreadsheet (efficiency assumed 2.0), Welch's t test on log2 | 4 |
| … then 2^-ΔΔCq pasted into Prism, Welch's t test on the linear scale | 14 |
| … the same with the equal-SD (Student) t test | 21 |

A t test on fold changes on the linear scale is the pattern Prism permits without warning.
Handing Prism log2 values removes it.

## Which test, and why Welch on log2

The `two_groups_log2` template runs **Welch's unpaired t test on the log2 values**, the same
test the engine uses (p < 0.05 and at least two-fold for an up or down call). Relative
quantities are roughly log-normal, so their logs are roughly normal; Welch's test does not
assume the two groups have the same spread. Because the values are already log2, the template
uses the ordinary t test, **not** Prism's lognormal t test (Prism 10.5 and later), which would
take the log a second time. The graph shows every unit with the mean and its 95 % confidence
interval on a linear axis of log2 values, never bars ± SEM.

Manual gate for the template (plan step 2.4): Prism's Welch P value for ODC1 on the demo must
equal the engine's to three significant figures. The engine's ODC1: fold 3.59×, p 2.29e-08
(53 vs 294 tumours). Prism number and screenshot: **not recorded yet** (no seat).

## How the bridge works (Mode S)

qPilot writes plain files; the scientist's own licensed Prism does all reading and writing of
Prism files, through Prism's documented script language. qPilot never writes or parses
`.prism` or `.pzfx`.

| File | What it is |
|---|---|
| `<gene>.csv` | One table per gene (UTF-8, comma-separated, `\n` line ends, fixed column order) |
| `run.pzc` | Prism script: for each gene, open the template, `GoTo D, 1`, `Import` the CSV, `SetSheetTitle` with the record ref and chain head, `Save` `<gene>_qpilot_<record>.pzfx`, append the provenance note to the Info sheet, export the graph (PDF by default), `Close`; finally write `qpilot_done.txt` |
| `send_back.pzc` | Prism script: open each saved project and `ExportTable` its data table to `sent_back/<gene>.csv`; write `qpilot_sent_back_done.txt`; never `Close` (that would discard unsaved edits) |
| `qpilot_provenance.json` | qPilot version and vendored LinRegPCR commit, study id, input sha256, chain head, design hash, every choice with its actor, each gene's holds fraction and confidence level with reasons, the conclusion rule, the caption in fact tokens and every other file's sha256. The sha256 of this file exactly as written is kept in `qpilot_bundle.json` (`info.provenance_sha256`), so the bundle sha256 covers every byte of it |
| `qpilot_bundle.json` | The `PrismBundle` the round trip is compared against, with its own sha256 (`bundle_sha256`) |
| `README.txt` | Short instructions for the scientist |
| `<template>.pzt` | The hand-made template, copied in when it exists (`qpilot/prism/templates/README.md`) |

One project per gene: a script can only make a new data table by duplicating one, and where
`DuplicateFamily` leaves the script afterwards is not documented, so each gene gets its own
copy of the template.

Prism runs a script invisibly and gives no completion signal, so each script's last action
writes a done file, which is GraphPad's own recipe (`OpenOutput "done.txt"`, `WText`,
`CloseOutput`). Studio deletes an old done file, launches the script and polls for the new
one:

- Windows: `"<prism.exe>" @"<folder>\run.pzc"` (documented);
- macOS: AppleScript `open POSIX file "<folder>/run.pzc"` inside `tell application "<Prism>"`
  (the form is documented; the application name and use from `osascript` are [R]). Double-
  clicking a `.pzc` file on macOS also starts Prism and runs it.

Every script command qPilot uses, with the GraphPad page that documents it, is listed in the
docstring of `qpilot/prism/script.py` and tested against an allow-list. Paths go in double
quotes; a path or text with a quote, a line break, another control character or non-ASCII
characters is refused.

Commands:

```
qpilot export prism --study <id> [--template two_groups_log2] [--genes ODC1,NTRK1] [--share] --out <folder>
qpilot prism verify --bundle <folder>
qpilot prism diff --study <id> --bundle <folder> --sent-back <folder>/sent_back
```

`--share` pseudonymises the row titles (sample names). The output folder must be new or
empty; nothing is written into the study's workspace. The MCP preview
(`qpilot.prism.preview`) returns what an export would write and writes nothing.

`qpilot prism verify` (and every round trip, before anything else) checks the bundle folder:
the bundle's own sha256, every file's sha256, and the provenance file byte for byte against the
sha256 the bundle holds, so a changed choice, actor, number or caption is reported, and so is
the same content written another way. A JSON file that holds a key twice anywhere is refused
as unreadable: a person reading it would see the first value, a JSON parser the last. The
checksums are plain sha256: they show an edit made without recomputing them, not a forgery
that recomputes them all. A bundle exported before the provenance file was checked by its
bytes does not verify; export it again.

## What sending the tables back checks

After editing in Prism, the scientist saves and runs `send_back.pzc`; `qpilot prism diff`
compares the exported tables with what came back (after checking the bundle's own checksums):

- **changed**: a number that differs from the exported value rounded to the returned text's
  own number of decimals (Prism may print fewer digits than qPilot wrote). It becomes a
  `prism.value_edit` proposal, "this value no longer matches the record", restore by default.
  It is never accepted silently.
- **missing**: a value qPilot wrote that comes back empty. Mode S cannot yet tell an exclusion
  from a deletion, so the proposal asks which, and why.
- **excluded**: only when the returned text carries an explicit exclusion marker. Which marker
  `ExportTable` writes for an excluded value, if any, is step 0.1's question; the hook exists
  and is off.
- **added or removed rows and columns**, and **unreadable** files or cells.

A missing or excluded value becomes a `prism.exclusion_reason` proposal ("You excluded sample
X for GENE in Prism. Reason?") with the engine's consequence: that gene's comparison again
without the value, fold change, p and conclusion before and after, and how many of all genes'
conclusions change. On the demo, leaving out ODC1's highest tumour (1496, MYCN-high) gives
3.590× → 3.319×, still up, and 0 of 58 conclusions change. Proposals are made by a rule; only
a person accepts them.

Tables sent back are untrusted input: at most 200 files, 5 MB each and 100,000 cells in all;
links and folders are not followed; a cell is a number only in plain decimal or exponent
notation and finite; nothing is evaluated; any other text is quarantined under a `text_id` and
never interpreted.

## Still unverified: step 0.1 on a real Prism seat [R]

Plan step 0.1's seven facts, none checked yet:

1. The Prism version, operating system and default save format of the seat.
2. That `Open <template>.pzt` → `GoTo` → `Import <csv>` → `Save <name>.pzfx` works on that
   version and the analyses recalculate, and which import options a script's `Import` applies
   (first row as titles, first column as row titles).
3. Whether `ExportTable` keeps excluded values, and how they appear in the CSV (and how titles
   and nested subcolumns appear).
4. Whether a script can set Info notes or constants (`SetInfo`) and table titles
   (`SetSheetTitle`).
5. The launch route on that OS (`prism.exe @script.pzc` on Windows, AppleScript on macOS), the
   macOS path form in `SetPath` (documented for Prism 5 only) and the done-file pattern.
6. The `TableType` values Prism writes for Nested and Multiple-variables tables, and how CSV
   columns fill a nested table's subcolumns on import.
7. Which t test the dialog pre-selects (Welch in the current guide; equal SDs in Prism 9), and
   whether the lognormal t tests (Prism 10.5 and later) are present.

Also open: how Prism decodes a `.pzc` file (qPilot writes ASCII only; CRLF for Windows, LF for
macOS), and whether Prism 10/11 still save `.pzfx` from a script.

## Why Mode X is off

Mode X would have qPilot fill (and later read) the documented XML data portion of a `.pzfx`
template itself, so no Prism would be needed on the machine. It is not built. GraphPad's
Prism Terms (effective 10 June 2025) forbid a licensee to "permit any third party to parse any
proprietary elements of the Product", naming `.pzfx` and `.prism` files, "for any commercial
purpose", and forbid reverse engineering, while GraphPad's own FAQ invites other software to
replace the data portion of a `.pzfx`. The clause binds Prism users, and qPilot's users are
Prism users, so whether an open-source tool filling or reading the documented data portion
counts as parsing proprietary elements, and whether "commercial purpose" covers industry users
of a free tool, are questions for the licence review in plan step 0.5. Until that answer is
filed here in writing, qPilot ships Mode S only and `prism/pzfx_xml.py` does not exist. This is
not legal advice; it is the question to ask.

## Templates

The three templates (`two_groups_log2.pzt`, `many_genes_log2.pzt`, `nested_superplot.pzt`) are
made by hand in Prism; how to build each is in
[`qpilot/prism/templates/README.md`](../qpilot/prism/templates/README.md). None exists yet.
`many_genes_log2` needs a grouped table (genes as rows), which the frozen `PrismLayout`
(`column` | `nested`) cannot describe, so its export waits for a contract change.

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.
