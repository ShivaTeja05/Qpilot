"""Before the first plate: how many samples a design needs and what it cannot detect (Dev 2).

Pure arithmetic over ``qpilot.schemas`` and the standard library. Two-sample comparison on the
log2 normalised scale with a normal approximation plus the usual +1 small-sample correction:

    n per group  = 2 (z_{1-alpha/2} + z_{power})^2 sigma^2 / delta^2 + 1,   delta = log2(fc)
    MDE (log2)   = (z_{1-alpha/2} + z_{power}) * sigma * sqrt(2 / n)

The formulas are normal approximations (optimistic for very small groups). The message also
reports a seeded simulation of qPilot's actual rule (Welch t-test and the 2-fold call), which is
the number to trust for small n.

``sigma`` is the standard deviation **between biological replicates on the log2 normalised
scale** (from a pilot or an earlier Analysis Record). Using the SD of technical replicate Cq
values instead would understate the samples needed by about an order of magnitude. This is a
design check, never "the power of the study you ran" (no post-hoc power).

**Replicate budget.** When RT and technical replicates are planned, each subject's value is the
mean of ``log2`` over its wells (as :mod:`qpilot.qpcr.quant` aggregates a biological unit), so
with balanced replicate counts the SE of a group mean is

    SE = sqrt(sigma_bio^2 / n_bio + sigma_RT^2 / (n_bio n_RT) + sigma_well^2 / (n_bio n_RT n_tech))

which is :func:`effective_sd` divided by ``sqrt(n_bio)``. Every formula above then runs on
:func:`effective_sd` with ``n = n_bio``: wells and RT reactions are never counted as n. The SDs
are inputs, never defaults; the planner does not estimate or assume a variance component. With
costs per subject, RT reaction and well, :func:`cheapest_design` enumerates replicate counts and
returns the cheapest design that reaches the target. See ``methods/replicate_budget.md``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from fractions import Fraction
from functools import lru_cache
from statistics import NormalDist
from typing import Any

from qpilot.explain.words import plural
from qpilot.schemas import PlanResult

SIGMA_HELP = "SD of log2 normalised expression between biological replicates (not technical Cq SD)"
SD_RT_HELP = (
    "SD on the log2 scale between reverse transcriptions of one RNA sample (RT replicates); "
    "with perfect doubling per cycle, one cycle is one log2 unit"
)
SD_WELL_HELP = (
    "SD on the log2 scale between wells of one cDNA (technical replicates); "
    "with perfect doubling per cycle, one cycle is one log2 unit"
)
# Plausible bounds: a 1000-fold scatter between replicates or a fold change beyond 1000 is a typo.
MAX_SD_LOG2 = 10.0
MAX_FOLD = 1000.0
MAX_N_PER_GROUP = 1_000_000
MAX_REPLICATES = 10  # RT reactions per subject or wells per RT reaction; beyond this is a typo
MAX_COST = 1e9  # per subject, RT reaction or well; beyond this is a typo (and costs stay finite)
MAX_CQ = 60.0  # no cycling protocol in use runs past this many cycles
SUBJECT_STEP = 2  # the comparison sentence adds this many subjects to each group
# Expected Cq -> well noise (see cq_well_noise and methods/replicate_budget.md). The Cq at which a
# single template copy crosses the threshold: an unsourced, lab-editable default; the intercept
# of your own standard curve (the Cq at log10 copies = 0) is the value to give.
CQ_ONE_COPY = 35.0
# MIQE (Bustin et al. 2009, Clin Chem 55:611-622): with Poisson sampling, 3 copies per reaction
# is the lowest load that puts at least one copy in 95 % of reactions.
LOD_COPIES = 3.0
_WORDS = "zero one two three four five six seven eight nine ten".split()
_ORDINALS = (
    "zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh".split()
)


def _z_sum(alpha: float, power: float) -> float:
    nd = NormalDist()
    return nd.inv_cdf(1 - alpha / 2) + nd.inv_cdf(power)


def default_fold(min_log2fc: float = 1.0) -> float:
    """The change worth finding a plan starts from: a quarter above the call rule's threshold.

    2.5× for qPilot's 2-fold rule. A true change exactly at the threshold looks smaller than it
    about half the time, so the rule calls it at most about half the time however many samples
    are run: a plan has to aim above the line to say how many samples a call needs.
    """
    return round(1.25 * 2.0**min_log2fc, 2)


def fold_words(min_log2fc: float = 1.0, alpha: float = 0.05) -> str:
    """The relation between the change worth finding and the call rule, in plain words."""
    line = f"{2.0**min_log2fc:g}"
    return (
        f"qPilot calls a change only when p < {alpha:g} and the measured change is at least "
        f"{line}-fold. A true {line}-fold change measures below {line}-fold about half the time, "
        f"so however many samples you run it is called only about half the time. Plan for a "
        f"change above {line}-fold: the plan starts at {default_fold(min_log2fc):g}×."
    )


def n_needed(fc: float, sd_log2: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Samples per group to detect a fold change ``fc`` (either direction) with ``power``."""
    delta = abs(math.log2(fc))
    return math.ceil(2 * _z_sum(alpha, power) ** 2 * sd_log2**2 / delta**2 + 1)


def mde_fold(n_per_group: int, sd_log2: float, alpha: float = 0.05, power: float = 0.80) -> float:
    """Smallest fold change a balanced design with ``n_per_group`` detects with ``power``."""
    return 2.0 ** (_z_sum(alpha, power) * sd_log2 * math.sqrt(2 / n_per_group))


