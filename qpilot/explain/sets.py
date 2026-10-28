"""The two sets of analyses behind every robustness count, in one place.

The page, the report, the CLI and the MCP tools all cite two different counts of analyses, and
they must never be confused (docs/user-guide.md §3, "Two sets of analyses, never confused"):

* **qPilot's choice grid** — the analyses qPilot itself checks: every combination of the
  options on the Decision Cards (control-gene sets, group cut-off, empty-well rule,
  amplification-call rule, and the efficiency models only when a person asks). It sets each
  gene's confidence level. 744 on the demo.
* **The audit's reasonable set** — the robustness audit is a wider, independent re-analysis
  (every combination of its own analysis decisions: 90,396 on the demo); its verdicts count only
  its reasonable analyses (144 on the demo), which leave out shortcuts such as single or paired
  control genes and keep the group cut-off and the correction for many genes as planned.

The frontend mirrors these words in ``frontend/src/lib/vocab.ts`` (the "two sets" block);
``tests/web/test_sets_words.py`` keeps the two copies the same.
"""

from __future__ import annotations

from collections.abc import Iterable

#: The analyses qPilot itself checks, in a count ("744 analyses qPilot checks").
GRID_COUNT = "analyses qPilot checks"
#: Its name, when both sets are on the page.
GRID_NAME = "qPilot's choice grid"
#: What it holds.
GRID_WHAT = "every combination of the options on the Decision Cards"
#: The audit's set its verdicts count ("the audit's 144 reasonable analyses").
AUDIT_NAME = "the audit's reasonable set"

#: The audit's decisions qPilot's grid varies too (its own ``impact`` dimensions), by audit id.
#: ``late_cq`` is the grid's amplification-call rule (its Cq cut-offs); ``nondetect`` its rule
#: for wells without a quantity. ``efficiency`` is in the grid only when a person asked for it.
SHARED = {"refs", "cut", "late_cq", "nondetect"}
#: The audit's decisions in plain words (``qsim.decisions.PLAIN``), in the audit's order.
AUDIT_PLAIN = {
    "efficiency": "the efficiency model",
    "flagged": "how flagged wells are handled",
    "late_cq": "the late-Cq cut-off",
    "nondetect": "how non-detects are handled",
    "replicates": "how replicate wells are combined",
    "refs": "the reference genes",
    "cut": "the group cut-off",
    "test": "the statistical test",
    "multiplicity": "the multiple-testing correction",
}
#: The audit's decisions when nothing more is known (the demo's eight; a design with technical
#: replicates adds ``replicates``).
DEFAULT_AUDIT = (
    "efficiency",
    "flagged",
    "late_cq",
    "nondetect",
    "refs",
    "cut",
    "test",
    "multiplicity",
)

#: What the audit does, without a count that goes stale (eight or nine decisions).
AUDIT_DOES = (
    "A wider, independent re-analysis than qPilot's grid: every combination of the audit's "
    "analysis decisions, one verdict per gene."
)


def _names(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _sentence(text: str) -> str:
    """A capital first letter (never on "qPilot"), as a sentence starts."""
    return text if text.startswith("qPilot") else text[:1].upper() + text[1:]


def audit_only(
    decisions: Iterable[str] = DEFAULT_AUDIT, *, efficiency_in_grid: bool = False
) -> list[str]:
    """The audit's decisions that qPilot's grid does not vary, in words.

    The multiple-testing correction is left out: the audit's verdicts hold it as planned.
    """
    shared = SHARED | ({"efficiency"} if efficiency_in_grid else set())
    return [
        AUDIT_PLAIN.get(d, d.replace("_", " "))
        for d in decisions
        if d not in shared and d != "multiplicity"
    ]


def bridge(decisions: Iterable[str] = DEFAULT_AUDIT, *, efficiency_in_grid: bool = False) -> str:
    """How the two sets differ, in plain words (the page's "Why two counts?")."""
    only = audit_only(decisions, efficiency_in_grid=efficiency_in_grid)
    first = ""
    if only:
        first = f"The audit also varies {_names(only)}, which qPilot's grid does not"
        if "the efficiency model" in only:
            first += " (it tests the efficiency models only when you ask, under Results)"
        first += "; "
    rest = (
        "its verdicts leave out single and paired control genes and keep the group cut-off as "
        "planned, which qPilot's grid varies. So the same gene can hold in a different share of "
        "each."
    )
    return _sentence(first + rest)


def counts_line(grid: int | None, *, reasonable: int | None = None, full: int | None = None) -> str:
    """Both counts and what each one is for, in two short sentences."""
    parts = []
    if grid:
        parts.append(
            f"qPilot's choice grid is the {grid:,} {GRID_COUNT} ({GRID_WHAT}); it sets each "
            "gene's confidence level."
        )
    if reasonable:
        wider = f"a wider re-analysis of {full:,} analyses" if full else "a wider re-analysis"
        parts.append(
            f"The robustness audit is {wider}; its verdicts count its {reasonable:,} "
            "reasonable ones."
        )
    return " ".join(parts)


def verdict_differs(reasonable: int | str | None) -> str:
    """Why a gene that leans on qPilot's grid can still hold in the audit (after its verdict).

    ``reasonable`` is the count, or a report's fact token for it (``{{f_rpt_…}}``).
    """
    n = f"{reasonable:,}" if isinstance(reasonable, int) else reasonable
    count = f"{n} reasonable analyses" if n else "reasonable analyses"
    return (
        f"The audit counts only its {count}, which keep the group cut-off as planned and leave "
        "out single and paired control genes, so a call can hold there and not in qPilot's grid."
    )
