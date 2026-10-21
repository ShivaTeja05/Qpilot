"""The Import Trust card: what curves processed before export mean for the analysis.

An instrument export whose curves were most likely baseline-subtracted by the vendor's software
(raw-ness verdict ``baseline_subtracted``, :mod:`qpilot.io.rawness`), or whose processing qPilot
could not tell (``unknown``), gets a Decision Card of kind ``capture.import_trust``, which only a
person decides (registered ``always_human`` in ``qpilot/qpcr/cards.py``). Science:
``agent-bus/contracts/scientist-spec-capture.md`` §4–5. Curves normalised to a passive reference
(``normalized``, Rn) keep their ground phase and are what LinRegPCR expects from those
instruments: no card, as for raw curves, rescaled curves, a Cq table and an RDML file.

Until a person decides, the analysis is the curves **as imported, capped at Moderate** (fail
closed: no study from vendor-baselined curves is graded High, decided or not). The options:

==================  =======================================================  ==============
option              the analysis                                             confidence
==================  =======================================================  ==============
``reexport_raw``    nothing analysed differently; the vendor's re-export     capped Moderate
                    recipe is shown (open the raw export as a new study)
``analyse_as_is``   LinRegPCR on the curves as imported                      capped Moderate
``cq_only``         the curves are not used: the instrument's Cq, quantity   capped Low
                    ``2^-Cq`` (``qpilot.qpcr.curves``, ``instrument_cq``)
==================  =======================================================  ==============

The caps are **qPilot policy**, not a published rule, and are worded so ("qPilot caps…"). The
analysis is carried by the design (``StudyDesign.import_trust``, :func:`analysis_for`), so a
record re-runs to the same grades; the choice itself is a ``curve.import_trust`` proposal in the
Studio session's hash-chained inbox, accepted by the person with a reason
(:meth:`qpilot.studio_service.Studio.decide_import_trust`).

Pure and deterministic: no model, no network. Every sentence here is qPilot's own wording; no
text from a file is ever put in one.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from qpilot.core.card_kinds import card_kind
from qpilot.core.confidence import Cap
from qpilot.schemas import CardOption, DecisionCard
from qpilot.schemas_studio import ImportTrust, ProposalCheck

CARD_KIND = "capture.import_trust"
CARD_ID = "card_import_trust"
PROPOSAL_KIND = "curve.import_trust"
SUBJECT = "import"
MAKER = "qpilot-import-trust"  # the rule that proposes a person's choice on the card
CAP_ID = "import_trust"  # the cap's id among a grade's checks
RULE_ID = "D-TRUST"
CAPTURE_FILE = "capture.json"  # written by qpilot.web.intake in the Studio session's folder
TEMPLATE = "import_trust"

#: Raw-ness verdicts that call for the card.
CARD_VERDICTS: tuple[str, ...] = ("baseline_subtracted", "unknown")
OPTIONS: tuple[str, ...] = ("reexport_raw", "analyse_as_is", "cq_only")
RECOMMENDED = "reexport_raw"
#: The option whose analysis is in use before a person decides.
IN_USE = "analyse_as_is"
ANALYSIS: dict[str, str] = {"reexport_raw": "as_is", "analyse_as_is": "as_is", "cq_only": "cq_only"}
LABELS: dict[str, str] = {
    "reexport_raw": "Re-export the raw curves",
    "analyse_as_is": "Analyse the curves as they are",
    "cq_only": "Use the instrument's Cq values only",
}
#: What each option does, in words (no numbers: the caps are levels).
EFFECTS: dict[str, str] = {
    "reexport_raw": (
        "Export the raw fluorescence and open it as a new study (how, below). Until then the "
        "analysis here is the curves as imported, with confidence capped at Moderate."
    ),
    "analyse_as_is": (
        "LinRegPCR analyses the curves as they were exported. Confidence is capped at Moderate."
    ),
    "cq_only": (
        "The curves are not used: each well's Cq is the instrument's and every cycle is assumed "
        "to double the product (the 2^-ΔΔCq assumption, efficiency not measured). Confidence is "
        "capped at Low."
    ),
}
QUESTION = "Can the imported curves be analysed as they are?"

_AS_IS_REASON = {
    "baseline_subtracted": (
        "qPilot caps confidence at Moderate: vendor-baselined curves (the instrument software "
        "subtracted a baseline before export, so LinRegPCR cannot estimate each well's own "
        "baseline and efficiency)"
    ),
    "unknown": (
        "qPilot caps confidence at Moderate: qPilot could not tell whether the curves were "
        "processed before export, so each well's efficiency may be biased"
    ),
}
_CQ_ONLY_REASON = (
    "qPilot caps confidence at Low: efficiency assumed (the instrument's Cq values, every cycle "
    "assumed to double the product; the curves are not used)"
)
_RECIPES = {
    "cfx": (
        "In CFX Manager or CFX Maestro, set the baseline setting to “No Baseline Subtraction” "
        "(and turn Fluorescent Drift Correction off) before exporting, export the data sheets "
        "again and open them as a new study."
    ),
    "quantstudio": (
        "Export the amplification data as Rn, or the Multicomponent Data, not Delta Rn, and open "
        "it as a new study."
    ),
}
_RECIPE = (
    "Export the fluorescence as the instrument read it, before any baseline subtraction or "
    "smoothing, from the instrument software, and open it as a new study."
)


def card_verdict(verdict: str | None) -> str | None:
    """The verdict when it calls for the card (``baseline_subtracted``/``unknown``), else None."""
    return verdict if verdict in CARD_VERDICTS else None


def analysis_for(option: str) -> str:
    """The analysis an option of the card leads to: ``as_is`` or ``cq_only``.

    Raises:
        ValueError: Not an option of the card.
    """
    try:
        return ANALYSIS[option]
    except KeyError:
        raise ValueError(f"the Import Trust card has no option {option!r}") from None


def cap_for(trust: ImportTrust | None) -> Cap | None:
    """The cap on every grade of a study with this import trust (``None``: no cap)."""
    if trust is None:
        return None
    if trust.analysis == "cq_only":
        return Cap(level="Low", check_id=CAP_ID, note=_CQ_ONLY_REASON)
    return Cap(level="Moderate", check_id=CAP_ID, note=_AS_IS_REASON[trust.verdict])


def caps(verdict: str) -> dict[str, Cap]:
    """Each option's cap for an import with this verdict (for the card)."""
    return {
        option: cap_for(ImportTrust(verdict=verdict, analysis=ANALYSIS[option]))  # type: ignore[misc]
        for option in OPTIONS
    }