def effective_sd(
    sd_bio: float,
    sd_rt: float | None = 0.0,
    sd_well: float | None = 0.0,
    n_rt: int = 1,
    n_tech: int = 1,
) -> float:
    """SD of one subject's value: the mean of log2 over its RT reactions and their wells.

    ``sqrt(sd_bio^2 + sd_rt^2 / n_rt + sd_well^2 / (n_rt * n_tech))`` for balanced replicate
    counts. When ``sd_rt`` and ``sd_well`` are both 0 or ``None`` it returns ``sd_bio`` itself,
    so a design without RT or well noise gives exactly the numbers of the single-SD planner.

    Args:
        sd_bio: SD between subjects (biological units) on the log2 scale, without RT or well
            noise.
        sd_rt: SD between RT reactions of one RNA sample; ``None`` counts as zero.
        sd_well: SD between wells of one cDNA; ``None`` counts as zero.
        n_rt: RT reactions per subject (at least 1).
        n_tech: wells per RT reaction (at least 1).

    Returns:
        The SD on the log2 scale of one subject's mean, the value a group mean averages.
    """
    if not sd_rt and not sd_well:
        return sd_bio
    rt, well = sd_rt or 0.0, sd_well or 0.0
    return math.sqrt(sd_bio**2 + rt**2 / n_rt + well**2 / (n_rt * n_tech))


def copies_per_well(cq: float, cq_one_copy: float = CQ_ONE_COPY, efficiency: float = 2.0) -> float:
    """Template copies a well holds on average when its target crosses at ``cq``.

    ``efficiency ** (cq_one_copy - cq)``: each cycle earlier than the one-copy Cq is one doubling
    more template (at perfect efficiency).
    """
    return float(efficiency ** (cq_one_copy - cq))


def poisson_sd_log2(copies: float) -> float:
    """SD on the log2 scale of a well's starting copies from Poisson sampling alone.

    Pipetting a template that holds on average ``N`` copies per well puts a Poisson number of
    copies in each well (SD ``sqrt(N)``, coefficient of variation ``1 / sqrt(N)``); on the log2
    scale (the delta method) that is ``1 / (ln 2 · sqrt(N))``, about one cycle at 2 copies and
    0.07 at 200. It is a floor: no technical replicate SD can be smaller at that load.
    Sources: MIQE (Bustin et al. 2009, Clin Chem 55:611-622), and Ståhlberg A, Kubista M (2014),
    Expert Rev Mol Diagn 14:323-331 (sampling noise at low copy numbers). The approximation
    under-states the spread below about 3 copies, where many wells hold none.
    """
    return 1.0 / (math.log(2) * math.sqrt(copies))


def cq_well_noise(
    expected_cq: float, sd_well: float | None, cq_one_copy: float = CQ_ONE_COPY
) -> dict[str, Any]:
    """The well SD a target expected at ``expected_cq`` has at least, and the one the plan uses.

    The plan uses the larger of the well SD given and the Poisson floor at that load: a well SD
    measured at a lower Cq already holds that pilot's (smaller) sampling noise, so the larger of
    the two never counts the sampling noise twice.
    """
    copies = copies_per_well(expected_cq, cq_one_copy)
    floor = poisson_sd_log2(copies)
    used = max(floor, sd_well or 0.0)
    return {
        "expected_cq": expected_cq,
        "cq_one_copy": cq_one_copy,
        "copies_per_well": copies,
        "sd_well_poisson": floor,
        "sd_well_given": sd_well,
        "sd_well_used": used,
        "below_lod": copies < LOD_COPIES,
    }


def _cq_sentences(noise: dict[str, Any]) -> list[str]:
    copies = noise["copies_per_well"]
    load = f"{copies:.3g} copies" if copies >= 1 else "less than one copy"
    text = (
        f"At Cq {noise['expected_cq']:g} a well holds about {load} of template (if one copy "
        f"crosses at Cq {noise['cq_one_copy']:g}, at perfect doubling), so Poisson sampling "
        f"alone scatters wells by {noise['sd_well_poisson']:.3g} log2 units"
    )
    given = noise["sd_well_given"]
    if given is None:
        text += "; the plan uses that as the well SD."
    elif noise["sd_well_used"] > given:
        text += f", more than the well SD you gave ({given:.3g}); the plan uses the larger."
    else:
        text += f"; the well SD you gave ({given:.3g}) is larger and is used."
    return [text]


def group_mean_se(
    n_bio: int,
    sd_bio: float,
    sd_rt: float | None = 0.0,
    sd_well: float | None = 0.0,
    n_rt: int = 1,
    n_tech: int = 1,
) -> float:
    """SE of one group's mean over ``n_bio`` subjects of a balanced nested design.

    ``sqrt(sd_bio^2 / n_bio + sd_rt^2 / (n_bio n_rt) + sd_well^2 / (n_bio n_rt n_tech))``, the
    same as ``effective_sd(...) / sqrt(n_bio)``; arguments as in :func:`effective_sd`.
    """
    return effective_sd(sd_bio, sd_rt, sd_well, n_rt, n_tech) / math.sqrt(n_bio)


def design_cost(
    n_bio: int,
    n_rt: int,
    n_tech: int,
    cost_subject: float,
    cost_rt: float,
    cost_well: float,
) -> float:
    """Cost of one group: ``n_bio (cost_subject + n_rt (cost_rt + n_tech cost_well))``."""
    return float(_cost(n_bio, n_rt, n_tech, _costs(cost_subject, cost_rt, cost_well)))


