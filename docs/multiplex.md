# Multiplex wells: several dyes in one reaction

A multiplex well measures several targets in the same reaction, one dye each: a TaqMan duplex
with the gene of interest in FAM and the reference gene in VIC or HEX, a 4-plex on a LightCycler
96 (FAM, HEX, Texas Red, Cy5), a SARS-CoV-2 panel with an internal control. qPilot reads every
curve of such a well and analyses each one as it analyses a well of a singleplex plate.

## What qPilot does

**Every dye gets its own analysis.** LinRegPCR (vendored unchanged, [method card](../methods/linregpcr.md))
analyses each dye of a multiplex plate as a plate of its own: the dye's curves, with their own
baseline, efficiency, Cq, starting quantity (N0) and amplification call, as LinRegPCR gives them
on that dye's export alone. A plate with one curve per well (the demo) is analysed as before.

Why: called on the whole plate, the vendored LinRegPCR gives each reaction's volume only to the
first curve of the well, so the other dyes' N0 came out as 0 and qPilot treated them as
*undetermined*. A duplex lost its reference gene, and relative quantification lost the well.

| File (`tests/fixtures/corpus/`) | Dyes per well | Curves with an N0, before → now |
|---|---|---|
| LightCycler 96 `lc96_bACTXY.rdml` | 4 (FAM bACT, Hex X, Texas Red Y, Cy5 IPC) | X 0 → 12, Y 0 → 12, IPC 0 → 14 (bACT 16 both) |
| QuantStudio 7 Pro eDNA plate | 2 (BRK2, IPC) | IPC 0 → 95 (BRK2 79 both) |
| CFX Maestro 4-plex (simulator) | 4 (E, N, ORF1ab, IEC) | IEC 0 → 96, N 0 → 96 (ORF1ab never amplifies) |
| 7500 export (Opentrons) | 1–2 (nCoV + IEC, Endo) | nCoV 0 → 21 (IEC 15 both) |

On the CFX 4-plex with IEC as the reference gene, Results had no gene before ("fewer than two
biological units with a value"); now E and N are compared on 47 + 47 units.

**Relative quantities use the reference measured in the same well.** qPilot averages a gene's
log2 N0 over a unit's wells and subtracts the reference genes' mean over the unit's wells. When
the gene and its reference share the wells and every one of them has both values, that is
exactly the mean of the per-well differences: same-well pairing, which cancels the pipetting
error in the amount of template, because both dyes read the same aliquot. The two differ only
where one dye of a well has no value while the other has one (a replicate where the gene did not
amplify, or a curve a person left out). On every multiplex file in the corpus they are the same
number (`qpilot.qpcr.multiplex.pairing_gaps` finds no such place). Where they would differ, the
person decides: leaving a well out leaves out every curve of it, so the gene and its reference
stay paired.

Why not pair always: a reference gene may be measured in another well (a triplex with a second
reference run singleplex), and qPilot's units, Decision Cards and robustness grid read one value
per unit and gene. Unit means with whole-well exclusions give the paired number wherever pairing
is defined, and the usual number everywhere else.

**A person's exclusions act on the reaction.** On the Run Gate and in Trace, leaving a
multiplex well out leaves out all its curves (one reaction), and the card says so. A Prism round
trip that clears one gene's replicate of a multiplex well is refused in words, because it would
leave the well's other genes out too. One amplification call for a whole multiplex well (a
`curve.well_call` proposal) is contradicted by the engine's check (D-CURVE): it would set every
dye's call at once, while LinRegPCR calls each dye's curve on its own.

## The internal positive control (G-IPC)

An internal positive control (IPC, IAC: a control template added at the same amount to every
reaction) should come up at about the same cycle in every well. A sample whose IPC comes up much
later than in the no-template wells probably held something that slowed the reaction: an
inhibitor. The genes measured with it may then be underestimated, or missed.

The Run Gate's rule **G-IPC** (pack `research-default` 1.3.0) recognises a target named IPC, IAC
or internal positive/amplification control that shares its wells with the study's targets.
Per plate:

* its expected Cq is the median over the no-template wells where it amplified, or, with fewer
  than two of them, over the plate's study wells;
* a study well whose IPC is **3 or more cycles later** is flagged (warn): possible inhibition;
* a well where neither the IPC nor any target amplified is flagged (warn): an inhibited reaction
  cannot be told from a negative one there;
* an IPC that did not amplify beside a target that did is *not* inhibition: a strongly
  amplifying target can use up the reaction before the IPC rises.

The 3 cycles are a lab-editable default (`delay_cycles`), not a published threshold; MIQE asks
for an inhibition check (dilution, spike or internal control) without fixing one. Like every
rule, G-IPC labels; a Decision Card follows only when leaving the flagged wells out could change
a conclusion (the consequence test). G-NTC-1 does not judge an IPC: it is meant to amplify in
the no-template wells.

On the QuantStudio 7 Pro eDNA plate the IPC's expected Cq is 27.73 (five no-template wells);
sample M22's four wells come up 3.5 to 4.2 cycles later, so G-IPC warns about them. On the
LightCycler 96 file it passes (six study wells, no no-template well).

The design rules propose leaving an IPC out of the comparison (role *ignore*, level Moderate): it
is a control, not a gene to compare between groups. The Run Gate still reads it.

## On the page

* **Design**: the plate map says *several dyes per well* and has a **Target shown** picker;
  a chosen well lists every curve it holds, with its dye.
* **Curves**: pick a gene to colour every well by that gene's curve; clicking a well opens that
  gene's curve.
* **Controls**: G-IPC per plate; a card's option that leaves out multiplex wells says every curve
  of each goes with it.

## Limits

* An internal control is recognised by its name. A control named otherwise (a phage name such
  as MS2) is not checked by G-IPC; name it IPC in the sample sheet or the instrument software.
* The Curve Judge (a learned second opinion on amplification) takes one curve per well and is not
  validated on probe chemistries, so it does not run on multiplex plates; LinRegPCR's call does.
* A multiplex plate where a dye's curves are too few for LinRegPCR's mean efficiency gives that
  dye no N0, as a small singleplex plate would.
