"""The further choices the grid tests on request, as the Results page shows them.

One panel per opt-in axis a design can ask for (:data:`qpilot.qpcr.designs.DESIGN_AXES`): the
efficiency models, the normaliser (NormFinder's and geNorm's best pairs, the global mean) and the
correction between plates. Each is read from the study's facts and its stored design: which
options were asked for, which apply, what each one alone changes, and the card it raised. Every
number is a fact; the words are plain.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from qpilot.schemas import DecisionCard, StudyResult
from qpilot.web.contract import AxisOptionView, AxisView
from qpilot.web.results_views import fact_ref, fact_text, plain_text

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore


@dataclass(frozen=True)
class _Words:
    """What a panel says in each state, and where its per-option numbers are."""

    status: Mapping[str, str]
    flips_prefix: str  # f_n_flipped_<prefix>_<option>
    command: str


_EFFICIENCY = _Words(
    status={
        "off": "Not tested in qPilot's grid: every quantity uses LinRegPCR's mean efficiency of "
        "each assay on each plate. Testing the other efficiency models adds them as one more "
        "choice of the grid; the analysis in use stays the same until a person decides otherwise. "
        "The robustness audit varies the efficiency model on its own, so its verdicts already "
        "include it; qPilot's grid tests it only when you ask here.",
        "swept": "Tested as one more choice of the grid: changing only the efficiency model "
        "changes {{f_n_flipped_efficiency}} of {{f_n_genes}} calls. Its Decision Card says what "
        "each model changes; the analysis in use stays LinRegPCR's mean efficiency until a "
        "person decides.",
        "screened_out": "Tried alone first: no efficiency model changes a call, and the largest "
        "move of a log2 fold change is {{f_screen_efficiency_dlog2fc}}, under the screening "
        "threshold, so the grid keeps LinRegPCR's mean efficiency and raises no card.",
        "not_applicable": "None of the efficiency models asked for applies to this study, so "
        "the grid keeps LinRegPCR's mean efficiency.",
        "single_option": "Only LinRegPCR's mean efficiency was asked for, so nothing else is "
        "tested.",
    },
    flips_prefix="eff",
    command="qpilot run --efficiency all",
)
_NORMALISER = _Words(
    status={
        "off": "Not tested in qPilot's grid: every gene is divided by the reference genes chosen "
        "for this study. "
        "Testing NormFinder's and geNorm's best pairs and the global mean adds them as one more "
        "choice of the grid; the reference genes in use stay the same until a person decides "
        "otherwise.",
        "swept": "Tested as one more choice of the grid: changing only the normaliser changes "
        "{{f_n_flipped_normaliser}} of {{f_n_genes}} calls. Its Decision Card says what each "
        "one changes; the reference genes in use stay the same until a person decides.",
        "screened_out": "Tried alone first: no other normaliser changes a call, and the largest "
        "move of a log2 fold change is {{f_screen_normaliser_dlog2fc}}, under the screening "
        "threshold, so the grid keeps the reference genes chosen and raises no card.",
        "not_applicable": "None of the other normalisers asked for applies to this study, so "
        "the grid keeps the reference genes chosen.",
        "single_option": "Only the reference genes chosen were asked for, so nothing else is "
        "tested.",
    },
    flips_prefix="norm",
    command="qpilot run --normaliser all",
)
_INTERRUN = _Words(
    status={
        "off": "Not tested in qPilot's grid: no quantity is corrected for differences between "
        "plates. Testing "
        "the inter-run calibrator and the factor correction adds them as one more choice of "
        "the grid, with a card only when a correction changes a call.",
        "swept": "Tested as one more choice of the grid: correcting between plates changes "
        "{{f_n_flipped_interrun}} of {{f_n_genes}} calls. Its Decision Card says what each "
        "correction changes; the analysis in use stays uncorrected until a person decides.",
        "screened_out": "Tried alone first: no correction between plates changes a call (the "
        "largest move of a log2 fold change is {{f_screen_interrun_dlog2fc}}), so the grid "
        "keeps the quantities uncorrected and raises no card.",
        "not_applicable": "No correction between plates can change anything in this study, so "
        "the grid keeps the quantities uncorrected.",
        "single_option": "Only the uncorrected quantities were asked for, so nothing else is "
        "tested.",
    },
    flips_prefix="irc",
    command="qpilot run --interrun all",
)
#: The efficiency panel of a file of Cq values only (``f_cq_only``; ``docs/cq-tables.md``): no
#: curve, so each assay's efficiency is its dilution series' or an assumed 2.0, never LinRegPCR's.
_EFFICIENCY_CQ = _Words(
    status={
        "off": "This file has Cq values only, so no efficiency was measured from curves: "
        "{{f_n_eff_series}} of the assays take their efficiency from their dilution series and "
        "{{f_n_eff_assumed}} assume {{f_eff_assumed_value}}, every cycle doubling the product "
        "({{f_eff_assumed_genes}}). Testing the efficiency models adds an efficiency of "
        "{{f_eff_assumed_value}} for every assay as one more choice of the grid; the analysis in "
        "use stays the same until a person decides otherwise.",
        "off_assumed": "This file has Cq values only and no assay has a dilution series, so "
        "every quantity assumes an efficiency of {{f_eff_assumed_value}}: every cycle doubles the "
        "product (the ΔΔCq assumption), not measured. No other efficiency model applies: a "
        "dilution series of each assay on the plate would measure it.",
        "swept": "Tested as one more choice of the grid: an efficiency of "
        "{{f_eff_assumed_value}} for every assay instead of each assay's dilution series changes "
        "{{f_n_flipped_efficiency}} of "
        "{{f_n_genes}} calls. Its Decision Card says what it changes; the analysis in use stays "
        "each assay's dilution series until a person decides.",
        "screened_out": "Tried alone first: an efficiency of {{f_eff_assumed_value}} for every "
        "assay changes no call, and the largest move of a log2 fold change is "
        "{{f_screen_efficiency_dlog2fc}}, "
        "under the screening threshold, so the grid keeps each assay's dilution series and "
        "raises no card.",
        "not_applicable": "None of the efficiency models asked for applies to this file of Cq "
        "values only, so the grid keeps each assay's efficiency as it is (its dilution series, "
        "else {{f_eff_assumed_value}}).",
        "single_option": "Only the efficiency in use was asked for, so nothing else is tested.",
    },
    flips_prefix="eff",
    command="qpilot run --efficiency all",
)
#: The primary efficiency option's label in a file of Cq values only.
CQ_PRIMARY_LABEL = "Each assay's efficiency from its dilution series, else 2.0 (Cq values only)"
WORDS: dict[str, _Words] = {
    "efficiency": _EFFICIENCY,
    "normaliser": _NORMALISER,
    "interrun": _INTERRUN,
}
#: Kept for callers of the efficiency panel's words.
AXIS_WORDS = _EFFICIENCY.status
EFFICIENCY_COMMAND = _EFFICIENCY.command


def _notes(name: str, facts: Mapping) -> list:
    """The panel's extra lines (facts only), per axis."""
    notes = []
    if name == "efficiency":
        if "f_n_eff_excluded_per_well" in facts:
            notes.append(
                fact_text(
                    "With each well's own efficiency, {{f_n_eff_excluded_per_well}} study wells "
                    "whose own efficiency is outside LinRegPCR's valid range are left out.",
                    facts,
                )
            )
        fallback = facts.get("f_eff_std_fallback")
        if fallback is not None and str(fallback.value) not in ("", "none"):
            notes.append(
                fact_text(
                    "Amplicons without a dilution series keep LinRegPCR's mean efficiency under "
                    "the dilution-series model: {{f_eff_std_fallback}}.",
                    facts,
                )
            )
    elif name == "normaliser":
        if "f_nf_agreement" in facts:
            notes.append(fact_text("{{f_nf_agreement}}", facts))
        if "f_gm_n_genes" in facts and "f_axis_normaliser_unavailable_global_mean" not in facts:
            notes.append(
                fact_text(
                    "The global mean is the mean of {{f_gm_n_genes}} genes. It is valid only "
                    "when the genes measured were not chosen for this comparison.",
                    facts,
                )
            )
        if "f_gm_shift_fold" in facts:
            notes.append(
                fact_text(
                    "Against the reference genes in use, the global mean is {{f_gm_shift_fold}} "
                    "in the first group compared with the second (p {{f_gm_shift_p}}).",
                    facts,
                )
            )
    elif name == "interrun" and "f_irc_n_split" in facts:
        notes.append(
            fact_text(
                "{{f_irc_n_split}} genes have their samples on more than one of the "
                "{{f_irc_n_runs}} plates; {{f_irc_n_calibrated}} of them have the same "
                "calibrator sample on each of their plates, and {{f_irc_n_pairs}} pairs of "
                "plates share a measurement.",
                facts,
            )
        )
    return notes


