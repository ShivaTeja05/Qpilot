# qPilot and GraphPad Prism

Scientists take qPCR results into GraphPad Prism for statistics and figures. qPilot's Prism
bridge hands Prism a project it cannot misread, carries the record into the project, and notices
what a scientist changed in Prism afterwards. It does the qPCR-specific part that Prism does not
do (raw curves, per-assay efficiency, several reference genes, robustness across reasonable
analyses) and leaves Prism to do what scientists already trust it for: familiar statistics and
publication graphs.

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.

> **Not yet opened in a real Prism by the qPilot team.** There is no Prism installation or
> licence on the development machine. The project file follows GraphPad's published XML schema
> (KB 1638) and the structure of files saved by Prism 6.0f, 7.0d, 8.0 and 10.2.2; every Prism
> behaviour that this does not settle is marked **[R]** below and in the code. The bundle also
> holds the same tables as CSV, so a project Prism refused would still leave the numbers usable.

## What a scientist gets

Send to Prism (the page) or `qpilot export prism` (the terminal) writes one folder, zipped for
download:

| File | What it is |
|---|---|
| `qpilot_<study>.pzfx` | **The Prism project.** It opens in GraphPad Prism as it is (double-click it, or File > Open): no template, no script. It holds an Info sheet, one Column table per gene and a Grouped table of all the genes (below). |
| `qpilot_<study>_replicates.pzfx` | Only when biological units have technical replicates: one Nested table per gene (one subcolumn per unit, its replicates as rows). A file of its own because the attributes Prism uses for a Nested table are inferred, not documented [R]: if a Prism version reads them otherwise, the main project is unaffected. |
| `<gene>.csv`, `<gene>_replicates.csv` | The same tables as plain CSV (UTF-8, commas, `\n`), the bytes the round trip compares against. |
| `README.txt` | Plain steps for Windows and macOS (this computer's first): open the project, add the t test and the graph, bring changes back. |
| `qpilot_provenance.json`, `qpilot_bundle.json` | How every value was made, and checksums (`qpilot prism verify`). |
| `run.pzc`, `send_back.pzc` | Only with `--scripts`: the optional Prism scripts for a template made by hand (below). |

### The project's contents

* **Info sheet "qPilot provenance"** (constants and notes): the study id, the decision record's
  head (sha256), the design hash, the input file's sha256, the scale, the groups, the reference
  genes, the undetermined-well rule, the conclusion rule, the test qPilot used, every analysis
  choice with who decided it (a person, qPilot, or not decided: the recommended option) and the
  person's reason from the decision record, the caption, the qPilot version and the
  not-affiliated line.
* **A Column table per gene** (`TableType="OneWay"`): first the row titles (one biological unit
  per row), then one data set per group in the design's order; each unit's log2 relative
  quantity is in its group's column, the other cell empty. With several comparisons planned in
  the design (`StudyDesign.comparisons`), a further Column table per gene and comparison
  (`<gene>__<comparison key>`); the first comparison keeps the plain names.
* **A Grouped table of all the genes** (`TableType="TwoWay"`, `YFormat="replicates"`): genes as
  rows, groups as data sets, the biological units as side-by-side subcolumns titled with the
  unit's name (`SubColumnTitles OwnSet="1"`), for Prism's "Multiple t tests – one per row".
  A group with more than 256 units needs Prism 9 or later (512 subcolumns, KB 845); beyond 512
  the table is left out and the bundle says so.
* Every table title carries the record ref and the short chain head
  (`ODC1 log2 RQ - qPilot <study> - chain <12 hex>`), as the CSV route always did.

### What qPilot cannot write: the test and the graph

A `.pzfx` file has two parts: the data tables and Info sheets as plain XML, which GraphPad
documents and invites other programs to write ("All you have to do is replace the data portion
of a .PZFX file, and resave it", FAQ 913), and Prism's analyses, graphs and layouts as a
compressed binary block only Prism writes. qPilot writes the first part only, so the project
opens with its tables and Info sheet and no analysis or graph. The README and the page say
exactly which clicks add them (the names may differ slightly between Prism versions):

1. Click a gene's table under Data Tables.
2. The test: **Analyze** → "t tests (and nonparametric tests)" → OK; choose Unpaired,
   Parametric and **Welch's correction** (do not assume equal SDs) → OK.
3. The graph: **New Graph** → the scatter plot of individual values with "Mean with 95% CI"
   → OK.

Prism keeps the analysis and the graph when the person saves the project; when values are later
excluded or changed in Prism, Prism recalculates them.

## What goes into Prism, and why log2

- **Log2 relative quantities**: log2 of the gene's efficiency-corrected starting quantity
  (LinRegPCR N0) minus the mean log2 of the reference genes, per biological unit. These are the
  engine's own numbers (`qpcr.quant.relative`), written so they read back bit for bit (a test
  compares `float.hex`).
- **One value per biological unit** in the Column tables. Technical replicates are averaged per
  unit by qPilot and never written as n; the Nested tables show them as rows inside each unit's
  subcolumn, so Prism's nested t test counts units, not wells.
- At the analysis choices the study's Decision Cards hold (a decided option, or the recommended
  one while a card is open), with every choice and who made it in the Info sheet and the
  provenance.