def _costs(*costs: float) -> tuple[Fraction, ...]:
    """Costs as the exact decimals written (0.1 is one tenth), so equal costs tie exactly."""
    return tuple(Fraction(str(c)) for c in costs)


def _cost(n_bio: int, n_rt: int, n_tech: int, costs: tuple[Fraction, ...]) -> Fraction:
    subject, rt, well = costs
    return n_bio * (subject + n_rt * (rt + n_tech * well))


def cheapest_design(
    fc: float,
    sd_bio: float,
    *,
    cost_subject: float,
    cost_rt: float,
    cost_well: float,
    sd_rt: float | None = None,
    sd_well: float | None = None,
    n_rt: int = 1,
    n_tech: int = 1,
    alpha: float = 0.05,
    power: float = 0.80,
) -> dict[str, Any]:
    """The cheapest balanced design that detects ``fc`` with ``power`` (per group, two groups).

    For every RT count and well count searched, the subjects needed are
    ``n_needed(fc, effective_sd(...))``, the same rule as the headline sample size, and the cost
    per group is :func:`design_cost`. A level is searched (from 1 to :data:`MAX_REPLICATES`)
    only when its SD was given: the planner never recommends a replicate whose noise it was not
    told, and keeps the planned ``n_rt`` or ``n_tech`` instead. Ties in cost go to the design
    with the smaller detectable fold, then fewer subjects, then fewer RT reactions, then fewer
    wells; costs are compared exactly (as fractions), so the choice is deterministic.

    Args:
        fc: the fold change to detect (either direction).
        sd_bio: SD between subjects on the log2 scale, without RT or well noise.
        cost_subject: cost of one subject (collection, extraction).
        cost_rt: cost of one RT reaction.
        cost_well: cost of one qPCR well.
        sd_rt: SD between RT reactions of one RNA sample; ``None`` keeps ``n_rt`` fixed.
        sd_well: SD between wells of one cDNA; ``None`` keeps ``n_tech`` fixed.
        n_rt: the planned RT reactions per subject (used when ``sd_rt`` is ``None``).
        n_tech: the planned wells per RT reaction (used when ``sd_well`` is ``None``).
        alpha: two-sided significance level.
        power: the chance of detecting ``fc`` when it is real.

    Returns:
        ``n_bio``, ``n_rt``, ``n_tech``, ``wells_per_group``, ``sd_effective``, ``mde_fold``,
        ``cost_per_group``, ``cost_both_groups`` and ``n_designs`` (how many were compared).
    """
    costs = _costs(cost_subject, cost_rt, cost_well)
    rts = range(1, MAX_REPLICATES + 1) if sd_rt is not None else (n_rt,)
    techs = range(1, MAX_REPLICATES + 1) if sd_well is not None else (n_tech,)
    candidates = []
    for r in rts:
        for t in techs:
            sd = effective_sd(sd_bio, sd_rt, sd_well, r, t)
            n = n_needed(fc, sd, alpha, power)
            mde = mde_fold(n, sd, alpha, power)
            candidates.append((_cost(n, r, t, costs), round(mde, 12), n, r, t, mde, sd))
    cost, _, n, r, t, mde, sd = min(candidates)
    return {
        "n_bio": n,
        "n_rt": r,
        "n_tech": t,
        "wells_per_group": n * r * t,
        "sd_effective": sd,
        "mde_fold": mde,
        "cost_per_group": float(cost),
        "cost_both_groups": float(2 * cost),
        "n_designs": len(candidates),
    }


SIM_REPS = 20_000


def mde_fold_groups(
    n_a: int, n_b: int, sd_log2: float, alpha: float = 0.05, power: float = 0.80
) -> float:
    """:func:`mde_fold` for two groups of different sizes (``n_a`` and ``n_b`` units).

    ``sqrt(2 / n)`` becomes ``sqrt(1 / n_a + 1 / n_b)``, so equal groups give exactly
    :func:`mde_fold`. The study a planner starts from is rarely balanced (the demo compares 53
    with 294 tumours).
    """
    return 2.0 ** (_z_sum(alpha, power) * sd_log2 * math.sqrt(1 / n_a + 1 / n_b))


def balanced_equivalent(n_a: int, n_b: int) -> float:
    """The balanced group size with the same precision as ``n_a`` vs ``n_b`` (harmonic mean)."""
    return 2.0 / (1 / n_a + 1 / n_b)


def pooled_sd(groups: Sequence[Sequence[float]]) -> tuple[float, int]:
    """The pooled within-group SD of log2 values and its degrees of freedom.

    ``sqrt(sum((n_i - 1) s_i^2) / sum(n_i - 1))`` over the groups that have at least two values:
    the spread between biological units of one condition, which is the ``sd_log2`` every
    function here expects (never the SD across both groups, which includes the effect itself).

    Raises:
        ValueError: Fewer than one degree of freedom (no group has two values).
    """
    ss = 0.0
    df = 0
    for values in groups:
        v = [float(x) for x in values if math.isfinite(float(x))]
        if len(v) < 2:
            continue
        mean = sum(v) / len(v)
        ss += sum((x - mean) ** 2 for x in v)
        df += len(v) - 1
    if df < 1:
        raise ValueError("a pooled SD needs a group with at least two values")
    return math.sqrt(ss / df), df


