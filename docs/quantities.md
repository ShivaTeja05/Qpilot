# Quantities: absolute quantification from a standard curve

Relative quantification compares a gene between groups. Many labs also need **how much** was
there: copies of a virus per reaction, copies per µL of extract, copies per ng of RNA. qPilot
reads that from a dilution series of known quantity measured with the samples (a standard
curve), with the interval a reader needs and the limits that say when a number is not to be
trusted. The method, its formulas and its references are in
[`methods/absolute_quantification.md`](../methods/absolute_quantification.md).

## Where it shows

**Results → Quantities** (after the design and the curves are confirmed, like every result): one
card for the study, an assay picker when there are several.

* **The standard curve**: Cq of every standard well against its quantity (log scale), the fitted
  line and its 95 % prediction band, standards that were not detected at the foot of the chart,
  the LOD and LOQ as dashed lines, and every unit read from the curve as a diamond (one outside
  the standards is visibly extrapolated). "View as table" lists each level: wells detected, mean
  and SD of Cq, the quantity it reads back as, and the CV.
* **The numbers**: slope, efficiency with its 95 % confidence interval, R², the levels, the LOD
  (empirical, and modelled by a logistic fit when levels are partly detected), the LOQ, where the
  standards' quantities came from, and what MIQE would question (efficiency outside 90–110 %,
  R² below 0.98).
* **Every biological unit**: wells detected, mean Cq, the quantity per reaction with its 95 %
  prediction interval, its group (a groups design), and notes in words: *above the top standard*,
  *below the lowest standard* (extrapolated), *below the limit of quantification*, *below the
  limit of detection*, *not detected in any well*, *some wells were not detected*, *read from
  another plate's curve*. "Flagged" lists only those with a note.
* **Per µL and per ng**: *Set the reaction input…* records what one reaction held (µL of
  template, ng of input, and what the standards count when the file does not say), with a reason,
  in the session's decision record. The study is analysed again with it; no fold change, call or
  Decision Card changes, and the blind stages stay confirmed.

A study without standards shows no card. Standards without a quantity (QuantStudio's
`Std 1` … `Std 5` are level numbers, not quantities) are listed with what to do.

> **Check the standard curve's wells.** A standard well counts as detected when it has a Cq and a
> quantity, even when LinRegPCR calls it "no amplification". On the QuantStudio 7 Pro eDNA curve of
> the corpus three flat wells enter the fit and give 154 % efficiency, R² 0.41 (87 %, R² 0.996
> without them). If a curve looks wrong, leave the flat wells out in Curves, with a reason
> ([science review](science-review-2026-10.md), J1, recommends requiring LinRegPCR's call).

## Giving the standards their quantities

The file's own quantities are used when it declares them (RDML `<quantity>`; the demo's are in
copies). Otherwise, on **Design → Set the design on this page → Samples**: select the standards,
choose *Standard*, give the **highest quantity** and the **dilution step** (10 for a ten-fold
series); the quantities are written in plate order. **From ng to copies…** beside the highest
quantity works it out from a mass: ng (or ng/µL), the length in base pairs (dsDNA) or bases
(ssDNA, RNA), and the molecule; *Use as the highest quantity* puts the result in the field.
A person's quantities take precedence over the file's.

## A gene detected in one group only

When a gene is measured in both groups but no unit of one group amplified, there is no fold
change to give (a ratio to nothing), and qPilot no longer makes one up from the lowest value
seen. Results lists it under *genes with no result* as **detected only in ⟨group⟩ (k of n
biological units)**, with that group's mean ΔCq (its Cq minus the mean Cq of the reference genes);
no cell of the choice grid compares a group made only of filled-in values, so the robustness and
the Decision Cards treat it the same way.

## API, CLI, exports

| | |
|---|---|
| `GET /api/studies/{id}/quantities` | every assay with standards: curves, LOD, LOQ, counts |
| `GET /api/studies/{id}/quantities/{target}` | one assay: points, levels, the prediction band, every unit |
| `POST /api/studies/{id}/quantities/reaction` | `{template_ul, input_ng, unit, reason, expected_head}` (a person; a Studio session) |
| `GET /api/tools/copies?ng=&length=&kind=&step=&levels=` | ng to copies and a dilution series |
| `qpilot quantify FILE… [--quantity "Std 1=1e5"] [--csv out.csv]` | any RDML file or instrument export, no study needed (absolute-only plates) |
| `qpilot copies --ng 1 --length 3000 [--kind dsDNA] [--step 10 --levels 6]` | ng to copies |
| Exports (CSV, Excel, supplement) | tables *Standard curves* and *Quantities* after *Per well*; a Methods paragraph; MIQE 2.0 items 5.13 (LOD) and 5.14 (dynamic range) |

Absolute-only plates (no comparison of groups, e.g. a viral-load run) cannot yet reach Results on
the page, which needs a comparison; `qpilot quantify` handles them today.
