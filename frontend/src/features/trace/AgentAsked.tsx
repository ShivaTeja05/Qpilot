/**
 * An agent's request to set wells aside at a place, shown beside the place where a person decides
 * (`qpcr_request_set_aside` over MCP files the agent's well exclusions in the Studio inbox; the
 * place's **Decide…** answers them: approve by choosing its option, turn down by keeping).
 * Nothing is set aside until a person does.
 */
import { Bot } from "lucide-react";
import { plural } from "@/lib/format";
import type { WherePlace } from "./api";

export type WhereRequest = NonNullable<WherePlace["requests"]>[number];

/** What the agent asked for, in words ("Set this well's value aside (3 wells)"). */
export function requestWords(r: WhereRequest): string {
  const n = r.wells.length;
  const asked = n ? ` (${plural(n, "well")})` : "";
  const putBack = r.put_back ?? [];
  const back = putBack.length ? `, and to put ${plural(putBack.length, "well")} back` : "";
  return `${r.option_label}${asked}${back}`;
}

export function AgentAsked({ requests }: { requests: WhereRequest[] }) {
  if (requests.length === 0) return null;
  return (
    <div
      className="mt-3 flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-[13px] text-fg"
      role="status"
    >
      <Bot className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <span>
        {requests.map((r, i) => (
          <span key={r.option} className="block">
            {i === 0 ? "An agent asked to " : "It also asked to "}
            <strong>{requestWords(r)}</strong>
            {r.reason ? <> because: &ldquo;{r.reason}&rdquo;</> : null}.
          </span>
        ))}
        <span className="block text-muted">
          Nothing changes until a person approves it (choose that option below) or turns it down
          (keep).
        </span>
      </span>
    </div>
  );
}