#: Efficiency models (``qpilot/qpcr/axes/efficiency.py``) an import's processing rules out.
_PROCESSED = (
    "the curves were processed before export (see Import Trust), so no well's own efficiency "
    "is trusted"
)
_NO_CURVES = "the curves are not used (Cq only), so no efficiency was measured"
_ASSUMED = "the analysis in use (Cq only) already assumes every cycle doubles the product"


def not_measured(trust: ImportTrust | None) -> dict[str, str]:
    """Efficiency options that do not apply under this import trust -> why, in plain words.

    Processed curves rule out each well's own efficiency (scientist-spec-capture.md §4); Cq
    only also rules out the per-amplicon mean (nothing was measured) and the assumed 2 (it is
    the analysis in use).
    """
    if trust is None:
        return {}
    out = {"per_well": _PROCESSED}
    if trust.analysis == "cq_only":
        out.update(per_well=_NO_CURVES, amplicon_mean=_NO_CURVES, assumed_2=_ASSUMED)
    return out


def recipe(connector_id: str) -> str:
    """How to export the raw curves from the software that wrote this export."""
    return _RECIPES.get(connector_id, _RECIPE)


_VERDICTS: dict[tuple[str, int, int], str | None] = {}
_VERDICTS_LOCK = threading.Lock()


