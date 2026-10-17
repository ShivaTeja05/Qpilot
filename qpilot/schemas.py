"""Shared data contracts between the engine, the core, the app and the AI layer.

FROZEN at T0. This module is the interface both developers build against; change it only
through the contract-change protocol in ``team/00-TEAM-PLAN-OVERVIEW.md`` §7. After T0 it is
owned by Dev 2.
"""

from typing import Any, Literal, Protocol

from pydantic import BaseModel

Conclusion = Literal["up", "down", "none"]
Actor = Literal["human", "agent", "system"]
Autonomy = Literal["suggest", "decide_and_tell", "automatic", "teach"]  # last two reserved
Level = Literal["High", "Moderate", "Low", "Very low"]


class ContrastResult(BaseModel):
    """One gene's comparison between the two groups under one set of analysis choices."""

    target: str
    log2fc: float
    fc: float
    ci: tuple[float, float]
    p: float
    t: float
    n_hi: int
    n_lo: int
    conclusion: Conclusion


class GenormResult(BaseModel):
    """Reference-gene stability ranking (geNorm M and V)."""

    M_initial: dict[str, float]
    order: list[str]
    V: dict[str, float]
    recommended: tuple[str, ...]
    cutoff_M: float = 1.5
    cutoff_V: float = 0.15


class DesignSummary(BaseModel):
    """How the two comparison groups were defined."""

    group_var: str
    cut: float
    n_hi: int
    n_lo: int
    note: str = "expression-defined"
    refs_primary: tuple[str, ...]


class Check(BaseModel):
    """One named component of a confidence grade."""

    id: str
    passed: bool
    note: str
    fact_ids: list[str] = []


class Grade(BaseModel):
    """Ordinal confidence level with every downgrade named; never a probability."""

    level: Level
    reasons: list[str]
    checks: list[Check]
    min_flip_changes: int | None = None


class GeneRobustness(BaseModel):
    """How often a gene's conclusion holds across the robustness grid."""

    target: str
    conclusion: Conclusion
    fc: float
    holds: float
    n_cells: int
    impact: dict[str, dict[str, Any]]  # dim -> {"flips": bool, "max_delta_log2fc": float}


class Fact(BaseModel):
    """A number (or label) the engine produced and that prose may reference by id."""

    id: str
    value: float | int | str
    fmt: str = "{}"
    unit: str = ""
    path: str = ""


class CardOption(BaseModel):
    """One option on a Decision Card and its consequence for each headline gene."""

    id: str
    label: str
    per_gene: dict[str, ContrastResult]


class DecisionCard(BaseModel):
    """A choice that could change a conclusion, with evidence, options and the decision."""

    id: str
    kind: Literal["reference_set", "group_cutoff", "undetermined"]
    rank: int
    impact: dict[str, Any]  # {"flips": bool, "n_genes_flipped": int, "max_delta_log2fc": float}
    evidence: dict[str, Any]
    options: list[CardOption]
    recommended: str
    rationale_template: str
    facts: list[str]
    autonomy: Autonomy = "suggest"
    effective_autonomy: Autonomy = "suggest"
    status: Literal["open", "decided", "auto_decided", "pending_human"] = "open"
    decision: str | None = None
    reason: str | None = None
    decided_by: Actor | None = None
    decided_at: str | None = None


class StudyResult(BaseModel):
    """Everything the engine computed for one study."""

    study_id: str
    input_sha256: str
    n_plates: int
    n_reactions: int
    n_samples: int
    design: DesignSummary
    genorm: GenormResult
    contrasts: dict[str, ContrastResult]
    robustness: dict[str, GeneRobustness]
    confidence: dict[str, Grade] = {}
    efficiency: dict[str, float] = {}
    conclusion_rule: dict[str, float] = {"alpha": 0.05, "min_log2fc": 1.0}
    facts: dict[str, Fact] = {}


class DecisionEntry(BaseModel):
    """One line of decisions.jsonl; ``hash`` is sha256 of the canonical JSON minus ``hash``."""

    seq: int
    prev_hash: str
    card_id: str
    option: str
    reason: str
    actor: Actor
    status: Literal["applied", "stale", "pending_human", "rejected", "auto"]
    at: str
    hash: str = ""


class DecisionOutcome(BaseModel):
    """What happened when someone (human, agent or system) tried to decide a card."""

    status: Literal["applied", "stale", "pending_human", "rejected"]
    chain_head: str
    card: DecisionCard | None = None
    reason: str | None = None


class PlanResult(BaseModel):
    """Design check before an experiment: samples needed and what the design cannot detect."""

    n_needed: int | None
    mde_fold: float | None
    cannot_detect: list[str]
    rules: list[str]
    message: str = ""


class DecisionSpace(Protocol):
    """What the core needs from any domain plugin. ``qpcr/space.py`` implements it."""

    dimensions: dict[str, list[Any]]
    primary: dict[str, Any]
    items: list[str]

    def evaluate(self, cell: dict[str, Any]) -> dict[str, ContrastResult]:
        """Return each item's result under one combination of choices."""
        ...

    def conclude(self, result: ContrastResult) -> Conclusion:
        """Map a result to up / down / none under the stated conclusion rule."""
        ...


class StudyStoreAPI(Protocol):
    """Implemented by ``core/store.py``; on disk; the only writer to a study workspace."""

    def get(self, study_id: str) -> StudyResult:
        """Load a study's results."""
        ...

    def put(self, result: StudyResult, cards: list[DecisionCard]) -> None:
        """Write a study's results and cards atomically."""
        ...

    def cards(self, study_id: str) -> list[DecisionCard]:
        """Load a study's Decision Cards."""
        ...

    def chain_head(self, study_id: str) -> str:
        """Hash of the latest decision entry (or of the input file when there is none)."""
        ...

    def append_decision(
        self,
        study_id: str,
        card_id: str,
        option: str,
        reason: str,
        actor: Actor,
        expected_head: str | None,
    ) -> DecisionOutcome:
        """Record a decision under a lock; refuse with ``stale`` if the head moved."""
        ...

    def pending(self, study_id: str) -> list[DecisionEntry]:
        """Decisions raised by agents that await a human."""
        ...
