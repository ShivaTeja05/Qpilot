"""Before the first plate: how many samples a design needs and what it cannot detect (Dev 2).

Pure arithmetic over ``qpilot.schemas`` and the standard library. Two-sample comparison on the
log2 normalised scale with a normal approximation plus the usual +1 small-sample correction:

    n per group  = 2 (z_{1-alpha/2} + z_{power})^2 sigma^2 / delta^2 + 1,   delta = log2(fc)
    MDE (log2)   = (z_{1-alpha/2} + z_{power}) * sigma * sqrt(2 / n)

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
    if fc <= 0 or fc == 1:
        raise ValueError("fc must be a positive fold change other than 1")
    if not (0 < alpha < 1 and 0 < power < 1):
        raise ValueError("alpha and power must be between 0 and 1")
    if n_per_group is not None and n_per_group < 2:
        raise ValueError("n_per_group must be at least 2")
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
    if sd_log2 <= 0:
        raise ValueError("sd_log2 must be positive")
    need = n_needed(fc, sd_log2, alpha, power)
    mde = mde_fold(n_per_group, sd_log2, alpha, power) if n_per_group else None
    target = max(fc, 1 / fc)
    cannot = []
    message = f"For a {target:g}-fold change you need {need} per group."
    if mde is not None:
        message = (
            f"At this noise, {n_per_group} per group detects at least {mde:.1f}-fold. " + message
        )
        if mde > target:
            cannot.append(
                f"A {target:g}-fold change: with {n_per_group} per group the smallest change "
                f"detected with {power:.0%} power is {mde:.1f}-fold."
            )
    return PlanResult(
        n_needed=need, mde_fold=mde, cannot_detect=cannot, rules=rules, message=message
    )
