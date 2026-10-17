"""A tiny, deterministic decision space so the core can be tested without the qPCR engine.

Dimensions: ``a`` in {0, 1, 2}, ``b`` in {"x", "y"} (6 cells). Items:
- ``g1`` is "up" in every cell;
- ``g2`` is "up" when ``a == 0`` and "none" otherwise (it flips on ``a``);
- ``g3`` is "down" when ``b == "x"`` and "none" otherwise (it flips on ``b``).
"""

from typing import Any

from qpilot.schemas import Conclusion, ContrastResult


def _result(target: str, log2fc: float, p: float) -> ContrastResult:
    fc = 2.0**log2fc
    return ContrastResult(
        target=target,
        log2fc=log2fc,
        fc=fc,
        ci=(fc / 1.5, fc * 1.5),
        p=p,
        t=0.0,
        n_hi=10,
        n_lo=20,
        conclusion=conclude_values(log2fc, p),
    )


def conclude_values(log2fc: float, p: float) -> Conclusion:
    """The demo conclusion rule: p < 0.05 and at least 2-fold."""
    if p < 0.05 and log2fc >= 1.0:
        return "up"
    if p < 0.05 and log2fc <= -1.0:
        return "down"
    return "none"


class ToySpace:
    """Implements ``qpilot.schemas.DecisionSpace`` with hand-picked outcomes."""

    def __init__(self) -> None:
        self.dimensions: dict[str, list[Any]] = {"a": [0, 1, 2], "b": ["x", "y"]}
        self.primary: dict[str, Any] = {"a": 0, "b": "x"}
        self.items: list[str] = ["g1", "g2", "g3"]
        self.calls = 0

    def evaluate(self, cell: dict[str, Any]) -> dict[str, ContrastResult]:
        """Return each item's result for one cell."""
        self.calls += 1
        a, b = cell["a"], cell["b"]
        return {
            "g1": _result("g1", 2.0 + 0.1 * a, 0.001),
            "g2": _result("g2", 1.5 if a == 0 else 0.5 - 0.1 * a, 0.01),
            "g3": _result("g3", -1.5 if b == "x" else -0.4, 0.01),
        }

    def conclude(self, result: ContrastResult) -> Conclusion:
        """Map a result to up / down / none."""
        return conclude_values(result.log2fc, result.p)
