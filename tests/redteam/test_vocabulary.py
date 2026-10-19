"""Repo-wide vocabulary lint: words qPilot must never use about its own output.

The product rule (team brief, rule 10; W3 P-rules): never write "validated" about a run or a
result, "valid run", "compliant", "IVD", "diagnostic", "root cause", "beats scientists", or
"mixed model" as a feature. qPilot is research software; the status words are
``pass / warn / fail / not_applicable`` and ``provisional / in_control / warning / rejection``.

What is scanned: every user-facing text in the repository: ``README.md``, ``SECURITY.md``,
``THREAT_MODEL.md``, ``CONTRIBUTING.md``, ``SKILL.md``, ``docs/``, ``methods/``, ``packs/`` and
every text file under ``qpilot/`` (prose templates, UI copy, method cards, MCP descriptions),
apart from vendored code and data tables. Tests, research notes and the simulator's internal
review notes are not scanned (they quote the words on purpose).

Allowed, and only these:

* a negation in the same clause before the word ("Not for clinical or diagnostic use",
  "no mixed model", "this is not a valid run");
* a line carrying the marker ``vocabulary: allow`` with a reason after it (for code that must
  spell a banned word, such as a refusal list). Keep these rare; each one is reviewed.

This is the one repository lint for the vocabulary rule (the Run Gate's copy is scanned here
too, because ``packs/`` and ``qpilot/`` are in scope).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

TOP_LEVEL = ("README.md", "SECURITY.md", "THREAT_MODEL.md", "CONTRIBUTING.md", "SKILL.md")
TREES = ("docs", "methods", "packs", "qpilot")
TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".html", ".jinja", ".j2", ".txt", ".json", ".css"}
EXCLUDED_DIRS = (
    "qpilot/vendor/",  # vendored third-party code, kept byte for byte
    "qpilot/data/",  # data tables (the HGNC list has a gene called IVD)
    "docs/review/",  # the red team's findings log quotes offending text on purpose
    "docs/classroom/",  # teaching material from the hackathon, kept as it was written
)
MAX_BYTES = 2_000_000
ALLOW_MARKER = "vocabulary: allow"
#: (file, text on the line) -> why it is allowed. Only for files the lint cannot mark itself.
ALLOWED_LINES: dict[tuple[str, str], str] = {
    ("THREAT_MODEL.md", "21 CFR Part 11; clinical or diagnostic use"): (
        "the line sits under the 'Out of scope' heading: a disclaimer, not a claim"
    ),
}
#: (file, rule) -> finding id, for violations reported to the owner and not yet fixed. The main
#: lint skips these; ``test_known_open_findings_are_fixed`` fails strictly once they are gone,
#: so the entry must then be deleted.
KNOWN_OPEN: dict[tuple[str, str], str] = {
    ("README.md", "mixed model (as a feature)"): "RT-002",
}

_RESULT = r"(?:run|plate|result|analysis|assay|experiment|conclusion|study|data ?set)s?"
RULES: dict[str, re.Pattern[str]] = {
    "validated (about a run or result)": re.compile(
        rf"\bvalidated {_RESULT}\b"
        rf"|\b{_RESULT} (?:is|are|was|were|has been|have been|gets?|got) validated\b(?! against)"
        rf"|\bvalidates? (?:the|your|a|an|this|each|every) {_RESULT}\b",
        re.IGNORECASE,
    ),
    "valid run": re.compile(r"\bvalid (?:run|plate)s?\b", re.IGNORECASE),
    "compliant": re.compile(r"\bcompliant\b", re.IGNORECASE),
    "IVD": re.compile(r"\bIVDR?\b"),
    "diagnostic": re.compile(r"\bdiagnostics?\b", re.IGNORECASE),
    "root cause": re.compile(r"\broot[- ]causes?\b", re.IGNORECASE),
    "beats scientists": re.compile(r"\bbeats? (?:the )?scientists?\b", re.IGNORECASE),
    "mixed model (as a feature)": re.compile(r"\bmixed[- ]models?\b", re.IGNORECASE),
}
NO_NEGATION = {"beats scientists"}
NEGATION = re.compile(
    r"\b(?:not|no|never|nor|without|cannot|neither|isn't|aren't|doesn't|don't|won't)\b"
    r"|n't\b|\bout of scope\b",
    re.IGNORECASE,
)
CLAUSE_BREAK = re.compile(r"[.!?;|]\s")
NEGATION_WINDOW = 80


def scanned_files(repo: Path = REPO) -> list[Path]:
    """Every file the lint reads, in a stable order."""
    files = [repo / name for name in TOP_LEVEL if (repo / name).is_file()]
    for tree in TREES:
        root = repo / tree
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(repo).parts
            if (
                path.is_file()
                and path.suffix.lower() in TEXT_SUFFIXES
                and "__pycache__" not in rel
                and not "/".join(rel).startswith(EXCLUDED_DIRS)
                and path.stat().st_size <= MAX_BYTES
            ):
                files.append(path)
    return files


def _negated(line: str, start: int) -> bool:
    """True when a negation word stands earlier in the same clause, close to the match."""
    before = line[max(0, start - NEGATION_WINDOW) : start]
    breaks = list(CLAUSE_BREAK.finditer(before))
    clause = before[breaks[-1].end() :] if breaks else before
    return bool(NEGATION.search(clause))


def violations(text: str) -> list[tuple[int, str, str]]:
    """(line number, rule, the line) for every banned use in ``text``."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for rule, pattern in RULES.items():
            for match in pattern.finditer(line):
                if rule not in NO_NEGATION and _negated(line, match.start()):
                    continue
                found.append((number, rule, line.strip()))
    return found


