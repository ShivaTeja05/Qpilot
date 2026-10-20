/**
 * The parts of the Gene section that qPilot's own analysis fills (no audit needed): the Decision
 * Cards that move this gene, the assay and its wells, and the reference genes' stability.
 */
import { ArrowUpRight } from "lucide-react";
import { Link } from "wouter";
import { GenormBars } from "@/charts";
import { GenePrismFigure, useHasPrismFigure } from "@/features/prism/GeneFigure";
import type { Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import { Badge, EmptyState } from "@/ui";
import { count, fixed, fold } from "@/lib/format";
import { cardStatusWords, isOpen } from "./adapters";
import type { AuditLab, GeneCardRef, GenormView } from "./api";
import { FactRows, Panel } from "./Panel";

type Workspace = Pick<Schemas["WorkspaceView"], "key" | "kind">;

/** The path that opens one Decision Card in Results. */
export function cardPath(workspace: Workspace, cardId: string): string {
  return sectionPath(workspace, "results", "card", cardId);
}

/** How far a choice moves the fold: `up to 1.35×` (a factor, either way). */
function moveWords(maxDeltaLog2: number | null | undefined): string | null {
  if (maxDeltaLog2 == null || !Number.isFinite(maxDeltaLog2)) return null;
  if (maxDeltaLog2 === 0) return "does not move it";
  return `moves it by up to ${fold(2 ** Math.abs(maxDeltaLog2))}`;
}

export function GeneCards({ workspace, gene, cards, loading }: { workspace: Workspace; gene: string; cards: GeneCardRef[]; loading?: boolean }) {
  const flipping = cards.filter((c) => c.flips).length;
  return (
    <Panel
      id="gene-cards"
      title="Decision Cards that affect this gene"
      hint={
        cards.length
          ? flipping
            ? `${count(flipping)} of these choices can change ${gene}'s call on its own.`
            : `None of these choices changes ${gene}'s call on its own; they move its fold.`
          : undefined
      }
    >
      {loading ? (
        <p className="text-[13px] text-muted">Reading the cards…</p>
      ) : cards.length ? (
        <ul className="space-y-2">
          {cards.map((c) => (
            <li key={c.id}>
              <Link
                href={cardPath(workspace, c.id)}
                className="group block rounded-lg border border-line bg-surface px-3 py-2.5 transition-colors hover:border-line-strong hover:bg-surface-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[13px] font-medium text-fg">{c.title}</span>
                  <ArrowUpRight aria-hidden className="mt-0.5 size-3.5 shrink-0 text-faint group-hover:text-fg" />
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {c.flips ? (
                    <Badge tone="warn">Can change the call alone</Badge>
                  ) : (
                    <Badge tone="neutral">Does not change the call alone</Badge>
                  )}
                  {isOpen(c) ? <Badge tone="accent">Open</Badge> : null}
                </div>
                <p className="mt-1.5 text-xs text-muted">{cardStatusWords(c)}</p>
                {moveWords(c.maxDeltaLog2) ? (
                  <p className="mt-1 text-xs text-fg">Across its options this choice {moveWords(c.maxDeltaLog2)}.</p>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">No Decision Card moves {gene}: the study's choices leave this gene where it is.</p>
      )}
    </Panel>
  );
}

/** Efficiency as `1.91 (91 % per cycle)`. */
function efficiencyWords(eff: number | null | undefined): string | null {
  if (eff == null || !Number.isFinite(eff)) return null;
  return `${fixed(eff, 2)} (${fixed((eff - 1) * 100, 0)} % per cycle)`;
}

/** Rows of the audit's lab view that the header already shows. */
const SHOWN_ABOVE = new Set(["p-value, planned analysis", "Samples in each group"]);

export function AssayWells({ efficiency, lab }: { efficiency?: number | null; lab?: AuditLab | null }) {
  const rows: [string, string][] = [];
  if (lab) {
    for (const r of lab.rows) if (!SHOWN_ABOVE.has(r.label)) rows.push([r.label, r.value]);
  } else {
    const eff = efficiencyWords(efficiency);
    if (eff) rows.push(["Efficiency, LinRegPCR assay mean", eff]);
  }
  return (
    <Panel id="gene-assay" title="Assay and wells" hint={lab ? "From the audit's reading of every well of this assay." : undefined}>
      {rows.length ? <FactRows rows={rows} /> : null}
      {!lab ? (
        <p className={rows.length ? "mt-3 text-xs text-muted" : "text-[13px] text-muted"}>
          The audit adds this assay's Cq spread, late and never-amplified wells, and flagged wells.
        </p>
      ) : null}
    </Panel>
  );
}

export function ReferenceStability({
  gene,
  genorm,
  lab,
}: {
  gene: string;
  genorm: GenormView | null | undefined;
  lab?: AuditLab | null;
}) {
  const used = genorm?.used ?? [];
  const differs = new Set((lab?.references ?? []).filter((r) => r.differs).map((r) => r.gene));
  const isRef = used.includes(gene);
  return (
    <Panel
      id="gene-refs"
      title="Reference genes"
      hint={
        isRef
          ? `${gene} is itself a reference gene: other genes are normalised to it.`
          : used.length
            ? `${gene} is normalised to ${used.length === 1 ? used[0] : `the mean of ${count(used.length)} reference genes`}.`
            : undefined
      }
    >
      {genorm && Object.keys(genorm.m).length ? (
        <>
          {/* One chart only: keep it full width (GenormBars lays M and V side by side from lg). */}
          <div className="lg:[&>div]:grid-cols-1">
            <GenormBars m={genorm.m} order={genorm.order} cutoffM={genorm.cutoff_m} used={used} differs={differs} only="m" />
          </div>
          {differs.size ? (
            <p className="mt-3 text-xs text-muted">
              Marked “differs between groups”: the audit found this reference gene's level differs between the
              groups, which can shift every gene normalised to it.
            </p>
          ) : null}
        </>
      ) : used.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {used.map((g) => (
            <li key={g}>
              <Badge>{g}</Badge>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState compact title="No reference genes named">
          This study does not say which reference genes it normalises to.
        </EmptyState>
      )}
    </Panel>
  );
}

/**
 * The gene's Prism figure (prism's), when the session's Prism project has a table for it: every
 * biological unit, the group means and their 95 % CI, as the Prism bundle will hold them. Mount it
 * for Studio sessions only (the preview is a session's).
 */
export function PrismCard({ workspace, gene }: { workspace: Workspace; gene: string }) {
  const has = useHasPrismFigure(workspace.key, gene);
  if (!has) return null;
  return (
    <Panel
      id="gene-prism"
      title="Prism figure"
      hint="Every biological unit, the group means and their 95 % CI, as the Prism bundle will hold them."
      actions={
        <Link href={sectionPath(workspace, "prism")} className="inline-flex items-center gap-1 text-xs text-accent underline-offset-4 hover:underline">
          Open Prism
          <ArrowUpRight className="size-3" aria-hidden />
        </Link>
      }
    >
      <GenePrismFigure sid={workspace.key} gene={gene} />
    </Panel>
  );
}
