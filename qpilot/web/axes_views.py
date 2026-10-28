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
        "off": "Not tested: every quantity uses LinRegPCR's mean efficiency of each assay on "
        "each plate. Testing the other efficiency models adds them as one more choice of the "
        "grid; the analysis in use stays the same until a person decides otherwise.",
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
        "off": "Not tested: every gene is divided by the reference genes chosen for this study. "
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
        "off": "Not tested: no quantity is corrected for differences between plates. Testing "
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
    words = WORDS[name]
    facts = result.facts
    status_fact = facts.get(f"f_axis_{name}")
    status = str(status_fact.value) if status_fact is not None else "off"
    if status not in words.status:
        status = "off"
    options = []
    for option in axis.catalogue:
        s = slug(option.id)
        why = facts.get(f"f_axis_{name}_unavailable_{s}")
        flips = facts.get(f"f_n_flipped_{words.flips_prefix}_{s}") or facts.get(
            f"f_screen_{name}_flips_{s}"
        )
        primary = option.tier == "primary"
        tested = status != "off" and (primary or option.id in asked) and why is None
        options.append(
            AxisOptionView(
                id=option.id,
                label=option.label,
                tier=option.tier,
                primary=primary,
                tested=tested,
                flips=fact_ref(flips) if flips is not None and not primary else None,
                unavailable=str(why.value) if why is not None else None,
            )
        )
    try:
        text = fact_text(words.status[status], facts)
    except (KeyError, TypeError, ValueError):
        text = plain_text(words.status["off"])
    try:
        notes = _notes(name, facts)
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