def session_verdict(folder: Path) -> str | None:
    """The raw-ness verdict of the export a Studio session was opened from, when it has a card.

    Read from the session's ``capture.json`` (kept per file size and time); ``None`` for a
    session opened from an RDML file, a verdict without a card, or a damaged record.
    """
    path = Path(folder) / CAPTURE_FILE
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _VERDICTS_LOCK:
        if key in _VERDICTS:
            return _VERDICTS[key]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        verdict = (record["meta"].get("rawness") or {}).get("study_verdict")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        verdict = None
    found = card_verdict(verdict if isinstance(verdict, str) else None)
    with _VERDICTS_LOCK:
        if len(_VERDICTS) > 256:
            _VERDICTS.clear()
        _VERDICTS[key] = found
    return found


def check(option: Any, verdict: str | None, n_instrument_cq: int) -> ProposalCheck:
    """``D-TRUST``: the engine's refute-only check of a ``curve.import_trust`` proposal.

    The engine refutes only what it can see: an option the card does not have, an import whose
    curves call for no card, and Cq only from an export without instrument Cq values. Which
    option to take is a person's decision; the best this says is ``consistent``.
    """
    details: dict[str, Any] = {"verdict": verdict, "n_instrument_cq": int(n_instrument_cq)}
    if option not in OPTIONS:
        note = "the Import Trust card's options are " + ", ".join(OPTIONS)
        return ProposalCheck(status="contradicted", rule_ids=[RULE_ID], details=details, note=note)
    if verdict is None:
        note = (
            "this study's curves call for no Import Trust card (raw, normalised to a passive "
            "reference, or not opened from an instrument export)"
        )
        return ProposalCheck(status="contradicted", rule_ids=[RULE_ID], details=details, note=note)
    if option == "cq_only" and n_instrument_cq < 1:
        note = "the export has no Cq values from the instrument, so nothing is left without curves"
        return ProposalCheck(status="contradicted", rule_ids=[RULE_ID], details=details, note=note)
    return ProposalCheck(
        status="consistent",
        rule_ids=[RULE_ID],
        details=details,
        note="the import's curves call for this card; which option to take is a decision",
    )


def trust_card(
    verdict: str,
    *,
    connector_id: str,
    plate_verdicts: dict[str, str] | None = None,
    n_instrument_cq: int = 0,
    n_wells: int = 0,
) -> DecisionCard:
    """The Import Trust Decision Card of an import with this verdict (always a person's).

    The card is open; a caller overlays a person's decision or an agent's request from the
    session's inbox. ``n_instrument_cq`` decides whether ``cq_only`` can be chosen.

    Raises:
        ValueError: The verdict calls for no card.
    """
    import qpilot.qpcr.cards  # noqa: F401  (registers the kind: always a person's decision)

    if card_verdict(verdict) is None:
        raise ValueError(f"a {verdict!r} import has no Import Trust card")
    kind = card_kind(CARD_KIND).name
    by_option = caps(verdict)
    return DecisionCard(
        id=CARD_ID,
        kind=kind,
        rank=0,
        impact={"flips": False, "n_genes_flipped": 0, "max_delta_log2fc": 0.0},
        evidence={
            "verdict": verdict,
            "plate_verdicts": dict(plate_verdicts or {}),
            "connector": connector_id,
            "n_instrument_cq": int(n_instrument_cq),
            "n_wells": int(n_wells),
            "recipe": recipe(connector_id),
            "in_use": IN_USE,
            "caps": {o: {"level": c.level, "reason": c.note} for o, c in by_option.items()},
            "cq_only_available": n_instrument_cq > 0,
        },
        options=[CardOption(id=o, label=LABELS[o], per_gene={}) for o in OPTIONS],
        recommended=RECOMMENDED,
        rationale_template=TEMPLATE,
        facts=[],
    )


__all__ = [
    "ANALYSIS",
    "CAPTURE_FILE",
    "CAP_ID",
    "CARD_ID",
    "CARD_KIND",
    "CARD_VERDICTS",
    "EFFECTS",
    "IN_USE",
    "LABELS",
    "MAKER",
    "OPTIONS",
    "PROPOSAL_KIND",
    "QUESTION",
    "RECOMMENDED",
    "SUBJECT",
    "analysis_for",
    "cap_for",
    "caps",
    "card_verdict",
    "check",
    "not_measured",
    "recipe",
    "session_verdict",
    "trust_card",
]
