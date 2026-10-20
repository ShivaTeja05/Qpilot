/**
 * The parts of the Gene section that qPilot's own analysis fills (no audit needed): the Decision
 * Cards that move this gene, one choice at a time from qPilot's grid, the assay and its wells,
 * and the reference genes' stability.
 */
import { ArrowUpRight } from "lucide-react";
import { Link } from "wouter";
import { GenormBars } from "@/charts";
import type { Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import { Badge, EmptyState, KeyValues, Table, TBody, TD, TH, THead, TR } from "@/ui";
import { count, fixed, fold, range } from "@/lib/format";
import type { AuditLab, GeneAssay, GeneCardRef, GeneImpact, Genorm } from "./api";
import { cardStatusWords, isOpen } from "./cards";
import { Panel } from "./Panel";
import { cardTitle, dimensionName } from "./words";

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
                  <span className="text-[13px] font-medium text-fg">{cardTitle(c)}</span>
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
                <p className="mt-1.5 text-xs text-muted">
                  {cardStatusWords(c)}
                  {moveWords(c.max_delta_log2fc) ? ` · Across its options this choice ${moveWords(c.max_delta_log2fc)}.` : ""}
                </p>
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

/** qPilot's grid, one decision at a time (shown when there is no audit to draw the full plot). */
export function ImpactTable({ impact }: { impact: Record<string, GeneImpact> }) {
  const rows = Object.entries(impact).sort(
    ([, a], [, b]) => Number(b.flips) - Number(a.flips) || b.max_delta_log2fc - a.max_delta_log2fc,
  );
  if (!rows.length) return null;
  return (
    <Table caption="Each decision qPilot varies, changed on its own">
      <THead>
        <TR>
          <TH>Decision</TH>
          <TH>Changes the call alone</TH>
          <TH numeric>Moves the fold by up to</TH>
        </TR>
      </THead>
      <TBody>
        {rows.map(([dim, i]) => (
          <TR key={dim}>
            <TD>{dimensionName(dim)}</TD>
            <TD>{i.flips ? <span className="font-medium text-warn">Yes</span> : <span className="text-muted">No</span>}</TD>
            <TD numeric>{i.max_delta_log2fc ? fold(2 ** Math.abs(i.max_delta_log2fc)) : "no change"}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

/** Efficiency as `1.91 (91 % per cycle)`. */
function efficiencyWords(eff: number | null | undefined): string | null {
  if (eff == null || !Number.isFinite(eff)) return null;
  return `${fixed(eff, 2)} (${fixed((eff - 1) * 100, 0)} % per cycle)`;
}

/** Rows of the audit's lab view that the header already shows. */
const SHOWN_ABOVE = new Set(["p-value, planned analysis", "Samples in each group"]);

export function AssayWells({ efficiency, assay, lab }: { efficiency?: number | null; assay?: GeneAssay | null; lab?: AuditLab | null }) {
  const rows: [string, string][] = [];
  if (lab) {
    for (const r of lab.rows) if (!SHOWN_ABOVE.has(r.label)) rows.push([r.label, r.value]);
  } else {
    const eff = efficiencyWords(assay?.efficiency ?? efficiency);
    if (eff) rows.push(["Amplification efficiency (LinRegPCR, assay mean)", eff]);
    if (assay?.n_wells != null) rows.push(["Wells", count(assay.n_wells)]);
    if (assay?.n_amplified != null) rows.push(["Wells that amplified", count(assay.n_amplified)]);
    if (assay?.n_undetermined != null) rows.push(["Wells that never amplified (undetermined)", count(assay.n_undetermined)]);
    if (assay?.cq_median != null)
      rows.push(["Cq, median [lowest–highest]", `${fixed(assay.cq_median, 1)} ${range(assay.cq_min, assay.cq_max)}`]);
  }
  return (
    <Panel id="gene-assay" title="Assay and wells" hint={lab ? "From the audit's reading of every well of this assay." : undefined}>
      {rows.length ? (
        <KeyValues rows={rows} />
      ) : (
        <EmptyState compact title="No well facts for this gene yet">
          Run the audit to see this assay's Cq spread, late and missing wells and flagged wells.
        </EmptyState>
      )}
    </Panel>
  );
}

export function ReferenceStability({
  gene,
  genorm,
  used,
  lab,
}: {
  gene: string;
  genorm: Genorm | null | undefined;
  used: readonly string[];
  lab?: AuditLab | null;
}) {
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
      {genorm && Object.keys(genorm.M_initial).length ? (
        <>
          <GenormBars m={genorm.M_initial} order={genorm.order} cutoffM={genorm.cutoff_M} used={used} differs={differs} only="m" />
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
        <p className="text-[13px] text-muted">This study does not say which reference genes it uses.</p>
      )}
    </Panel>
  );
}
