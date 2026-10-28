"""Counted nouns in plain words, one copy for the whole product (never "well(s)").

The page has its own in ``frontend/src/lib/format.ts`` (``plural``); every sentence the server,
the CLI, the report or the MCP tools write counts nouns with these two.
"""

from __future__ import annotations


def noun(n: int, one: str, many: str | None = None) -> str:
    """The noun for a count: ``well`` for 1, ``wells`` otherwise (``many`` when irregular)."""
    return one if n == 1 else (many or f"{one}s")


def plural(n: int, one: str, many: str | None = None) -> str:
    """A count with its noun: ``1 well``, ``3 wells``, ``2 analyses`` (with ``many``)."""
    return f"{n} {noun(n, one, many)}"