Why log2: on the demo study (64 plates, 58 genes, the same groups and the same five reference
genes in every row), the usual route from the instrument to Prism changes conclusions the
engine makes (`docs/studio-measured.md`, measured with qPilot's own engine):

| Route into Prism | Conclusions (of 58) that differ from the engine |
|---|---|
| ΔΔCq in a spreadsheet (efficiency assumed 2.0), Welch's t test on log2 | 4 |
| … then 2^-ΔΔCq pasted into Prism, Welch's t test on the linear scale | 14 |
| … the same with the equal-SD (Student) t test | 21 |

A t test on fold changes on the linear scale is the pattern Prism permits without warning.
Handing Prism log2 values removes it. The page's "What the usual route into Prism would change"
panel shows these counts on the study's own plates (stored facts; the server caches the answer
per study and results file, so a warm request costs only the blind gate, ~0.4 s on a busy
laptop; while the session's file is still being read after a restart it answers `warming`
instead of waiting).

## Which test, and why Welch on log2

Welch's unpaired t test on the log2 values is the test the engine uses (p < 0.05 and at least
two-fold for an up or down call). Relative quantities are roughly log-normal, so their logs are
roughly normal; Welch's test does not assume the two groups have the same spread. Because the
values are already log2, use the ordinary t test, **not** Prism's lognormal t test (Prism 10.5
and later), which would take the log a second time; the Info sheet says so. Graph every unit
with the mean and its 95 % confidence interval on a linear axis of log2 values, never bars ±
SEM.

Manual gate (plan step 2.4): Prism's Welch P value for ODC1 on the demo must equal the engine's
to three significant figures. The engine's ODC1: fold 3.59×, p 2.29e-08 (53 vs 294 tumours).
Prism number and screenshot: **not recorded yet** (no seat).

## Bringing changes back (the round trip)

After editing in Prism the scientist saves the project (File > Save; if Prism asks for a format,
keep Prism XML, `.pzfx`). qPilot then reads the saved project:

- on the page, Round trip: upload the saved `.pzfx` (Prism on another computer; the file is
  kept in the bundle's `returned/` folder), or give the folder or file it was saved in (when
  Prism runs on this computer that is the bundle folder, prefilled);
- in a terminal: `qpilot prism diff --study <id> --bundle <folder> [--returned <file or folder>]`.

It checks the bundle's own checksums first, finds each exported table in the saved project by
its exact title, and compares it with the checksummed CSVs:

- **excluded**: a value Prism marks excluded (`<d Excluded="1">`, shown in blue italics with an
  asterisk in Prism) becomes a `prism.exclusion_reason` proposal: "You excluded sample X for
  GENE in Prism. Reason?";
