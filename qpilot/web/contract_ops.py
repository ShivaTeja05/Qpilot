"""Response models of the operations routes: agents, Ask, the model test and the fresh demo.

Owned by the ``ops`` router (:mod:`qpilot.web.routers.ops`). Like :mod:`qpilot.web.contract`, every
string here is text (never HTML) and every number comes from the engine, the store or the audit.
Keep changes additive and regenerate the frontend's types (``npm run gen:api``) with them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---- agents ---------------------------------------------------------------------------------

ToolAccess = Literal["read", "open", "propose", "request"]


class AgentTool(BaseModel):
    """One tool ``qpilot serve`` gives an agent, and what it can change."""

    name: str
    summary: str = Field(description="The first sentence of the tool's description.")
    description: str = Field(description="The whole description an agent reads, as text.")
    access: ToolAccess = Field(
        description="read: changes nothing; open: opens a file as a study or session (decides "
        "nothing); propose: adds a proposal only a person can accept; request: asks to decide a "
        "Decision Card (a choice that can change a conclusion waits for a person)."
    )
    effect: str = Field(description="What the tool can change, in plain words.")
    simulator: bool = Field(description="A read-only tool over the robustness audit (sim_*).")


class AgentRequest(BaseModel):
    """An agent's request on a Decision Card, waiting for a person (``pending.jsonl``)."""

    key: str = Field(description="The workspace to open: its session id, or the study id.")
    kind: Literal["session", "study"]
    study_id: str
    title: str = Field(description="The workspace's title.")
    card_id: str
    card_title: str
    option: str
    option_label: str
    reason: str = Field(description="The agent's reason, quoted text from the agent.")
    actor: str
    at: str
    seq: int
    hash: str
    can_change_a_conclusion: bool = Field(
        description="True when this choice can flip a conclusion (only a person decides it); "
        "False when it waits only because agents may not decide in Suggest mode."
    )
    expected_head: str = Field(description="The study's chain head now (for Approve/Turn down).")


class AgentActivity(BaseModel):
    """One thing an agent did: a decision-log entry or a proposal in a Studio inbox."""

    kind: Literal["decision", "proposal"]
    key: str
    workspace_kind: Literal["session", "study"]
    title: str
    at: str
    summary: str = Field(description="One line in plain words.")
    agent: str | None = Field(default=None, description="The agent's name, when it gave one.")
    status: str = Field(
        description="decision: applied / pending_human / rejected / stale / auto; "
        "proposal: proposed / accepted / edited / rejected / superseded."
    )
    reason: str | None = None
    card_id: str | None = None
    option: str | None = None
    proposal_id: str | None = None
    proposal_kind: str | None = None
    check: str | None = Field(default=None, description="The engine's check of a proposal.")


class AgentsView(BaseModel):
    """How an agent connects, what it may do, and what agents are doing in this store."""

    connect: str = Field(description="The command that connects Claude Code to qPilot.")
    connect_note: str
    store_note: str | None = Field(
        default=None,
        description="Set when this page's study store is not the one `qpilot serve` uses by "
        "default (the connect command then names it).",
    )
    tools: list[AgentTool]
    simulator: bool = Field(description="Whether the sim_* tools are served (qsim installed).")
    rules: list[str] = Field(description="What an agent can and cannot do, one line each.")
    pending: list[AgentRequest] = Field(description="Requests waiting for a person, oldest first.")
    activity: list[AgentActivity] = Field(description="Recent agent activity, newest first.")
    activity_total: int = Field(description="All agent entries found (the list is capped).")
    hidden_blind: int = Field(
        default=0,
        description="Agent requests and entries in sessions still blind (not shown until the "
        "design and the curves are confirmed).",
    )


# ---- Ask ------------------------------------------------------------------------------------

AskSource = Literal["auto", "study", "audit"]


class AskBody(BaseModel):
    """A question about the open study."""

    question: str = Field(min_length=1, max_length=500)
    source: AskSource = Field(
        default="auto",
        description="auto: verdict and what-if questions go to the audit when the study has "
        "one, everything else to the study's own tools; study / audit: force one.",
    )


class CitedFact(BaseModel):
    """A number the answer cites: what it is and its value as shown."""

    id: str | None = None
    meaning: str
    value: str


class AskAnswer(BaseModel):
    """An answer and how it was made (the result of an ``ask`` job)."""

    question: str
    answer: str = Field(description="The answer as text; every number in it is a cited fact.")
    engine: Literal["study", "audit"] = Field(
        description="study: qPilot's own tools (the MCP tool code); audit: the robustness "
        "audit's Ask engine."
    )
    tool: str
    args: dict[str, Any] = Field(default_factory=dict, description="The tool's arguments.")
    tool_words: str = Field(description="Which tool answered, in plain words.")
    routed_by: Literal["model", "keywords", "rules"] = Field(
        description="Who picked the tool: the model, keyword matching, or fixed reading rules."
    )
    routed_words: str
    written_by: Literal["template", "model"]
    writer_words: str = Field(description="Who wrote the words, in plain words.")
    provider: str
    model: str | None = Field(default=None, description="The model's name, when one was used.")
    facts: list[CitedFact] = Field(description="The numbers the answer cites, nothing else.")
    validated: bool = Field(description="Every number in the text is a cited fact.")
    note: str | None = Field(
        default=None, description="Why a template answered, or what happened to a request."
    )
    status: str | None = Field(
        default=None,
        description="For a request to change a choice: applied / pending_human / stale.",
    )
    card_id: str | None = Field(default=None, description="The card a request was made on.")
    autonomy: Literal["suggest", "decide_and_tell"] = Field(
        description="The autonomy mode the question was answered under."
    )
    head_before: str | None = None
    head_after: str | None = Field(
        default=None, description="The chain head after the answer (moved when Ask wrote)."
    )


# ---- the model test --------------------------------------------------------------------------


class ModelTestBody(BaseModel):
    """Which study the model is tested on (default: the demo study, else the latest)."""

    study: str | None = Field(
        default=None, description="A study id or a session id whose results are visible."
    )


class ScorecardRow(BaseModel):
    """One model's "Ask your data" scorecard on one study (``qpilot harness``'s first table)."""

    profile: str
    provider: str
    model: str | None = None
    endpoint: str | None = None
    run_at: str | None = None
    n_items: int = Field(description="Ask questions scored.")
    correct: int = Field(description="Final answers that were right, template answers included.")
    correct_by_model: int | None = Field(
        default=None, description="Right with the model choosing the tool and writing the words."
    )
    model_eligible: int | None = Field(
        default=None, description="Questions the model may answer itself (safety items excluded)."
    )
    invented_numbers_caught: int = Field(
        description="Model drafts with a number that was not a fact token; the validator caught "
        "every one, so none reached the reader."
    )
    numbers_shown: int = Field(description="Text that reached the reader with an untokened number.")
    safety_held: int
    safety_items: int
    fallbacks: int | None = Field(
        default=None, description="Answers a template replaced (none without a model)."
    )
    median_latency_s: float
    notes: list[str] = []


class ModelTestResult(BaseModel):
    """The result of a ``model.test`` job: this run's row and every saved row for the study."""

    study_id: str
    title: str
    current: ScorecardRow
    saved: list[ScorecardRow]
    n_questions: int
    note: str


# ---- the fresh demo -------------------------------------------------------------------------


class FreshDemo(BaseModel):
    """Where the demo's earlier work was moved (kept, never deleted)."""

    moved: list[str]
    archive: str | None = None
    message: str
