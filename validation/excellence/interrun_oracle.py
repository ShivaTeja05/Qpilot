"""Correction between plates, written again from the two papers.

* Inter-run calibration (Hellemans et al., Genome Biol 2007; 8:R19): per gene, a calibrator
  measured on every plate; the plate's calibration factor is the geometric mean, over the
  calibrators, of each calibrator's quantity on the plate divided by its geometric mean over the
  plates; every quantity of that gene on that plate is divided by it.
* Factor correction (Ruijter et al., Biomol Detect Quantif 2015; 5:10-14; the RDML consortium's
  ``interRunCorr``): for each pair of plates the geometric mean of every ratio of a shared
  measurement (same target and sample, every pair of replicate wells); a missing pair is
  estimated through a plate both share data with (two rounds); a plate's factor is the
  geometric mean of its column; every quantity on it is divided by its factor.

Dictionaries and loops on the natural-log scale (qPilot works in numpy on log2).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping


def calibration_factors(
    wells: Iterable[tuple[str, str, str, float]], calibrators: Mapping[str, Iterable[str]]
) -> dict[tuple[str, str], float]:
    """``(plate, target) -> factor`` from ``(plate, sample, target, quantity)`` wells."""
    logs: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for plate, sample, target, q in wells:
        logs[(target, sample, plate)].append(math.log(q))
    out = {}
    for target, samples in calibrators.items():
        samples = list(samples)
        plates = sorted({p for (t, s, p) in logs if t == target and s in samples})
        per = {
            (s, p): sum(logs[(target, s, p)]) / len(logs[(target, s, p)])
            for s in samples
            for p in plates
        }
        for p in plates:
            devs = [per[(s, p)] - sum(per[(s, q)] for q in plates) / len(plates) for s in samples]
            out[(p, target)] = math.exp(sum(devs) / len(devs))
    return out


def plate_factors(wells: Iterable[tuple[str, str, str, float]]) -> dict[str, float]:
    """``plate -> factor`` (Ruijter et al. 2015) from ``(plate, sample, target, quantity)``."""
    logs: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    plates: set[str] = set()
    for plate, sample, target, q in wells:
        logs[(target, sample)][plate].append(math.log(q))
        plates.add(plate)
    runs = sorted(plates)
    total: dict[tuple[str, str], float] = defaultdict(float)
    count: dict[tuple[str, str], int] = defaultdict(int)
    for by_plate in logs.values():
        for a in by_plate:
            for b in by_plate:
                if a == b:
                    continue
                for va in by_plate[a]:
                    for vb in by_plate[b]:
                        total[(a, b)] += vb - va  # log(f_b / f_a)
                        count[(a, b)] += 1
    m: dict[tuple[str, str], float] = {k: total[k] / count[k] for k in total}
    for r in runs:
        if any((r, c) in m for c in runs):
            m[(r, r)] = 0.0
    for _ in range(2):  # Eq. 3: through a plate both share data with
        for r in runs:
            for c in runs:
                if r == c or (r, c) in m:
                    continue
                guesses = []
                for o in runs:
                    if o == c or (r, o) not in m:
                        continue
                    diffs = [
                        m[(i, o)] - m[(i, c)]
                        for i in runs
                        if i != r and (i, o) in m and (i, c) in m
                    ]
                    if diffs:
                        guesses.append(m[(r, o)] - sum(diffs) / len(diffs))
                if guesses:
                    m[(r, c)] = sum(guesses) / len(guesses)
                    m[(c, r)] = -m[(r, c)]
    out = {}
    for c in runs:
        column = [m[(r, c)] for r in runs if (r, c) in m]
        if len(column) >= 2:
            out[c] = math.exp(sum(column) / len(column))
    return out
