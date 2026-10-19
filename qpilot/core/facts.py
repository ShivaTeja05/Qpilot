"""The fact registry: every number that prose may show, with an id, a format and a source path.

Domain-agnostic. Prose (templates or model output) never contains a number directly; it carries
``{{fact_id}}`` tokens that are rendered from this registry, so every number on screen can be
traced to the engine output that produced it.

Fact-id convention: lowercase, digits and underscores, starting ``f_``, e.g.
``f_fc_odc1_recommended`` or ``f_holds_nm23a``. Use :func:`slug` for the name parts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from qpilot.schemas import Fact

FACT_ID = re.compile(r"^f_[a-z0-9_]+\Z")


def slug(name: str) -> str:
    """Make an id part from a display name: ``ALUsq(Eurogentec)`` -> ``alusq_eurogentec``."""
    out = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not out:
        raise ValueError(f"cannot make a slug from {name!r}")
    return out


class FactRegistry:
    """An ordered, id-keyed collection of :class:`~qpilot.schemas.Fact`."""

    def __init__(self, facts: Iterable[Fact] | Mapping[str, Fact] = ()) -> None:
        self._facts: dict[str, Fact] = {}
        values = facts.values() if isinstance(facts, Mapping) else facts
        for fact in values:
            self.add(fact)

    def add(self, fact: Fact) -> Fact:
        """Register a fact; ids must follow the convention and be unique."""
        if not FACT_ID.match(fact.id):
            raise ValueError(f"bad fact id {fact.id!r}: use lowercase f_<metric>_<slug>_<context>")
        if fact.id in self._facts and self._facts[fact.id] != fact:
            raise ValueError(f"fact id registered twice with different values: {fact.id}")
        self._facts[fact.id] = fact
        return fact

    def get(self, fact_id: str) -> Fact:
        """Return the fact with this id; ``KeyError`` if unknown."""
        return self._facts[fact_id]

    def __contains__(self, fact_id: object) -> bool:
        return fact_id in self._facts

    def __len__(self) -> int:
        return len(self._facts)

    def ids(self) -> list[str]:
        """All fact ids, sorted."""
        return sorted(self._facts)

    def as_dict(self) -> dict[str, Fact]:
        """A shallow copy of the id -> fact mapping."""
        return dict(self._facts)

    def render(self, fact_id: str) -> str:
        """Format a fact's value with its ``fmt`` and append its unit."""
        return render_fact(self.get(fact_id))

    def to_json(self) -> str:
        """Deterministic JSON (sorted keys) in the same shape as ``facts.json``."""
        data = {fid: self._facts[fid].model_dump() for fid in self.ids()}
        return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> FactRegistry:
        """Load a registry from ``facts.json`` text."""
        raw = json.loads(text)
        return cls(Fact.model_validate(value) for value in raw.values())

    @classmethod
    def from_file(cls, path: str | Path) -> FactRegistry:
        """Load a registry from a ``facts.json`` file."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def render_fact(fact: Fact) -> str:
    """Format one fact: ``fmt`` applied to the value, then the unit (``3.6×``, ``1.4%``)."""
    try:
        text = fact.fmt.format(fact.value)
    except (ValueError, TypeError):
        text = str(fact.value)
    return f"{text}{fact.unit}"
