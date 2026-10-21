"""Small hand-built per-well tables and toy decision spaces for the Run Gate tests.

A table has the columns the gate reads from :func:`qpilot.qpcr.curves.analyse_study`; every
well is written out by hand so each test says exactly which control did what. The toy space is
a :class:`qpilot.schemas.DecisionSpace` whose results depend on which wells are left out, so the
consequence test can be checked without the qPCR engine.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from qpilot.core.rules import RuleEval
from qpilot.schemas import ContrastResult, Fact

COLUMNS = [
    "run_id",
    "well",
    "sample",
    "sample_type",
    "target",
    "note",
    "eff_indiv",
    "eff_target",
    "cq",
    "amplification",
]
TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
#: Numerals in rule text that are names or labels, not data (they are allowed outside facts).
LABELS = ("MIQE 2.0", "95 %", "R²")


def well(
    plate: str,
    name: str,
    target: str,
    sample: str,
    kind: str = "unkn",
    cq: float | None = 25.0,
    *,
    amplified: bool | None = None,
    eff: float = 1.9,
    eff_indiv: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    """One well. ``cq=None`` is a well that did not amplify; ``amplified`` overrides the call."""
    amp = cq is not None if amplified is None else amplified
    return {
        "run_id": plate,
        "well": name,
        "sample": sample,
        "sample_type": kind,
        "target": target,
        "note": note,
        "eff_indiv": eff if eff_indiv is None else eff_indiv,
        "eff_target": eff,
        "cq": float("nan") if cq is None else float(cq),
        "amplification": bool(amp),
    }


def table(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """The per-well table of ``rows`` (in the order given)."""
    return pd.DataFrame(list(rows), columns=COLUMNS)


def replicates(
    plate: str,
    target: str,
    sample: str,
    cqs: Iterable[float | None],
    kind: str = "unkn",
    start: int = 1,
    row: str = "A",
    eff: float = 1.9,
) -> list[dict[str, Any]]:
    """Replicate wells of one sample (wells ``<row><start>``, ``<row><start+1>`` …)."""
    return [
        well(plate, f"{row}{start + i}", target, sample, kind, cq, eff=eff)
        for i, cq in enumerate(cqs)
    ]


def rendered(text: str, facts: Mapping[str, Fact]) -> str:
    """``text`` with every fact token replaced by its value as the page writes it."""
    from qpilot.core.facts import render_fact

    return TOKEN.sub(lambda m: render_fact(facts[m.group(1)]), text)


def check_cited(ev: RuleEval, facts: Mapping[str, Fact]) -> None:
    """Every number an evaluation shows is a registered fact it cites.

    The cited tokens are among the evaluation's ``facts`` (which may also hold numbers kept as
    evidence only), every one of them registered; with the tokens taken out, no digit is left in
    the reason except in the :data:`LABELS`.
    """
    cited = TOKEN.findall(ev.reason)
    assert set(cited) <= set(ev.facts), (ev.rule_id, cited, ev.facts)
    for fid in ev.facts:
        assert fid in facts, (ev.rule_id, fid)
        assert facts[fid].path.startswith(f"gate/{ev.rule_id}/"), facts[fid].path
    bare = TOKEN.sub("", ev.reason)
    for label in LABELS:
        bare = bare.replace(label, "")
    assert not re.search(r"\d", bare), (ev.rule_id, ev.reason)
    assert "{{" not in bare and "}}" not in bare


# ---------- a toy decision space whose results depend on the wells left out ----------


def result(target: str, log2fc: float, p: float = 0.01, n: int = 6) -> ContrastResult:
    fc = 2.0**log2fc
    return ContrastResult(
        target=target,
        log2fc=log2fc,
        fc=fc,
        ci=(fc / 1.5, fc * 1.5),
        p=p,
        t=0.0,
        n_hi=n,
        n_lo=n,
        conclusion=conclude(log2fc, p),
    )


def conclude(log2fc: float, p: float) -> str:
    """p < 0.05 and at least 2-fold."""
    if p < 0.05 and log2fc >= 1.0:
        return "up"
    if p < 0.05 and log2fc <= -1.0:
        return "down"
    return "none"


class ToyGateSpace:
    """Dimensions ``a`` in {0, 1} and ``b`` in {"x", "y"}; primary ``a=0, b=x``.

    With nothing left out: ``g1`` up (log2FC 2.0), ``g2`` up (1.5), ``g3`` down (-1.5) when
    ``a == 0`` and ``none`` (-0.6) when ``a == 1``. Leaving out a well changes things:

    * ``P/flip``: ``g2`` drops to 0.4 everywhere (a primary flip);
    * ``P/big``: ``g1`` moves by +0.8 (a magnitude change, every call kept);
    * ``P/small``: ``g1`` moves by +0.1 (nothing that matters);
    * ``P/elsewhere``: ``g3`` becomes ``down`` also at ``a == 1`` (a flip at other settings only);
    * ``P/gone``: ``g2`` can no longer be compared (it is withheld).
    """

    def __init__(self, excluded: Iterable[str] = ()) -> None:
        self.excluded = frozenset(excluded)
        self.dimensions: dict[str, list[Any]] = {"a": [0, 1], "b": ["x", "y"]}
        self.primary: dict[str, Any] = {"a": 0, "b": "x"}
        self.items = [
            i for i in ("g1", "g2", "g3") if not ("P/gone" in self.excluded and i == "g2")
        ]
        self.calls = 0

    def evaluate(self, cell: dict[str, Any]) -> dict[str, ContrastResult]:
        self.calls += 1
        a = cell["a"]
        g1 = 2.0 + (0.8 if "P/big" in self.excluded else 0.0)
        g1 += 0.1 if "P/small" in self.excluded else 0.0
        g2 = 0.4 if "P/flip" in self.excluded else 1.5
        g3 = -1.5 if a == 0 or "P/elsewhere" in self.excluded else -0.6
        out = {"g1": result("g1", g1), "g2": result("g2", g2), "g3": result("g3", g3)}
        return {k: v for k, v in out.items() if k in self.items}

    def conclude(self, res: ContrastResult) -> str:
        return conclude(res.log2fc, res.p)


def rule_eval(
    options: Mapping[str, list[str]],
    verdict: str = "fail",
    rule_id: str = "G-NTC-1",
    scope: Mapping[str, str] | None = None,
) -> RuleEval:
    """A rule evaluation pointing at wells, with consequence options."""
    keys = sorted({k for v in options.values() for k in v})
    return RuleEval(
        rule_id=rule_id,
        check="ntc_gap",
        scope=dict(scope or {"plate": "P", "target": "T"}),
        outcome="tainted" if verdict == "fail" else "amplified_clear",
        verdict=verdict,
        reason="Some wells.",
        flagged=keys,
        options={k: list(v) for k, v in options.items()},
    )
