"""Which curves count as amplified: the options of the ``amp_call`` analysis choice.

LinRegPCR decides for every well whether it found a starting quantity (``n0``). Many labs apply
a Cq cut-off on top ("Cq above 35 means not detected") before any further calculation. Where to
draw that line is a choice that can change conclusions, so qPilot treats it as one dimension of
the robustness grid (:class:`qpilot.qpcr.space.QpcrSpace`), with these rules:

* ``linregpcr`` (recommended, the default): a well counts when LinRegPCR gives it a quantity.
  This is exactly what the engine did before the dimension existed.
* ``cq_le_40``, ``cq_le_38``, ``cq_le_35``: a well whose engine Cq (LinRegPCR's TD0) is greater
  than the cut-off becomes undetermined (``n0`` = NaN) for every target, control genes included;
  the analysis then runs unchanged. The 35-cycle line is common and not recommended: a dilution
  standard of a few copies is expected to come up late, and such a line calls it "not detected".

A person's resolution of a disagreement (``StudyDesign.well_calls``, keyed ``"<run_id>/<well>"``)
overrides every rule: ``False`` makes the well undetermined, ``True`` keeps its quantity even past
a cut-off. A well without a quantity never counts.

A learned call (the Curve Judge) is not defined here. :func:`register_learned` is the documented
hook another module may call to add it, and only after its transfer validation has passed;
nothing calls it today.

Deterministic: no model call and no network.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from qpilot.schemas import ContrastResult
from qpilot.schemas_studio import AmpCallRule, WellCall

METHOD_CARD_PATH = "methods/amp_call.md"
DEFAULT_AMP_CALLS: tuple[str, ...] = ("linregpcr",)  # the legacy default: no amp_call dimension
STUDIO_AMP_CALLS: tuple[str, ...] = ("linregpcr", "cq_le_40", "cq_le_38", "cq_le_35")
RECOMMENDED = "linregpcr"
SCREEN_MIN_LOG2FC = 0.5  # W3 §4.2: a dimension enters the grid if it flips or moves log2fc > 0.5

RULES: dict[str, AmpCallRule] = {
    "linregpcr": AmpCallRule(
        id="linregpcr",
        label="LinRegPCR's own call (a starting quantity was found)",
        kind="linregpcr",
        recommended=True,
        note="Every well with a LinRegPCR starting quantity counts; the engine's default.",
        method_card=METHOD_CARD_PATH,
    ),
    "cq_le_40": AmpCallRule(
        id="cq_le_40",
        label="Cq ≤ 40 (a later Cq counts as not detected)",
        kind="cq_max",
        cq_max=40.0,
        note="A well with Cq above the line is undetermined for every gene, controls included.",
        method_card=METHOD_CARD_PATH,
    ),
    "cq_le_38": AmpCallRule(
        id="cq_le_38",
        label="Cq ≤ 38 (a later Cq counts as not detected)",
        kind="cq_max",
        cq_max=38.0,
        note="A well with Cq above the line is undetermined for every gene, controls included.",
        method_card=METHOD_CARD_PATH,
    ),
    "cq_le_35": AmpCallRule(
        id="cq_le_35",
        label="Cq ≤ 35 (common, not recommended)",
        kind="cq_max",
        cq_max=35.0,
        note=(
            "A common lab rule; it calls late but real wells, such as a few-copy standard, "
            "not detected."
        ),
        method_card=METHOD_CARD_PATH,
    ),
}
_BUILTIN = frozenset(RULES)
_LEARNED: dict[str, Callable[[pd.DataFrame], pd.Series]] = {}

METHOD_CARD: dict[str, Any] = {
    "id": "amp_call",
    "version": "1",
    "title": "Which curves count as amplified",
    "source": (
        "qPilot's own rules around LinRegPCR's call (Ruijter et al., Nucleic Acids Res 2009; "
        "Untergasser et al., BMC Bioinformatics 2021); the Cq cut-offs are common lab practice, "
        "not a published method"
    ),
    "implementation": "qpilot/qpcr/amp_call.py",
    "inputs": ["per-well table: run_id, well, n0, cq", "StudyDesign.well_calls (optional)"],
    "outputs": [
        "the per-well table with n0 = NaN where a rule says not amplified",
        "WellCall per well under every rule; the wells where rules disagree",
    ],
    "acceptance_tests": [
        "tests/engine/test_amp_call.py::test_rules_on_a_toy_table",
        "tests/engine/test_amp_call.py::test_demo_amp_call_oracle",
        "tests/engine/test_amp_call.py::test_demo_std15_late_wells",
    ],
    "licence": "Apache-2.0",
    "card": METHOD_CARD_PATH,
}


class AmpCallError(ValueError):
    """An unknown rule, or a per-well table that lacks what a rule needs."""


def get_rule(rule_id: str) -> AmpCallRule:
    """The rule with this id (built-in or registered); :class:`AmpCallError` if unknown."""
    try:
        return RULES[rule_id]
    except KeyError:
        known = ", ".join(RULES)
        raise AmpCallError(
            f"unknown amplification-call rule {rule_id!r} (known: {known})"
        ) from None


def register_learned(rule: AmpCallRule, predict: Callable[[pd.DataFrame], pd.Series]) -> None:
    """Add a learned amplification call as one more option (the Curve Judge hook).

    Call this only after the learned call's transfer validation has passed for the instrument
    in use (``qPilot-STUDIO-PRISM-PLAN.md`` step 4.3); a call that failed it ships disabled and
    is never registered. Nothing in qPilot calls this today.

    Args:
        rule: The option, with ``kind="learned"`` and an id that is not a built-in rule.
        predict: Maps the per-well table to a Series on the same index: ``True`` (amplified),
            ``False`` (not amplified), or missing / ``None`` for a curve the model cannot score,
            which then keeps LinRegPCR's call. It must be deterministic and run offline; a well
            without a quantity still never counts.

    Raises:
        AmpCallError: The rule is not ``learned`` or its id is a built-in rule.
    """
    if rule.kind != "learned":
        raise AmpCallError(f"rule {rule.id!r}: only a 'learned' rule can be registered")
    if rule.id in _BUILTIN:
        raise AmpCallError(f"rule {rule.id!r} is built in and cannot be replaced")
    RULES[rule.id] = rule
    _LEARNED[rule.id] = predict


def well_keys(curves: pd.DataFrame) -> pd.Series:
    """``"<run_id>/<well>"`` for every row: the key of ``well_roles``, ``well_calls`` and so on."""
    return curves["run_id"].astype(str) + "/" + curves["well"].astype(str)


def amplified(
    curves: pd.DataFrame, rule_id: str, well_calls: Mapping[str, bool] | None = None
) -> pd.Series:
    """Whether each well counts as amplified under one rule (a boolean Series on the index).

    Args:
        curves: The per-well table (needs ``n0``; Cq rules also need ``cq``).
        rule_id: One of :data:`RULES`.
        well_calls: A person's per-well resolutions (``"<run_id>/<well>"`` -> amplified).

    Raises:
        AmpCallError: Unknown rule, or a Cq rule on a table without a ``cq`` column.
    """
    rule = get_rule(rule_id)
    has_quantity = curves["n0"].notna()
    if rule.kind == "linregpcr":
        called = has_quantity
    elif rule.kind == "cq_max":
        if "cq" not in curves.columns:
            raise AmpCallError(f"rule {rule_id!r} needs the per-well Cq column 'cq'")
        called = has_quantity & ~(curves["cq"] > rule.cq_max)
    else:
        predicted = _LEARNED[rule_id](curves).reindex(curves.index)
        scored = predicted.notna()  # a curve the model cannot score keeps LinRegPCR's call
        learned = predicted.where(scored, False).astype(bool)
        called = has_quantity & learned.where(scored, True)
    if well_calls:
        override = well_keys(curves).map(well_calls)
        called = called.where(override.isna(), has_quantity & override.eq(True))
    return called.astype(bool)


def apply_rule(
    curves: pd.DataFrame, rule_id: str, well_calls: Mapping[str, bool] | None = None
) -> pd.DataFrame:
    """A copy of the per-well table with ``n0`` = NaN wherever the rule says not amplified.

    Every target is treated alike, control genes included; no row is removed, so a rule never
    changes which samples are in the analysis, only which of their wells are undetermined.
    """
    out = curves.copy()
    out.loc[~amplified(curves, rule_id, well_calls), "n0"] = np.nan
    return out


def well_calls(
    curves: pd.DataFrame,
    rule_ids: Sequence[str],
    overrides: Mapping[str, bool] | None = None,
) -> list[WellCall]:
    """Each well's call under every rule, in the table's row order."""
    calls = {rule_id: amplified(curves, rule_id, overrides).to_numpy() for rule_id in rule_ids}
    cq = curves["cq"] if "cq" in curves.columns else pd.Series(np.nan, index=curves.index)
    out = []
    for i, row in enumerate(curves.itertuples(index=False)):
        value = cq.iloc[i]
        out.append(
            WellCall(
                run_id=str(row.run_id),
                well=str(row.well),
                sample=str(row.sample),
                target=str(row.target),
                sample_type=str(row.sample_type),
                cq=None if pd.isna(value) else float(value),
                calls={rule_id: bool(called[i]) for rule_id, called in calls.items()},
            )
        )
    return out


def disagreements(calls: Sequence[WellCall]) -> list[WellCall]:
    """The wells whose call differs between rules (the ones a person may want to look at)."""
    return [call for call in calls if len(set(call.calls.values())) > 1]


# ---------- screening: does the choice matter enough to enter the grid? ----------


@dataclass(frozen=True)
class RuleScreen:
    """One rule tried alone from the primary analysis: genes it flips, largest log2fc shift."""

    rule_id: str
    flipped: tuple[str, ...]
    max_delta_log2fc: float

    @property
    def n_flipped(self) -> int:
        """How many genes change their conclusion under this rule alone."""
        return len(self.flipped)


@dataclass(frozen=True)
class AmpScreen:
    """The screening result (plan W3 §4.2); ``admitted`` decides whether the grid gets the axis."""

    primary: str
    rules: tuple[RuleScreen, ...]
    min_log2fc: float
    admitted: bool


def screen_amp_call(
    evaluate: Callable[[dict[str, Any]], Mapping[str, ContrastResult]],
    primary: Mapping[str, Any],
    options: Sequence[str],
    items: Sequence[str],
    min_log2fc: float = SCREEN_MIN_LOG2FC,
) -> AmpScreen:
    """Try each rule alone from the primary cell and decide whether the axis enters the grid.

    The axis is admitted when some rule flips a conclusion or moves a log2 fold change by more
    than ``min_log2fc``; either way the result is reported (as facts).

    Args:
        evaluate: The decision space's ``evaluate`` (a cell with an ``amp_call`` entry).
        primary: The primary cell (its ``amp_call`` is the primary rule).
        options: Every rule of the axis, primary first.
        items: The genes compared.
        min_log2fc: The shift that admits the axis without a flip.
    """
    base = evaluate(dict(primary))
    screens = []
    for rule_id in options[1:]:
        results = evaluate({**primary, "amp_call": rule_id})
        flipped = tuple(g for g in items if results[g].conclusion != base[g].conclusion)
        shifts = [abs(results[g].log2fc - base[g].log2fc) for g in items]
        finite = [s for s in shifts if np.isfinite(s)]
        screens.append(RuleScreen(rule_id, flipped, float(max(finite, default=0.0))))
    admitted = any(s.n_flipped or s.max_delta_log2fc > min_log2fc for s in screens)
    return AmpScreen(str(options[0]), tuple(screens), float(min_log2fc), admitted)
