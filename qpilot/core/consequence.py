"""What an option does to the conclusions: the three consequence classes, ranked.

Domain-agnostic. Items are plain string ids (genes for qPCR) and the core never imports a domain
plugin. A plugin computes, for every item, its baseline (log2 fold change, call, half-width of
the 95 % confidence interval on the log2 scale) and the ``(log2fc, call)`` it would have under one
option (keep a well, read it another way, set a sample aside, ...). :func:`classify` then says
what that option does, in one of three classes, ranked best-first in :data:`CLASSES`:

* ``changes_call``: at least one call (up / down / none) changes;
* ``beyond_ci``: no call changes, but a log2 fold change moves by more than its baseline CI
  half-width;
* ``changes_nothing``: neither.

With ``root`` given (the result the person clicked) the class is the root item's own; the
changed calls are still listed for every item, so "it changes the call here, and also these
two elsewhere" is one object. Without a root the class is the worst over all items.

An item missing from the option's mapping can no longer be concluded under that option (its
data are gone); it counts as a changed call, with no delta. Deltas that are not finite (an item
with no test) are ignored for the size of the change.

Deterministic: no model call and no network.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

CLASSES: tuple[str, ...] = ("changes_call", "beyond_ci", "changes_nothing")  # best first
CLASS_RANK: dict[str, int] = {name: i for i, name in enumerate(CLASSES)}
NO_LONGER_CONCLUDED = "withheld"  # the call of an item the option leaves without data


@dataclass(frozen=True)
class Baseline:
    """One item's result under the analysis everyone sees today."""

    log2fc: float
    call: str
    half_ci: float  # half-width of the 95 % CI on the log2 scale; NaN when there is no test


@dataclass(frozen=True)
class Consequence:
    """What one option does to the conclusions.

    ``cls`` is one of :data:`CLASSES`; ``changed_calls`` are the items whose call changes,
    sorted; ``root_delta`` is the root item's change in log2 fold change (``None`` without a
    root, or when the root has no finite change); ``max_abs_delta`` is the largest absolute
    change over all items (0.0 when none is finite); ``root`` is the item the class is for
    (``None``: any item).
    """

    cls: str
    changed_calls: tuple[str, ...]
    n_changed: int
    root_delta: float | None
    max_abs_delta: float
    root: str | None = None

    @property
    def effect(self) -> float:
        """Size of the change used for ranking: ``|root_delta|`` with a root, else the largest."""
        if self.root is not None:
            return abs(self.root_delta) if self.root_delta is not None else 0.0
        return self.max_abs_delta

    def as_dict(self) -> dict[str, Any]:
        """Plain data (lists, not tuples) for JSON output."""
        out = asdict(self)
        out["changed_calls"] = list(self.changed_calls)
        return out


NOTHING = Consequence("changes_nothing", (), 0, 0.0, 0.0)  # what "keep" does (any root)


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def classify(
    base: Mapping[str, Baseline],
    option: Mapping[str, tuple[float, str]],
    root: str | None = None,
) -> Consequence:
    """Classify one option against the baseline.

    Args:
        base: Item id -> its baseline result.
        option: Item id -> ``(log2fc, call)`` under the option. Items in ``option`` that are
            not in ``base`` are ignored.
        root: The item the question is about, or ``None`` for "any item".

    Returns:
        The :class:`Consequence`.

    Raises:
        KeyError: ``root`` is not an item of ``base``.
    """
    if root is not None and root not in base:
        raise KeyError(f"root item {root!r} is not in the baseline")
    changed: list[str] = []
    beyond: list[str] = []
    deltas: dict[str, float] = {}
    for item, ref in base.items():
        if item not in option:
            changed.append(item)
            continue
        log2fc, call = option[item]
        if call != ref.call:
            changed.append(item)
        delta = float(log2fc) - float(ref.log2fc)
        if not math.isfinite(delta):
            continue
        deltas[item] = delta
        if _finite(ref.half_ci) and abs(delta) > ref.half_ci:
            beyond.append(item)
    max_abs = max((abs(d) for d in deltas.values()), default=0.0)
    changed_calls = tuple(sorted(changed))
    if root is None:
        root_delta = None
        if changed_calls:
            cls = "changes_call"
        elif beyond:
            cls = "beyond_ci"
        else:
            cls = "changes_nothing"
    else:
        root_delta = deltas.get(root)
        if root in changed:
            cls = "changes_call"
        elif root in beyond:
            cls = "beyond_ci"
        else:
            cls = "changes_nothing"
    return Consequence(cls, changed_calls, len(changed_calls), root_delta, max_abs, root)


def classify_roots(
    base: Mapping[str, Baseline], option: Mapping[str, tuple[float, str]]
) -> dict[str | None, Consequence]:
    """:func:`classify` for "any item" (key ``None``) and for every item as the root, at once.

    One pass over the items instead of one per root; each value equals
    ``classify(base, option, root)``.
    """
    overall = classify(base, option, None)
    changed = set(overall.changed_calls)
    out: dict[str | None, Consequence] = {None: overall}
    for item, ref in base.items():
        delta = None
        if item in option:
            d = float(option[item][0]) - float(ref.log2fc)
            delta = d if math.isfinite(d) else None
        if item in changed:
            cls = "changes_call"
        elif delta is not None and _finite(ref.half_ci) and abs(delta) > ref.half_ci:
            cls = "beyond_ci"
        else:
            cls = "changes_nothing"
        out[item] = Consequence(
            cls, overall.changed_calls, overall.n_changed, delta, overall.max_abs_delta, item
        )
    return out


def sort_key(cons: Consequence) -> tuple[int, float, float]:
    """Most consequential first.

    With a root: class, then the root's change, then the number of calls changed elsewhere.
    For any item: class, then the number of calls changed, then the largest change.
    """
    if cons.root is not None:
        return (CLASS_RANK[cons.cls], -cons.effect, -cons.n_changed)
    return (CLASS_RANK[cons.cls], -cons.n_changed, -cons.max_abs_delta)


def best(cons: Sequence[Consequence]) -> Consequence:
    """The most consequential of several options (ties keep the first given).

    Raises:
        ValueError: ``cons`` is empty.
    """
    if not cons:
        raise ValueError("no consequence to choose from")
    return min(cons, key=sort_key)
