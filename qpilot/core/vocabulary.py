"""The words qPilot never uses in prose, and the one check that finds them.

Domain-agnostic. qPilot says what the data shows and what to check next; it never claims a
diagnosis, a cause, or a status it cannot show (``add_plan.md`` §2 rule 9). Say "consistent
with", "the file says", "seen before", "follows the instrument", "changes k of N conclusions",
"what to check", or "cannot tell from biology without replicates" instead.

:func:`banned_words` finds the terms of :data:`BANNED` in any text that reaches a person or a
model: rendered templates, card labels and notes, report pages, tool answers. Matching ignores
case and respects word boundaries, so ``validate`` (the command) and ``validation`` pass while
``validated`` does not, and ``genorm_validated`` (an identifier) is not a word of its own. The
words of a multi-word term may be split by spaces, line breaks or hyphens.

:data:`ALLOWED_PHRASES` are fixed disclaimers that must keep their wording (the research-use
line says "not for clinical or diagnostic use"); they are removed before the scan, and so are
the caller's allowed names (a gene called ``IVD`` is a gene, not a claim).

Deterministic; no model call.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: Terms that never appear in qPilot prose (case-insensitive, word-bounded), with the plural
#: and verb forms a sentence would use.
BANNED: tuple[str, ...] = (
    "diagnosis",
    "diagnoses",
    "diagnose",
    "diagnosed",
    "diagnosing",
    "diagnostic",
    "diagnostics",
    "root cause",
    "root causes",
    "detects inhibition",
    "detected inhibition",
    "error found",
    "errors found",
    "validated",
    "valid run",
    "valid runs",
    "invalid run",
    "invalid runs",
    "faulty instrument",
    "faulty instruments",
    "compliant",
    "IVD",
    "IVDs",
)
#: Fixed disclaimers that keep a banned word because they deny the claim.
ALLOWED_PHRASES: tuple[str, ...] = (
    "not for clinical or diagnostic use",  # qpilot/__init__.py, the app footer, the MCP server
    "not for diagnostic use",
    "not part 11 compliant",  # the audit-posture statement planned in add_plan.md 4.5
)

_SEPARATOR = r"[\s\-]+"  # between the words of a term: spaces, line breaks, hyphens


def _phrase(text: str) -> str:
    """A word-bounded pattern for ``text`` whose words may be split by any separator."""
    words = text.split()
    return r"(?<!\w)" + _SEPARATOR.join(re.escape(w) for w in words) + r"(?!\w)"


_CANONICAL = {" ".join(term.lower().split()): term for term in BANNED}
# Longest first, so "invalid runs" is found whole rather than as "invalid run" plus "s".
_BANNED = re.compile(
    "|".join(_phrase(t) for t in sorted(BANNED, key=lambda t: (-len(t), t))), re.IGNORECASE
)
_ALLOWED = re.compile(
    "|".join(_phrase(p) for p in sorted(ALLOWED_PHRASES, key=lambda p: (-len(p), p))),
    re.IGNORECASE,
)


def banned_words(text: str, allowed_names: Iterable[str] = ()) -> list[str]:
    """The banned terms in ``text``, each once, in the order they first appear.

    Args:
        text: Prose to check (plain text; ``{{fact_id}}`` tokens are identifiers and never
            match).
        allowed_names: Names the text may contain as they are (genes, samples, plates), removed
            before the scan, longest first, like the number validator's allowed names.

    Returns:
        The matching entries of :data:`BANNED` as written there (``"IVD"``, ``"root cause"``);
        an empty list when the text is clean.
    """
    remainder = _ALLOWED.sub(" ", text)
    for name in sorted({n for n in allowed_names if n}, key=len, reverse=True):
        remainder = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", remainder, flags=re.I)
    found: list[str] = []
    for match in _BANNED.finditer(remainder):
        term = _CANONICAL[" ".join(re.split(_SEPARATOR, match.group(0).lower()))]
        if term not in found:
            found.append(term)
    return found


__all__ = ["ALLOWED_PHRASES", "BANNED", "banned_words"]
