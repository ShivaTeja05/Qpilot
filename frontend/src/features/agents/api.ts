/**
 * The Agents section's requests. Approve and Turn down are a person's decisions on the card
 * the agent asked about: the same calls the Decision Cards in Results make.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { onLiveEvent } from "@/api/live";
import { requestJson } from "@/features/record/api";
import { cardTitle, optionLabel } from "@/features/record/words";
import { shortHash } from "@/lib/format";
import { useWrite } from "@/shell/writes";
import type { AgentsView, PendingRequest } from "./types";

/** Agents' tools, the requests waiting for a person and recent agent activity. */
export function useAgents(workspaceKey: string, studyId: string | null | undefined) {
  const qc = useQueryClient();
  const queryKey = ["w", workspaceKey, "agents", studyId];
  // The list spans every study: any study's or inbox's change (an agent writing from its own
  // process, another tab) refreshes it, not only this workspace's.
  useEffect(
    () =>
      onLiveEvent((event) => {
        if (event.type === "study.changed" || event.type === "proposals.changed")
          void qc.invalidateQueries({ queryKey: ["w", workspaceKey, "agents"] });
      }),
    [qc, workspaceKey],
  );
  return useQuery({ queryKey, queryFn: () => requestJson<AgentsView>("/api/agents") });
}

/** `DecisionDone` (`qpilot/web/contract.py`): the answer to decide / turn down. */
interface Outcome {
  outcome: { status: string; chain_head: string; reason?: string | null };
  message: string;
  head: string;
}

export type Verdict = "approve" | "turn_down";

const cardPath = (r: PendingRequest) =>
  `/api/studies/${encodeURIComponent(r.study_id)}/cards/${encodeURIComponent(r.card_id)}`;

/**
 * Approve an agent's request (decide its card with the option it asked for) or turn it down,
 * with the person's reason. Re-reads the workspace and says what happened in a toast.
 */
export function useAnswerRequest(workspaceKey: string | null | undefined, onDone?: () => void) {
  return useWrite<{ request: PendingRequest; verdict: Verdict; reason: string }, Outcome>({
    workspaceKey,
    mutationFn: ({ request, verdict, reason }) =>
      requestJson<Outcome>(`${cardPath(request)}/${verdict === "approve" ? "decide" : "reject-request"}`, {
        method: "POST",
        body: JSON.stringify({ option: request.option, reason, expected_head: request.expected_head }),
      }),
    success: (done, { request, verdict }) => {
      if (done.outcome.status === "stale")
        return { title: "Something was decided on this card first", description: "Here is the current state; look again." };
      const what = `${cardTitle(request)} → ${optionLabel(request)}`;
      return {
        title: verdict === "approve" ? `Approved: ${what}` : `Turned down: ${what}`,
        description: `${done.message} Added to the record (chain ${shortHash(done.head)}).`,
      };
    },
    onSuccess: (done) => {
      if (done.outcome.status !== "stale") onDone?.();
    },
  });
}
