"""Run Gate's consequence test: does a failing or warning rule change any conclusion?

Domain-agnostic. A rule evaluation (``core/rules.py``) points at some items (wells, for qPCR) and
offers options such as "exclude the flagged wells". For each option the plugin builds the same
decision space the study uses with those items left out; this module re-runs the whole grid on
it and compares it with the analysis as it stands (``keep``), item by item:

* ``flip`` — some item's primary-cell conclusion differs (including an item that can no longer
  be tested at all: it is ``withheld``);
* ``magnitude`` — no flip, but some item's log2 fold change moves by more than
  ``magnitude_log2`` or its grid agreement by at least ``magnitude_agreement``;
* ``none`` — neither;
* ``unknown`` — the option could not be evaluated (the plugin says why).

The rule's class is the worst over its options (flip > unknown > magnitude > none) and gives
the triage (W2 spec C.4, without a cost model): ``none`` -> ``ignore`` (logged), ``magnitude``
-> ``rescue`` (the option that keeps every call and moves log2FC least), ``flip`` -> ``human``,
``unknown`` -> ``defer``. A rule whose options can flip a conclusion becomes a Decision Card of
kind ``gate.rule``; :func:`core.decisions.needs_human` then makes it a person's decision for
every actor. Rules label; nothing here changes the analysis.

"Changes elsewhere": an option that flips no primary call can still change a conclusion at
other settings of the grid. That is reported (``n_flipped_anywhere``) and also raises a card,
decided automatically to keep the analysis as it is, so an agent asking to apply the option
must still ask a person (the same rule as ``build_cards``' ``AUTO_REASON_ELSEWHERE``).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel

from qpilot.core import robustness
from qpilot.core.decisions import rank_cards
from qpilot.core.rules import RuleEval, summarise
from qpilot.schemas import CardOption, ContrastResult, DecisionCard, DecisionSpace, Fact

ConsequenceClass = Literal["none", "magnitude", "flip", "unknown"]
Triage = Literal["ignore", "rescue", "human", "defer"]
WITHHELD = "withheld"
KEEP = "keep"
#: Project conventions (scientist spec section 3), unsourced; a pack can override them.
MAGNITUDE_LOG2 = 0.5
MAGNITUDE_AGREEMENT = 0.10
_RANK = {"none": 0, "magnitude": 1, "unknown": 2, "flip": 3}
_TRIAGE: dict[str, Triage] = {
    "none": "ignore",
    "magnitude": "rescue",
    "flip": "human",
    "unknown": "defer",
}
GATE_CARD_KIND = "gate.rule"
GATE_TEMPLATE = "gate_rule_v1"
AUTO_REASON_GATE = (
    "Decided automatically: leaving out the wells this rule points at changes no conclusion "
    "at the recommended settings. At other settings it can, so an agent must ask a person."
)
MAX_CARD_ITEMS = 20


class Baseline(BaseModel):
    """The analysis as it stands: per item, its primary call, log2FC and grid agreement."""

    model_config = {"arbitrary_types_allowed": True}

    items: list[str]
    calls: dict[str, str]
    log2fc: dict[str, float]
    agreement: dict[str, float]
    results: dict[str, ContrastResult]
    dimensions: dict[str, list[Any]]
    cells: Any = None  # pandas Series indexed by (cell index tuple, item) -> conclusion


class AtCell:
    """A decision space read at another primary cell (the analysis in use, not the planned one).

    Every other dimension of the grid stays as it is, so the grid itself is the same; only what
    counts as "the analysis as it stands" moves. Dimensions the space does not have are ignored,
    and dimensions the cell does not name keep the space's own primary option.
    """

    def __init__(self, space: DecisionSpace, cell: Mapping[str, Any]) -> None:
        self.space = space
        self.dimensions = space.dimensions
        self.items = space.items
        self.primary = {
            **space.primary,
            **{k: v for k, v in cell.items() if k in space.dimensions and v in space.dimensions[k]},
        }

    def evaluate(self, cell: dict[str, Any]) -> dict[str, ContrastResult]:
        """The wrapped space's results for ``cell``."""
        return self.space.evaluate(cell)

    def conclude(self, result: ContrastResult) -> str:
        """The wrapped space's conclusion rule."""
        return self.space.conclude(result)


