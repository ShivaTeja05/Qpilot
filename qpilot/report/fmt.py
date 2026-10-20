"""Numbers in the exported files, written as the page writes them (``src/lib/format.ts``).

fold ``3.59×`` · ``0.57×``; CI ``[2.42–5.33]``; p ``0.003`` · ``< 0.001``; share of analyses
``64 %`` (never rounded to the ends); counts ``24 576``.
"""

from __future__ import annotations

import math

NNBSP = " "
EN_DASH = "–"
MINUS = "−"
MISSING = "—"


def _finite(x: float | None) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def count(n: float | None) -> str:
    """``24 576``."""
    if not _finite(n):
        return MISSING
    text = f"{round(n):,}".replace(",", NNBSP)  # type: ignore[arg-type]
    return text.replace("-", MINUS)


def fold_number(fc: float | None) -> str:
    """Two decimals from 1 up, two significant digits below."""
    if not _finite(fc) or fc <= 0:  # type: ignore[operator]
        return MISSING
    if fc >= 1:  # type: ignore[operator]
        return f"{fc:.2f}"
    digits = max(2, 1 - math.floor(math.log10(fc)))  # type: ignore[arg-type]
    return f"{fc:.{min(digits, 6)}f}"


def fold(fc: float | None) -> str:
    """``3.59×``."""
    n = fold_number(fc)
    return n if n == MISSING else f"{n}×"


def ci(lo: float | None, hi: float | None) -> str:
    """``[2.42–5.33]``."""
    if not (_finite(lo) and _finite(hi)):
        return MISSING
    return f"[{fold_number(lo)}{EN_DASH}{fold_number(hi)}]"


def p_value(p: float | None) -> str:
    """``< 0.001``, ``0.003``; never rounded across 0.05."""
    if not _finite(p) or p < 0:  # type: ignore[operator]
        return MISSING
    if p < 0.001:  # type: ignore[operator]
        return f"<{NNBSP}0.001"
    if p >= 0.995:  # type: ignore[operator]
        return "1.00"
    decimals = 3 if p < 0.1 else 2  # type: ignore[operator]
    text = f"{p:.{decimals}f}"
    while decimals < 6 and (p < 0.05) != (float(text) < 0.05):  # type: ignore[operator]
        decimals += 1
        text = f"{p:.{decimals}f}"
    return text


def percent(fraction: float | None) -> str:
    """``64 %``; ``> 99 %`` and ``< 1 %`` near the ends."""
    if not _finite(fraction):
        return MISSING
    f = min(1.0, max(0.0, float(fraction)))  # type: ignore[arg-type]
    if 0 < f < 0.005:
        return f"<{NNBSP}1{NNBSP}%"
    if 0.995 <= f < 1:
        return f">{NNBSP}99{NNBSP}%"
    return f"{round(f * 100)}{NNBSP}%"


CALL_WORD = {"up": "▲ up", "down": "▼ down", "none": "— no call"}
