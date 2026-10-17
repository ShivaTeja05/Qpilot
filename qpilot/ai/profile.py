"""The lab profile: a lab's conventions and examples drawn from its own recorded decisions.

``qpilot_profile.yaml`` (path from ``QPILOT_PROFILE``) can set tone and language, standing
conventions, the conclusion rule in words, and how many few-shot examples to use. Few-shot
examples are built **only from decisions a human made** (``actor == "human"``), so neither an
agent nor the system can teach the model its own behaviour. Loaded with ``yaml.safe_load``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import BaseModel

from qpilot.schemas import DecisionCard, DecisionEntry

AUTONOMY_POLICY = (
    "Automatic: a choice that cannot change any conclusion is decided by the system and logged.",
    "Agent may apply: such non-flipping choices, when the scientist allows decide-and-tell.",
    "Human only: any choice that can flip a conclusion, at every level, for every actor.",
)


class Profile(BaseModel):
    """A lab's preferences for how the model explains things."""

    name: str = "default"
    tone: str = "plain, precise, for a scientist who is not a statistician"
    language: str = "English"
    conventions: list[str] = []
    conclusion_rule: str = "up or down only if p < alpha and the change is at least two-fold"
    max_fewshots: int = 3


def load_profile(path: str | Path | None = None) -> Profile:
    """Load a profile from ``path`` or ``QPILOT_PROFILE``; the default profile otherwise."""
    target = path or os.environ.get("QPILOT_PROFILE")
    if not target:
        return Profile()
    data = yaml.safe_load(Path(target).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("a profile must be a YAML mapping")
    data.pop("autonomy_policy", None)  # fixed in code, shown for reference only
    return Profile.model_validate(data)


def build_fewshots(
    entries: Iterable[DecisionEntry], cards: Iterable[DecisionCard], limit: int = 3
) -> list[dict[str, str]]:
    """Recent human decisions as examples: card kind, the option chosen and the reason."""
    by_id = {c.id: c for c in cards}
    shots = []
    for entry in reversed(list(entries)):
        if entry.actor != "human" or entry.status != "applied" or entry.card_id not in by_id:
            continue
        card = by_id[entry.card_id]
        labels = {o.id: o.label for o in card.options}
        shots.append(
            {
                "card": card.kind,
                "choice": labels.get(entry.option, entry.option),
                "reason": entry.reason,
            }
        )
        if len(shots) >= limit:
            break
    return list(reversed(shots))


def autonomy_policy() -> list[str]:
    """The three-line autonomy policy shown in the app header, the profile and the record."""
    return list(AUTONOMY_POLICY)
