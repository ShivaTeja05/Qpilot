/**
 * The shapes the Agents section reads: `GET /api/agents` (`qpilot/web/contract_ops.py`,
 * `AgentsView`). Replaced by the generated contract types (`Schemas[...]`) once the route is
 * merged and `schema.d.ts` regenerated.
 */

/** What a tool can change: nothing, open a file as a study, add a proposal, or request a decision. */
export type ToolAccess = "read" | "open" | "propose" | "request";

export interface AgentTool {
  name: string;
  /** The first sentence of the tool's description. */
  summary: string;
  description: string;
  access: ToolAccess;
  /** What the tool can change, in plain words. */
  effect: string;
  /** A read-only tool over the robustness audit (`sim_*`). */
  simulator: boolean;
}

/** An agent's request on a Decision Card, waiting for a person. */
export interface PendingRequest {
  /** The workspace to open: its session id, or the study id. */
  key: string;
  kind: "session" | "study";
  study_id: string;
  /** The workspace's title. */
  title: string;
  card_id: string;
  card_title: string;
  option: string;
  option_label: string;
  reason: string;
  actor: string;
  at: string;
  seq: number;
  hash: string;
  /** False when it waits only because agents may not decide in Suggest mode. */
  can_change_a_conclusion: boolean;
  /** The study's chain head now (sent with Approve / Turn down). */
  expected_head: string;
}

/** One thing an agent did: a decision-log entry or a proposal in a Studio inbox. */
export interface AgentActivity {
  kind: "decision" | "proposal";
  key: string;
  workspace_kind: "session" | "study";
  title: string;
  at: string;
  /** One line in plain words. */
  summary: string;
  agent?: string | null;
  status: string;
  reason?: string | null;
  card_id?: string | null;
  option?: string | null;
  proposal_id?: string | null;
  proposal_kind?: string | null;
  /** The engine's check of a proposal. */
  check?: string | null;
}

export interface AgentsView {
  connect: string;
  connect_note: string;
  store_note?: string | null;
  tools: AgentTool[];
  simulator: boolean;
  rules: string[];
  pending: PendingRequest[];
  activity: AgentActivity[];
  activity_total: number;
  hidden_blind: number;
}
