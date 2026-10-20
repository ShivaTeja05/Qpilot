/** All genes: a virtualised, sortable table with filters that also dim the map. */
import { Search } from "lucide-react";
import { useMemo } from "react";
import { CALLS, CALL_ORDER, LEVEL_ORDER, VERDICTS, VERDICT_ORDER } from "@/charts";
import { ci, count, fold, pValue, percent } from "@/lib/format";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  ConclusionTag,
  DataTable,
  Input,
  LevelTag,
  SegmentedControl,
  Select,
  Switch,
  VerdictTag,
  type ColumnDef,
} from "@/ui";
import type { GeneRow } from "./api";
import { gridSize } from "./MapPanel";

export interface GeneFilter {
  text: string;
  call: "all" | "up" | "down" | "none";
  level: string;
  verdict: string;
  flips: boolean;
}

export const NO_FILTER: GeneFilter = {
  text: "",
  call: "all",
  level: "all",
  verdict: "all",
  flips: false,
};

export function isFiltered(f: GeneFilter): boolean {
  return Boolean(f.text) || f.call !== "all" || f.level !== "all" || f.verdict !== "all" || f.flips;
}

export function matches(g: GeneRow, f: GeneFilter): boolean {
  if (f.text && !g.gene.toLowerCase().includes(f.text.toLowerCase())) return false;
  if (f.call !== "all" && g.conclusion !== f.call) return false;
  if (f.level !== "all" && g.level !== f.level) return false;
  if (f.verdict !== "all" && g.verdict !== f.verdict) return false;
  if (f.flips && g.flips_by.length === 0) return false;
  return true;
}

function HoldsCell({ holds }: { holds: number | null | undefined }) {
  if (holds == null) return <span className="text-faint">—</span>;
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span
        className="hidden h-1.5 w-12 overflow-hidden rounded-full bg-sunken sm:inline-block"
        aria-hidden
      >
        <span
          className="block h-full rounded-full bg-accent"
          style={{ width: `${Math.round(holds * 100)}%` }}
        />
      </span>
      <span>{percent(holds)}</span>
    </span>
  );
}

