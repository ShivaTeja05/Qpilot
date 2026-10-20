/** The shapes the Agents section reads: `GET /api/agents` (`qpilot/web/contract_ops.py`). */
import type { Schemas } from "@/api/client";

export type AgentsView = Schemas["AgentsView"];
export type AgentTool = Schemas["AgentTool"];
/** What a tool can change: nothing, open a file as a study, add a proposal, or request a decision. */
export type ToolAccess = AgentTool["access"];
/** An agent's request on a Decision Card, waiting for a person. */
export type PendingRequest = Schemas["AgentRequest"];
/** What became of an agent's request (api-ops a808f19; additive, in the schema once regenerated). */
export type RequestState = "waiting" | "approved" | "turned_down" | "decided_otherwise" | "closed";
/** One thing an agent did: a decision-log entry or a proposal in a Studio inbox. */
export type AgentActivity = Schemas["AgentActivity"] & {
  seq?: number | null;
  hash?: string | null;
  request_state?: RequestState | null;
  settled_by?: string | null;
  settled_at?: string | null;
};
