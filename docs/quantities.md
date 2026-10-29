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
  standards' quantities came from, what Taylor et al. 2010 would question (efficiency outside
  90–110 %, R² below 0.98), and the curve's g with which interval a quantity gets: the usual one,
  or Fieller's exact one when g is above 0.05 (a weak curve, where the usual one is too narrow).
  With fewer than 20 wells per level the LOD's words say that 95 % means every well, and that
  ten replicates around the limit make it firmer (Forootan 2017; Klymus 2020).
* **Standards that look wrong**: a standard whose Cq breaks the order of the series (earlier
  than most wells with ten-fold more template, or later than most with ten-fold less) or that
  sits more than 3.5 residual SDs off its line is listed under the curve, with what the curve
  would be without it (efficiency, R², LOQ). qPilot never leaves a standard out: **Propose
  leaving these out** files one proposal per well in Curves, and you accept or reject each with a
  reason (`POST /api/studies/{id}/quantities/standards`).
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

Wells LinRegPCR calls "no amplification" never enter a standard curve, even when they carry a
Cq (on the QuantStudio 7 Pro eDNA curve of the corpus three flat wells did, and gave 154 %
efficiency; without them 87.1 %, R² 0.9962; [science review](science-review-2026-10.md), J1).

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
| `POST /api/studies/{id}/quantities/reaction` | `{template_ul, input_ng, unit, reason, expected_head}` (a person; a Studio session). `expected_head` is required: the quantities view's `inbox_head`; 409 `stale` in words when something was decided since, 422 without it |
| `GET /api/tools/copies?ng=&length=&kind=&step=&levels=` | ng to copies and a dilution series |
| `qpilot quantify FILE… [--quantity "Std 1=1e5"] [--csv out.csv]` | any RDML file or instrument export, no study needed (absolute-only plates) |
| `qpilot copies --ng 1 --length 3000 [--kind dsDNA] [--step 10 --levels 6]` | ng to copies |
| Exports (CSV, Excel, supplement) | tables *Standard curves* and *Quantities* after *Per well*; a Methods paragraph; MIQE 2.0 items 5.13 (LOD) and 5.14 (dynamic range) |

## A run that only quantifies (no groups compared)

A viral load, a wastewater sample, the copy number of a construct, a sequencing library: many
runs measure **how much** and compare nothing. On **Design → Set the design on this page**,
*What is this study for?* says so: **Quantify samples** (the default is *Compare groups*). It is
your design item, recorded with your reason like any other; the rules propose it when the file
itself declares the standards' quantities (the run was set up as a standard curve) and no sample
sheet names groups, and you accept or reject it (it is never in "Accept all consistent").

* **The design needs standards with a quantity, not a comparison.** No reference gene, no
  groups, no comparison: *What the design still needs* asks instead for standards (at least three
  levels) with their quantities. Groups, if you set them, only sort and label the samples. A
  comparison you set earlier is kept aside and comes back if you switch to *Compare groups*.
* **Curves** as usual (blind).
* **Results** shows the quantities as the result: how many sample results are *quantified*,
  *below the limit of quantification*, *below the limit of detection*, *not detected* or
  extrapolated; the standard curve; each sample's quantity with its 95 % prediction interval and
  what is reported for it. Click a sample to see its wells: plate, Cq, detected or not, what each
  well alone reads as, the one more than 2-fold from the others named, and its curve.
* **The choices that can change what is reported** are Decision Cards: *which wells count as
  detected* (LinRegPCR's own call or a Cq cut-off at 40, 38 or 35 cycles) and *how precise a
  quantity must be to be reported* (the LOQ line, CV 35 % or 25 %). qPilot quantifies every
  sample under every combination; a card waits for you only when another option changes what is
  reported for at least one sample (its class, or its number by more than 2-fold), and lists
  each sample it changes. What you choose is what the Quantities view, the report and the
  exports use. Then confirm the choices.
* **Controls** runs every rule (NTC, no-RT, positive control, G-STD, G-MELT…) and asks whether
  leaving a rule's wells out changes what is reported for a sample (a standard counts: it moves
  the curve). G-STD reads the quantities you gave the standards.
* **Report**: the summary, Methods (the curves, LOD, LOQ, intervals, and the choices tested),
  MIQE, limitations and the exports (*Standard curves*, *Quantities*) speak of quantities; the
  Analysis Record verifies and re-runs like any other.
* **Not for a quantification run**: Gene, Audit, Trace, Claims, Prism and Plan next compare
  groups; the rail locks them with the reason, and their API answers `409 quantify`.

The MCP tool `qpcr_quantities(study_id, target=None)` reads the same numbers for an agent.
