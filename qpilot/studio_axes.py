"""What testing the normaliser or the correction between plates would add (Studio's proposal).

:meth:`qpilot.studio_service.Studio.axis_offer` and :meth:`~qpilot.studio_service.Studio.
propose_axis` ask this module for the two opt-in axes added after the efficiency models: which
options apply to the confirmed design (the engine's own answer: the study model built with the
axis on, :func:`qpilot.qpcr.study.build_model`), why the others do not, and the numbers and
words the rule's ``choice.axis`` proposal cites. Nothing is written here; a person still decides.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

import pandas as pd

from qpilot.schemas_studio import Evidence

#: The method card each axis's proposal cites.
METHOD_CARDS = {
    "normaliser": "methods/normfinder.md: NormFinder, geNorm's best pair and the global mean",
    "interrun": "methods/inter_run_calibration.md: how to correct differences between plates",
}
NOUN = {"normaliser": "the other normalisers", "interrun": "the corrections between plates"}


def offer(axis: str, settings: Any, curves: pd.DataFrame) -> dict[str, Any]:
    """``options`` (primary first), ``unavailable`` and ``evidence`` for ``axis`` on a study.

    ``settings`` are the confirmed design's :class:`~qpilot.qpcr.study.StudySettings`;
    ``curves`` its curve analysis's per-well table.
    """
    from qpilot.qpcr import interrun as irc
    from qpilot.qpcr.axes import normaliser as norm_axis
    from qpilot.qpcr.study import build_model

    every = norm_axis.OPTIONS if axis == "normaliser" else irc.OPTIONS
    model = build_model(curves, dataclasses.replace(settings, **{axis: every}))
    state = model.space.axes[axis]
    notes = dict(model.axis_notes.get(axis, {}))
    unavailable = dict(state.unavailable)
    options = tuple(o.id for o in state.options if o.id not in unavailable)
    return {"options": options, "unavailable": unavailable, "evidence": _numbers(axis, notes)}


def _numbers(axis: str, notes: Mapping[str, Any]) -> dict[str, Any]:
    if axis == "normaliser":
        found = notes.get("normfinder") or {}
        gm = notes.get("global_mean") or {}
        return {
            "normfinder_pair": found.get("best_pair"),
            "normfinder_pair_stability": found.get("pair_stability"),
            "normfinder_grouped": found.get("grouped"),
            "genorm_pair": notes.get("genorm_pair"),
            "agreement": notes.get("agreement") or "",
            "planned": notes.get("planned") or [],
            "global_mean_genes": gm.get("n_genes"),
            "global_mean_min_genes": gm.get("min_genes"),
            "global_mean_note": gm.get("threshold_note"),
            "global_mean_shift": gm.get("group_shift"),
        }
    return {
        "plates": notes.get("n_runs"),
        "split_genes": notes.get("n_split_targets", 0),
        "calibrated_genes": len(notes.get("calibrators") or {}),
        "plate_pairs_sharing": notes.get("n_plate_pairs_sharing", 0),
    }


def evidence(axis: str, numbers: Mapping[str, Any]) -> list[Evidence]:
    """The rule's evidence for testing ``axis``: the method card and the study's own numbers."""
    out = [Evidence(kind="rule", ref=axis, note=f"method card {METHOD_CARDS[axis]}")]
    if axis == "normaliser":
        if numbers.get("agreement"):
            stability = numbers.get("normfinder_pair_stability")
            value = f" (stability value {stability:.3f})" if stability is not None else ""
            groups = " with the study's groups" if numbers.get("normfinder_grouped") else ""
            out.append(
                Evidence(
                    kind="pattern",
                    ref="NormFinder and geNorm",
                    note=f"{numbers['agreement']} NormFinder ran{groups}{value}.",
                )
            )
        if numbers.get("global_mean_genes") is not None:
            out.append(
                Evidence(
                    kind="pattern",
                    ref="the global mean",
                    note=f"{numbers['global_mean_genes']} genes have a value in every "
                    f"compared unit; {numbers['global_mean_note']}",
                )
            )
        return out
    out.append(
        Evidence(
            kind="pattern",
            ref="plates",
            note=f"{numbers['plates']} plates; {numbers['split_genes']} genes have their "
            f"samples on more than one plate; {numbers['calibrated_genes']} of them have the "
            f"same calibrator sample on each of their plates; {numbers['plate_pairs_sharing']} "
            "pairs of plates share a measurement (the same gene in the same sample)",
        )
    )
    return out


def reasons(axis: str, on: bool, unavailable: Mapping[str, str], labels: Mapping[str, str]):
    """The rule's reasons, in plain words (what testing it does, what is not offered)."""
    if not on:
        return [
            f"stop testing {NOUN[axis]}: the analysis goes back to the grid without that "
            "choice; what a person decided on the other cards is carried back"
        ]
    if axis == "normaliser":
        lead = (
            "qPilot divides each gene by the reference genes chosen for this study; testing "
            "NormFinder's and geNorm's best pairs and the global mean shows which conclusions "
            "depend on that choice. The reference genes in use stay the same until a person "
            "decides otherwise on the card it raises; what a person decided on the other cards "
            "is carried to it, unless that choice matters more there."
        )
    else:
        lead = (
            "qPilot does not correct differences between plates; testing the inter-run "
            "calibrator and the factor correction shows whether a conclusion depends on that. "
            "A card is raised only when a correction changes a call, and the analysis in use "
            "stays uncorrected until a person decides it."
        )
    return [
        lead,
        *(
            f"not offered: {lower_first(labels.get(o, o))} ({why})"
            for o, why in sorted(unavailable.items())
        ),
    ]


def lower_first(text: str) -> str:
    """``The mean of …`` -> ``the mean of …``; a name such as ``NormFinder's`` keeps its case."""
    first = text.split(" ", 1)[0]
    return text[:1].lower() + text[1:] if first[1:].islower() else text
