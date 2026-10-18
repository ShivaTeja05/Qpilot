# Method card: Trace (from a result back to the wells to look at)

**What it answers.** A scientist looks at one result (a gene's call), one sample or one well and asks which input made it this way, and whether it matters. Trace takes the arithmetic as right and walks back through the numbers the result was built from: conclusion → group set → sample value → target well / normaliser → reference well → plate controls. It ends at a physical place (plate, well, tube) with what is unusual there, what each option would do to the result, and whether that changes the call. It gives one of four answers: *a place to look*, *a choice to look at* (the wells show nothing that changes the result, but changing one analysis choice alone flips it), *nothing to look at* (the influential samples are listed with "nothing unusual"), or *absent* (the sample is in no comparison).

**References.** Robust z (median and 1.4826 × MAD). The normalisation factor as a quality signal: Vermeulen et al., *Nucleic Acids Research* 39: e63 (2011). LinRegPCR's well notes: Ruijter et al., *Nucleic Acids Research* 37: e45 (2009). The 5-cycle NTC window: MIQE 2.0. Kinetic outlier detection (the idea behind S4): Bar et al. 2003. The walk and the checks S1, S6 and S7 are qPilot's own.

**Implementation.** `qpilot/qpcr/trace.py` (`build_context`, `trace_gene`, `trace_sample`, `trace_well`, `trace_store`, `exclusion_effect`, `TraceResult.card`, `TRACE_THRESHOLDS`, `METHOD_CARD`); the consequence classes in `qpilot/core/consequence.py`; fixed-group what-if evaluation in `qpilot/qpcr/space.py` (`QpcrSpace.cell_arrays`, `group_masks`, `evaluate_arrays`, `evaluate_with`); the panel in `qpilot/explain/trace_text.py`.

| Step | Definition | Cut-off |
|---|---|---|
| Groups | Held fixed in every scenario: the primary cut's masks. Leave-one-out, reading a reference from the others, setting a sample aside and bringing one back never re-derive the groups | — |
| Influence of a sample value | Leave-one-out Welch in closed form from centred group sums; results this close to the call rule are recomputed exactly | `boundary_tol` 1e-9 |
| Influence of a reference well | Its value replaced by the expected value moves every relative value of the sample by the deviation ÷ k; closed form, all samples × references × genes | — |
| Walk | Depth-first in order of influence; a child is pruned when it moves the result by less than a share of the result's CI half-width **and** no check fails below it **and** it does not change the call. Failed checks are known per subtree before the walk | `eps_ci_share` 0.1 |
| S1 reference well | Expected value of reference r: mean of the sample's other references + r's offset (median over the compared samples of r minus the mean of the others). The sample's single reference with the largest robust \|z\| is flagged. Needs three or more references | \|z\| > 3.5 |
| S2 whole sample late | Per sample, median over its wells of Cq minus the plate's median Cq (a plate is one target on one run); robust z, late side | z > 3.5 |
| S4 whole-sample efficiency | The same with the well's efficiency; shown only when both rules hold | \|z\| > 3.5 and \|shift\| > 0.05 |
| S5 curve note | A LinRegPCR note on a well that carries a value. `Ncopy < 10` and `Ncopy > 100 Mio` describe the amount, not the curve, and never fail; free-text notes are mapped to fixed codes | any other note |
| S6 NTC window | A study well with Cq ≥ (lowest NTC Cq of its plate − window). "Nothing found" is claimed per plate, only where no NTC amplified | 5 cycles |
| S7 absent | A sample in no comparison: the empty reference or marker wells (addresses and notes). Restore (one empty reference only): fill it with the mean of the other references + its offset; the group by the fixed marker threshold | — |
| Options | `keep`; `read_from_other_refs` (reference wells); `set_aside_value` (a target well: only that value); `set_aside` (the sample, from every comparison). Each is evaluated exactly with the groups fixed | — |
| Consequence | `changes_call` > `beyond_ci` (the fold change moves by more than its CI half-width) > `changes_nothing`; for the root gene, and the changed calls of every gene | — |
| Ranking | Class, then the size of the change, then \|z\|, then sample id | — |
| Facts | Every number shown: `f_trace_<root>_<rank>_<field>` and `f_trace_<root>_<field>`; sample ids, plates and wells are string facts | — |

**What we changed from the plan.** S3 (references shifted, targets not) is cut, as the plan says. S8 needs a sample sheet with annotations and is listed as what the data cannot show; S9 is not applicable without technical replicates. `read_from_other_refs` is offered for every reference-well place, not only S1 ones. A place is an address: a sample flagged both late (S2) and near an NTC (S6) gives two places, its tube and its well. In a well trace, S1 fails on the well when its own \|z\| exceeds the threshold. The "other reference wells agree with each other" line is judged without the flagged well (S1 run on the remaining references), so one far-off well does not drag the others' expected values.

**On the demo study** (Vermeulen 64 plates, groups 53 MYCN-high vs 294 rest, 58 genes; re-measured with this code; numbers in `tests/engine/test_trace.py`).

| Plan step | What | Plan says | Measured | Status |
|---|---|---|---|---|
| T1 CAMTA2 | First place, class | 2016 · HMBS_20080318 · K22, changes the call | the same (via read from the other references: no call → down) | holds |
| T1 CAMTA2 | Top 3 | 1924/F23 and 1772/O13 in the top 3 | ranks 2 and 3 (×2.71 and ×2.21) | holds |
| T1 CAMTA2 | Influential, nothing unusual | 2530 | 2530 first (+0.0747 log2), then 1837 and 111; setting 111 aside alone changes the call | holds |
| §4.5 panel | "No single tumour decides it" | — | 15 single samples each change the call when set aside; the panel says so | wording corrected |
| §4.5 panel | "+ 8 more unusual wells" | 8 | 15 places: 3 change the call, 12 change nothing (8 S1, 2 S2 tubes, 1 S6 well, 1 S5 well) | number differs |
| §4.5 panel | "NTCs clean" | all plates | clean on HMBS, HPRT1, SDHA(1) and UBC(2) plates only; CAMTA2's plate has 2 amplifying NTCs | claimed per plate |
| T1 sample | 1846 | in no comparison: HMBS A22 did not amplify | the same; restoring it puts it in "rest" and changes no call | holds |
| T1 absent | Tumours in no comparison | 19 | 19 (14 with one empty reference, 12 of them on HMBS_20080318); restoring the 14 changes PAICS only (+0.958 → +1.014), 2 of them join the high group | holds |
| T1 well | HMBS_20080318:K22 | feeds 58, pull 2.47 log2, changes CAMTA2 and IGSF4 | feeds 58, pull −2.473 log2 (×5.55), z −9.24; reading it from the other references changes CAMTA2 and IGSF4, setting the tumour aside changes CAMTA2 only | holds |
| T1 LOO | Calls changed by one tumour; largest shift | 4 of 58; 0.295 | 4 of 58 (CAMTA2, DPYSL3, IGSF4, PRKACB_bis); 0.2948 (CDH5, tumour 1758); median gene 0.0953 | holds |
| T1 S1 | Flags | 11 of 347 | 11 of 347, 3 with \|z\| > 5; all 11 read from the other references at once change 5 calls | holds |
| T1 S4 | Efficiency shift | nothing worth showing | 0 shown (range −0.020 … +0.032; the robust z alone would flag 4) | holds with the floor |
| F11 S2 | Late tumours | 7 at z > 3.5 | 7 (only 2714 and 2748 are compared); 46 more than two cycles late | holds |
| F13 S6 | Wells near an NTC | 21 wells, 11 plates | 21 wells on 7 plates (11 is the number of plates with an amplifying NTC; 23 NTCs amplified) | plate count differs |
| T1 speed | Full 58-gene trace after the curve cache | < 1 s | context 0.16 s; context + 58 gene traces + JSON 0.59–0.61 s; a cold process 1.9 s, of which imports 1.08 s | holds |
| T1 determinism | Byte-identical JSON | yes | the same sha256 in two processes | holds |
| T1 synthetic | +6 cycles in one reference well "ranks first" | ranks first | first in its own sample's trace whenever flagged (40 of 50 seeded cases flagged); first study-wide in 0 of 50, because 2016, 1924 and 2753 are larger. +8 cycles: 30 of 30 flagged, 3 of 30 first study-wide. On a clean toy study it is first | holds only within the sample |
| T1 synthetic | +3 cycles on every well: S2 fires, S1 does not | S2 fires | S2 fires in 7 of 50 on the demo (it needs over 4.3 cycles there); S1 in 0 of 50. On a clean toy study S2 fires and S1 does not | does not hold on the demo |

**What is not claimed.** Trace never names a cause: each line says what the data look like, which bench step that is consistent with and what to check. A single target well that is off cannot be told apart from biology without replicates. A fault shared by every sample of one group looks like biology. It cannot see the wrong sample in a tube, RNA integrity, RT replicates or no-RT controls. In the demo layout each sample sits at the same well on every plate, so a sample and its well position are confounded; Trace lists the plates where the same position is late (K22: HMBS and NHLH2) as context and never blames the instrument block. Thresholds are study-relative; a robust z with a MAD of zero gives no flag. With technical replicates a place names the first of its wells. Trace only reads: every change is a decision a person makes on a `trace_set_aside` card.

**Validation.** `tests/engine/test_trace.py` (on a toy study built in the test: the fixed-group helpers equal `QpcrSpace.evaluate` in every cell; the closed forms equal exact evaluation; planted faults for S1, S2, S5, S6 and S7; ranking, pruning and facts; the card and `exclusion_effect`; byte-stable JSON; the panel passes the validator for every root and degrades without facts. On the demo: every number in the table above). `tests/core/test_consequence.py` (the classes, roots, missing items, ranking).

**Licence.** Apache-2.0 (qPilot's own code).
