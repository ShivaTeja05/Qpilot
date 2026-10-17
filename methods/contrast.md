# Method card: group comparison (Welch t-test on log2 relative quantities)

**What it answers.** Is a gene higher or lower in one group than the other, by how much, and with what uncertainty?

**Implementation.** `qpilot/qpcr/contrast.py::welch_contrast`, reproducing the validation oracle (`planning/verification/verify.py`).

| Step | Definition |
|---|---|
| Input per sample | `log2(n0_gene) − mean(log2(n0_controls))` (see `qpilot/qpcr/quant.py`); `n0` is LinRegPCR's efficiency-corrected starting quantity |
| Groups | Fixed once from the primary control genes (all five on the demo); never re-derived when other control genes are tried |
| Test | Welch's unequal-variance t-test on the two groups' log2 values; Welch–Satterthwaite degrees of freedom |
| Fold change | `fc = 2^(mean_high − mean_rest)` |
| 95 % CI | `2^(diff ± t_0.975,df × SE)` |
| Conclusion rule (shown everywhere) | **up** if p < 0.05 and fc ≥ 2; **down** if p < 0.05 and fc ≤ 0.5; otherwise **no call** |

**What is not claimed.** No mixed model and no plate effect (the demo has one gene per plate, so plate and gene are perfectly confounded); no prediction interval; no correction for testing 58 genes (the robustness meter measures sensitivity to analysis choices, not significance hunting); no kinetic outlier test; no censored-data model for undetermined wells (they are dropped or capped, and that choice is itself tested in the robustness grid).

**On the demo study (recommended control set, top 15 %, drop):** ODC1 3.59× [2.42–5.33] up; BIRC5 4.01× [2.93–5.49] up; NTRK1 0.07× [0.03–0.14] down; NM23A 2.19× up, which becomes 1.62× "no call" with HMBS alone.

**Why the rule is a choice.** Two-fold and p < 0.05 are conventions, not laws. qPilot states the rule wherever a conclusion appears and treats it as a candidate dimension of the robustness grid (roadmap).
