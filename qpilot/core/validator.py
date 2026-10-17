"""The "no naked numbers" validator for any prose shown to a human or returned to an agent.

Domain-agnostic, shared by the explanation templates and the model layer. A text passes only if
every ``{{fact_id}}`` token names a known fact with a value, and **no digit remains** once the
tokens and the caller's allowed names (gene or sample names such as ``ODC1`` or ``SDHA(1)``) are
removed. This is deliberately stricter than a "number-like token" regex: ``x2``, ``95%``,
``2-fold``, ``MIQE 2.0``, dates and superscripts (``³``) are all rejected unless they come from
a fact (any character for which ``str.isnumeric()`` is true counts as a digit).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from pydantic import BaseModel

from qpilot.core.facts import render_fact
from qpilot.schemas import Fact, StudyResult

TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
ANY_TOKEN = re.compile(r"\{\{([^{}]*)\}\}")


class ValidationResult(BaseModel):
    """Outcome of :func:`validate`; ``ok`` only when all three lists are empty."""

    ok: bool
    unknown_ids: list[str] = []
    empty_ids: list[str] = []
    naked_numbers: list[str] = []

    def error(self) -> str:
        """One line describing what failed, for a retry prompt or a log."""
        parts = []
        if self.unknown_ids:
            parts.append(f"unknown fact ids: {', '.join(self.unknown_ids)}")
        if self.empty_ids:
            parts.append(f"facts without a value: {', '.join(self.empty_ids)}")
        if self.naked_numbers:
            parts.append(
                "numbers not written as {{fact_id}} tokens: " + ", ".join(self.naked_numbers)
            )
        return "; ".join(parts) or "ok"


def _strip_names(text: str, names: Iterable[str]) -> str:
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        pattern = rf"(?<![\w(]){re.escape(name)}(?![\w)])"
        text = re.sub(pattern, " ", text)
    return text


def validate(
    text: str, facts: Mapping[str, Fact], allowed_names: Iterable[str] = ()
) -> ValidationResult:
    """Check ``text`` for unknown or empty fact tokens and for any digit outside a token."""
    unknown: list[str] = []
    empty: list[str] = []
    for raw_id in ANY_TOKEN.findall(text):
        fid = raw_id.strip()
        if not TOKEN.fullmatch("{{" + raw_id + "}}") or fid not in facts:
            unknown.append(raw_id)
        elif facts[fid].value is None or facts[fid].value == "":
            empty.append(fid)
    remainder = _strip_names(ANY_TOKEN.sub(" ", text), allowed_names)
    naked = [word for word in remainder.split() if any(ch.isnumeric() for ch in word)]
    return ValidationResult(
        ok=not (unknown or empty or naked),
        unknown_ids=sorted(set(unknown)),
        empty_ids=sorted(set(empty)),
        naked_numbers=naked,
    )


def render_tokens(text: str, facts: Mapping[str, Fact]) -> str:
    """Replace each ``{{fact_id}}`` with its formatted value (plain text, no markup).

    Call :func:`validate` first; unknown ids are left as they are.
    """

    def sub(match: re.Match[str]) -> str:
        fact = facts.get(match.group(1))
        return render_fact(fact) if fact is not None else match.group(0)

    return TOKEN.sub(sub, text)


def names_from_result(result: StudyResult) -> set[str]:
    """Names that may appear verbatim in prose about a study: items, references, group label."""
    names = set(result.contrasts) | set(result.robustness) | set(result.genorm.M_initial)
    names |= set(result.design.refs_primary) | {result.design.group_var}
    return names
