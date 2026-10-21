# Method card: replicate budget (biological, RT and technical replicates)

**What it answers.** Before the first plate: given how much subjects, reverse transcriptions (RT) and wells each scatter, what is the smallest change a planned design can detect? Which buys more, another technical replicate, another RT replicate or more subjects? Which design reaches the target at the lowest cost? Technical replicates are never counted as biological n; the planner shows what they do buy, and the limit they cannot get past.

**References.** The variance of a balanced nested (hierarchical) mean is a textbook result. For qPCR it is the design of Tichopad A, Kitchen R, Riedmaier I, Becker C, Ståhlberg A, Kubista M. *Design and optimization of reverse-transcription quantitative PCR experiments.* Clinical Chemistry 55(10): 1816–1823 (2009). That paper was not re-read for this card, and none of its variance components is used as a default (see "What we changed"). The six-technical-replicate example is from Bustin 2025, *Int J Mol Sci* 26: 7796, as cited in the planning notes; the paper could not be read offline (see the Bustin section below).

**Implementation.** `qpilot/qpcr/plan.py`: `effective_sd`, `group_mean_se`, `design_cost`, `cheapest_design`, and the keyword-only arguments of `plan` (`sd_rt`, `sd_well`, `n_rt`, `n_tech`, `cost_subject`, `cost_rt`, `cost_well`, `expected_cq`), which fill `PlanResult.budget`. CLI: `qpilot plan --sd-rt --sd-well --n-rt --n-tech --cost-subject --cost-rt --cost-well --cq`.

| Quantity | Definition | Rule |
|---|---|---|
| σ_bio (`sd_log2`) | SD between subjects (biological units) on the log2 normalised scale, **without** RT or well noise | Input; > 0 and ≤ 10 |
| σ_RT (`sd_rt`), σ_well (`sd_well`) | SD between RT reactions of one RNA sample, and between wells of one cDNA, on the same scale | Inputs; 0 to 10; `None` = not given, counted as zero |
| n_RT, n_tech | RT reactions per subject; wells per RT reaction | Whole numbers, 1 to 10 |
| Effective SD | √(σ_bio² + σ_RT²/n_RT + σ_well²/(n_RT·n_tech)): the SD of one subject's value, the mean of log2 over its wells, as `qpilot/qpcr/quant.py` averages a biological unit | Equals σ_bio itself when σ_RT and σ_well are both 0 or not given |
| SE of a group mean | √(σ_bio²/n_bio + σ_RT²/(n_bio·n_RT) + σ_well²/(n_bio·n_RT·n_tech)) = effective SD / √n_bio | — |
| Subjects needed, MDE | The single-SD planner's formulas (normal approximation, two groups, two-sided; +1 small-sample correction on n) with the effective SD and n = n_bio | Wells and RT reactions never enter n |
| Comparison | The planned MDE next to one more well per RT, one more RT reaction per subject, and two more subjects per group | A step appears only when its SD was given |
| Limits | The MDE with unlimited wells (σ_well term removed) and with unlimited RT reactions and wells (σ_bio alone) at the planned subjects | Shown when the SD of that level was given |
| Cost per group | n_bio·(c_subject + n_RT·(c_RT + n_tech·c_well)); both groups cost twice that | Costs 0 to 10⁹ each; all three are needed |
| Cheapest design | For each n_RT and n_tech searched, n_bio = the subjects needed; the lowest cost wins | A level is searched from 1 to 10 only when its SD was given; otherwise the planned count is kept |
| Ties | Equal cost → smaller detectable fold → fewer subjects → fewer RT reactions → fewer wells | Costs are compared exactly, as the decimals written (0.1 is one tenth) |
| Expected Cq (`expected_cq`) | Accepted and echoed | The claim-floor check needs add_plan 1.4's floor pack, which does not exist; the budget says `claim_floor: "not_built"` and applies no floor |

**What we changed from the published method.** Nothing in the formula. Four choices are ours:
- **No assumed variance components.** Every SD is an input. When σ_RT or σ_well is missing the budget says so and gives that replicate no effect, instead of filling in a literature range; the planner never recommends a replicate whose noise it was not told.
- **The target is the headline rule.** A design "reaches the target" when n_bio ≥ the subjects needed for the fold change at the stated power, the same rule as `n_needed`.
- **The search is bounded** by the input caps (1 to 10 RT reactions, 1 to 10 wells per RT): 100 designs at most.
- **All three costs are required** for the cheapest design (enter 0 for a free item). A missing cost would otherwise count as free and steer the answer towards unlimited replicates.

**Scale of the inputs.** All three SDs are on the scale the comparison uses: log2 normalised expression. With perfect doubling per cycle, one cycle is one log2 unit; at an efficiency of 1.9 one cycle is 0.93 log2 units. RT yield that moves every gene of one cDNA alike cancels in normalisation, so σ_RT is the part that does not cancel. The reference genes' wells add their own noise: for k replicated reference genes, σ_well is about the target's well SD × √(1 + 1/k). σ_bio from the SD of subject means in a pilot already holds that pilot's RT and well noise; entering σ_RT and σ_well on top of it counts that noise twice (the budget says this in a note).