@pytest.mark.parametrize(
    "text",
    [
        "This is a validated run.",
        "Your results are validated by qPilot.",
        "qPilot validates your plate in seconds.",
        "A valid run needs three NTCs.",
        "The report is MIQE-compliant.",
        "Use it as an IVD.",
        "A diagnostic answer for every sample.",
        "Find the root cause of a failed plate.",
        "qPilot beats scientists at curve calling.",
        "Fit a mixed model to every study.",
    ],
)
def test_each_banned_use_is_caught(text: str) -> None:
    assert violations(text), text


@pytest.mark.parametrize(
    "text",
    [
        "For research use only. Not for clinical or diagnostic use.",
        "There is no plate-effect or mixed model.",
        "A pass here does not make this a valid run.",
        "qPilot is not an IVD and never a diagnostic.",
        "The curve analysis was validated against published results on one platform.",
        "refusal words: ['valid run']  # vocabulary: allow (the refusal list itself)",
        "Names are validated at load and escaped.",
    ],
)
def test_negations_and_marked_lines_are_allowed(text: str) -> None:
    assert not violations(text), violations(text)


def test_the_lint_reads_the_user_facing_text() -> None:
    names = {p.relative_to(REPO).as_posix() for p in scanned_files()}
    assert "README.md" in names
    assert "THREAT_MODEL.md" in names
    assert any(n.startswith("methods/") for n in names)
    assert any(n.startswith("docs/") for n in names)
    assert "qpilot/studio_state.py" in names
    assert not any("/vendor/" in n for n in names)


def repo_violations() -> list[tuple[str, int, str, str]]:
    """(file, line number, rule, line) for every banned use in the scanned files."""
    found = []
    for path in scanned_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        name = path.relative_to(REPO).as_posix()
        for number, rule, line in violations(text):
            if any(name == f and snippet in line for f, snippet in ALLOWED_LINES):
                continue
            found.append((name, number, rule, line))
    return found


def test_no_banned_vocabulary_in_user_facing_text() -> None:
    problems = [
        f"{name}:{number}: [{rule}] {line[:160]}"
        for name, number, rule, line in repo_violations()
        if (name, rule) not in KNOWN_OPEN
    ]
    assert not problems, "banned vocabulary (team brief rule 10):\n" + "\n".join(problems)


@pytest.mark.parametrize(
    "known",
    [
        pytest.param(key, id=finding, marks=pytest.mark.xfail(strict=True, reason=finding))
        for key, finding in KNOWN_OPEN.items()
    ],
)
def test_known_open_findings_are_fixed(known: tuple[str, str]) -> None:
    left = [v for v in repo_violations() if (v[0], v[2]) == known]
    assert not left, left