export function GenesPanel({
  genes,
  filter,
  onFilter,
  dimLabel,
  selected,
  onOpen,
}: {
  genes: GeneRow[];
  filter: GeneFilter;
  onFilter: (f: GeneFilter) => void;
  dimLabel: (dim: string) => string;
  selected: string | null;
  onOpen: (gene: string) => void;
}) {
  const audited = genes.some((g) => g.verdict);
  const cells = gridSize(genes);
  const shown = genes.filter((g) => matches(g, filter)).length;
  const columns = useMemo<ColumnDef<GeneRow, unknown>[]>(
    () => [
      {
        id: "gene",
        header: "Gene",
        accessorKey: "gene",
        meta: { width: "8.5rem" },
        cell: ({ row }) => (
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate font-medium text-fg">{row.original.gene}</span>
            {row.original.headline && (
              <Badge tone="accent" className="shrink-0">
                headline
              </Badge>
            )}
          </span>
        ),
      },
      {
        id: "call",
        header: "Call",
        accessorFn: (g) => CALL_ORDER.indexOf(g.conclusion),
        meta: { width: "6rem" },
        cell: ({ row }) => <ConclusionTag conclusion={row.original.conclusion} />,
      },
      {
        id: "fold",
        header: "Fold",
        accessorFn: (g) => Math.log2(g.fc),
        meta: { numeric: true, width: "4.75rem" },
        cell: ({ row }) => fold(row.original.fc),
      },
      {
        id: "holds",
        header: cells ? `Holds (of ${count(cells)})` : "Holds",
        accessorFn: (g) => g.holds ?? -1,
        meta: { numeric: true, width: "7.5rem" },
        cell: ({ row }) => <HoldsCell holds={row.original.holds} />,
      },
      {
        id: "level",
        header: "Confidence",
        accessorFn: (g) =>
          g.level ? LEVEL_ORDER.indexOf(g.level as (typeof LEVEL_ORDER)[number]) : 9,
        meta: { width: "8rem" },
        cell: ({ row }) => <LevelTag level={row.original.level} />,
      },
      ...(audited
        ? ([
            {
              id: "verdict",
              header: "Audit",
              accessorFn: (g) =>
                g.verdict ? VERDICT_ORDER.indexOf(g.verdict as (typeof VERDICT_ORDER)[number]) : 9,
              meta: { width: "10.5rem" },
              cell: ({ row }) =>
                row.original.verdict ? <VerdictTag verdict={row.original.verdict} /> : null,
            },
          ] satisfies ColumnDef<GeneRow, unknown>[])
        : []),
      {
        id: "ci",
        header: "95 % CI",
        accessorFn: (g) => Math.log2(g.ci[0] ?? Number.NaN),
        meta: { numeric: true, width: "8.5rem" },
        cell: ({ row }) => ci(row.original.ci[0], row.original.ci[1]),
      },
      {
        id: "p",
        header: "p",
        accessorKey: "p",
        meta: { numeric: true, width: "5.5rem" },
        cell: ({ row }) => pValue(row.original.p),
      },
      {
        id: "why",
        header: "Why this level",
        accessorFn: (g) => g.reasons.join(" "),
        enableSorting: false,
        meta: { width: "22rem" },
        cell: ({ row }) => {
          const g = row.original;
          const flips = g.flips_by.map(dimLabel);
          const now = g.at_your_choices?.differs
            ? `With your choices: ${fold(g.at_your_choices.fc)}, ${g.at_your_choices.conclusion === "none" ? "no call" : g.at_your_choices.conclusion}.`
            : null;
          const text = [
            now,
            ...g.reasons,
            flips.length ? `A single choice can flip it: ${flips.join(", ").toLowerCase()}.` : null,
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <span className="block truncate text-[12px] text-muted" title={text}>
              {text || "—"}
            </span>
          );
        },
      },
    ],
    [audited, dimLabel, cells],
  );

  const set = (patch: Partial<GeneFilter>) => onFilter({ ...filter, ...patch });
  const callCount = (c: string) => genes.filter((g) => g.conclusion === c).length;

  return (
    <Card as="section" aria-labelledby="genes-title">
      <CardHeader
        id="genes-title"
        title="All genes"
        hint={`${count(shown)} of ${count(genes.length)} shown. Filters here also dim the map. Click a gene to open it.`}
      />
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:w-52">
            <Search
              className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint"
              aria-hidden
            />
            <Input
              type="search"
              aria-label="Find a gene"
              placeholder="Find a gene"
              value={filter.text}
              onChange={(e) => set({ text: e.target.value })}
              className="h-8 pl-8"
            />
          </div>
          <SegmentedControl
            label="Call"
            size="sm"
            value={filter.call}
            onValueChange={(v) => set({ call: v })}
            options={[
              { value: "all", label: "All" },
              ...CALL_ORDER.map((c) => ({
                value: c,
                label: `${CALLS[c].arrow} ${CALLS[c].label} ${count(callCount(c))}`,
              })),
            ]}
          />
          <Select
            label="Confidence"
            size="sm"
            value={filter.level}
            onValueChange={(v) => set({ level: v })}
            options={[
              { value: "all", label: "Any confidence" },
              ...LEVEL_ORDER.map((l) => ({ value: l, label: l })),
            ]}
          />
          {audited && (
            <Select
              label="Audit verdict"
              size="sm"
              value={filter.verdict}
              onValueChange={(v) => set({ verdict: v })}
              options={[
                { value: "all", label: "Any verdict" },
                ...VERDICT_ORDER.map((v) => ({ value: v, label: VERDICTS[v].label })),
              ]}
            />
          )}
          <Switch
            checked={filter.flips}
            onCheckedChange={(v) => set({ flips: v })}
            label="Only genes one choice can flip"
          />
        </div>
        <DataTable
          data={genes}
          columns={columns}
          getRowId={(g) => g.gene}
          label={`All genes: call, fold change with its 95 % confidence interval, p, the share ${cells ? `of the ${count(cells)} analyses` : "of the analyses"} qPilot checks that give the same call, and the confidence level`}
          rowFilter={(g) => matches(g, filter)}
          initialSorting={[{ id: "holds", desc: false }]}
          onRowClick={(g) => onOpen(g.gene)}
          selectedId={selected}
          height={520}
          empty="No gene matches these filters. Clear a filter to see more."
        />
      </CardBody>
    </Card>
  );
}
