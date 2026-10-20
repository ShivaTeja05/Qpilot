"""Facts and fact-bound text: no number is ever typed into a sentence of the report.

:class:`ReportFacts` is the engine's facts (``facts.json``) plus **derived report facts**: a value
the store holds in a field that has no fact id (a gene's group sizes, a version, a count of
entries, a number from the audit). A derived fact has the id prefix ``f_rpt_`` and a ``path``
that says where it was read, as ``<source>:<JSON pointer>`` (RFC 6901), optionally followed by
``@min``, ``@max``, ``@len`` or ``@count=<value>`` for an aggregate of what the pointer names. It
is a copy, never a new statistic.

:meth:`ReportFacts.text` builds a :class:`~qpilot.report.model.ReportText` from parts: a ``str``
is prose with ``{{f_id}}`` tokens and is checked by :func:`qpilot.core.validator.validate` (an
unknown token, or a digit outside the tokens and the allowed names, raises :class:`ProseError`);
:class:`Q` is a string quoted from the study (data, never checked, never markup); :class:`Cite`
is a citation marker.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from qpilot.core.facts import FACT_ID, render_fact, slug
from qpilot.core.validator import TOKEN, validate
from qpilot.report.model import ReportFact, ReportSegment, ReportText
from qpilot.schemas import Fact

DERIVED_PREFIX = "f_rpt_"
NNBSP = " "  # the page writes "65 %" with a narrow no-break space


class ProseError(ValueError):
    """Report text that would show a number not bound to a fact (a bug in the report)."""


@dataclass(frozen=True)
class Q:
    """A string quoted from the study (a name, an option, a reason): data, shown as text."""

    text: str


@dataclass(frozen=True)
class Cite:
    """A citation marker ``[n]`` (the Methods' reference list)."""

    n: int


Part = str | Q | Cite


def pointer(*keys: object) -> str:
    """An RFC 6901 JSON pointer to ``keys`` (``/`` and ``~`` escaped)."""
    return "".join("/" + str(k).replace("~", "~0").replace("/", "~1") for k in keys)


def safe_slug(name: str) -> str:
    """:func:`qpilot.core.facts.slug`, but never raising (``x`` for a name with no letters)."""
    try:
        return slug(name)
    except ValueError:
        return "x"


def shown(fact: Fact) -> str:
    """A fact as the page writes it: the engine's rendering, a percent sign set apart."""
    text = render_fact(fact)
    if fact.fmt.endswith("%}") and text.endswith("%") and not text.endswith(" %"):
        text = text[:-1].rstrip() + NNBSP + "%"
    if fact.unit.strip() == "%" and text.endswith("%"):
        text = text[:-1].rstrip() + NNBSP + "%"
    return text


class ReportFacts:
    """The engine's facts plus the report's derived ones; remembers which were cited."""

    def __init__(self, engine: Mapping[str, Fact]) -> None:
        self._facts: dict[str, Fact] = {f: v for f, v in engine.items() if FACT_ID.match(f)}
        self._derived: set[str] = set()
        self.cited: list[str] = []
        self.names: set[str] = set()

    def __contains__(self, fid: object) -> bool:
        return fid in self._facts

    def get(self, fid: str) -> Fact | None:
        """A fact, or None."""
        return self._facts.get(fid)

    def value(self, fid: str, default: Any = None) -> Any:
        """A fact's raw value, or ``default`` when it is absent."""
        fact = self._facts.get(fid)
        return fact.value if fact is not None else default

    def has(self, *fids: str) -> bool:
        """True when every one of these facts exists (and is not empty)."""
        return all(self._facts.get(f) is not None and self._facts[f].value != "" for f in fids)

    def derive(
        self,
        name: str,
        value: float | int | str,
        path: str,
        fmt: str = "{}",
        unit: str = "",
    ) -> str:
        """Register (or re-use) the derived fact ``f_rpt_<name>``; return its id.

        Raises:
            ValueError: A bad id, or the same id derived before with another value.
        """
        fid = DERIVED_PREFIX + name
        if not FACT_ID.match(fid):
            raise ValueError(f"bad derived fact id {fid!r}")
        fact = Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path)
        old = self._facts.get(fid)
        if old is not None and old != fact:
            raise ValueError(f"derived fact {fid} registered twice with different values")
        self._facts[fid] = fact
        self._derived.add(fid)
        return fid

    def count(self, name: str, value: int, path: str) -> str:
        """Register a derived count; return its token."""
        return tok(self.derive(name, int(value), path))

    def tok(self, fid: str) -> str:
        """The token of an existing fact (raises ``KeyError`` when there is none)."""
        if fid not in self._facts:
            raise KeyError(fid)
        return tok(fid)

    def text(self, *parts: Part, names: Iterable[str] = ()) -> ReportText:
        """Fact-bound text from prose, quoted data and citation markers (see the module doc).

        Raises:
            ProseError: An unknown or empty fact token, or a digit outside tokens and names.
        """
        allowed = self.names | set(names)
        segments: list[ReportSegment] = []
        cited: list[str] = []
        for part in parts:
            if isinstance(part, Q):
                if part.text:
                    segments.append(ReportSegment(text=part.text, quote=True))
                continue
            if isinstance(part, Cite):
                segments.append(ReportSegment(text=f"[{part.n}]", cite=part.n))
                continue
            check = validate(part, self._facts, allowed)
            if not check.ok:
                raise ProseError(f"report text fails the no-naked-numbers check: {check.error()}")
            last = 0
            for match in TOKEN.finditer(part):
                if match.start() > last:
                    segments.append(ReportSegment(text=part[last : match.start()]))
                fid = match.group(1)
                segments.append(ReportSegment(text=shown(self._facts[fid]), fact=fid))
                if fid not in cited:
                    cited.append(fid)
                last = match.end()
            if last < len(part):
                segments.append(ReportSegment(text=part[last:]))
        for fid in cited:
            if fid not in self.cited:
                self.cited.append(fid)
        plain = "".join(s.text for s in segments if s.cite is None)
        return ReportText(plain=_tidy(plain), segments=segments, facts=cited)

    def cited_facts(self) -> dict[str, ReportFact]:
        """Every cited fact as the API shows it, sorted by id."""
        out = {}
        for fid in sorted(self.cited):
            fact = self._facts[fid]
            out[fid] = ReportFact(
                id=fid,
                text=shown(fact),
                value=fact.value,
                unit=fact.unit,
                path=fact.path,
                derived=fid in self._derived,
            )
        return out


def tok(fid: str) -> str:
    """The token for one fact id: ``{{f_id}}``."""
    return "{{" + fid + "}}"


_SPACE_BEFORE = re.compile(r"\s+([,.;:)])")


def _tidy(text: str) -> str:
    """One space between words, none before punctuation (where a citation marker was left out)."""
    return _SPACE_BEFORE.sub(r"\1", " ".join(text.split()))


def with_cites(text: ReportText) -> str:
    """A text as plain text with its citation markers (``… LinRegPCR [2, 3].``)."""
    out: list[str] = []
    for seg, group in cite_groups(text):
        out.append(seg.text if group is None else " [" + ", ".join(map(str, group)) + "]")
    return _tidy("".join(out))


def cite_groups(text: ReportText) -> list[tuple[ReportSegment, list[int] | None]]:
    """Segments with adjacent citation markers merged: ``(segment, None)`` or ``(first, [n…])``."""
    out: list[tuple[ReportSegment, list[int] | None]] = []
    for seg in text.segments:
        if seg.cite is not None and out and out[-1][1] is not None:
            out[-1][1].append(seg.cite)
        elif seg.cite is not None:
            out.append((seg, [seg.cite]))
        else:
            out.append((seg, None))
    return out
