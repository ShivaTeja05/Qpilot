/**
 * The Studio session's own hash-chained log (every proposal, acceptance and rejection on the
 * design, the curves, the choices and Prism), shown by stage run: what was proposed, what a
 * person accepted or turned down, with the reasons they gave, and which run made an analysis.
 */
import { ChevronDown, Link2, Unlink } from "lucide-react";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { Badge, Card, CardBody, CardHeader, Hash } from "@/ui";
import type { HistoryView, StudioMilestone } from "./api";
import { ACTION_WORD, ACTOR_LOWER, STAGE_WORD, timeSpan } from "./words";

function Run({
  id,
  milestone,
  open,
  onToggle,
  study,
}: {
  id: string;
  milestone: StudioMilestone;
  open: boolean;
  onToggle: () => void;
  study: string;
}) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (open) ref.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [open]);
  const range =
    milestone.first_seq === milestone.last_seq
      ? `#${milestone.first_seq}`
      : `#${milestone.first_seq}–${milestone.last_seq}`;
  return (
    <li ref={ref} id={`run-${id}`} className="py-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-2 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-focus"
      >
        <ChevronDown
          aria-hidden
          className={cn(
            "mt-0.5 size-4 shrink-0 text-faint transition-transform duration-150",
            !open && "-rotate-90",
          )}
        />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[13px] font-medium text-fg">{milestone.title}</span>
            {milestone.led_to ? (
              <Badge tone="accent">
                {milestone.led_to === study ? "made this analysis" : `made ${milestone.led_to}`}
              </Badge>
            ) : null}
            {!milestone.chain_intact ? (
              <Badge tone="danger" icon={<Unlink />}>
                link broken
              </Badge>
            ) : null}
          </span>
          <span className="block text-[12px] text-faint">
            <span className="font-mono tabular">{range}</span> ·{" "}
            {timeSpan(milestone.at_first, milestone.at_last)}
            {milestone.before ? " · before this analysis" : " · after this analysis was made"}
          </span>
        </span>
      </button>
      {open ? (
        <div className="mt-2 ml-6 space-y-2">
          <ul className="space-y-1.5 text-[13px]">
            {milestone.items.map((item) => (
              <li key={`${item.kind}-${item.action}`}>
                <span className="font-mono text-fg tabular">{count(item.n)}</span>{" "}
                <span className="text-fg">{item.title.toLowerCase()}</span>{" "}
                <span className="text-muted">{ACTION_WORD[item.action] ?? item.action}</span>
                <span className="text-faint">
                  {" "}
                  ·{" "}
                  {Object.entries(item.actors)
                    .map(([who, n]) => `${ACTOR_LOWER[who] ?? who} ×${count(n)}`)
                    .join(", ")}
                </span>
                {item.subjects.length && item.n <= 3 ? (
                  <span className="text-muted"> ({item.subjects.join(", ")})</span>
                ) : null}
                {item.reasons.length ? (
                  <span className="block pl-4 text-[12px] text-muted">
                    {item.reasons.map((r) => `“${r}”`).join(" · ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          <p className="flex items-center gap-1.5 text-[12px] text-faint">
            Chain after this run <Hash value={milestone.head} />
          </p>
        </div>
      ) : null}
    </li>
  );
}

export function StudioLog({
  view,
  open,
  onToggle,
}: {
  view: HistoryView;
  open: string | null;
  onToggle: (id: string) => void;
}) {
  if (!view.studio.length) return null;
  return (
    <Card as="section" aria-labelledby="studio-log-title">
      <CardHeader
        id="studio-log-title"
        title="Studio log"
        hint={`What happened to this file in Studio, by stage: ${view.studio
          .map((m) => STAGE_WORD[m.stage])
          .filter((w, i, a) => a.indexOf(w) === i)
          .join(", ")}. It is hash-chained like the decisions.`}
        actions={
          <Badge
            tone={view.studio_intact ? "ok" : "danger"}
            icon={view.studio_intact ? <Link2 /> : <Unlink />}
          >
            {view.studio_intact ? "Intact" : "Broken"}
          </Badge>
        }
      />
      <CardBody className="pt-0">
        <ol className="divide-y divide-line">
          {view.studio.map((m) => {
            const id = `m${m.first_seq}`;
            return (
              <Run
                key={id}
                id={id}
                milestone={m}
                open={open === id}
                onToggle={() => onToggle(id)}
                study={view.study_id}
              />
            );
          })}
        </ol>
      </CardBody>
    </Card>
  );
}
