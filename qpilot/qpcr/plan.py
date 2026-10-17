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
"""

from __future__ import annotations

import math
from statistics import NormalDist

from qpilot.schemas import PlanResult

SIGMA_HELP = "SD of log2 normalised expression between biological replicates (not technical Cq SD)"
# Plausible bounds: a 1000-fold scatter between replicates or a fold change beyond 1000 is a typo.
MAX_SD_LOG2 = 10.0
MAX_FOLD = 1000.0
MAX_N_PER_GROUP = 1_000_000


def _z_sum(alpha: float, power: float) -> float:
    nd = NormalDist()
    return nd.inv_cdf(1 - alpha / 2) + nd.inv_cdf(power)


def n_needed(fc: float, sd_log2: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Samples per group to detect a fold change ``fc`` (either direction) with ``power``."""
    delta = abs(math.log2(fc))
    return math.ceil(2 * _z_sum(alpha, power) ** 2 * sd_log2**2 / delta**2 + 1)


def mde_fold(n_per_group: int, sd_log2: float, alpha: float = 0.05, power: float = 0.80) -> float:
    """Smallest fold change a balanced design with ``n_per_group`` detects with ``power``."""
    return 2.0 ** (_z_sum(alpha, power) * sd_log2 * math.sqrt(2 / n_per_group))


SIM_REPS = 20_000


def simulate_calls(
    fc: float,
    sd_log2: float,
    n_per_group: int,
    alpha: float = 0.05,
    min_log2fc: float = 1.0,
    reps: int = SIM_REPS,
) -> tuple[float, float]:
    """Simulate qPilot's own rule on a true ``fc``; return (P(significant), P(called)).

    Each replicate is a study with ``n_per_group`` normal log2 values per group and SD
    ``sd_log2``; it runs a Welch t-test and counts a call only when it is significant **and** the
    observed change reaches ``2**min_log2fc`` in the true direction. For normal data each group's
    mean and variance are independent (normal and scaled chi-square), so they are drawn directly:
    the same distribution as drawing every value, in memory that does not grow with
    ``n_per_group``. Seeded, so the same inputs give the same numbers.
    """
    import numpy as np
    from scipy import stats

    rng = np.random.default_rng(0)
    delta = math.log2(fc)
    n = n_per_group
    mean_hi = rng.normal(delta, sd_log2 / math.sqrt(n), size=reps)
    mean_lo = rng.normal(0.0, sd_log2 / math.sqrt(n), size=reps)
    var_hi = sd_log2**2 * rng.chisquare(n - 1, size=reps) / (n - 1)
    var_lo = sd_log2**2 * rng.chisquare(n - 1, size=reps) / (n - 1)
    se2_hi, se2_lo = var_hi / n, var_lo / n
    diff = mean_hi - mean_lo
    t = diff / np.sqrt(se2_hi + se2_lo)
    df = (se2_hi + se2_lo) ** 2 / ((se2_hi**2 + se2_lo**2) / (n - 1))
    p = 2 * stats.t.sf(np.abs(t), df)
    significant = p < alpha
    same_direction = np.sign(diff) == np.sign(delta)
    called = significant & same_direction & (np.abs(diff) >= min_log2fc)
    return float(significant.mean()), float(called.mean())


RARELY_CALLED = 0.05  # below this, the design "cannot detect" the change under qPilot's rule


def _fold(x: float) -> str:
    """A fold change for prose, never rounded onto the 2-fold line it falls short of."""
    text = f"{x:.3g}"
    return "just under 2" if x < 2 and float(text) >= 2 else text


def _check_inputs(
    fc: float, sd_log2: float | None, n_per_group: int | None, alpha: float, power: float
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


def plan(
    fc: float = 2.0,
    sd_log2: float | None = None,
    n_per_group: int | None = None,
    alpha: float = 0.05,
    power: float = 0.80,
    n_plates: int | None = None,
    calibrator_on_every_plate: bool | None = None,
    n_candidate_refs: int | None = None,
    one_sample_per_subject: bool | None = None,
) -> PlanResult:
    """Check a design before it is run.

    Args:
        fc: the smallest fold change worth detecting (e.g. 2.0).
        sd_log2: SD of log2 normalised expression between biological replicates; ``None``
            gives a message instead of numbers.
        n_per_group: the planned samples per group; enables the minimum detectable effect.
        alpha: two-sided significance level.
        power: the chance of detecting ``fc`` when it is real.
        n_plates: how many plates the study spans.
        calibrator_on_every_plate: whether an inter-run calibrator is on every plate.
        n_candidate_refs: how many candidate reference genes will be tested.
        one_sample_per_subject: solid tissue with one sample per subject.
    """
    _check_inputs(fc, sd_log2, n_per_group, alpha, power)
    rules = _rules(n_plates, calibrator_on_every_plate, n_candidate_refs, one_sample_per_subject)
    if sd_log2 is None:
        return PlanResult(
            n_needed=None,
            mde_fold=None,
            cannot_detect=[],
            rules=rules,
            message=f"Sigma unknown: give the {SIGMA_HELP}, from a pilot or an earlier "
            "Analysis Record, to get a sample size.",
        )
    need = n_needed(fc, sd_log2, alpha, power)
    mde = mde_fold(n_per_group, sd_log2, alpha, power) if n_per_group else None
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
    sig, called = simulate_calls(fc, sd_log2, need, alpha)
    if called < RARELY_CALLED:
        cannot.append(
            f"A {shown}-fold change: qPilot's rule calls it up or down {called:.0%} of the time "
            f"even at {need} per group, because a call needs the observed change to reach 2-fold."
        )
    message += (
        f" Simulated with qPilot's own rule at {need} per group: significant {sig:.0%} of the"
        f" time, called up/down {called:.0%}, because a call also needs the observed change to"
        f" reach 2-fold."
    )
    if n_per_group:
        sig_n, called_n = simulate_calls(fc, sd_log2, n_per_group, alpha)
        message += (
            f" At the planned {n_per_group} per group: significant {sig_n:.0%},"
            f" called {called_n:.0%}."
        )
    if target < 2:
        message += (
            " A true change below 2-fold is called only when noise makes it look 2-fold or more;"
            " to detect smaller changes, the conclusion rule itself would have to change."
        )
    return PlanResult(
        n_needed=need, mde_fold=mde, cannot_detect=cannot, rules=rules, message=message
    )
