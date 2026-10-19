"""Facts and fact-bound text for the report: no number is ever typed into a sentence.

:class:`ReportFacts` is the record's own facts (``facts.json``) plus **derived report facts**: a
value the record holds in a field that has no fact id yet (a gene's group sizes in
``results.json``, a version in ``versions.json``, a hash in ``CHECKSUMS.sha256``). A derived fact
has the id prefix ``f_rpt_`` and a ``path`` naming the record member and field it was read from,
e.g. ``results.json:contrasts.ODC1.n_hi``; it is a copy, never a new calculation, except where the
id says what it counts (``f_rpt_n_eff_outside``), and then the path names the inputs.

:func:`fact_text` turns token text (``{{f_id}}`` tokens) into a :class:`Text`: the token form,
plain text and HTML (each number in ``<span class="fact" data-fact="…">``, everything else
escaped). It runs :func:`qpilot.core.validator.validate` first and raises :class:`ProseError` if
a token is unknown or a digit is left outside a token and the allowed names: a report that would
show a naked number is a bug, never output.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from pydantic import BaseModel

from qpilot.core.facts import FACT_ID, render_fact, slug
from qpilot.core.validator import TOKEN, validate
from qpilot.schemas import Fact

DERIVED_PREFIX = "f_rpt_"


class ProseError(ValueError):
    """Report text that would show a number not bound to a fact (a bug in the report)."""


class Text(BaseModel):
    """One piece of fact-bound text in three renderings, with the facts it cites."""

    tokens: str
    plain: str
    html: str
    fact_ids: list[str] = []


def tok(fid: str) -> str:
    """The token for one fact id: ``{{f_id}}``."""
    return "{{" + fid + "}}"


def safe_slug(name: str) -> str:
    """:func:`qpilot.core.facts.slug`, but never raising (``x`` for a name with no letters)."""
    try:
        return slug(name)
    except ValueError:
        return "x"


class ReportFacts(Mapping[str, Fact]):
    """The record's facts plus derived ``f_rpt_*`` facts; remembers which ones were cited."""

    def __init__(self, record_facts: Mapping[str, Fact]) -> None:
        self._facts: dict[str, Fact] = {
            fid: f for fid, f in record_facts.items() if FACT_ID.match(fid)
        }
        self.cited: set[str] = set()

    def __getitem__(self, fid: str) -> Fact:
        return self._facts[fid]

    def __iter__(self) -> Iterator[str]:
        return iter(self._facts)

    def __len__(self) -> int:
        return len(self._facts)

    def value(self, fid: str, default: object = None) -> object:
        """A fact's raw value, or ``default`` when the fact is absent."""
        fact = self._facts.get(fid)
        return fact.value if fact is not None else default

    def derive(
        self, name: str, value: float | int | str, fmt: str = "{}", unit: str = "", path: str = ""
    ) -> str:
        """Register (or re-use) the derived fact ``f_rpt_<name>``; return its id.

        Raises:
            ValueError: The same id was derived before with another value.
        """
        fid = DERIVED_PREFIX + name
        if not FACT_ID.match(fid):
            raise ValueError(f"bad derived fact id {fid!r}")
        fact = Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path)
        old = self._facts.get(fid)
        if old is not None and old != fact:
            raise ValueError(f"derived fact {fid} registered twice with different values")
        self._facts[fid] = fact
        return fid

    def render(self, fid: str) -> str:
        """A fact's formatted value (marks it cited)."""
        self.cited.add(fid)
        return render_fact(self._facts[fid])

    def span(self, fid: str) -> str:
        """A fact as an HTML span naming its id (marks it cited)."""
        value = html.escape(self.render(fid))
        safe_id = html.escape(fid, quote=True)
        return f'<span class="fact" data-fact="{safe_id}" title="{safe_id}">{value}</span>'

    def cited_facts(self) -> dict[str, Fact]:
        """Every cited fact, sorted by id (the report's ``facts`` section)."""
        return {fid: self._facts[fid] for fid in sorted(self.cited) if fid in self._facts}


@dataclass
class Names:
    """Text that may appear verbatim in prose: gene, group and option names, method phrases."""

    items: set[str]

    def __iter__(self) -> Iterator[str]:
        return iter(self.items)

    def add(self, *names: str) -> None:
        """Allow more names."""
        self.items.update(n for n in names if n)


def fact_text(tokens: str, facts: ReportFacts, names: Iterable[str] = ()) -> Text:
    """Validate token text and render it as plain text and HTML.

    Raises:
        ProseError: An unknown or empty fact token, or a digit outside the tokens and names.
    """
    check = validate(tokens, facts, list(names))
    if not check.ok:
        raise ProseError(f"report text fails the no-naked-numbers check: {check.error()}")
    plain_parts: list[str] = []
    html_parts: list[str] = []
    cited: list[str] = []
    last = 0
    for match in TOKEN.finditer(tokens):
        literal = tokens[last : match.start()]
        plain_parts.append(literal)
        html_parts.append(html.escape(literal))
        fid = match.group(1)
        plain_parts.append(facts.render(fid))
        html_parts.append(facts.span(fid))
        if fid not in cited:
            cited.append(fid)
        last = match.end()
    plain_parts.append(tokens[last:])
    html_parts.append(html.escape(tokens[last:]))
    return Text(tokens=tokens, plain="".join(plain_parts), html="".join(html_parts), fact_ids=cited)
