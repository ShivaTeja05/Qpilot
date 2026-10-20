/**
 * The Agents section's requests. Approve and Turn down are a person's decisions on the card
 * the agent asked about: the same calls the Decision Cards in Results make.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { requestJson } from "@/features/record/api";
import type { AgentsView, PendingRequest } from "./types";

/** Agents' tools, the requests waiting for a person and recent agent activity. */
export function useAgents(workspaceKey: string, studyId: string | null | undefined) {
  return useQuery({
    // Includes the study id so a `study.changed` event for it refreshes the list live.
    queryKey: ["w", workspaceKey, "agents", studyId],
    queryFn: () => requestJson<AgentsView>("/api/agents"),
  });
}

interface Outcome {
  status: string;
  chain_head?: string;
  reason?: string | null;
}

const cardPath = (r: PendingRequest) =>
  `/api/studies/${encodeURIComponent(r.study_id)}/cards/${encodeURIComponent(r.card_id)}`;

/** Approve an agent's request: decide its card with the option it asked for, with a reason. */
export function useApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ request, reason }: { request: PendingRequest; reason: string }) =>
      requestJson<Outcome>(`${cardPath(request)}/decide`, {
        method: "POST",
        body: JSON.stringify({ option: request.option, reason, expected_head: request.head ?? null }),
      }),
    onSettled: (_d, _e, { request }) => void qc.invalidateQueries({ predicate: (q) => q.queryKey.includes(request.study_id) }),
  });
}

/** Turn an agent's request down, with a reason (it stays in the chain as turned down). */
export function useTurnDown() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ request, reason }: { request: PendingRequest; reason: string }) =>
      requestJson<Outcome>(`${cardPath(request)}/turn-down`, {
        method: "POST",
        body: JSON.stringify({ option: request.option, reason, expected_head: request.head ?? null }),
      }),
    onSettled: (_d, _e, { request }) => void qc.invalidateQueries({ predicate: (q) => q.queryKey.includes(request.study_id) }),
  });
}