def sigma_interval(sd_log2: float, df: int, level: float = 0.95) -> tuple[float, float]:
    """The chi-square confidence interval of an SD estimated with ``df`` degrees of freedom.

    A sigma from a small pilot is itself uncertain; planning with the upper end is the safe
    choice. From ``sd * sqrt(df / chi2_{(1+level)/2, df})`` to
    ``sd * sqrt(df / chi2_{(1-level)/2, df})``.
    """
    from scipy import stats

    tail = (1 - level) / 2
    lo = sd_log2 * math.sqrt(df / stats.chi2.ppf(1 - tail, df))
    hi = sd_log2 * math.sqrt(df / stats.chi2.ppf(tail, df))
    return float(lo), float(hi)


def simulate_calls(
    fc: float,
    sd_log2: float,
    n_per_group: int,
    alpha: float = 0.05,
    min_log2fc: float = 1.0,
    reps: int = SIM_REPS,
    n_other: int | None = None,
) -> tuple[float, float]:
    """Simulate qPilot's own rule on a true ``fc``; return (P(significant), P(called)).

    Each replicate is a study with ``n_per_group`` normal log2 values per group and SD
    ``sd_log2``; it runs a Welch t-test and counts a call only when it is significant **and** the
    observed change reaches ``2**min_log2fc`` in the true direction. For normal data each group's
    mean and variance are independent (normal and scaled chi-square), so they are drawn directly:
    the same distribution as drawing every value, in memory that does not grow with
    ``n_per_group``. Seeded, so the same inputs give the same numbers. ``n_other`` gives the
    second group its own size (``None``: the same size).

    The draws do not depend on ``fc`` or ``sd_log2`` (a study is ``delta + sd * noise``, and the
    t statistic's denominator and Welch's degrees of freedom scale with ``sd``), so they and each
    replicate's critical t are computed once per group sizes and level (:func:`_draws`) and every
    gene planned at those sizes reuses them: "p < alpha" is "|t| above the critical t of that
    replicate's degrees of freedom".
    """
    import numpy as np

    n = n_per_group
    m = n if n_other is None else n_other
    noise, scale, t_crit = _draws(n, m, reps, alpha)
    delta = math.log2(fc)
    diff = delta + sd_log2 * noise
    t = diff / (sd_log2 * scale)
    significant = np.abs(t) > t_crit
    same_direction = np.sign(diff) == np.sign(delta)
    called = significant & same_direction & (np.abs(diff) >= min_log2fc)
    return float(significant.mean()), float(called.mean())


@lru_cache(maxsize=96)
def _draws(n: int, m: int, reps: int, alpha: float) -> tuple[Any, Any, Any]:
    """The seeded draws of :func:`simulate_calls` for groups of ``n`` and ``m`` (at SD 1).

    ``noise`` is the difference of the two group means, ``scale`` the Welch standard error and
    ``t_crit`` each replicate's two-sided critical t at ``alpha`` (for its Welch degrees of
    freedom). The draws come in the order the planner always drew them (the first group's mean,
    the second's, then their variances), from ``default_rng(0)``.
    """
    import numpy as np
    from scipy import special

    rng = np.random.default_rng(0)
    mean_hi = rng.normal(0.0, 1 / math.sqrt(n), size=reps)
    mean_lo = rng.normal(0.0, 1 / math.sqrt(m), size=reps)
    var_hi = rng.chisquare(n - 1, size=reps) / (n - 1)
    var_lo = rng.chisquare(m - 1, size=reps) / (m - 1)
    se2_hi, se2_lo = var_hi / n, var_lo / m
    df = (se2_hi + se2_lo) ** 2 / (se2_hi**2 / (n - 1) + se2_lo**2 / (m - 1))
    t_crit = special.stdtrit(df, 1 - alpha / 2)
    out = (mean_hi - mean_lo, np.sqrt(se2_hi + se2_lo), t_crit)
    for array in out:
        array.setflags(write=False)
    return out


RARELY_CALLED = 0.05  # below this, the design "cannot detect" the change under qPilot's rule


def n_for_call(
    fc: float,
    sd_log2: float,
    power: float = 0.80,
    alpha: float = 0.05,
    min_log2fc: float = 1.0,
    reps: int = SIM_REPS,
    n_max: int = MAX_N_PER_GROUP,
) -> int | None:
    """The smallest balanced group size at which qPilot's rule calls a true ``fc`` with ``power``.

    :func:`n_needed` sizes a study for significance; a call also needs the observed change to
    reach ``2**min_log2fc``. Searched with :func:`simulate_calls` (seeded): from
    :func:`n_needed` up by doubling, then bisected. ``None`` when no size reaches ``power``: a
    true change at or below the rule's threshold is called at most about half the time however
    many samples there are, and none beyond ``n_max``.
    """
    delta = abs(math.log2(fc))
    if delta <= min_log2fc and power >= 0.5:
        return None

    def called(n: int) -> float:
        return simulate_calls(fc, sd_log2, n, alpha, min_log2fc, reps)[1]

    lo = max(2, min(n_needed(fc, sd_log2, alpha, power), n_max)) - 1
    if lo >= 2 and called(lo) >= power:  # start below the first size that qualifies
        lo = 1
    hi = max(lo + 1, 2)
    while called(hi) < power:
        if hi >= n_max:
            return None
        lo, hi = hi, min(hi * 2, n_max)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if called(mid) >= power:
            hi = mid
        else:
            lo = mid
    return hi


