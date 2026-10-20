/**
 * The study's trace (`…/trace`): which calls hang on few samples (the fewest that change each
 * call, checked exhaustively for one and two), the samples behind the most calls with their
 * plates and unusual wells, the control-gene wells that disagree with their sample's others,
 * and the samples in no comparison with the empty well behind each. Every row opens a trace.
 */
import { useMemo } from "react";
import { Link, useLocation } from "wouter";
import type { Schemas } from "@/api/client";
import { sectionPath } from "@/shell/sections";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  ConclusionTag,
  DataTable,
  NumberCell,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  type ColumnDef,
} from "@/ui";
import { count, fixed, fold, pValue } from "@/lib/format";
import { asConclusion } from "@/lib/vocab";
import type { GeneRow, Missing, Overview, Suspect, TraceScope } from "./api";
import { useTraceStudy } from "./api";
import { FactText } from "./FactText";
import { TraceWaiting } from "./GeneTrace";
import { CALL_WORD, SAMPLE_FLAG, address, effectPercent } from "./words";

type Workspace = Schemas["WorkspaceView"];

const MISSING_WORDS: Record<string, string> = {
  empty_reference: "a control-gene well has no value",
  empty_marker: "the marker gene's well has no value",
  excluded: "a person excluded its control-gene wells",
  not_in_groups: "in neither group",
  empty_target: "no value for the gene",
};

function kWords(g: Pick<GeneRow, "flip_k" | "flip_exact">, limit: number): string {
  if (g.flip_k == null) return `more than ${count(limit)}`;
  return `${g.flip_exact ? "" : "≤ "}${count(g.flip_k)}`;
}