def at_cell(space: DecisionSpace, cell: Mapping[str, Any] | None) -> DecisionSpace:
    """``space`` read at ``cell`` (see :class:`AtCell`); ``space`` itself when ``cell`` is empty."""
    return AtCell(space, cell) if cell else space


def baseline(space: DecisionSpace, grid: pd.DataFrame | None = None) -> Baseline:
    """Summarise ``space`` (and its grid, computed when not given) for comparison."""
    grid = robustness.run_grid(space) if grid is None else grid
    results = space.evaluate(space.primary)
    calls = {item: space.conclude(results[item]) for item in space.items}
    agreement = _agreement(grid, calls)
    return Baseline(
        items=list(space.items),
        calls=calls,
        log2fc={item: float(results[item].log2fc) for item in space.items},
        agreement=agreement,
        results={item: results[item] for item in space.items},
        dimensions={k: list(v) for k, v in space.dimensions.items()},
        cells=_cell_series(grid),
    )


def _agreement(grid: pd.DataFrame, calls: Mapping[str, str]) -> dict[str, float]:
    if grid.empty:
        return {item: 1.0 for item in calls}
    primary = grid["item"].map(calls)
    agree = (grid["conclusion"] == primary).groupby(grid["item"]).mean()
    return {item: float(agree.get(item, 1.0)) for item in calls}


def _cell_series(grid: pd.DataFrame) -> pd.Series:
    idx = [c for c in grid.columns if c.endswith(robustness.IDX_SUFFIX)]
    keyed = grid.set_index([*idx, "item"])["conclusion"]
    return keyed.sort_index()


class ItemChange(BaseModel):
    """One item whose primary call, log2FC or agreement differs under an option."""

    item: str
    call_keep: str
    call_option: str
    log2fc_keep: float | None
    log2fc_option: float | None
    agreement_keep: float
    agreement_option: float | None


class OptionConsequence(BaseModel):
    """What one option (leaving some items out) does to every conclusion."""

    option: str
    excluded: list[str]
    consequence: ConsequenceClass
    reason: str = ""
    n_flipped: int = 0
    flipped: list[str] = []
    n_flipped_anywhere: int = 0
    flipped_anywhere: list[str] = []
    max_delta_log2fc: float = 0.0
    max_delta_agreement: float = 0.0
    changed: list[ItemChange] = []


