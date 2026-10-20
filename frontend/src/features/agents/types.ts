/**
 * The shapes the Agents section reads (`GET /api/agents`). They mirror what the server builds
 * from `qpilot serve`'s tool list and the store, and are replaced by the generated contract
 * types (`Schemas[...]`) when the route lands.
 */

/** What a tool lets an agent do: look, ask a question, propose something, or request a decision. */
export type ToolKind = "read" | "ask" | "propose" | "request";

export interface AgentTool {
  name: string;
  description: string;
  kind: ToolKind;
}

/** An agent's request on a Decision Card that waits for a person. */
export interface PendingRequest {
  study_id: string;
  study_title?: string | null;
  card_id: string;
  card_title?: string | null;
  option: string;
  option_label?: string | null;
  reason: string;
  agent?: string | null;
  at: string;
  seq: number;
  hash: string;
  /** The study's current chain head, to send as `expected_head`. */
  head?: string | null;
}

/** Something an agent did: a decision entry (a request or an applied choice) or a proposal. */
export interface AgentActivity {
  study_id: string;
  study_title?: string | null;
  what: "decision" | "proposal";
  title: string;
  detail?: string | null;
  status: string;
  reason?: string | null;
  agent?: string | null;
  at: string;
  id?: string | null;
}

export interface AgentsView {
  /** The command(s) that connect an MCP client, e.g. `claude mcp add qpilot -- qpilot serve`. */
  connect: string[];
  tools: AgentTool[];
  pending: PendingRequest[];
  recent: AgentActivity[];
}
