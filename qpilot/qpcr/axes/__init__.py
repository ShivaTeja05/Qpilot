"""The axis registry: every analysis choice the decision space can vary, declared once.

An **axis** is one dimension of the robustness grid (:class:`qpilot.qpcr.space.QpcrSpace`): a
name, the stage of the pipeline it acts in, its options and which one is primary. The space
composes the stages in this order, memoising each stage's output by the options of that stage
and the stages before it, so adding an axis never recomputes curves:

===============  ===============================================================================
stage            what it does
===============  ===============================================================================
``matrix``       per-well quantities -> units x genes ``log2 N0`` (``amp_call``, ``efficiency``)
``aggregation``  technical replicates -> biological units (reserved)
``nondetect``    what a well that never amplified becomes (``undetermined``)
``normaliser``   divide by the mean of the control genes (``refs``)
``groups``       which units are compared (``cut``)
``test``         the two-group test (vectorised Welch)
===============  ===============================================================================

The registry also fixes the **dimension order**, so the column and row order of ``grid.csv``
never depend on which optional axes a study switches on: ``refs, cut, undetermined, amp_call``
(the legacy grid, exactly as before the registry existed), then the opt-in axes.

Legacy axes are always in the grid when they apply; opt-in axes are offered only when a
setting, design or profile asks for them, and may be screened out
(:func:`qpilot.core.robustness.screen_axis`) when no option changes anything that matters.
Every axis that is offered is reported in :attr:`QpcrSpace.axes` with its status, including the
ones held at their primary option, so a reader can always see what was and was not varied.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

Stage = Literal["matrix", "aggregation", "nondetect", "normaliser", "groups", "test"]
STAGES: tuple[Stage, ...] = ("matrix", "aggregation", "nondetect", "normaliser", "groups", "test")
Tier = Literal["primary", "defensible", "common_practice"]
AxisStatus = Literal["swept", "screened_out", "not_applicable", "single_option"]


class AxisError(ValueError):
    """An unknown axis or option, or an option that does not apply to this study."""


@dataclass(frozen=True)
class AxisOption:
    """One option of an axis.

    ``id`` is stable (card option id, fact slug, JSON key); ``value`` is what appears in
    ``space.dimensions`` and ``grid.csv``.
    """

    id: str
    value: Any
    label: str
    tier: Tier = "defensible"

    def as_dict(self) -> dict[str, Any]:
        """JSON form (tuples become ``a|b|c``, as in ``grid.csv``)."""
        return {
            "id": self.id,
            "value": option_text(self.value),
            "label": self.label,
            "tier": self.tier,
        }


@dataclass(frozen=True)
class AxisDef:
    """What the registry knows about an axis, independent of any study."""

    name: str
    stage: Stage
    title: str
    legacy: bool
    card_kind: str | None = None
    method_card: str | None = None
    catalogue: tuple[AxisOption, ...] = ()  # the named options (empty: options come from the study)

    def option(self, option_id: str) -> AxisOption:
        """The catalogue option with this id; :class:`AxisError` when unknown."""
        for option in self.catalogue:
            if option.id == option_id:
                return option
        known = ", ".join(o.id for o in self.catalogue) or "(options come from the study)"
        raise AxisError(f"unknown option {option_id!r} for axis {self.name!r} (known: {known})")


@dataclass(frozen=True)
class AxisState:
    """An axis as one study offers it: options, primary, and whether the grid sweeps it."""

    name: str
    stage: Stage
    title: str
    options: tuple[AxisOption, ...]
    primary: AxisOption
    status: AxisStatus
    reason: str = ""
    legacy: bool = False
    unavailable: tuple[tuple[str, str], ...] = ()  # (option id, why it does not apply here)

    def as_dict(self) -> dict[str, Any]:
        """JSON form for ``axes.json``, MCP and the UI (stable key order)."""
        return {
            "name": self.name,
            "stage": self.stage,
            "title": self.title,
            "legacy": self.legacy,
            "status": self.status,
            "reason": self.reason,
            "primary": self.primary.id,
            "options": [o.as_dict() for o in self.options],
            "unavailable": dict(self.unavailable),
        }


def option_text(value: Any) -> Any:
    """A dimension value as ``grid.csv`` writes it: tuples joined with ``|``."""
    return "|".join(map(str, value)) if isinstance(value, tuple) else value


# ---- the registry --------------------------------------------------------------------------

_UNDETERMINED = (
    AxisOption("drop", "drop", "Drop empty wells", "primary"),
    AxisOption("cap", "cap", "Count empty wells as very low (cap)", "defensible"),
    AxisOption(
        "floor",
        "floor",
        "Substitute the plate's detection floor for empty wells",
        "defensible",
    ),
    AxisOption(
        "censored_mle",
        "censored_mle",
        "Treat empty wells as below the detection floor (censored model)",
        "defensible",
    ),
)

_EFFICIENCY = (
    AxisOption(
        "linregpcr",
        "linregpcr",
        "LinRegPCR's mean efficiency of the amplicon on each plate",
        "primary",
    ),
    AxisOption("per_well", "per_well", "Each well's own efficiency", "defensible"),
    AxisOption(
        "amplicon_mean",
        "amplicon_mean",
        "One efficiency per amplicon over all its plates",
        "defensible",
    ),
    AxisOption("assumed_2", "assumed_2", "Efficiency assumed to be 2.0 (100 %)", "common_practice"),
    AxisOption(
        "standard_curve",
        "standard_curve",
        "Efficiency from the plate's dilution series",
        "defensible",
    ),
)

AXES: dict[str, AxisDef] = {
    axis.name: axis
    for axis in (
        AxisDef(
            "refs",
            "normaliser",
            "Which control genes to divide by",
            legacy=True,
            card_kind="reference_set",
        ),
        AxisDef(
            "cut",
            "groups",
            "Where to draw the line between the groups",
            legacy=True,
            card_kind="group_cutoff",
        ),
        AxisDef(
            "undetermined",
            "nondetect",
            "What to do with wells that never amplified",
            legacy=True,
            card_kind="undetermined",
            method_card="methods/nondetect.md",
            catalogue=_UNDETERMINED,
        ),
        AxisDef(
            "amp_call",
            "matrix",
            "Which curves count as amplified",
            legacy=False,
            card_kind="amp_call",
            method_card="methods/amp_call.md",
        ),
        AxisDef(
            "efficiency",
            "matrix",
            "Which efficiency turns Cq into quantity",
            legacy=False,
            card_kind="numbers.efficiency_model",
            method_card="methods/efficiency_model.md",
            catalogue=_EFFICIENCY,
        ),
    )
}
DIMENSION_ORDER: tuple[str, ...] = tuple(AXES)
#: The non-detect options of the legacy grid; the others are opt-in.
LEGACY_UNDETERMINED: tuple[str, ...] = ("drop", "cap")


def get_axis(name: str) -> AxisDef:
    """The registered axis with this name; :class:`AxisError` when unknown."""
    try:
        return AXES[name]
    except KeyError:
        raise AxisError(f"unknown axis {name!r} (known: {', '.join(AXES)})") from None


def ordered(names: Sequence[str]) -> list[str]:
    """``names`` in registry (dimension) order; unknown names raise :class:`AxisError`."""
    for name in names:
        get_axis(name)
    return [name for name in DIMENSION_ORDER if name in set(names)]


def stage_index(name: str) -> int:
    """Position of the axis's stage in the pipeline (``matrix`` = 0)."""
    return STAGES.index(get_axis(name).stage)


def state(
    name: str,
    options: Sequence[AxisOption],
    primary_id: str,
    status: AxisStatus,
    reason: str = "",
    title: str | None = None,
    unavailable: Sequence[tuple[str, str]] = (),
) -> AxisState:
    """An :class:`AxisState` for a registered axis; checks the primary is one of the options."""
    axis = get_axis(name)
    options = tuple(options)
    hits = [o for o in options if o.id == primary_id]
    if len(hits) != 1:
        raise AxisError(f"primary option {primary_id!r} of axis {name!r} is not one of its options")
    return AxisState(
        name=name,
        stage=axis.stage,
        title=title or axis.title,
        options=options,
        primary=hits[0],
        status=status,
        reason=reason,
        legacy=axis.legacy,
        unavailable=tuple(unavailable),
    )


__all__ = [
    "AXES",
    "DIMENSION_ORDER",
    "LEGACY_UNDETERMINED",
    "STAGES",
    "AxisDef",
    "AxisError",
    "AxisOption",
    "AxisState",
    "AxisStatus",
    "Stage",
    "get_axis",
    "option_text",
    "ordered",
    "stage_index",
    "state",
]