def _finite(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def compare(
    option: str,
    excluded: Iterable[str],
    base: Baseline,
    variant: DecisionSpace,
    magnitude_log2: float = MAGNITUDE_LOG2,
    magnitude_agreement: float = MAGNITUDE_AGREEMENT,
    grid: pd.DataFrame | None = None,
) -> tuple[OptionConsequence, dict[str, ContrastResult]]:
    """Compare ``variant`` (the space with ``excluded`` left out) with the baseline.

    Returns the consequence and the variant's primary-cell results (for the card).
    """
    grid = robustness.run_grid(variant) if grid is None else grid
    results = variant.evaluate(variant.primary)
    calls = {item: variant.conclude(results[item]) for item in variant.items}
    agreement = _agreement(grid, calls)
    changed: list[ItemChange] = []
    flipped: list[str] = []
    deltas: list[float] = [0.0]
    agree_deltas: list[float] = [0.0]
    for item in base.items:
        keep_call, keep_fc, keep_agree = base.calls[item], base.log2fc[item], base.agreement[item]
        if item not in calls:
            flipped.append(item)
            changed.append(
                ItemChange(
                    item=item,
                    call_keep=keep_call,
                    call_option=WITHHELD,
                    log2fc_keep=_finite(keep_fc),
                    log2fc_option=None,
                    agreement_keep=keep_agree,
                    agreement_option=None,
                )
            )
            continue
        fc = float(results[item].log2fc)
        delta = abs(fc - keep_fc) if math.isfinite(fc) and math.isfinite(keep_fc) else 0.0
        agree_delta = abs(agreement[item] - keep_agree)
        deltas.append(delta)
        agree_deltas.append(agree_delta)
        if calls[item] != keep_call:
            flipped.append(item)
        if calls[item] != keep_call or delta > 1e-12 or agree_delta > 1e-12:
            changed.append(
                ItemChange(
                    item=item,
                    call_keep=keep_call,
                    call_option=calls[item],
                    log2fc_keep=_finite(keep_fc),
                    log2fc_option=_finite(fc),
                    agreement_keep=keep_agree,
                    agreement_option=agreement[item],
                )
            )
    anywhere = _flipped_anywhere(base, variant, grid)
    max_delta, max_agree = max(deltas), max(agree_deltas)
    if flipped:
        cls: ConsequenceClass = "flip"
    elif max_delta > magnitude_log2 or max_agree >= magnitude_agreement - 1e-12:
        cls = "magnitude"
    else:
        cls = "none"
    out = OptionConsequence(
        option=option,
        excluded=sorted(set(excluded)),
        consequence=cls,
        n_flipped=len(flipped),
        flipped=flipped,
        n_flipped_anywhere=len(anywhere),
        flipped_anywhere=anywhere,
        max_delta_log2fc=max_delta,
        max_delta_agreement=max_agree,
        changed=changed,
    )
    return out, results


def _flipped_anywhere(base: Baseline, variant: DecisionSpace, grid: pd.DataFrame) -> list[str]:
    """Items whose conclusion differs in at least one cell (same grid), withheld items too."""
    missing = [item for item in base.items if item not in variant.items]
    same_grid = {k: list(v) for k, v in variant.dimensions.items()} == base.dimensions
    if not same_grid or base.cells is None:
        return missing  # cells cannot be matched one to one; the primary comparison stands
    mine = _cell_series(grid)
    joined = pd.concat([base.cells.rename("keep"), mine.rename("option")], axis=1, join="inner")
    diff = joined[joined["keep"] != joined["option"]]
    moved = set(diff.index.get_level_values("item")) if len(diff) else set()
    return [item for item in base.items if item in moved or item in missing]


def unknown(option: str, excluded: Iterable[str], reason: str) -> OptionConsequence:
    """An option that could not be evaluated, with the reason in plain words."""
    return OptionConsequence(
        option=option, excluded=sorted(set(excluded)), consequence="unknown", reason=reason
    )


def unchanged(option: str, excluded: Iterable[str], reason: str) -> OptionConsequence:
    """An option that leaves the analysis exactly as it is (e.g. the items are not analysed)."""
    return OptionConsequence(
        option=option, excluded=sorted(set(excluded)), consequence="none", reason=reason
    )


class Consequence(BaseModel):
    """The consequence test of one rule evaluation: every option, the worst class, the triage."""

    eval_key: str
    rule_id: str
    scope: dict[str, str]
    verdict: str
    consequence: ConsequenceClass
    triage: Triage
    rescue_option: str | None = None
    options: list[OptionConsequence]
    facts: list[str] = []
    card_id: str | None = None


def classify(options: list[OptionConsequence]) -> tuple[ConsequenceClass, Triage, str | None]:
    """The worst class over the options, its triage and (for ``rescue``) the option to apply."""
    if not options:
        return "none", "ignore", None
    worst = max(options, key=lambda o: _RANK[o.consequence]).consequence
    rescue = None
    if worst == "magnitude":
        candidates = [o for o in options if o.consequence == "magnitude"]
        rescue = min(candidates, key=lambda o: (o.max_delta_log2fc, o.option)).option
    return worst, _TRIAGE[worst], rescue


def eval_id(ev: RuleEval) -> str:
    """A short, stable id for a rule evaluation (12 hex of the sha256 of its key)."""
    return hashlib.sha256(ev.key.encode("utf-8")).hexdigest()[:12]


def card_id_for(ev: RuleEval) -> str:
    """The Decision Card id of a rule evaluation's card."""
    return f"card_gate_{eval_id(ev)}"


def consequence_facts(
    ev: RuleEval, options: list[OptionConsequence]
) -> tuple[dict[str, Fact], dict[str, list[str]]]:
    """Facts for each option's counts: ``f_gate_nflip_<id>_<option>`` and the like.

    Returns the facts and, per option, their ids.
    """
    facts: dict[str, Fact] = {}
    per_option: dict[str, list[str]] = {}
    base = eval_id(ev)
    for opt in options:
        stem = f"{base}_{opt.option}"
        rows = [
            (f"f_gate_nflip_{stem}", opt.n_flipped, "{}", "n_flipped"),
            (f"f_gate_nflipany_{stem}", opt.n_flipped_anywhere, "{}", "n_flipped_anywhere"),
            (f"f_gate_dlog2_{stem}", round(opt.max_delta_log2fc, 6), "{:.2f}", "max_delta_log2fc"),
            (f"f_gate_nexcl_{stem}", len(opt.excluded), "{}", "n_excluded"),
        ]
        ids = []
        for fid, value, fmt, name in rows:
            path = f"gate/{ev.rule_id}/{base}/{opt.option}/{name}"
            facts[fid] = Fact(id=fid, value=value, fmt=fmt, path=path)
            ids.append(fid)
        per_option[opt.option] = ids
    return facts, per_option


def gate_card(
    ev: RuleEval,
    consequence: Consequence,
    keep_results: Mapping[str, ContrastResult],
    option_results: Mapping[str, Mapping[str, ContrastResult]],
    option_labels: Mapping[str, str],
    headline: Iterable[str] = (),
) -> DecisionCard | None:
    """A ``gate.rule`` Decision Card when an option can change a conclusion; else ``None``.

    Options: ``keep`` (the analysis as it stands, the recommended option: nothing changes
    silently) and each consequence option. ``per_gene`` shows the items whose call changes
    (anywhere) plus the headline items, at most :data:`MAX_CARD_ITEMS`. A card that flips a
    primary call is ``open`` (a person decides; the rationale says the wells are worth
    repeating); one that flips only elsewhere is decided automatically to ``keep`` and still
    needs a person if an agent asks.
    """
    flips = any(o.n_flipped for o in consequence.options)
    anywhere = [i for o in consequence.options for i in o.flipped_anywhere]
    if not flips and not anywhere:
        return None
    shown = list(dict.fromkeys([*(i for o in consequence.options for i in o.flipped), *anywhere]))
    shown += [h for h in headline if h in keep_results and h not in shown]
    shown = shown[:MAX_CARD_ITEMS]
    options = [
        CardOption(
            id=KEEP,
            label="Keep every well (the analysis as it stands)",
            per_gene={i: keep_results[i] for i in shown if i in keep_results},
        )
    ]
    for opt in consequence.options:
        results = option_results.get(opt.option, {})
        options.append(
            CardOption(
                id=opt.option,
                label=option_labels.get(opt.option, opt.option.replace("_", " ")),
                per_gene={i: results[i] for i in shown if i in results},
            )
        )
    n_flip = max((o.n_flipped for o in consequence.options), default=0)
    impact = {
        "flips": flips,
        "n_genes_flipped": n_flip,
        "max_delta_log2fc": max((o.max_delta_log2fc for o in consequence.options), default=0.0),
        "flips_anywhere": bool(anywhere) or flips,
        "n_genes_flipped_anywhere": len(set(anywhere)),
    }
    card = DecisionCard(
        id=card_id_for(ev),
        kind=GATE_CARD_KIND,
        rank=0,
        impact=impact,
        evidence={
            "rule_id": ev.rule_id,
            "scope": dict(ev.scope),
            "verdict": ev.verdict,
            "outcome": ev.outcome,
            "flagged": list(ev.flagged),
            "consequence": consequence.consequence,
            "triage": consequence.triage,
        },
        options=options,
        recommended=KEEP,
        rationale_template=GATE_TEMPLATE,
        facts=[*ev.facts, *consequence.facts],
    )
    if not flips:
        card = card.model_copy(
            update={
                "status": "auto_decided",
                "decision": KEEP,
                "reason": AUTO_REASON_GATE,
                "decided_by": "system",
            }
        )
    return card


def run_consequences(
    evals: Iterable[RuleEval],
    base: Baseline,
    build_variant: Callable[[list[str]], DecisionSpace | OptionConsequence],
    magnitude_log2: float = MAGNITUDE_LOG2,
    magnitude_agreement: float = MAGNITUDE_AGREEMENT,
) -> list[tuple[RuleEval, Consequence, dict[str, dict[str, ContrastResult]]]]:
    """The consequence test for every ``warn``/``fail`` evaluation that offers options.

    ``build_variant(excluded)`` returns the study's space with those items left out, or an
    :class:`OptionConsequence` when it can say the answer without a re-run (``unchanged``) or
    cannot evaluate it (``unknown``). Identical exclusion sets are evaluated once.
    """
    cache: dict[tuple[str, ...], tuple[OptionConsequence, dict[str, ContrastResult]]] = {}
    out = []
    for ev in evals:
        if ev.verdict not in ("warn", "fail") or not ev.options:
            continue
        options: list[OptionConsequence] = []
        results: dict[str, dict[str, ContrastResult]] = {}
        for option, keys in sorted(ev.options.items()):
            key = tuple(sorted(set(keys)))
            if key not in cache:
                variant = build_variant(list(key))
                if isinstance(variant, OptionConsequence):
                    # "unchanged": every result is the analysis as it stands (shown on the card
                    # like any option); "unknown": there is nothing to show.
                    same = variant.consequence == "none" and not variant.changed
                    cache[key] = (variant, dict(base.results) if same else {})
                else:
                    cache[key] = compare(
                        option, key, base, variant, magnitude_log2, magnitude_agreement
                    )
            done, res = cache[key]
            options.append(done.model_copy(update={"option": option}))
            results[option] = res
        cls, triage, rescue = classify(options)
        out.append(
            (
                ev,
                Consequence(
                    eval_key=ev.key,
                    rule_id=ev.rule_id,
                    scope=dict(ev.scope),
                    verdict=ev.verdict,
                    consequence=cls,
                    triage=triage,
                    rescue_option=rescue,
                    options=options,
                ),
                results,
            )
        )
    return out


# ---------- the report ----------

GATE_SCHEMA = "qpilot.gate/1"


def _clean(value: Any) -> Any:
    """JSON-safe: NaN and infinities become ``None`` (strict JSON has no NaN)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


class GateReport(BaseModel):
    """Everything one gate run produced. ``gate.json`` is all but ``evals`` and ``cards``.

    ``units`` are the plugin's gating units (plates, for qPCR) -> ``gated`` | ``ungated``.
    """

    pack: dict[str, str]
    units: dict[str, str]
    counts: dict[str, int]
    consequences: list[Consequence]
    triage: dict[str, int]
    facts: dict[str, Fact]
    evals: list[RuleEval]
    cards: list[DecisionCard]

    def gate_data(self) -> dict[str, Any]:
        """The content of ``gate.json``."""
        return _clean(
            {
                "schema": GATE_SCHEMA,
                "pack": self.pack,
                "units": self.units,
                "counts": self.counts,
                "triage": self.triage,
                "consequences": [c.model_dump(mode="json") for c in self.consequences],
                "cards": [c.id for c in self.cards],
                "facts": {fid: f.model_dump(mode="json") for fid, f in sorted(self.facts.items())},
                "note": "Research use only. Rules label; they never change a conclusion.",
            }
        )

    def evals_data(self) -> list[dict[str, Any]]:
        """The content of ``rule_evals.json``."""
        return _clean([ev.model_dump(mode="json") for ev in self.evals])


def build_report(
    pack: dict[str, str],
    units: Mapping[str, str],
    evals: list[RuleEval],
    done: list[tuple[RuleEval, Consequence, dict[str, dict[str, ContrastResult]]]],
    base: Baseline,
    facts: Mapping[str, Fact],
    option_labels: Mapping[str, str],
    headline: Iterable[str] = (),
) -> GateReport:
    """Assemble the report: consequence facts, one card per rule that can change a conclusion."""
    all_facts = dict(facts)
    consequences, cards = [], []
    for ev, consequence, results in done:
        extra, _per_option = consequence_facts(ev, consequence.options)
        all_facts.update(extra)
        consequence = consequence.model_copy(update={"facts": sorted(extra)})
        card = gate_card(ev, consequence, base.results, results, option_labels, headline)
        if card is not None:
            consequence = consequence.model_copy(update={"card_id": card.id})
            cards.append(card)
        consequences.append(consequence)
    triage = dict.fromkeys(("ignore", "rescue", "human", "defer"), 0)
    for consequence in consequences:
        triage[consequence.triage] += 1
    return GateReport(
        pack=dict(pack),
        units=dict(units),
        counts=summarise(evals),
        consequences=consequences,
        triage=triage,
        facts=all_facts,
        evals=evals,
        cards=rank_cards(cards),
    )