def _n(facts: Mapping, fid: str) -> int:
    fact = facts.get(fid)
    try:
        return int(fact.value) if fact is not None else 0
    except (TypeError, ValueError):
        return 0


def _cq_unavailable(facts: Mapping) -> dict[str, str]:
    """A Cq-only study's efficiency models that do not apply, from its facts (asked or not)."""
    from qpilot.qpcr.cq_only import NOT_APPLICABLE

    out = {"per_well": NOT_APPLICABLE["per_well"], "amplicon_mean": NOT_APPLICABLE["amplicon_mean"]}
    if _n(facts, "f_n_eff_series"):
        out["standard_curve"] = (
            "the analysis in use already takes each assay's efficiency from its dilution series"
        )
    else:
        out["assumed_2"] = "the analysis in use already assumes an efficiency of 2.0"
        out["standard_curve"] = "no assay has a dilution series with at least 3 levels"
    return out


def _cq_notes(facts: Mapping) -> list:
    """Each analysed assay's efficiency in words (facts ``f_eff_words_*``), sorted."""
    return [
        fact_text("{{" + fid + "}}", facts)
        for fid in sorted(facts)
        if fid.startswith("f_eff_words_")
    ]


def axis_view(
    name: str,
    result: StudyResult,
    cards: Sequence[DecisionCard],
    asked: Sequence[str],
    session: str | None,
) -> AxisView:
    """One further choice's panel, read from the study's facts."""
    from qpilot.core.facts import slug
    from qpilot.qpcr.axes import get_axis

    axis = get_axis(name)
    facts = result.facts
    cq_values = name == "efficiency" and "f_cq_only" in facts
    words = _EFFICIENCY_CQ if cq_values else WORDS[name]
    status_fact = facts.get(f"f_axis_{name}")
    status = str(status_fact.value) if status_fact is not None else "off"
    if status not in words.status:
        status = "off"
    said = status
    if cq_values and status == "off" and _n(facts, "f_n_eff_series") == 0:
        said = "off_assumed"
    absent = _cq_unavailable(facts) if cq_values else {}
    options = []
    for option in axis.catalogue:
        s = slug(option.id)
        why = facts.get(f"f_axis_{name}_unavailable_{s}")
        flips = facts.get(f"f_n_flipped_{words.flips_prefix}_{s}") or facts.get(
            f"f_screen_{name}_flips_{s}"
        )
        primary = option.tier == "primary"
        unavailable = str(why.value) if why is not None else absent.get(option.id)
        tested = status != "off" and (primary or option.id in asked) and unavailable is None
        options.append(
            AxisOptionView(
                id=option.id,
                label=CQ_PRIMARY_LABEL if cq_values and primary else option.label,
                tier=option.tier,
                primary=primary,
                tested=tested,
                flips=fact_ref(flips) if flips is not None and not primary else None,
                unavailable=unavailable,
            )
        )
    try:
        text = fact_text(words.status[said], facts)
    except (KeyError, TypeError, ValueError):
        text = plain_text(words.status["off"])
    try:
        notes = _cq_notes(facts) if cq_values else _notes(name, facts)
    except (KeyError, TypeError, ValueError):
        notes = []
    card = next((c for c in cards if c.kind == axis.card_kind), None)
    return AxisView(
        name=name,
        title=axis.title,
        status=status,  # type: ignore[arg-type]
        text=text,
        options=options,
        card_id=card.id if card is not None else None,
        notes=notes,
        can_propose=session is not None,
        command=None if session is not None else words.command,
    )


def axis_views(
    store: StudyStore,
    result: StudyResult,
    cards: Sequence[DecisionCard],
    session: str | None,
) -> list[AxisView]:
    """Every further choice the grid can test on request, in the registry's order."""
    from qpilot.qpcr.designs import DESIGN_AXES

    try:
        design = store.design(result.study_id)
    except (OSError, ValueError):
        design = None
    out = []
    for name in DESIGN_AXES:
        asked = tuple((design.axes or {}).get(name, ())) if design is not None else ()
        out.append(axis_view(name, result, cards, asked, session))
    return out


__all__ = ["AXIS_WORDS", "EFFICIENCY_COMMAND", "WORDS", "axis_view", "axis_views"]
