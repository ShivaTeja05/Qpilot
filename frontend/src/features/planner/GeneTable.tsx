/**
 * Every compared gene under the plan: its noise, what this study found, the samples it needs,
 * what the plan's size detects and how often qPilot calls it. A row adds or removes the gene
 * from the next experiment.
 */
import { Check } from "lucide-react";
import { useMemo, useState } from "react";
import { count, fixed, fold, percent } from "@/lib/format";
import { Badge, ConclusionTag, DataTable, Input, SegmentedControl, type ColumnDef } from "@/ui";
import type { PlanGene, PlannerGene } from "./api";

interface Row extends PlanGene {
  measured: PlannerGene | undefined;
}

export interface GeneTableProps {
  plan: PlanGene[];
  measured: PlannerGene[];
  nPlan: number;
  target: string;
  onToggle: (gene: string) => void;
}

export function GeneTable({ plan, measured, nPlan, target, onToggle }: GeneTableProps) {
  const [filter, setFilter] = useState("");
  const [show, setShow] = useState<"all" | "chosen" | "short">("all");
  const byGene = useMemo(() => new Map(measured.map((g) => [g.gene, g])), [measured]);
  const rows = useMemo<Row[]>(
    () => plan.map((g) => ({ ...g, measured: byGene.get(g.gene) })),
    [plan, byGene],
  );
  const rowFilter = useMemo(() => {
    if (show === "chosen") return (r: Row) => r.focus;
    if (show === "short") return (r: Row) => !r.detectable;
    return undefined;
  }, [show]);

  const columns = useMemo<ColumnDef<Row, unknown>[]>(
    () => [
      {
        id: "gene",
        header: "Gene",
        accessorKey: "gene",
        meta: { width: "9.5rem" },
        cell: ({ row }) => (
          <span className="flex min-w-0 items-center gap-1.5">
            <span
              aria-hidden
              className={
                row.original.focus
                  ? "inline-flex size-4 shrink-0 items-center justify-center rounded bg-accent text-accent-fg"
                  : "inline-flex size-4 shrink-0 rounded border border-line-strong"
              }
            >
              {row.original.focus ? <Check size={12} /> : null}
            </span>
            <span className="truncate font-medium text-fg">{row.original.gene}</span>
            <span className="sr-only">{row.original.focus ? "(in the next experiment)" : ""}</span>
          </span>
        ),
      },
      {
        id: "sigma",
        header: "σ [95 % CI]",
        accessorKey: "sigma",
        meta: { numeric: true, width: "9.5rem" },
        cell: ({ row }) => {
          const m = row.original.measured;
          return (
            <span title="SD of log2 relative quantity between samples of one group">
              {row.original.sigma.toFixed(2)}{" "}
              <span className="text-muted">
                {m ? `[${fixed(m.sigma_ci[0], 2)}–${fixed(m.sigma_ci[1], 2)}]` : ""}
              </span>
            </span>
          );
        },
      },
      {
        id: "found",
        header: "This study",
        accessorFn: (r) => r.measured?.fc ?? null,
        meta: { numeric: true, width: "8.5rem" },
        cell: ({ row }) => {
          const m = row.original.measured;
          if (!m) return "—";
          return (
            <span className="inline-flex items-center justify-end gap-1.5">
              {fold(m.fc)}
              <ConclusionTag conclusion={m.conclusion} compact />
            </span>
          );
        },
      },
      {
        id: "need",
        header: "n for p < α",
        accessorKey: "n_needed",
        meta: { numeric: true, width: "6.5rem" },
        cell: ({ row }) => count(row.original.n_needed),
      },
      {
        id: "call",
        header: "n for a call",
        accessorFn: (r) =>
          r.n_for_call ?? (r.call_reachable === false ? Number.POSITIVE_INFINITY : null),
        meta: { numeric: true, width: "6.5rem" },
        cell: ({ row }) => {
          const r = row.original;
          if (r.n_for_call != null) return count(r.n_for_call);
          if (r.call_reachable === false)
            return (
              <span className="text-warn" title="No size reaches the power for a call">
                none
              </span>
            );
          return (
            <span className="text-faint" title="Choose the gene to compute it">
              ·
            </span>
          );
        },
      },
      {
        id: "mde",
        header: `Detects at ${count(nPlan)}`,
        accessorKey: "mde_fold",
        meta: { numeric: true, width: "7.5rem" },
        cell: ({ row }) => (
          <span className={row.original.detectable ? "" : "text-warn"}>
            ≥ {fold(row.original.mde_fold)}
          </span>
        ),
      },
      {
        id: "called",
        header: `Called at ${count(nPlan)}`,
        accessorKey: "p_called",
        meta: { numeric: true, width: "7rem" },
        cell: ({ row }) => percent(row.original.p_called),
      },
      {
        id: "now",
        header: "Detects now",
        accessorKey: "current_mde_fold",
        meta: { numeric: true, width: "7rem" },
        cell: ({ row }) =>
          row.original.current_mde_fold > 0 ? `≥ ${fold(row.original.current_mde_fold)}` : "—",
      },
      {
        id: "eff",
        header: "Efficiency",
        accessorFn: (r) => r.measured?.efficiency ?? null,
        meta: { numeric: true, width: "7rem" },
        cell: ({ row }) => {
          const m = row.original.measured;
          if (m?.efficiency == null) return "—";
          return (
            <span className="inline-flex items-center justify-end gap-1">
              {m.efficiency_outside ? (
                <Badge tone="warn" title="Outside 90–110 %: check with a standard curve">
                  check
                </Badge>
              ) : null}
              {m.efficiency.toFixed(2)}
            </span>
          );
        },
      },
    ],
    [nPlan],
  );

  const short = rows.filter((r) => !r.detectable).length;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <SegmentedControl
          label="Which genes"
          size="sm"
          value={show}
          onValueChange={setShow}
          options={[
            { value: "all", label: `All ${count(rows.length)}` },
            { value: "chosen", label: `Chosen ${count(rows.filter((r) => r.focus).length)}` },
            { value: "short", label: `Short of ${target} ${count(short)}` },
          ]}
        />
        <Input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Find a gene"
          aria-label="Find a gene"
          className="h-8 w-44"
        />
        <p className="ml-auto text-[12px] text-muted">Click a row to add or remove the gene.</p>
      </div>
      <DataTable
        data={rows}
        columns={columns}
        getRowId={(r) => r.gene}
        label={`Every compared gene under the plan (${count(nPlan)} per group)`}
        height={420}
        initialSorting={[{ id: "sigma", desc: true }]}
        globalFilter={filter || undefined}
        rowFilter={rowFilter}
        onRowClick={(r) => onToggle(r.gene)}
        empty="No gene matches. Clear the filter."
      />
      <p className="mt-2 text-[12px] leading-relaxed text-muted">
        “n for p &lt; α” is the normal-approximation size (as{" "}
        <code className="font-mono">qpilot plan</code> gives it); “n for a call” is the simulated
        size at which qPilot’s rule (significant and at least the rule’s fold) calls the change with
        the chosen power, computed for the chosen genes. “Detects” is the smallest change reaching p
        &lt; α with that power; “now” uses this study’s own group sizes. σ’s range is its 95 %
        chi-square interval.
      </p>
    </div>
  );
}
