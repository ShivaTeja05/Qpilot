# Analysing a table of Cq values (no curves)

Many labs keep only the Cq values the instrument software exported: an Excel or CSV table
(sample, gene, condition, gene type, Cq), typed or saved by hand, or an RDML file without
amplification curves. qPilot analyses such a file end to end, with the same Studio stages, the
same engine and the same Analysis Record as a file with curves. This page says what works without
curves, what does not, and why curves are better when you have them.

## How to open one

Drop the table (or the RDML file) on **Open**, alone or with a sample sheet. A table with a
condition, group or animal column is its own sample sheet; a *Gene type* column (Reference,
Housekeeping, Target) declares the reference genes. The page says *"holds Cq values only (no
amplification curves)"* for each experiment, and then:

1. **Design** (blind): set the reference genes, the groups and the comparison on the Design page
   (or accept what the rules propose from the table). Type the dilution series, if the plate has
   one, as standards with their quantities: it gives the assays' efficiency (below).
2. **Curves** (blind): there is no curve to judge, so **Check the curves** proposes the
   amplification rule (*a well counts when the file gives it a Cq*; the Cq cut-offs 40, 38 and
   35 stay choices whose consequences are shown later) and the page shows **Your Cq table** to
   confirm instead of curves: each sample's Cq per well and plate, the wells without a Cq, the
   replicate sets whose spread is wider than the Run Gate's rule G-REP expects (the same numbers),
   each assay's efficiency, and what does not apply. No group, fold change or p-value is shown.
3. **Results**, Decision Cards, Trace, Prism, the report and the record follow as usual.

The same works from the CLI and MCP: `qpilot run`, `qpilot record`, `qpilot verify` and
`qpilot rerun` treat a Cq-only file like any other.

## What qPilot does with the Cq values

Each well's starting quantity is **N0 = E^−Cq**, with E its assay's efficiency:

* **From the assay's dilution series** when the design has one on the plate (at least three
  levels with a Cq and a falling line): E = 10^(−1/slope) of Cq against log10 quantity, exactly
  the fit of the efficiency model *standard_curve*. A plate without its own series for an assay
  uses the mean E of the assay's series on its other plates (one efficiency per assay). A series
  whose E is outside (1.0, 2.3), which no PCR can have, is not used, and the page says so.
* **Otherwise assumed to be 2.0**: every cycle doubles the product, the 2^−ΔΔCq assumption. With
  an assumed efficiency for every assay, the log2 fold change is exactly −ΔΔCq of your Cq values.

Everything after that is the engine as it is for curves: technical replicates averaged within a
biological unit (never counted as n), the reference genes (geNorm when there are three or more),
Welch's test, the conclusion rule, the robustness grid, Decision Cards, Trace (to the well's
Cq), the exports and the Analysis Record. The robustness grid varies only the choices that apply:
the reference set, the Cq cut-off, the non-detect rule, and, when a dilution series gives an
efficiency, an assumed 2.0 instead (*Also test efficiency models*).

## What does not apply, and says so

Without curves these are **not applicable**, said in those words on the page, never a failure:

| Needs a curve | Why |
|---|---|
| LinRegPCR's baseline, efficiency and fit per well | there is no curve to fit |
| The Curve Judge | there is no curve to read |
| The raw-ness check (Import Trust) | there are no curves whose processing could be checked |
| Melt curves (G-MELT) | the file has none |
| The efficiency models *each well's own* and *one per amplicon* | they are LinRegPCR's numbers |

The baseline and the Cq themselves were set by the instrument software before export: the report
asks you to state that software, its baseline setting and its threshold (MIQE 2.0 item 5.3), and
says that no raw fluorescence was available (5.1) and no curve examples can be shown (5.7).

**Confidence** is capped by qPilot policy (as for the Import Trust card's *Cq only*): at **Low**
while any analysed assay's efficiency is assumed, at **Moderate** when every assay's comes from
its dilution series, because no well's amplification curve could be checked either way.

## Why curves are better

A Cq alone says *when* a well crossed a threshold, not *how* it got there. With the raw curves,
LinRegPCR (Ruijter et al., 2009) fits each well's own baseline and measures each well's own
efficiency in its log-linear phase, so the assay's efficiency is measured in the study's own
wells rather than assumed (an assumed 2.0 where the true efficiency is 1.9 misstates a
5-cycle difference by about 29 %),
a plateau or a noisy, late or flat curve is seen and can be left out, the Curve Judge checks the
calls, and melt curves show whether one product was made. If the instrument software can still
export the amplification data (RDML, or the raw RFU/Rn tables), open that export instead: the
same design, the stronger analysis.

The Cq-only path is in `qpilot/qpcr/cq_only.py` (efficiency, cap, words),
`qpilot/qpcr/curves.py` (`cq_only_run`, `without_curves`), the Curves stage's table in
`qpilot/web/cq_table_views.py` (`GET /api/sessions/{sid}/cq-table`) and
`frontend/src/features/curves/CqTablePanel.tsx`.