**Worked example** (the measured map, σ_bio 0.5, σ_RT 0.4, σ_well 0.3, 2-fold, 80 % power). With 6 subjects, 1 RT and 1 well, the detectable fold is 2.21. A second technical replicate gives 2.13 and a third 2.10. A second RT replicate gives 1.99, and two more subjects also give 1.99. With unlimited wells it is 2.05; with unlimited RT reactions and wells it is 1.75. At 100 per subject, 5 per RT and 2 per well, the cheapest of 100 designs is 6 subjects × 3 RT × 2 wells: 762 per group, detecting 1.88-fold. Six is the fewest subjects any design can use here, and 4 RT × 1 well costs 768. The planned 6 × 1 × 1 costs 642 per group and does not reach the target, because it needs 9 subjects.

**Bustin 2025's six-technical-replicate example** (1.5-fold at SD 0.5 Cq, 80 % power). The paper's exact test is **unverified**: it could not be read offline (plan §7 fact 2). The closest interpretation we can reproduce is a one-sample comparison, the mean of n replicate values against a fixed value, under the normal approximation: n = (z₀.₉₇₅ + z₀.₈₀)²·σ²/δ² = 5.73, so 6. Six replicates detect 1.49-fold. Other readings give other numbers:

| Reading | Replicates for 1.5-fold | At six replicates |
|---|---|---|
| One-sample, normal approximation (closest) | 5.73 → 6 | detects 1.49-fold |
| One-sample, exact t-test | 8 (power 0.73 at 7, 0.81 at 8) | power 0.63 |
| Two samples, one per group, each in n wells (the planner's two-group design), normal approximation | 11.5 → 12; 13 with the planner's +1 | detects 1.75-fold |
| The same at an efficiency of 1.9 (SD 0.46 log2 units) | one-sample 4.92 → 5; two-sample 9.83 → 10 | — |

A two-group comparison needs about twice the replicates of a one-sample one at the same SD. Either way, technical replicates measure one sample more precisely. They say nothing about the spread between subjects. With any σ_bio > 0, the planner's limits show the fold no number of wells can get below.

**Measured (synthetic, seeded).** A test-only simulator draws a biological effect per subject, an RT effect per RT reaction and a well effect per well, then averages each subject's wells as `quant` does. Its aggregation is checked against `quant.log2_matrix` on a planted table. The check covers 5 designs at a formula power of 0.5 and 0.8, with 40,000 simulated studies each. The variance of a subject's value is within 0.4 % of effective SD² (ratios 0.998–1.003). Power under the formula's own z-test is within 0.2 percentage points of the formula (acceptance: 1). Welch's t-test on the subject values is within 0.5 points of `simulate_calls` run on the effective SD (200,000 draws). So qPilot's own seeded simulation on the effective SD is exact for balanced nested designs. The normal approximation is optimistic for small groups. At a nominal 80 %, Welch's test reaches 46 % with 3 subjects per group, 70 % with 6, 75 % with 10 and 78 % with 20. That is why the message and the cheapest design also report the simulated rate. The cheapest design in the worked example is significant 78 % of the time.

**On the demo study.** The Vermeulen file has 366 study samples with one well per sample and gene: no technical or RT replicates. So no σ_RT or σ_well can be measured from it, and `quant.replicate_sd` is empty (NaN) everywhere. The engine's averaging was checked on the real table instead. Every real well was copied into 2 RT reactions × 3 wells with seeded noise (σ_RT 0.4, σ_well 0.3), and `quant.log2_matrix` averaged each unit. Over 23,101 unit × gene values, what is left over has variance 0.0953 against the formula's 0.0950, and mean −0.002.

**What is not claimed.**
- The planner does not estimate variance components from data. The nested decomposition stays deferred (red-team 04-D5); it takes the SDs as given.
- The formula holds for balanced designs. Unequal replicate counts, or wells lost to undetermined values, change the weights: `quant` averages wells, not RT means.
- It is a design check, never the power of a study already run.
- Costs are linear per item. Plate capacity, batch effects and fixed costs are not modelled.
- No claim-floor or limit-of-detection check is made for an expected Cq.

**Validation.** `tests/core/test_plan.py`:
- With σ_RT = σ_well = 0 (or not given), the numbers are exactly the single-SD planner's at 6 designs × 5 argument sets: `mde_fold`, `n_needed`, the message and the "cannot detect" list.
- The SE formula is checked literally, and the map's worked numbers and the comparison sentence are reproduced.
- The nested Monte Carlo agrees with the formula, and the simulator's aggregation is checked against `quant`.
- The Bustin readings are computed.
- The cost optimiser picks the hand-checked cheapest design, including a tie broken by rule and decimal-exact ties, and matches an independent enumeration.
- Inputs outside what any real design has are refused, and the CLI flags work.
- On the demo: no replicates, and the planted-replicate check through `quant`.

**Licence.** Apache-2.0 (qPilot's own code).
