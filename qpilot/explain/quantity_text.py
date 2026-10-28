"""The words of a quantification study's Decision Cards (``quantity_amp_v1``, ``quantity_loq_v1``).

A study that quantifies samples (:mod:`qpilot.qpcr.quantify_study`) has two choices that can
change what is reported for a sample: which wells count as detected, and how precise a quantity
must be to be reported (the LOQ line). Every number is a ``{{fact_id}}`` token, as in
:mod:`qpilot.explain.templates`; assay and sample names never enter the text (they may hold
digits, which the validator refuses outside a token).
"""

from __future__ import annotations

from collections.abc import Mapping

from qpilot.schemas import DecisionCard, Fact

Facts = Mapping[str, Fact]

#: The card's impact line when no option changes a reported result.
NO_CHANGE = "No sample's reported result changes with this choice"


def _t(fid: str) -> str:
    return "{{" + fid + "}}"


def _changed(facts: Facts, dim: str) -> str:
    fid = f"f_qn_changed_{dim}"
    if fid not in facts or "f_qn_items" not in facts:
        return ""
    fold = _t("f_qn_fold") if "f_qn_fold" in facts else "twofold"
    if not facts[fid].value:
        anywhere = facts.get(f"f_qn_changed_anywhere_{dim}")
        if anywhere is not None and anywhere.value:
            return (
                f"At the planned settings no option changes what is reported for any of the "
                f"{_t('f_qn_items')} sample results; at other settings {_t(anywhere.id)} can "
                "change, so an agent must ask a person to change it."
            )
        return (
            f"No option changes what is reported for any of the {_t('f_qn_items')} sample "
            f"results (its class, or its number by more than {fold})."
        )
    return (
        f"Another option reports {_t(fid)} of the {_t('f_qn_items')} sample results "
        f"differently (another class, or a number that moves by more than {fold}), so a person "
        "decides, with a reason."
    )


def amp_text(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    """``quantity_amp_v1``: which wells count as detected, for the quantities."""
    text = (
        "Which wells count as detected decides which standards are on the curve, the limit of "
        "detection, and how many wells of each sample are detected. "
    )
    if "f_amp_primary" in facts:
        text += f"This analysis counts a well by {_t('f_amp_primary')}; "
        text += "the other options are Cq cut-offs, which call a late well not detected. "
    return text + _changed(facts, "amp_call")


def loq_text(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    """``quantity_loq_v1``: how precise a quantity must be to be reported."""
    text = (
        "The limit of quantification is the lowest standard whose read-back quantities agree "
        "closely enough; below it a sample is detected but its number is not precise. "
    )
    if "f_qn_loq_cv" in facts:
        text += (
            f"This analysis asks for a coefficient of variation of at most {_t('f_qn_loq_cv')} "
            "(Forootan et al.); a stricter line can move the limit up. "
        )
    return text + _changed(facts, "loq_cv")


def impact_tokens(card: DecisionCard, facts: Facts) -> str:
    """The impact line of a quantity card (fact tokens)."""
    dim = str(card.evidence.get("dimension") or "")
    fid = f"f_qn_changed_{dim}"
    if card.impact.get("flips") and fid in facts and "f_qn_items" in facts:
        return f"{_t(fid)} of {_t('f_qn_items')} sample results change with this choice"
    return NO_CHANGE