- **deleted**: an empty cell where qPilot wrote a value becomes the same proposal, worded "You
  deleted …" (a saved project tells a deletion from an exclusion, which the CSV route cannot);
- **changed**: a number that differs from the exported value rounded to the saved text's own
  decimals becomes a `prism.value_edit` proposal ("this value no longer matches the record";
  restore by default). It is never accepted silently. A comma decimal separator (`3,5`, which
  Prism writes in some locales) reads as a point;
- a value excluded, deleted or changed in the **table of all genes** is the same value as in the
  gene's Column table and is reported once, as that table's cell;
- a table renamed or deleted in Prism is reported (never guessed); tables a person added are
  left alone; a project given unchanged since export says "save the project in Prism first";
  when only the main project is given, the Nested tables are not compared (the notes say so).

Each exclusion's consequence is computed by the engine as accepting it would apply it: the study
analysed again with the value excluded (the same function applies it to the design, then the
engine runs at the exported choices, together with the exclusions a person already accepted),
so the numbers a person approves are the numbers the engine then reports. It shows that gene's
fold change, p and conclusion before and after, and how many of all genes' conclusions change; a
gene the engine then withholds reads "withheld", with the engine's reason. On the demo, leaving
out ODC1's highest tumour gives 3.590× → 3.319×, still up, and 0 of 58 conclusions change (a
test checks this through the saved-project route). Proposals are made by a rule; only a person
accepts them.

A value of the Nested table is one technical replicate. Its proposal names the replicate
(`GENE/unit/rep n`) and carries the exact well behind that row of the exported table (`well`:
`<run_id>/<well>`), and accepting it excludes that well.

What comes back is untrusted input. A project file is read only when it is at most 64 MB and a
regular file (links are refused, never followed), parsed with lxml with entities, DTDs and the
network off (a `<!DOCTYPE` or `<!ENTITY` is refused before parsing), at most 2,000 tables and
2,000,000 cells; Prism's binary block is skipped unread; a cell is a number only in plain decimal
or exponent notation and finite; nothing is evaluated; any other text is quarantined under a
`text_id`. A folder may hold at most 20 project files.

The older CSV route still works: with `--scripts`, `send_back.pzc` exports the tables to
`sent_back/`, and the round trip reads that folder as before (an empty cell there may be an
exclusion or a deletion, so its question asks which).

## A draft stays valid while its numbers do (no needless re-draft)

The Prism project is drafted as a proposal and accepted by a person, for one analysis. A
decision that changes the analysis id but no number in the exported tables (for example testing
the efficiency models as a further choice and deciding that card with the planned option) used
to mark the accepted draft as belonging to "an earlier analysis", so it had to be drafted
again. Now the draft keeps the digest of the tables it exports (`tables_sha256`: each table's
gene, layout, name and CSV sha256; titles, which carry the record ref and chain head, are left
out). A project accepted for an earlier analysis is **still current** when the current
analysis's tables have the same digest (`Studio.prism_project`); the page says "Still current
for this analysis" and Send works without a new draft. A draft made before digests were kept is
compared by the tables its own analysis exports now. Comparing rebuilds both analyses' tables
(seconds), so the reading routes never wait for it: they report `checking` and a background
`prism.check` job compares them and tells the page.

## Provenance and checksums

`qpilot_provenance.json` holds the qPilot version and vendored LinRegPCR commit, study id, input
sha256, chain head, design hash, every choice with its actor, each gene's holds fraction and
confidence level with reasons, the conclusion rule, the caption in fact tokens and every checked
file's sha256. Its own sha256 is kept in `qpilot_bundle.json` (`info.provenance_sha256`), so the
bundle sha256 covers every byte of it. The project files are not checked files (Prism saves them,
which is the point); their sha256 as written is kept in the bundle's info (`project_sha256`,
`replicates_project_sha256`). `qpilot prism verify --bundle <folder>` (and every round trip,
before anything else) checks the bundle: a changed choice, actor, number or caption is reported.
A JSON file that holds a key twice anywhere is refused as unreadable. The checksums are plain
sha256: they show an edit made without recomputing them, not a forgery that recomputes them all.

