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

## Group effect (reverse-normalisation guard)

**What it answers.** Does a control gene differ between the two groups being compared? geNorm's M ranks stability over all samples together, so it cannot see this. A control gene that is higher in one group moves every target's fold change by the same amount: it can normalise a real difference away, or create one. The reference-set card therefore says `genorm_validated: false` and shows this check next to the geNorm numbers.

**Implementation.** `qpilot/qpcr/refgenes.py::group_effect`, on the same log2 starting quantities and the same groups as the comparison (the primary cut-off, groups fixed from the recommended control genes). Welch's t-test comes from `qpilot/qpcr/contrast.py::welch`.

| Quantity | Definition | Flag |
|---|---|---|
| Pair shift | For every pair of candidates (a, b) in candidate order, the per-sample log2 ratio a − b; mean in the high group minus mean in the rest, two-sided Welch t-test; samples missing either gene are dropped. Reported as a log2 shift, a fold (2^shift) and p; pairs listed largest shift first | \|shift\| ≥ 0.5 log2 (1.4-fold) → flagged |
| Raw shift (context only) | Each candidate's own log2 level, high minus rest, Welch t-test | Never flagged: it includes the amount of cDNA put in, which the ratio cancels |

A flagged pair says that at least one of its two genes moves with the group; it cannot say which. The useful consequence: normalising a target to a alone instead of b alone changes its log2 fold change by exactly the pair's shift (up to samples dropped for missing values), so the pair shift is the size of the disagreement between the two single-gene analyses.

**On the demo study** (MYCN-high 53 vs rest 294; 10 pairs). Three pairs are flagged: HMBS:UBC(2) +0.81 log2 (1.76×, p = 0.058), HMBS:HPRT1 +0.71 (1.63×, p = 0.045) and SDHA(1):UBC(2) +0.54 (1.45×, p = 0.13). The next largest, HPRT1:SDHA(1) at −0.43 (p = 0.15), is below the flag. Raw levels, high minus rest: UBC(2) −0.81 (p = 0.00097), HPRT1 −0.70 (p = 0.0071), ALUsq(Eurogentec) −0.39 (p = 0.022), SDHA(1) −0.27 (p = 0.35), HMBS 0.00 (p = 1.0). The HMBS:UBC(2) shift is the whole ODC1 gap between the two single-gene analyses: ODC1 is 2.66× up with HMBS alone and 4.66× with UBC(2) alone, and log2(4.66 / 2.66) = 0.81.

**No multiple-testing correction.** All 10 pairs are tested at once and their p-values are shown uncorrected; the flag uses the size of the shift, not p. Treat a flagged pair as a reason to look before choosing control genes, not as a finding.
