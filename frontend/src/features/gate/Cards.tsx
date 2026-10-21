/**
 * The `gate.rule` Decision Cards, read-only, in the Decision Cards' visual language: the question,
 * what it changes, each option with its per-gene calls (the calls that change in bold), and how it
 * was worked out. Nothing is decided here: wells are left out where wells are excluded (Curves in
 * a Studio session), and for a study analysed outside Studio the wells are followed in Trace.
 */
import { CircleCheck, TriangleAlert } from "lucide-react";
import { Link } from "wouter";
import type { Schemas } from "@/api/client";
import { CALLS, Glyph, type CallKey } from "@/charts";
import { FactText } from "@/features/results/FactText";
import { cn } from "@/lib/cn";
import { fold } from "@/lib/format";
import { sectionPath } from "@/shell/sections";
import { Badge, Card } from "@/ui";
import type { Evaluation, GateCard, GateView } from "./api";
import { VerdictChip } from "./Pieces";
import { whereText } from "./words";

type Workspace = Schemas["WorkspaceView"];

const STATUS: Record<string, { label: string; tone: "accent" | "ok" | "warn" | "neutral" }> = {
  open: { label: "A person decides", tone: "accent" },
  decided: { label: "Decided", tone: "ok" },
  auto_decided: { label: "Decided automatically", tone: "neutral" },
  pending_human: { label: "Agent request", tone: "warn" },
};

function callOf(conclusion: string): CallKey {
  return (conclusion as CallKey) in CALLS ? (conclusion as CallKey) : "none";
}

export function GateCardView({
  card: view,
  evaluation,
  workspace,
  excludeIn,
}: {
  card: GateCard;
  evaluation: Evaluation | undefined;
  workspace: Workspace;
  excludeIn: GateView["exclude_in"];
}) {
  const card = view.card;
  const status = STATUS[card.status] ?? STATUS.open!;
  const flips = Boolean(card.impact.flips);
  const titleId = `gate-card-${card.id}`;
  return (
    <Card
      as="article"
      aria-labelledby={titleId}
      className={cn(card.status === "open" && flips && "border-accent/50")}
    >
      <div className="flex items-start gap-3 p-4 pb-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={titleId} className="text-[15px] font-semibold tracking-tight text-fg">
              {view.title}
            </h3>
            <Badge tone={status.tone}>{status.label}</Badge>
          </div>
          {evaluation && (
            <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
              <VerdictChip verdict={evaluation.verdict} />
              <span>
                <span className="font-mono text-[12px]">{evaluation.rule_id}</span>{" "}
                {evaluation.title} · {whereText(evaluation)}
              </span>
            </p>
          )}
          <p
            className={cn(
              "mt-1 flex items-start gap-1.5 text-[13px]",
              flips ? "text-fg" : "text-muted",
            )}
          >
            {flips ? (
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
            ) : (
              <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden />
            )}
            <FactText text={view.impact} />
          </p>
          <p className="mt-1 text-[13px] text-muted">{view.status_line}</p>
        </div>
      </div>
      <div className="space-y-3 px-4 pb-4">
        <div>
          <h4 className="mb-1.5 text-[12px] font-medium text-muted">
            Options{view.genes.length ? ` · what each gives for ${view.genes.join(", ")}` : ""}
          </h4>
          <ul className="space-y-1.5">
            {view.options.map((o) => {
              const missing = view.genes.filter((g) => !o.effects.some((e) => e.gene === g));
              return (
                <li
                  key={o.id}
                  className={cn(
                    "flex flex-col gap-1.5 rounded-lg border p-2.5",
                    o.recommended ? "border-accent bg-accent-soft/40" : "border-line",
                  )}
                >
                  <span className="flex items-start gap-2">
                    <span className="min-w-0 flex-1 text-[13px] text-fg">{o.label}</span>
                    <span className="flex shrink-0 flex-wrap justify-end gap-1">
                      {o.recommended && <Badge tone="accent">Recommended</Badge>}
                      {o.chosen && <Badge tone="ok">In use</Badge>}
                    </span>
                  </span>
                  {(o.effects.length > 0 || missing.length > 0) && (
                    <span className="flex flex-wrap gap-x-3 gap-y-1">
                      {o.effects.map((e) => {
                        const c = callOf(e.conclusion);
                        return (
                          <span
                            key={e.gene}
                            className={cn(
                              "tabular inline-flex items-center gap-1 text-[12px]",
                              e.changes_call ? "font-semibold text-fg" : "text-muted",
                            )}
                          >
                            <span>{e.gene}</span>
                            <span>{fold(e.fc)}</span>
                            <Glyph mark={CALLS[c]} size={9} />
                            <span className={e.changes_call ? "" : "sr-only"}>
                              {CALLS[c].short}
                            </span>
                            {e.changes_call && (
                              <span className="font-normal text-warn">(changes)</span>
                            )}
                          </span>
                        );
                      })}
                      {missing.map((g) => (
                        <span
                          key={g}
                          className="inline-flex items-center gap-1 text-[12px] font-semibold text-fg"
                        >
                          <span>{g}</span>
                          <span>no call: it can no longer be compared</span>
                          <span className="font-normal text-warn">(changes)</span>
                        </span>
                      ))}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
        <details className="rounded-lg bg-sunken/60 px-3 py-2 text-[13px]">
          <summary className="cursor-pointer font-medium text-muted select-none hover:text-fg">
            How this was worked out
          </summary>
          <p className="mt-1.5 leading-relaxed text-muted">
            <FactText text={view.explanation} />
          </p>
        </details>
        <p className="text-[13px]">
          {excludeIn === "curves" ? (
            <Link
              href={sectionPath(workspace, "curves")}
              className="font-medium text-accent hover:underline"
            >
              Leave wells out in Curves
            </Link>
          ) : (
            <Link
              href={sectionPath(workspace, "trace")}
              className="font-medium text-accent hover:underline"
            >
              Follow the calls down to their wells in Trace
            </Link>
          )}
        </p>
      </div>
    </Card>
  );
}

export function GateCards({ view, workspace }: { view: GateView; workspace: Workspace }) {
  const byId = new Map(view.evaluations.map((e) => [e.id, e]));
  const evalOf = (card: GateCard) =>
    byId.get(view.consequences.find((c) => c.card_id === card.card.id)?.id ?? "");
  return (
    <section aria-labelledby="gate-cards-title">
      <div className="mb-3">
        <h2 id="gate-cards-title" className="text-base font-semibold tracking-tight text-fg">
          Decision Cards from the controls
        </h2>
        <p className="mt-0.5 text-[13px] text-muted">
          A card exists only when leaving a rule&rsquo;s wells out can change a conclusion. Read
          here; nothing is decided on this page.
        </p>
      </div>
      {view.cards.length === 0 ? (
        <Card className="p-4 text-[13px] text-muted">
          No control finding can change a conclusion, so there is nothing to decide.
        </Card>
      ) : (
        <ol className="space-y-3">
          {view.cards.map((c) => (
            <li key={c.card.id}>
              <GateCardView
                card={c}
                evaluation={evalOf(c)}
                workspace={workspace}
                excludeIn={view.exclude_in}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