## Commands

```
qpilot export prism --study <id> [--genes ODC1,NTRK1] [--share] [--platform windows|macos] --out <folder>
qpilot export prism ... --scripts [--template two_groups_log2] [--graphs pdf] [--prism-dir <dir>]
qpilot export prism ... --scripts-only          # the older bundle: CSV tables and Prism scripts
qpilot prism verify --bundle <folder>
qpilot prism diff --study <id> --bundle <folder> [--returned <saved .pzfx or its folder>]
qpilot prism diff --study <id> --bundle <folder> --sent-back <folder>/sent_back
```

`--share` pseudonymises the row titles (sample names). The output folder must be new or empty;
nothing is written into the study's workspace. The MCP preview (`qpcr_prism_preview`) returns
what an export would write (the project's tables included) and writes nothing; `qpcr_prism_diff`
takes the bundle folder (holding the saved project) as its returned folder.

## The optional scripts (Mode S, for a template made by hand)

Before the project file existed, the bundle relied on Prism scripts (`.pzc`) and a template made
by hand in Prism (`qpilot/prism/templates/README.md`). That route stays as an extra for people
who keep their own templates: `--scripts` adds `run.pzc` (open the template, import each table,
save one project per gene, export the graph, write `qpilot_done.txt`) and `send_back.pzc` (export
each data table to `sent_back/`). It imports only the tables of the template's layout. Every
script command qPilot uses, with the GraphPad page that documents it, is listed in the docstring
of `qpilot/prism/script.py` and tested against an allow-list; paths with a quote, a line break
or non-ASCII characters are refused. The page never shows the scripts' command line as the main
instruction (it is in a collapsed "optional" section of the Send answer only for such bundles).

## Writing and reading `.pzfx`: licence position

Earlier versions did not write `.pzfx` themselves ("Mode X off"), pending a licence question:
GraphPad's Prism Terms (10 June 2025) forbid a licensee to "permit any third party to parse any
proprietary elements of the Product", naming `.pzfx` and `.prism` files. qPilot now writes and
reads only the part of a `.pzfx` that GraphPad documents as plain XML and invites other programs
to write (FAQ 913, KB 1638); it never writes, decodes or parses the binary analyses/graphs block,
which is skipped unread when a saved project comes back. The structure was learned from
GraphPad's published schema, files saved by Prism, and open-source readers and writers under the
MIT licence (`THIRD_PARTY_NOTICES.md`); no code was copied. A lab that wants certainty about its
own licence terms can still ask GraphPad; this is not legal advice.

## Still unverified on a real Prism seat [R]

1. That Prism 9, 10 and 11 open the project as written (no `Template` block, `CreatedByProgram`
   "qPilot", the default namespace), on Windows and macOS.
2. That `TableType="OneWay" ExtTableType="Nested"` with `YFormat="replicates"` and
   `SubColumnTitles` opens as a Nested table (inferred from the MultipleVariables pattern of
   Prism 10's own files); hence the separate replicates project.
3. That pressing Save on an opened `.pzfx` in Prism 10/11 keeps the `.pzfx` format (Prism 11's
   default is the new `.prism` format; the README says to keep `.pzfx` if asked).
4. The exact menu and button names of the clicks above in each Prism version.
5. Which t test the dialog pre-selects (Welch in the current guide; equal SDs in Prism 9), and
   whether the lognormal t tests (Prism 10.5 and later) are present.
6. For the optional scripts: the import options a script's `Import` applies, whether
   `ExportTable` keeps excluded values, `SetInfo`/`SetSheetTitle`, and the macOS `SetPath` form.

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.
