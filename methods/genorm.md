# Method card: geNorm control-gene stability

**What it answers.** Are the control ("reference") genes actually stable across the samples, and how many should be averaged?

**Reference.** Vandesompele J, De Preter K, Pattyn F, et al. *Accurate normalization of real-time quantitative RT-PCR data by geometric averaging of multiple internal control genes.* Genome Biology 3(7): research0034 (2002).

**Implementation.** `qpilot/qpcr/refgenes.py::genorm`, written to reproduce the validation oracle (`planning/verification/verify.py`) step by step.

| Quantity | Definition | Cut-off |
|---|---|---|
| M (stability) | For each candidate, the mean over the other candidates of the standard deviation (n − 1) of the pairwise log2 ratio, over samples where both are measured | M < 1.5 = stable enough (geNorm's heuristic for homogeneous samples) |
| Ranking | Remove the candidate with the highest M, recompute, repeat until two remain; ranking = the last two (in input order) then the removed genes, last removed first | — |
| V(n/n+1) | SD of the difference between the normalisation factor (mean log2) of the top n and the top n + 1 genes, over samples where all n + 1 are measured | V < 0.15 → n genes are enough |
| Recommended set | Smallest n with V(n/n+1) < 0.15; if none, all candidates | — |
| Robust M (extra) | Same as M with the scaled median absolute deviation (×1.4826) instead of the SD | Reported only, never used for decisions |

**What we changed from the published method.** Nothing in the definitions. qPilot works on log2 efficiency-corrected starting quantities (`Ncopy` from LinRegPCR) rather than on relative quantities computed with an assumed efficiency of 2; this is the input the oracle used.

**On the demo study.** M = 1.64–2.03 for all five candidates, none below 1.5; V2/3 = 0.56, V3/4 = 0.39, V4/5 = 0.33, none below 0.15 → recommended set = all five. In a heterogeneous tumour panel that is expected, and it is the reason the control-gene choice changes 31 of 58 conclusions. qPilot says this on the Decision Card before anyone asks.

**Limits.** geNorm assumes the candidates are not co-regulated; it cannot detect a set that drifts together. NormFinder (Andersen et al. 2004) addresses that and is on the roadmap, reimplemented from the paper because its original code may not be redistributed.
