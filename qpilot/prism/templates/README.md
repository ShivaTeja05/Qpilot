# Prism templates (made by hand in Prism)

Step 2.4 of the Studio plan is manual: a person builds each template once in GraphPad Prism,
and qPilot only supplies data. GraphPad recommends this pattern: build the project in Prism,
replace the data, and Prism recalculates the analyses and graphs.

**Status: none of the three template files exists yet.** There is no Prism seat on the
development machine. Until a template is here, `qpilot export prism` still writes the CSV
tables, `run.pzc`, `send_back.pzc`, `qpilot_provenance.json` and `README.txt`, and the README
in the bundle says which template to build. Menu names below follow GraphPad's current user
guide; anything marked [R] is unverified until plan step 0.1 on a real seat.

| Template | Table type | Analysis | Graph | Exported by qPilot? | Prism version saved in |
|---|---|---|---|---|---|
| `two_groups_log2.pzt` | Column | Welch's unpaired t test on log2 | every point, mean ± 95 % CI | yes (column layout) | not made yet |
| `many_genes_log2.pzt` | Grouped | multiple unpaired t tests, FDR | one row per gene | not yet (see below) | not made yet |
| `nested_superplot.pzt` | Nested | nested t test | markers by biological unit | yes (nested layout) | not made yet |

## Rules for every template

1. **qPilot never opens, reads or writes a template.** It copies the file into the bundle
   folder byte for byte, and Prism opens it when `run.pzc` runs (`Open "<template>.pzt"`).
2. **One data table, and it is the first one.** `run.pzc` goes to `GoTo D, 1` and imports the
   gene's CSV there. Leave the data table empty in the saved template: whether `Import`
   clears cells beyond the new data is [R].
3. **Set the import options once, by hand, before saving.** Make an example bundle
   (`qpilot export prism --study <id> --genes ODC1 --out example`) and import
   `example/ODC1.csv` into the data table with: comma delimiter, decimal point `.`, first row
   as column (data set) titles, first column as row titles. Check that the values land
   unchanged, then clear the data and keep the analysis and graph. Whether a script's
   `Import` then uses the same options is [R] (step 0.1).
4. **Keep the Info sheet** (Prism's default "Project info 1"). `run.pzc` appends the
   provenance note to its notes with `SetInfo "...", 1, 2`.
5. **Save as a template** (`.pzt`) under the exact file name below into this folder, and fill
   in the "Prism version saved in" column (version, operating system, date, who).

## `two_groups_log2.pzt`

What it receives: a column table, first column `Sample` (row titles: one biological unit per
row), then one column per group in the design's order (on the demo: `MYCN-high`, `rest`). Each
unit's log2 relative quantity is in its group's column; the other cell in its row is empty.

1. New project: **Column** table, "Enter replicate values, stacked into columns".
2. Analysis: **Analyze → Column analyses → t tests (and nonparametric tests)**, columns A and B.
   - Experimental design: **Unpaired**; **Parametric**.
   - **Welch's correction: do not assume equal SDs** (Prism's current default is Welch;
     Prism 9 defaulted to equal SDs, so check it).
   - Do **not** choose the lognormal t test: the values are already log2, and a lognormal
     test would take the log a second time.
   - Two-tailed P value; report the 95 % confidence interval of the difference.
   - Options: show the exact P value with at least four significant digits (not
     "<0.0001"); the exact wording of this option differs between versions [R].
3. Graph: the column table's default **scatter dot plot**, every point shown, **mean with
   95 % CI** as error bars. Y axis title: **log2 relative quantity**. Linear Y axis (the values
   are already logs). No bars.

**Manual gate (step 2.4).** Export the demo study with `--genes ODC1`, put this template into
the bundle folder and run `run.pzc`. Prism's Welch P value for ODC1 must equal the engine's to
three significant figures. The engine's ODC1 on the demo: fold 3.59× (log2 difference 1.844),
p 2.29e-08, n 53 vs 294. Record both numbers, the Prism version and a screenshot in
`docs/prism.md`. This is the first time Prism reproduces a qPilot number independently.

## `many_genes_log2.pzt`

What it would receive: one **grouped** table, one row per gene, one data set per group, the
biological units as side-by-side subcolumns.

1. New project: **Grouped** table, "Enter … replicate values in side-by-side subcolumns", with
   as many subcolumns as the largest group has biological units (the maximum number of
   subcolumns is [R]).
2. Analysis: **Analyze → Grouped analyses → Multiple t tests – one per row**: unpaired,
   parametric, **do not assume equal SDs (Welch)**, then **multiple comparisons by false
   discovery rate** (two-stage step-up method of Benjamini, Krieger and Yekutieli, Q = 5 %).
3. Graph: a volcano plot (log2 difference against −log10 P) or the default results graph.

**Not exported yet.** The frozen contract (`PrismLayout` in `qpilot/schemas_studio.py`) knows
only the `column` and `nested` layouts, so `qpilot export prism --template many_genes_log2`
refuses with a message. A `grouped` layout needs a contract change first.

## `nested_superplot.pzt`

What it receives (only when the study has technical replicates): a nested table, first column
`Replicate` (row titles `rep 1`, `rep 2`, …), then per group one subcolumn per biological unit
with its technical replicates stacked as rows. Every group is padded with empty subcolumns
(`<group>/empty_<k>`) to the largest group's number of units, because a nested table has one
subcolumn count for all data sets [R]. GraphPad: subcolumn titles cannot be imported, so the
unit names travel in the CSV header and in `qpilot_bundle.json`.

1. New project: **Nested** table (Prism 8 or later), with as many subcolumns as the largest
   group has biological units.
2. Analysis: **Analyze → Nested analyses → Nested t test**, unpaired. Technical replicates are
   then nested within units, so n is the number of biological units, never wells.
3. Graph: a nested scatter plot (SuperPlot style): every replicate shown, **markers or colours
   by subcolumn (biological unit)**, with each unit's mean, and mean ± 95 % CI per group.
   Y axis title: **log2 relative quantity**.

How CSV columns fill a nested table's subcolumns on import is [R] (step 0.1).

---

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.