export function OverviewPage({ workspace, scope }: { workspace: Workspace; scope: TraceScope }) {
  const q = useTraceStudy(scope);
  if (!q.data) {
    return (
      <>
        <Header />
        {q.error ? (
          <TraceWaiting error={q.error} onRetry={() => void q.refetch()} what="the study" />
        ) : (
          <div className="flex flex-col gap-4" role="status" aria-label="Tracing the study">
            <Skeleton className="h-4 w-[32rem] max-w-full" />
            <Skeleton className="h-64 w-full rounded-xl" />
          </div>
        )}
      </>
    );
  }
  const view = q.data;
  return (
    <>
      <Header />
      <p className="mb-5 max-w-4xl text-[14px] leading-relaxed text-fg">
        <FactText text={view.texts.summary} />
      </p>
      <Ladder trace={view.trace} />
      <div className="mt-5 grid gap-5 2xl:grid-cols-2">
        <FragileGenes workspace={workspace} trace={view.trace} />
        <Suspects workspace={workspace} trace={view.trace} />
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <OffWells workspace={workspace} trace={view.trace} />
        <LeftOut trace={view.trace} />
      </div>
      <Card as="section" aria-labelledby="trace-o-checked" className="mt-5">
        <CardHeader id="trace-o-checked" level={3} title="Checked, and what the data cannot show" />
        <CardBody className="grid gap-4 md:grid-cols-2">
          <ul className="flex list-disc flex-col gap-1 pl-4 text-[13px] text-fg">
            {view.trace.checked.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-[13px] text-fg">
            {view.trace.cannot_show.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </>
  );
}

function Header() {
  return (
    <header className="mb-4">
      <div className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">Trace</div>
      <h1 className="text-2xl font-semibold tracking-tight text-fg">What each result stands on</h1>
      <p className="mt-1 max-w-3xl text-sm text-muted">
        Follow any call down to the samples, wells and plates behind it. Every number is the
        engine&rsquo;s, recomputed exactly with samples set aside; nothing here changes your
        analysis.
      </p>
    </header>
  );
}

/** How many genes need 1, 2, 3–5, 6–20 or more samples set aside to change their call. */
function Ladder({ trace }: { trace: Overview }) {
  const limit = trace.thresholds.flip_search_limit ?? 20;
  const buckets = [
    { label: "1 sample", test: (k: number | null) => k === 1 },
    { label: "2 samples", test: (k: number | null) => k === 2 },
    { label: "3–5", test: (k: number | null) => k != null && k >= 3 && k <= 5 },
    { label: `6–${count(limit)}`, test: (k: number | null) => k != null && k >= 6 },
    { label: `more than ${count(limit)}`, test: (k: number | null) => k == null },
  ].map((b) => ({ ...b, n: trace.genes.filter((g) => b.test(g.flip_k ?? null)).length }));
  const total = Math.max(1, trace.genes.length);
  return (
    <figure
      className="m-0"
      aria-label={`How many samples it takes to change each call: ${buckets.map((b) => `${b.label}: ${count(b.n)} genes`).join("; ")}.`}
    >
      <figcaption className="mb-2 text-xs font-medium text-muted">
        How many samples it takes to change each of the {count(trace.genes.length)} calls
      </figcaption>
      <div className="flex h-9 overflow-hidden rounded-lg border border-line" aria-hidden="true">
        {buckets.map((b, i) =>
          b.n ? (
            <div
              key={b.label}
              className="flex items-center justify-center text-[12px] font-medium tabular"
              style={{
                width: `${(100 * b.n) / total}%`,
                background:
                  i === 0 ? "var(--warn-soft)" : i === 1 ? "var(--surface-2)" : "var(--surface)",
                borderRight: "1px solid var(--line)",
                color: "var(--text)",
              }}
              title={`${b.label}: ${count(b.n)} genes`}
            >
              {b.n}
            </div>
          ) : null,
        )}
      </div>
      <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
        {buckets.map((b) => (
          <li key={b.label}>
            <span className="tabular font-medium text-fg">{count(b.n)}</span>{" "}
            {b.n === 1 ? "gene" : "genes"}: {b.label}
          </li>
        ))}
      </ul>
    </figure>
  );
}

function FragileGenes({ workspace, trace }: { workspace: Workspace; trace: Overview }) {
  const [, navigate] = useLocation();
  const limit = trace.thresholds.flip_search_limit ?? 20;
  const columns = useMemo<ColumnDef<GeneRow, unknown>[]>(
    () => [
      { id: "rank", header: "#", accessorKey: "rank", meta: { numeric: true, width: "3.5rem" } },
      {
        id: "gene",
        header: "Gene",
        accessorKey: "gene",
        meta: { width: "8rem" },
        cell: ({ row }) => <span className="font-medium text-fg">{row.original.gene}</span>,
      },
      {
        id: "call",
        header: "Call",
        accessorKey: "conclusion",
        meta: { width: "6.5rem" },
        cell: ({ row }) => <ConclusionTag conclusion={asConclusion(row.original.conclusion)} />,
      },
      {
        id: "fold",
        header: "Fold",
        accessorKey: "fc",
        meta: { numeric: true, width: "5rem" },
        cell: ({ row }) => fold(row.original.fc),
      },
      {
        id: "p",
        header: "p",
        accessorKey: "p",
        meta: { numeric: true, width: "5rem" },
        cell: ({ row }) => pValue(row.original.p),
      },
      {
        id: "k",
        header: "Samples that change it",
        accessorFn: (g) => g.flip_k ?? 1e9,
        meta: { numeric: true, width: "9.5rem" },
        cell: ({ row }) => kWords(row.original, limit),
      },
      {
        id: "single",
        header: "Alone",
        accessorKey: "n_flip_single",
        meta: { numeric: true, width: "4.5rem" },
      },
      {
        id: "top",
        header: "Moves it most",
        accessorKey: "top_unit",
        meta: { width: "8rem" },
        cell: ({ row }) =>
          row.original.top_unit ? (
            <span className="text-muted">
              {row.original.top_unit}{" "}
              <span className="tabular">
                {row.original.top_d_log2fc != null ? effectPercent(row.original.top_d_log2fc) : ""}
              </span>
            </span>
          ) : (
            "—"
          ),
      },
    ],
    [limit],
  );
  return (
    <Card as="section" aria-labelledby="trace-o-genes">
      <CardHeader
        id="trace-o-genes"
        title="Calls that hang on few samples"
        hint="The fewest samples whose removal together changes each call (one and two checked exhaustively). Click a gene to trace it."
      />
      <CardBody>
        <DataTable
          data={trace.genes}
          columns={columns}
          getRowId={(g) => g.gene}
          label="Genes by how few samples change their call"
          height={420}
          onRowClick={(g) => navigate(sectionPath(workspace, "trace", g.gene))}
          empty="No compared gene to trace."
        />
      </CardBody>
    </Card>
  );
}

function Suspects({ workspace, trace }: { workspace: Workspace; trace: Overview }) {
  const shown = trace.suspects.slice(0, 16);
  return (
    <Card as="section" aria-labelledby="trace-o-suspects">
      <CardHeader
        id="trace-o-suspects"
        title="Samples behind the most calls"
        hint={`Samples whose removal alone changes a call, or whose wells show something unusual (${count(trace.suspects.length)}).`}
      />
      <CardBody>
        {shown.length ? (
          <ol className="flex flex-col divide-y divide-line">
            {shown.map((s) => (
              <SuspectRow key={s.unit} workspace={workspace} s={s} />
            ))}
          </ol>
        ) : (
          <p className="text-[13px] text-muted">
            No single sample changes a call, and no sample&rsquo;s wells stand out.
          </p>
        )}
      </CardBody>
    </Card>
  );
}

const callList = (changes: readonly { gene: string; call_before: string; call_after: string }[]) =>
  changes
    .map((c) => `${c.gene} (${CALL_WORD[c.call_before]} → ${CALL_WORD[c.call_after]})`)
    .join(", ");

/** What reading the sample's odd control-gene well as expected does, in words. */
export function readWords(s: Suspect): string {
  const after = s.read_as_expected ?? [];
  const what = after.length
    ? `${callList(after)} ${after.length === 1 ? "changes" : "change"}`
    : "no call changes";
  if (!s.read_regrouped) return `Read as its other control genes predict, ${what}.`;
  const held = s.read_groups_held ?? [];
  return (
    `Read as its other control genes predict, the groups change (${s.read_regrouped}) and ${what}; ` +
    `with every sample kept in its group, ${held.length ? `${callList(held)} ${held.length === 1 ? "changes" : "change"}` : "no call changes"}.`
  );
}

function SuspectRow({ workspace, s }: { workspace: Workspace; s: Suspect }) {
  const flags = s.flags.map((f) => SAMPLE_FLAG[f]?.word ?? f);
  return (
    <li className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-fg">Sample {s.unit}</span>
        {s.group ? <span className="text-[12px] text-muted">{s.group}</span> : null}
        {flags.map((f) => (
          <Badge key={f} tone="warn">
            {f}
          </Badge>
        ))}
      </div>
      <p className="text-[13px] text-fg">
        {s.n_genes_flipped ? (
          <>
            Alone it changes {count(s.n_genes_flipped)} {s.n_genes_flipped === 1 ? "call" : "calls"}
            :{" "}
            {s.genes_flipped.map((g, i) => (
              <span key={g}>
                {i ? ", " : ""}
                <Link
                  href={sectionPath(workspace, "trace", g)}
                  className="font-medium text-accent underline-offset-4 hover:underline"
                >
                  {g}
                </Link>
              </span>
            ))}
            .
          </>
        ) : (
          <>
            Alone it changes no call (it moves {s.max_gene} most,{" "}
            {effectPercent(s.max_abs_d_log2fc)} at most).
          </>
        )}
        {s.read_as_expected ? <> {readWords(s)}</> : null}
      </p>
      {s.wells.length ? (
        <p className="text-[12px] text-muted">
          Look at: {s.wells.map((w) => `${w.gene} ${address(w)}`).join("; ")}
        </p>
      ) : null}
    </li>
  );
}

function OffWells({ workspace, trace }: { workspace: Workspace; trace: Overview }) {
  const rows = trace.suspects.flatMap((s) =>
    s.wells.filter((w) => w.flags.includes("reference_pull")).map((w) => ({ s, w })),
  );
  return (
    <Card as="section" aria-labelledby="trace-o-off">
      <CardHeader
        id="trace-o-off"
        title="Control-gene wells that disagree"
        hint="Each reads far from what its sample's other control genes predict, so it moves every value of that sample."
      />
      <CardBody>
        {rows.length ? (
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>Sample</TH>
                  <TH>Control gene</TH>
                  <TH>Plate · well</TH>
                  <TH numeric>Cq</TH>
                  <TH numeric>Plate median</TH>
                  <TH numeric>Every value</TH>
                  <TH>Calls it changes, read as expected</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map(({ s, w }) => (
                  <TR key={w.key}>
                    <TD>{s.unit}</TD>
                    <TD>{w.gene}</TD>
                    <TD>{address(w)}</TD>
                    <TD numeric>
                      <NumberCell>{w.cq != null ? fixed(w.cq, 1) : "—"}</NumberCell>
                    </TD>
                    <TD numeric>
                      <NumberCell muted>
                        {w.plate_median_cq != null ? fixed(w.plate_median_cq, 1) : "—"}
                      </NumberCell>
                    </TD>
                    <TD numeric>
                      <NumberCell>
                        {w.pull_log2 != null
                          ? `${fixed(2 ** Math.abs(w.pull_log2), 2)}× ${w.pull_log2 > 0 ? "high" : "low"}`
                          : "—"}
                      </NumberCell>
                    </TD>
                    <TD>
                      {s.read_as_expected?.length
                        ? s.read_as_expected.map((c, i) => (
                            <span key={c.gene}>
                              {i ? ", " : ""}
                              <Link
                                href={sectionPath(workspace, "trace", c.gene)}
                                className="text-accent underline-offset-4 hover:underline"
                              >
                                {c.gene}
                              </Link>
                            </span>
                          ))
                        : "none"}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        ) : (
          <p className="text-[13px] text-muted">
            Every sample&rsquo;s control-gene wells agree with each other
            {trace.cell.refs.length < 3
              ? " (with fewer than three control genes this cannot be checked)"
              : ""}
            .
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function LeftOut({ trace }: { trace: Overview }) {
  const rows: Missing[] = trace.left_out;
  return (
    <Card as="section" aria-labelledby="trace-o-left">
      <CardHeader
        id="trace-o-left"
        title="Samples in no comparison"
        hint={`${count(rows.length)} of ${count(trace.n_units)} samples enter no result, and the well that put each one there.`}
      />
      <CardBody>
        {rows.length ? (
          <div
            className="max-h-[420px] overflow-auto rounded-md focus-visible:outline-2 focus-visible:outline-accent"
            tabIndex={0}
            role="region"
            aria-label="The list of samples in no comparison (scrolls)"
          >
            <Table>
              <THead>
                <TR>
                  <TH>Sample</TH>
                  <TH>Why</TH>
                  <TH>The well(s)</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((m) => (
                  <TR key={m.unit}>
                    <TD>{m.unit}</TD>
                    <TD>{MISSING_WORDS[m.reason] ?? m.reason}</TD>
                    <TD className="text-muted">
                      {m.wells.map((w) => `${w.gene} ${address(w)}`).join("; ") || "—"}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        ) : (
          <p className="text-[13px] text-muted">Every sample of the study is in the comparison.</p>
        )}
      </CardBody>
    </Card>
  );
}
