/** The shapes the Agents section reads: `GET /api/agents` (`qpilot/web/contract_ops.py`). */
import type { Schemas } from "@/api/client";

export type AgentsView = Schemas["AgentsView"];
export type AgentTool = Schemas["AgentTool"];
/** What a tool can change: nothing, open a file as a study, add a proposal, or request a decision. */
export type ToolAccess = AgentTool["access"];
/** An agent's request on a Decision Card, waiting for a person. */
export type PendingRequest = Schemas["AgentRequest"];
/** One thing an agent did: a decision-log entry or a proposal in a Studio inbox. */
export type AgentActivity = Schemas["AgentActivity"];
