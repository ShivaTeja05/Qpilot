"""The "no naked numbers" validator for any prose shown to a human or returned to an agent.

Domain-agnostic, shared by the explanation templates and the model layer. A text passes only if
every ``{{fact_id}}`` token names a known fact with a value, and **no digit remains** once the
tokens and the caller's allowed names (gene or sample names such as ``ODC1`` or ``SDHA(1)``) are
removed. This is deliberately stricter than a "number-like token" regex: ``x2``, ``MIQE 2.0``,
dates and superscripts (``³``) are all rejected unless they come from a fact (any character
for which ``str.isnumeric()`` is true counts as a digit). Spelled-out amounts ("seven-fold",
"ninety percent", "half of") are rejected too. The study's stated method constants (the 95 %
confidence level, the p < 0.05 and 2-fold call rule) are allowed only in their method phrasing
("95 % confidence interval", "p < 0.05", "the 2-fold line", "at least 2-fold") through
:func:`method_constants`, because there they describe the method, not the data; a bare "2x" or
"95%" is a data claim and must be a token.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from pydantic import BaseModel

from qpilot.core.facts import render_fact
from qpilot.schemas import Fact, StudyResult

TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
_NUMBER_WORD = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|"
    r"ninety|hundred|thousand|half|quarter|third|double|triple|quadruple"
)
SPELLED_AMOUNT = re.compile(
    rf"\b(?:(?:{_NUMBER_WORD})[\s-]+)*(?:{_NUMBER_WORD})[\s-]*"
    r"(?:fold|times|percent|per\s+cent|%)\b|\b(?:half|twice|a\s+third|a\s+quarter)\s+(?:of|as)\b",
    re.I,
)
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
        pattern = rf"(?<!\w){re.escape(name)}(?!\w)"
        text = re.sub(pattern, " ", text, flags=re.I)
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
    naked += [m.group(0) for m in SPELLED_AMOUNT.finditer(remainder)]
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


CI_LEVEL = 95  # the confidence level every interval in qPilot uses


def method_constants(result: StudyResult) -> set[str]:
    """The stated method, in the phrasing prose may quote it in: the CI level and the call rule.

    These are not data: "95 % confidence interval", "p < 0.05", "at least 2-fold" describe how
    every number was computed. Only these phrasings pass; a bare "95%", "0.05" or "2x" in a
    sentence is a data claim and must be a fact token.
    """
    alpha = result.conclusion_rule.get("alpha", 0.05)
    fold = 2 ** result.conclusion_rule.get("min_log2fc", 1.0)
    a, f = f"{alpha:g}", f"{fold:g}"
    out = {
        f"{level} {what}"
        for level in (f"{CI_LEVEL}%", f"{CI_LEVEL} %")
        for what in ("confidence interval", "confidence intervals", "confidence", "CI")
    }
    out |= {f"p {op} {a}" for op in ("<", "≤", "<=", "below", "under")} | {f"p<{a}"}
    out |= {f"p-value below {a}", f"p-values below {a}", f"significance level {a}"}
    folds = [f"{f}-fold", f"{f} fold"] + (["two-fold", "twofold"] if f == "2" else [])
    for word in folds:
        out |= {f"at least {word}", f"{word} or more", f"the {word}", f"reach {word}"}
        out |= {f"reaches {word}", f"look {word}"}
        out |= {f"{word} {what}" for what in ("rule", "line", "threshold", "cut-off", "call")}
    return out


def names_from_result(result: StudyResult) -> set[str]:
    """Text prose may use verbatim: items, references, group label and the method constants."""
    names = set(result.contrasts) | set(result.robustness) | set(result.genorm.M_initial)
    names |= set(result.design.refs_primary) | {result.design.group_var}
    return names | method_constants(result)
