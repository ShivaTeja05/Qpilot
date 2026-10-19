"""Decision Card kinds: an open registry with validated names (gap G3).

Domain-agnostic. A card's ``kind`` says what the choice is about (which control genes, where to
cut the groups, what a gate rule's failure means ...). It used to be a closed list of four; now
a plugin registers the kinds it builds::

    register_card_kind("gate.rule", "What a failing control means for the conclusions",
                       owner="gate")

Two checks, at two moments:

* **Spelling, always** (``qpilot.schemas.CARD_KIND_PATTERN``): lower-case ``snake_case``, at most
  one ``namespace.`` prefix, 64 characters. A card loaded from disk is checked only for this, so
  a record written by a build that knew more kinds still loads, and a kind is always safe to put
  in HTML, a log line or a fact id.
* **Registration, when a card is built** (``core/decisions.CardSpec`` and :func:`card_kind`):
  code that makes a card must name a registered kind.

The escalation rule never depends on the kind: a card that can flip a conclusion is human-only
whatever it is called. A kind can only make it stricter: ``always_human=True`` makes every card
of that kind human-only even when nothing flips, and a kind this build does not know (an older
or newer record) is treated the same way. Fail closed.

The four kinds the qPCR plugin had from the start are registered here so that existing records,
the toy spaces in the core tests and the demo keep working unchanged; their titles are the ones
the explanation layer always showed.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator, Mapping

from pydantic import BaseModel, ConfigDict

from qpilot.schemas import CARD_KIND_PATTERN, MAX_CARD_KIND

MAX_TITLE = 120
_NAME = re.compile(CARD_KIND_PATTERN)
_LOCK = threading.Lock()


class CardKindError(ValueError):
    """A card kind that is misspelt, unregistered, or registered twice with different meanings."""


class CardKind(BaseModel):
    """What the core knows about one kind of Decision Card."""

    model_config = ConfigDict(frozen=True)

    name: str
    title: str
    owner: str
    #: The decision-space dimension every card of this kind is about, when it is fixed
    #: (``reference_set`` -> ``refs``); ``None`` when cards of the kind are not tied to one.
    dimension: str | None = None
    #: Every card of this kind is a human decision, even when no option changes a conclusion.
    always_human: bool = False
    description: str = ""


_REGISTRY: dict[str, CardKind] = {}


def check_kind_name(name: object) -> str:
    """Return ``name`` if it is a well-spelt kind, else raise :class:`CardKindError`."""
    if not isinstance(name, str) or len(name) > MAX_CARD_KIND or not _NAME.fullmatch(name):
        raise CardKindError(
            f"card kind {str(name)[:80]!r} is not lower-case snake_case with at most one "
            f"'namespace.' prefix and {MAX_CARD_KIND} characters"
        )
    return name


def register_card_kind(
    name: str,
    title: str,
    owner: str,
    *,
    dimension: str | None = None,
    always_human: bool = False,
    description: str = "",
) -> CardKind:
    """Register a kind (idempotent for the same definition) and return it.

    Registering the same name again with a different title, owner, dimension, ``always_human``
    or description raises :class:`CardKindError`: two plugins must not mean two things by one
    kind.
    """
    check_kind_name(name)
    title = " ".join(str(title).split())
    if not title or len(title) > MAX_TITLE:
        raise CardKindError(f"card kind {name!r}: title must be 1..{MAX_TITLE} characters")
    if not owner or not _NAME.fullmatch(owner):
        raise CardKindError(f"card kind {name!r}: owner must be a snake_case plugin name")
    kind = CardKind(
        name=name,
        title=title,
        owner=owner,
        dimension=dimension,
        always_human=bool(always_human),
        description=" ".join(str(description).split()),
    )
    with _LOCK:
        existing = _REGISTRY.get(name)
        if existing is not None and existing != kind:
            raise CardKindError(
                f"card kind {name!r} is already registered by {existing.owner!r} with a "
                "different definition"
            )
        _REGISTRY.setdefault(name, kind)
        return _REGISTRY[name]


def card_kind(name: str) -> CardKind:
    """The registered kind called ``name``; :class:`CardKindError` when it is not registered."""
    check_kind_name(name)
    try:
        return _REGISTRY[name]
    except KeyError:
        raise CardKindError(
            f"card kind {name!r} is not registered; register it with "
            "qpilot.core.card_kinds.register_card_kind before building cards of that kind"
        ) from None


def is_registered(name: str) -> bool:
    """True when ``name`` is a registered kind."""
    return isinstance(name, str) and name in _REGISTRY


def registered_kinds() -> list[CardKind]:
    """Every registered kind, sorted by name."""
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def requires_human(name: str) -> bool:
    """True when every card of kind ``name`` is human-only: ``always_human``, or not known here."""
    kind = _REGISTRY.get(name) if isinstance(name, str) else None
    return kind is None or kind.always_human


def kind_title(name: str) -> str:
    """The kind's title, or the name with spaces when it is not registered."""
    kind = _REGISTRY.get(name) if isinstance(name, str) else None
    return kind.title if kind is not None else str(name).replace("_", " ")


class _Titles(Mapping[str, str]):
    """A read-only, live view ``kind name -> title`` (what ``ai/explain.KIND_TITLE`` exposes)."""

    def __getitem__(self, name: str) -> str:
        return _REGISTRY[name].title

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(_REGISTRY))

    def __len__(self) -> int:
        return len(_REGISTRY)


#: Live mapping of registered kind names to titles; kinds registered later appear here too.
TITLES: Mapping[str, str] = _Titles()


# The qPCR plugin's original four kinds. They stay here (not in qpcr/) so that the core tests'
# toy spaces and every record written before kinds were opened keep building and loading.
register_card_kind("reference_set", "Which control genes to normalise to", "qpcr", dimension="refs")
register_card_kind("group_cutoff", "Where to cut the comparison groups", "qpcr", dimension="cut")
register_card_kind(
    "undetermined",
    "What to do with wells that never amplified",
    "qpcr",
    dimension="undetermined",
)
register_card_kind("amp_call", "Which curves count as amplified", "qpcr", dimension="amp_call")