def _fold(x: float) -> str:
    """A fold change for prose, never rounded onto the 2-fold line it falls short of."""
    text = f"{x:.3g}"
    return "just under 2" if x < 2 and float(text) >= 2 else text


def _number(value: object) -> bool:
    """A real finite number (``True``/``False`` are not numbers here)."""
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _check_budget_inputs(
    sd_rt: float | None,
    sd_well: float | None,
    n_rt: int,
    n_tech: int,
    costs: dict[str, float | None],
    expected_cq: float | None,
) -> None:
    """Refuse replicate, cost and Cq values no real design has."""
    for name, sd in (("sd_rt", sd_rt), ("sd_well", sd_well)):
        if sd is not None and not (_number(sd) and 0 <= sd <= MAX_SD_LOG2):
            raise ValueError(f"{name} must be a number from 0 to {MAX_SD_LOG2:g} (log2 units)")
    for name, n in (("n_rt", n_rt), ("n_tech", n_tech)):
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_REPLICATES:
            raise ValueError(f"{name} must be a whole number from 1 to {MAX_REPLICATES}")
    for name, cost in costs.items():
        if cost is not None and not (_number(cost) and 0 <= cost <= MAX_COST):
            raise ValueError(f"{name} must be a number from 0 to {MAX_COST:,.0f}")
    if expected_cq is not None and not (_number(expected_cq) and 0 < expected_cq <= MAX_CQ):
        raise ValueError(f"expected_cq must be a cycle number above 0 and at most {MAX_CQ:g}")


def _check_inputs(
    fc: float,
    sd_log2: float | None,
    n_per_group: int | None,
    alpha: float,
    power: float,
    *,
    sd_rt: float | None = None,
    sd_well: float | None = None,
    n_rt: int = 1,
    n_tech: int = 1,
    costs: dict[str, float | None] | None = None,
    expected_cq: float | None = None,
) -> None:
    """Refuse values no real design has, before any arithmetic can overflow or allocate."""
    values = [fc, alpha, power] + ([sd_log2] if sd_log2 is not None else [])
    if not all(isinstance(v, int | float) and math.isfinite(v) for v in values):
        raise ValueError("fc, sd_log2, alpha and power must be finite numbers")
    if not (1 / MAX_FOLD <= fc <= MAX_FOLD) or fc == 1:
        raise ValueError(
            f"fc must be a fold change other than 1, between 1/{MAX_FOLD:g} and {MAX_FOLD:g}"
        )
    if not (0 < alpha < 1 and 0 < power < 1):
        raise ValueError("alpha and power must be between 0 and 1")
    if sd_log2 is not None and not (0 < sd_log2 <= MAX_SD_LOG2):
        raise ValueError(f"sd_log2 must be positive and at most {MAX_SD_LOG2:g} ({SIGMA_HELP})")
    if n_per_group is not None and not (2 <= n_per_group <= MAX_N_PER_GROUP):
        raise ValueError(f"n_per_group must be between 2 and {MAX_N_PER_GROUP:,}")
    _check_budget_inputs(sd_rt, sd_well, n_rt, n_tech, costs or {}, expected_cq)


def _rules(
    n_plates: int | None,
    calibrator_on_every_plate: bool | None,
    n_candidate_refs: int | None,
    one_sample_per_subject: bool | None,
) -> list[str]:
    rules = []
    if n_plates and n_plates > 1 and calibrator_on_every_plate is False:
        rules.append(
            "Plate is confounded with gene: put the same inter-run calibrator sample on every "
            "plate, or run each gene for all samples on one plate (Hellemans 2007)."
        )
    if n_candidate_refs is not None and n_candidate_refs < 3:
        rules.append(
            "Cannot run geNorm with fewer than three candidate reference genes: test at least "
            "three across all conditions (Vandesompele 2002)."
        )
    if one_sample_per_subject:
        rules.append(
            "With one tissue sample per subject, spend replicates on more subjects or samples "
            "rather than on repeated reverse transcriptions (Tichopad 2009)."
        )
    return rules


def _plural(n: int, word: str) -> str:
    return plural(n, word)


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _money(x: float) -> str:
    """A cost for prose: whole amounts without decimals, others with two."""
    return f"{int(x):,}" if x == int(x) and abs(x) < 1e15 else f"{x:,.2f}"


def _sd_text(value: float | None) -> str:
    return "not given" if value is None else f"{value:.3g}"


def _clause(subject: str, plural: bool, before: float, after: float, first: bool) -> str:
    """One step of the comparison sentence, worded from the two folds it compares."""
    move, leave = ("move", "leave") if plural else ("moves", "leaves")
    what = "the detectable fold" if first else "it"
    if _fold(after) == _fold(before):
        return f"{subject} {leave} {what} at {_fold(after)}"
    start = f" from {_fold(before)}" if first else ""
    return f"{subject} {move} {what}{start} to {_fold(after)}"


def _missing_sd_notes(sd_rt: float | None, sd_well: float | None) -> list[str]:
    if sd_rt is None and sd_well is None:
        return [
            "No RT or well SD given, so RT and technical replicates are given no effect. "
            "Measure both in a pilot with RT and technical replicates; the planner does not "
            "assume them."
        ]
    if sd_rt is None:
        return ["No RT SD given: RT noise counts as zero; a cheapest design keeps the RT count."]
    if sd_well is None:
        return ["No well SD given: well noise counts as zero; a cheapest design keeps the wells."]
    return []


