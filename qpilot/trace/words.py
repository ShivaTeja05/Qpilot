"""Trace's sentences: every number and name a ``{{fact}}``, written as the page writes numbers.

A sentence is built with :meth:`Facts.tok`, which registers a value and returns its token, and
checked with :meth:`Facts.check` (no naked number: the core validator, with no allowed names).
Numbers read as the page shows them (``docs/app.md`` §5): folds ``3.59×`` / ``0.57×``, a
fold below one also as "1.98-fold lower", p ``< 0.001`` / ``0.003`` (never rounded across the
rule's alpha), cycles with one decimal, counts as integers. Wording follows the plan: "look
here first because", "consistent with"; never a diagnosis.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from qpilot.core.facts import slug
from qpilot.core.validator import validate
from qpilot.schemas import Fact

TIMES = "×"
NNBSP = " "


def fold_fmt(fc: float) -> str:
    """The page's fold format for one value: two decimals from 1 up, two significant below."""
    if not math.isfinite(fc) or fc <= 0:
        return "{}"
    if fc >= 1:
        return "{:.2f}"
    digits = max(2, 1 - math.floor(math.log10(fc)))
    return "{:." + str(min(digits, 6)) + "f}"


def p_text(p: float | None, alpha: float = 0.05) -> str:
    """A p-value as the page writes it (``< 0.001``, ``0.0496``: never across ``alpha``)."""
    if p is None or not math.isfinite(p) or p < 0:
        return "not available"
    if p < 0.001:
        return f"<{NNBSP}0.001"
    if p >= 0.995:
        return "1.00"
    decimals = 3 if p < 0.1 else 2
    text = f"{p:.{decimals}f}"
    while decimals < 6 and (p < alpha) != (float(text) < alpha):
        decimals += 1
        text = f"{p:.{decimals}f}"
    return text


def call_word(call: str) -> str:
    """``up`` / ``down`` / ``no call``."""
    return {"up": "up", "down": "down", "none": "no call"}[call]


class Facts:
    """The facts of one trace; :meth:`tok` registers a value and returns its token."""

    def __init__(self, prefix: str) -> None:
        self.prefix = f"f_trace_{slug(prefix)}"
        self.facts: dict[str, Fact] = {}
        self.texts: dict[str, str] = {}

    def fid(self, key: str) -> str:
        """The fact id of ``key`` (slugged)."""
        return f"{self.prefix}_{slug(key)}"

    def tok(self, key: str, value: Any, fmt: str = "{}", unit: str = "", path: str = "") -> str:
        """Register ``value`` under ``key`` (the same key twice must be the same value)."""
        fid = self.fid(key)
        if isinstance(value, float | np.floating):
            value = float(value)
            if not math.isfinite(value):
                value, fmt, unit = "not available", "{}", ""
        elif isinstance(value, bool | np.bool_):
            value = str(bool(value)).lower()
        elif isinstance(value, np.integer):
            value = int(value)
        fact = Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path or f"trace.{key}")
        old = self.facts.get(fid)
        if old is not None and (old.value, old.fmt, old.unit) != (fact.value, fact.fmt, fact.unit):
            raise ValueError(f"trace fact {fid} registered twice with different values")
        self.facts.setdefault(fid, fact)
        return "{{" + fid + "}}"

    def name(self, key: str, value: str) -> str:
        """A name (sample, gene, plate, well) as a string fact: names may hold digits."""
        return self.tok(key, str(value))

    def fold(self, key: str, fc: float) -> str:
        """A fold change as ``3.59×``."""
        return self.tok(key, float(fc), fold_fmt(float(fc)), TIMES)

    def times(self, key: str, log2: float) -> str:
        """The size of a log2 change as an unsigned factor, ``1.05×``."""
        return self.fold(key, float(2 ** abs(log2)))

    def pct(self, key: str, log2: float) -> str:
        """The size of a log2 change as a percentage of the fold change, ``5.3 %``."""
        return self.tok(key, float(100 * (2 ** abs(log2) - 1)), "{:.1f}", NNBSP + "%")

    def change(self, key: str, log2fc: float) -> str:
        """A fold change in words: ``3.59× higher`` or ``1.98-fold lower``."""
        if log2fc < 0:
            return f"{self.tok(key, float(2**-log2fc), '{:.2f}', '-fold')} lower"
        return f"{self.fold(key, float(2**log2fc))} higher"

    def p(self, key: str, p: float | None, alpha: float) -> str:
        """A p-value as the page writes it."""
        return self.tok(key, p_text(p, alpha))

    def count(self, key: str, n: int) -> str:
        """A count."""
        return self.tok(key, int(n))

    def cycles(self, key: str, cq: float | None) -> str:
        """A Cq (one decimal)."""
        return self.tok(key, float(cq) if cq is not None else math.nan, "{:.1f}")

    def say(self, text_id: str, text: str) -> str:
        """Keep sentence ``text_id`` after checking it has no naked number."""
        check = validate(text, self.facts)
        if not check.ok:
            raise ValueError(f"trace text {text_id!r} failed the no-naked-numbers check: {check}")
        self.texts[text_id] = text
        return text_id
