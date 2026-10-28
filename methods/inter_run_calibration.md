# Method card: correcting differences between plates

**What it answers.** When a gene's samples are measured on more than one plate (run), each plate adds its
own offset (threshold, efficiency, master mix). Would a conclusion change if those offsets were removed, and
how: with an inter-run calibrator measured on every plate, or with the measurements the plates share?

**References.**
- Hellemans J, Mortier G, De Paepe A, Speleman F, Vandesompele J. *qBase relative quantification framework
  and software for management and automated analysis of real-time quantitative PCR data.* Genome Biol
  8(2):R19 (2007) — inter-run calibration, and sample maximisation (every sample of a gene on one plate).
- Ruijter JM, Ruiz Villalba A, Hellemans J, Untergasser A, van den Hoff MJB. *Removal of between-run
  variation in a multi-plate qPCR experiment.* Biomol Detect Quantif 5:10–14 (2015). PMC4822202 — factor
  correction.

**Implementation.** `qpilot/qpcr/interrun.py` (numpy, log2 scale), the opt-in `interrun` axis of the
decision space (matrix stage: the correction follows the efficiency model and the amplification rule, on the
wells the rule counts as amplified). The steps follow the RDML consortium's `interRunCorr`
(`qpilot/vendor/rdmlpython/rdml.py`, MIT), reimplemented so that it works on qPilot's per-well table for any
import rather than only on an RDML 1.4 file after LinRegPCR.

| Option | What it does |
|---|---|
| `none` (primary) | No correction |
| `calibrator` | Per gene and plate: the calibration factor is the calibrators' mean `log2 N0` on that plate minus their mean over the gene's plates (several calibrators: their mean, i.e. the geometric mean of their factors); subtracted from every well of that gene on that plate. A calibrator is a non-study sample (any RDML type but `unkn` and the negative controls `ntc/nac/ntp/nrt/opt`, e.g. the planner's `IRC`, type `pos`) with a quantity for that gene on **every** one of its plates. A gene without one is left as it is and listed |
| `factor` | One factor per plate for all targets (Ruijter 2015): for every pair of plates, the mean over every shared measurement (same target in the same sample, any type but the negative controls) and every pair of their replicate wells of `log2(value on B / value on A)` (Eq. 2); a pair without a shared measurement is estimated through the other plates (Eq. 3, two passes, row by row); each plate's factor is the mean of its column (Eq. 4); every quantity on the plate is divided by it (Eq. 5). A plate that shares nothing is left as it is and listed. Where `interRunCorr` would take the log of a missing ratio while filling a gap, that estimate is skipped |

**When it applies.** Only when some gene's study wells are on two or more plates. When every gene's samples
are on one plate (sample maximisation), a plate's offset is the same for every sample of that gene and cancels
exactly in every fold change: no correction can change a result, and the axis says so ("not applicable").
`calibrator` additionally needs a split gene with a calibrator on each of its plates, `factor` a measurement
two plates share. D-AXIS refutes a proposal the file cannot support.

**Screening.** The axis enters the grid, and raises its Decision Card (`numbers.interrun`), **only when a
correction alone flips a call**; a correction that only moves fold changes is held at `none` and reported.
Absent by default: every existing design hash, study id and the demo output are unchanged.

**Tests.** `tests/numbers/test_interrun.py`: a known plate offset (0, +1, −0.5 log2) is removed exactly by
the calibrator (one common constant left); plate factors are recovered from shared samples to 0.02 log2 and a
missing plate pair is filled through a third plate (Eq. 3); a plate sharing nothing is left as it is; one
plate per gene is reported as unable to change a fold change; negative controls never enter.

**On the demo study** (64 plates, one gene per plate, every sample on every plate but never the same gene on
two plates): neither correction applies — no gene is split over plates, and no two plates share a
measurement, so factor correction has nothing to compare. A gene and its reference genes are on different
plates, but that does not matter: each plate's offset shifts every unit of its gene by the same amount.
Measured: dividing every plate by a random factor (log2 factors from N(0, 1), −2.3 to +2.0) changes no call in
any of the 186 analyses × 58 genes, and the largest change of a log2 fold change is 3.6 × 10⁻¹⁴ (rounding).
None of the real corpus files splits a gene over plates either (the K. phaffii LinRegPCR file has 6 plates,
one gene each).