def _compare(
    n_bio: int,
    sd_bio: float,
    sd_rt: float | None,
    sd_well: float | None,
    n_rt: int,
    n_tech: int,
    alpha: float,
    power: float,
) -> dict[str, Any]:
    """The planned design's detectable fold next to one more of each replicate level."""

    def mde(n: int, r: int, t: int, rt: float | None, well: float | None) -> float:
        return mde_fold(n, effective_sd(sd_bio, rt, well, r, t), alpha, power)

    return {
        "planned": mde(n_bio, n_rt, n_tech, sd_rt, sd_well),
        "one_more_well": None if sd_well is None else mde(n_bio, n_rt, n_tech + 1, sd_rt, sd_well),
        "one_more_rt": None if sd_rt is None else mde(n_bio, n_rt + 1, n_tech, sd_rt, sd_well),
        "more_subjects": mde(n_bio + SUBJECT_STEP, n_rt, n_tech, sd_rt, sd_well),
        "subjects_added": SUBJECT_STEP,
        "wells_limit": None if sd_well is None else mde(n_bio, n_rt, n_tech, sd_rt, 0.0),
        "replicates_limit": None if sd_rt is None else mde(n_bio, n_rt, n_tech, 0.0, 0.0),
    }


def _compare_sentences(
    n_bio: int, n_rt: int, n_tech: int, compare: dict[str, Any], power: float
) -> list[str]:
    planned = compare["planned"]
    steps = []
    if compare["one_more_well"] is not None:
        subject = f"a {_ORDINALS[n_tech + 1]} technical replicate"
        steps.append((subject, False, compare["one_more_well"]))
    if compare["one_more_rt"] is not None:
        steps.append((f"a {_ORDINALS[n_rt + 1]} RT replicate", False, compare["one_more_rt"]))
    more = f"{_WORDS[SUBJECT_STEP]} more subjects per group"
    steps.append((more, True, compare["more_subjects"]))
    clauses = [
        _clause(subject, plural, planned, after, first=i == 0)
        for i, (subject, plural, after) in enumerate(steps)
    ]
    head = (
        f"At {n_bio} subjects per group ({_plural(n_rt, 'RT reaction')} each, "
        f"{_plural(n_tech, 'well')} per RT, {power:.0%} power): "
    )
    sentences = [head + "; ".join(clauses) + "."]
    limits = []
    if compare["wells_limit"] is not None:
        limits.append(f"no number of wells gets below {_fold(compare['wells_limit'])}-fold")
    if compare["replicates_limit"] is not None:
        what = "RT reactions and wells" if compare["wells_limit"] is not None else "RT reactions"
        limits.append(f"no number of {what} below {_fold(compare['replicates_limit'])}-fold")
    if limits:
        sentences.append(
            f"Replicates cannot stand in for subjects: at {n_bio} per group, "
            + ", and ".join(limits)
            + "."
        )
    return sentences


