/**
 * The Results section's data: `GET /api/studies/{id}/results` (the ResultsView), `/cards` (the
 * Decision Cards with their view fields) and the writes on a card (decide, undo, turn down an
 * agent's request, explain). Every query key starts with `["w", key]` so live events refresh it.
 *
 * The types mirror the API's contract (qpilot/web/contract.py: ResultsView, GeneRow, CardsView);
 * the page formats every number itself and never types one in.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";

// ---- types (the contract's ResultsView / CardsView) ---------------------------------------------

export interface GeneCheck {
  id: string;
  passed: boolean;
  note: string;
}

export interface GeneRow {
  gene: string;
  headline: boolean;
  conclusion: "up" | "down" | "none";
  fc: number;
  ci: [number, number];
  p: number;
  n_hi: number;
  n_lo: number;
  holds: number;
  n_cells: number;
  level: string | null;
  reasons: string[];
  checks: GeneCheck[];
  /** The decision dimensions whose single change flips this gene's call. */
  flips_by: string[];
  efficiency?: number | null;
  verdict?: string | null;
  verdict_label?: string | null;
}

export interface ResultsView {
  study_id: string;
  summary: {
    n_plates: number;
    n_reactions: number;
    n_samples: number;
    groups: { label: string; n: number }[];
    design_line?: string | null;
    mode?: string | null;
  };
  rule: { alpha: number; min_log2fc: number; text: string };
  references: {
    used: string[];
    candidates?: string[];
    genorm: {
      M_initial: Record<string, number>;
      order: string[];
      V: Record<string, number>;
      recommended: string[];
      cutoff_M: number;
      cutoff_V: number;
    };
  };
  genes: GeneRow[];
  headline: string[];
  audit: { status: string; verdict_counts?: Record<string, number> | null } | null;
  chain_head: string | null;
}


interface ContrastLike {
  fc: number;
  conclusion: "up" | "down" | "none";
  p?: number;
  ci?: [number, number];
}

export interface CardBase {
  id: string;
  kind: string;
  rank: number;
  impact: Record<string, unknown>;
  evidence: Record<string, unknown>;
  options: { id: string; label: string; per_gene: Record<string, ContrastLike> }[];
  recommended: string;
  status: "open" | "decided" | "auto_decided" | "pending_human";
  decision?: string | null;
  reason?: string | null;
  decided_by?: string | null;
  decided_at?: string | null;
}

export interface CardView extends CardBase {
  title: string;
  status_line: string;
  impact_text: string;
  explanation_text: string;
  /** The option an agent asked for while the card waits for a person. */
  pending_option?: string | null;
  /** The option Undo would go back to (a new chain entry), when undo is possible. */
  undo_option?: string | null;
}

export interface CardsView {
  head: string | null;
  cards: CardView[];
}

// ---- reads --------------------------------------------------------------------------------------

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "same-origin",
      ...init,
      headers: init?.body ? { "content-type": "application/json", ...init.headers } : init?.headers,
    });
  } catch {
    throw new ApiError(0, "offline", "qPilot is not answering. Is `qpilot app` still running?");
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const e = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | undefined)?.error;
    throw new ApiError(response.status, e?.code ?? `http_${response.status}`, e?.message ?? "The server could not answer this request.", e?.details ?? {});
  }
  return body as T;
}

const studyUrl = (studyId: string, path = "") => `/api/studies/${encodeURIComponent(studyId)}${path}`;

export function useResults(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "results", studyId],
    enabled: Boolean(studyId),
    queryFn: () => call<ResultsView>(studyUrl(studyId!, "/results")),
  });
}

export function useCards(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "cards", studyId],
    enabled: Boolean(studyId),
    queryFn: () => call<CardsView>(studyUrl(studyId!, "/cards")),
  });
}

// ---- writes (always as a person; the server sets the actor) -------------------------------------

export interface CardAction {
  card: string;
  action: "decide" | "undo" | "reject" | "explain";
  option?: string;
  reason?: string;
  expected_head?: string | null;
}

export interface DecideOutcome {
  status: string;
  chain_head: string;
  card?: CardView | null;
  reason?: string | null;
}

export function useCardAction(key: string, studyId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ card, action, ...body }: CardAction) =>
      call<DecideOutcome & { text?: string; written_by?: string; facts?: Record<string, unknown> }>(
        studyUrl(studyId, `/cards/${encodeURIComponent(card)}/${action}`),
        { method: "POST", body: JSON.stringify(body) },
      ),
    onSettled: (_data, _error, vars) => {
      if (vars.action !== "explain") void qc.invalidateQueries({ queryKey: ["w", key] });
    },
  });
}