def _cheapest(
    fc: float,
    sd_bio: float,
    sd_rt: float | None,
    sd_well: float | None,
    n_rt: int,
    n_tech: int,
    costs: dict[str, float | None],
    alpha: float,
    power: float,
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """(cheapest design or None, sentences, notes) for the costs given."""
    labels = {"cost_subject": "subject", "cost_rt": "RT reaction", "cost_well": "well"}
    missing = [f"per {labels[k]}" for k, v in costs.items() if v is None]
    if missing:
        return (
            None,
            [],
            [
                f"Cheapest design not computed: give the cost {_and(missing)} as well "
                "(zero if it costs nothing)."
            ],
        )
    if not any(costs.values()):
        return None, [], ["Cheapest design not computed: every cost is zero."]
    best = cheapest_design(
        fc,
        sd_bio,
        sd_rt=sd_rt,
        sd_well=sd_well,
        n_rt=n_rt,
        n_tech=n_tech,
        alpha=alpha,
        power=power,
        **costs,
    )
    sig, called = simulate_calls(fc, best["sd_effective"], best["n_bio"], alpha)
    best["simulated_significant"], best["simulated_called"] = sig, called
    shown = _fold(max(fc, 1 / fc))
    sentence = (
        f"Cheapest design (of {best['n_designs']} compared) that detects a {shown}-fold change "
        f"with {power:.0%} power at these costs: {best['n_bio']} subjects per group, "
        f"{_plural(best['n_rt'], 'RT reaction')} each and {_plural(best['n_tech'], 'well')} "
        f"per RT, costing {_money(best['cost_per_group'])} per group "
        f"({_money(best['cost_both_groups'])} for both groups). Simulated with qPilot's own "
        f"rule, it is significant {sig:.0%} of the time and called up or down {called:.0%}."
    )
    return best, [sentence], []


def _budget(
    fc: float,
    sd_bio: float | None,
    n_bio: int | None,
    *,
    sd_rt: float | None,
    sd_well: float | None,
    n_rt: int,
    n_tech: int,
    costs: dict[str, float | None],
    expected_cq: float | None,
    alpha: float,
    power: float,
    cq_one_copy: float = CQ_ONE_COPY,
) -> dict[str, Any]:
    """The replicate budget: effective SD, the comparison, the cheapest design and notes.

    An expected Cq sets the well SD's floor (:func:`cq_well_noise`); the sentences say so.
    """
    noise = None if expected_cq is None else cq_well_noise(expected_cq, sd_well, cq_one_copy)
    notes = _missing_sd_notes(sd_rt, sd_well if noise is None else noise["sd_well_used"])
    if noise is not None:
        sd_well = noise["sd_well_used"]
    budget: dict[str, Any] = {
        "inputs": {
            "sd_bio": sd_bio,
            "sd_rt": sd_rt,
            "sd_well": sd_well,
            "n_bio": n_bio,
            "n_rt": n_rt,
            "n_tech": n_tech,
            **costs,
            "expected_cq": expected_cq,
            "cq_one_copy": None if noise is None else cq_one_copy,
        },
        "sd_effective": None,
        "n_bio_needed": None,
        "planned": None,
        "compare": None,
        "cheapest": None,
        "searched": None,
        "cq_noise": noise,
        "sentences": [] if noise is None else _cq_sentences(noise),
        "notes": notes,
    }
    if sd_bio is None:
        notes.append("Biological SD unknown: the replicate budget needs it too.")
        return budget
    if sd_rt is not None or sd_well is not None:
        notes.append(
            "The biological SD is read as the spread between subjects alone. The SD of subject "
            "means from a pilot already holds that pilot's RT and well noise, so entering both "
            "counts that noise twice."
        )
    sd = effective_sd(sd_bio, sd_rt, sd_well, n_rt, n_tech)
    need = n_needed(fc, sd, alpha, power)
    budget["sd_effective"], budget["n_bio_needed"] = sd, need
    sentences = budget["sentences"]
    sentences.append(
        f"Each subject is measured in {_plural(n_rt, 'RT reaction')} with "
        f"{_plural(n_tech, 'well')} per RT; the SD of its mean is {sd:.3g} log2 units "
        f"(biological {_sd_text(sd_bio)}, RT {_sd_text(sd_rt)}, well {_sd_text(sd_well)}), "
        "and every sample size here counts subjects, never wells."
    )
    if n_bio:
        compare = _compare(n_bio, sd_bio, sd_rt, sd_well, n_rt, n_tech, alpha, power)
        budget["compare"] = compare
        budget["planned"] = {
            "n_bio": n_bio,
            "n_rt": n_rt,
            "n_tech": n_tech,
            "wells_per_group": n_bio * n_rt * n_tech,
            "se_group_mean": group_mean_se(n_bio, sd_bio, sd_rt, sd_well, n_rt, n_tech),
            "mde_fold": compare["planned"],
            "reaches_target": n_bio >= need,
            "cost_per_group": None,
        }
        sentences.extend(_compare_sentences(n_bio, n_rt, n_tech, compare, power))
    if any(v is not None for v in costs.values()):
        best, extra, cost_notes = _cheapest(
            fc, sd_bio, sd_rt, sd_well, n_rt, n_tech, costs, alpha, power
        )
        budget["cheapest"] = best
        sentences.extend(extra)
        notes.extend(cost_notes)
        if best is not None:
            budget["searched"] = {
                "n_rt": [1, MAX_REPLICATES] if sd_rt is not None else [n_rt, n_rt],
                "n_tech": [1, MAX_REPLICATES] if sd_well is not None else [n_tech, n_tech],
            }
        if best is not None and budget["planned"] is not None:
            planned = budget["planned"]
            planned["cost_per_group"] = design_cost(n_bio, n_rt, n_tech, **costs)
            verdict = "reaches" if planned["reaches_target"] else "does not reach"
            sentences.append(
                f"The planned design costs {_money(planned['cost_per_group'])} per group and "
                f"{verdict} the target."
            )
    return budget


def plan(
    fc: float | None = None,
    sd_log2: float | None = None,
    n_per_group: int | None = None,
    alpha: float = 0.05,
    power: float = 0.80,
    n_plates: int | None = None,
    calibrator_on_every_plate: bool | None = None,
    n_candidate_refs: int | None = None,
    one_sample_per_subject: bool | None = None,
    *,
    min_log2fc: float = 1.0,
    sd_rt: float | None = None,
    sd_well: float | None = None,
    n_rt: int = 1,
    n_tech: int = 1,
    cost_subject: float | None = None,
    cost_rt: float | None = None,
    cost_well: float | None = None,
    expected_cq: float | None = None,
    cq_one_copy: float | None = None,
) -> PlanResult:
    """Check a design before it is run.

    Without any replicate or cost argument the result is exactly the single-SD planner's, with
    ``budget`` ``None``. With them, ``sd_log2`` is the biological SD alone, ``n_per_group``
    counts subjects, and every number (``n_needed``, ``mde_fold``, the simulation) runs on
    :func:`effective_sd` for the planned RT and well counts; ``budget`` adds the comparison
    sentence and, with all three costs, the cheapest design (:func:`cheapest_design`).

    Args:
        fc: the smallest fold change worth detecting; ``None`` (the default) starts from
            :func:`default_fold` (2.5× for the 2-fold rule), as Plan next and the CLI do.
        sd_log2: SD of log2 normalised expression between biological replicates; ``None``
            gives a message instead of numbers. With ``sd_rt`` or ``sd_well`` it is the SD
            between subjects alone, without RT or well noise.
        n_per_group: the planned samples (subjects) per group; enables the minimum detectable
            effect and the comparison sentence.
        alpha: two-sided significance level.
        power: the chance of detecting ``fc`` when it is real.
        n_plates: how many plates the study spans.
        calibrator_on_every_plate: whether an inter-run calibrator is on every plate.
        n_candidate_refs: how many candidate reference genes will be tested.
        one_sample_per_subject: solid tissue with one sample per subject.
        min_log2fc: the conclusion rule's threshold (1.0: a call needs at least 2-fold).
        sd_rt: SD on the log2 scale between RT reactions of one RNA sample (0 to 10).
        sd_well: SD on the log2 scale between wells of one cDNA (0 to 10).
        n_rt: planned RT reactions per subject (1 to 10).
        n_tech: planned wells per RT reaction (1 to 10).
        cost_subject: cost of one subject, for the cheapest design (needs all three costs).
        cost_rt: cost of one RT reaction.
        cost_well: cost of one qPCR well.
        expected_cq: expected Cq of the target. It sets the well SD's floor: the Poisson
            sampling noise of the copies a well holds at that Cq (:func:`cq_well_noise`); the
            plan uses the larger of that floor and ``sd_well``. Below 3 copies per well
            (MIQE's detection limit) the target is in ``cannot_detect``.
        cq_one_copy: the Cq at which one copy crosses the threshold (your standard curve's
            intercept); default :data:`CQ_ONE_COPY`. Used only with ``expected_cq``.

    Raises:
        ValueError: an input outside what any real design has.
    """
    if fc is None:
        fc = default_fold(min_log2fc)
    costs = {"cost_subject": cost_subject, "cost_rt": cost_rt, "cost_well": cost_well}
    _check_inputs(
        fc,
        sd_log2,
        n_per_group,
        alpha,
        power,
        sd_rt=sd_rt,
        sd_well=sd_well,
        n_rt=n_rt,
        n_tech=n_tech,
        costs=costs,
        expected_cq=expected_cq,
    )
    if cq_one_copy is not None and not (_number(cq_one_copy) and 0 < cq_one_copy <= MAX_CQ):
        raise ValueError(f"cq_one_copy must be a cycle number above 0 and at most {MAX_CQ:g}")
    one_copy = CQ_ONE_COPY if cq_one_copy is None else float(cq_one_copy)
    rules = _rules(n_plates, calibrator_on_every_plate, n_candidate_refs, one_sample_per_subject)
    asked = (sd_rt, sd_well, expected_cq, *costs.values())
    budget = None
    if any(v is not None for v in asked) or n_rt != 1 or n_tech != 1:
        budget = _budget(
            fc,
            sd_log2,
            n_per_group,
            sd_rt=sd_rt,
            sd_well=sd_well,
            n_rt=n_rt,
            n_tech=n_tech,
            costs=costs,
            expected_cq=expected_cq,
            alpha=alpha,
            power=power,
            cq_one_copy=one_copy,
        )
    noise = None if expected_cq is None else cq_well_noise(expected_cq, sd_well, one_copy)
    if noise is not None:
        sd_well = noise["sd_well_used"]
    if sd_log2 is None:
        return PlanResult(
            n_needed=None,
            mde_fold=None,
            cannot_detect=[],
            rules=rules,
            message=f"Sigma unknown: give the {SIGMA_HELP}, from a pilot or an earlier "
            "Analysis Record, to get a sample size.",
            budget=budget,
        )
    sd = effective_sd(sd_log2, sd_rt, sd_well, n_rt, n_tech)
    need = n_needed(fc, sd, alpha, power)
    mde = mde_fold(n_per_group, sd, alpha, power) if n_per_group else None
    target = max(fc, 1 / fc)
    shown = _fold(target)
    cannot = []
    message = f"For a {shown}-fold change you need {need} per group."
    if mde is not None:
        message = (
            f"At this noise, {n_per_group} per group detects at least {mde:.1f}-fold. " + message
        )
        if mde > target:
            cannot.append(
                f"A {shown}-fold change: with {n_per_group} per group the smallest change "
                f"detected with {power:.0%} power is {mde:.1f}-fold."
            )
    line = _fold(2.0**min_log2fc)
    if noise is not None and noise["below_lod"]:
        cannot.append(
            f"A target at Cq {expected_cq:g}: a well holds about "
            f"{noise['copies_per_well']:.2g} copies, fewer than the {LOD_COPIES:g} a reaction "
            "needs to hold one copy 95 % of the time (MIQE), so many wells will not amplify "
            "and no number of replicates makes it measurable. Load more template."
        )
    sig, called = simulate_calls(fc, sd, need, alpha, min_log2fc)
    if called < RARELY_CALLED:
        cannot.append(
            f"A {shown}-fold change: qPilot's rule calls it up or down {called:.0%} of the time "
            f"even at {need} per group, because a call needs the observed change to reach "
            f"{line}-fold."
        )
    message += (
        f" Simulated with qPilot's own rule at {need} per group: significant {sig:.0%} of the"
        f" time, called up/down {called:.0%}, because a call also needs the observed change to"
        f" reach {line}-fold."
    )
    if n_per_group:
        sig_n, called_n = simulate_calls(fc, sd, n_per_group, alpha, min_log2fc)
        message += (
            f" At the planned {n_per_group} per group: significant {sig_n:.0%},"
            f" called {called_n:.0%}."
        )
    if target < 2.0**min_log2fc:
        message += (
            f" A true change below {line}-fold is called only when noise makes it look {line}-fold"
            " or more; to detect smaller changes, the conclusion rule itself would have to change."
        )
    return PlanResult(
        n_needed=need,
        mde_fold=mde,
        cannot_detect=cannot,
        rules=rules,
        message=message,
        budget=budget,
    )
