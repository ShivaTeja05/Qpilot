/**
 * What Prism will get, before anything is written: per gene the table exactly as the CSV will
 * hold it and an approximation of the template's graph, then the test, the graph, the scale,
 * the analysis choices the tables are exported at, the caption and the files.
 */
import { AlertTriangle, FileText } from "lucide-react";
import { useState } from "react";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  KeyValues,
  LoadingBlock,
  SegmentedControl,
  Select,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { count, plural } from "@/lib/format";
import { usePrismPreview, type PrismPreview, type Workspace } from "./api";
import { log2Text, PrismFigure } from "./PrismFigure";
import { cellNumber } from "./tables";
import { cardWords } from "./words";

export function PreviewCard({ workspace }: { workspace: Workspace }) {
  const [gene, setGene] = useState<string | null>(null);
  const preview = usePrismPreview(workspace.key);
  return (
    <Card as="section" aria-labelledby="prism-preview-title">
      <CardHeader
        id="prism-preview-title"
        title="What Prism will get"
        hint="Nothing is written until you press Send to Prism. These are the engine's own numbers, read back bit for bit."
      />
      <CardBody>
        {preview.isPending ? (
          <div className="flex flex-col gap-2">
            <LoadingBlock label="Building the preview" lines={6} />
            <p className="text-[12px] text-muted">The first preview after qPilot starts rebuilds the analysis's tables; it can take half a minute.</p>
          </div>
        ) : preview.error ? (
          <ErrorPanel error={preview.error} title="No Prism preview" onRetry={() => void preview.refetch()} compact />
        ) : (
          <PreviewBody preview={preview.data} gene={gene} onGene={setGene} />
        )}
      </CardBody>
    </Card>
  );
}

export function PreviewBody({
  preview,
  gene: asked,
  onGene,
}: {
  preview: PrismPreview;
  gene: string | null;
  onGene: (gene: string) => void;
}) {
  const genes = preview.genes;
  const gene = asked && genes.includes(asked) ? asked : (genes[0] ?? null);

  if (!gene) {
    return (
      <EmptyState icon={<FileText />} title="No tables to send" compact>
        The comparison has no gene with values in both groups, so there is nothing for Prism to test. Check the design's
        groups and the reference genes.
      </EmptyState>
    );
  }

  const info = preview.bundle.info ?? {};
  const template = preview.template;
  const figure = preview.figures?.[gene] ?? null;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {genes.length <= 6 ? (
          <SegmentedControl label="Gene" value={gene} onValueChange={onGene} options={genes.map((g) => ({ value: g, label: g }))} />
        ) : (
          <Select label="Gene" value={gene} onValueChange={onGene} options={genes.map((g) => ({ value: g, label: g }))} />
        )}
        <p className="text-[12px] text-muted">
          {plural(genes.length, "table")}, one per gene · template{" "}
          <span className="font-mono text-fg">{template.file || preview.bundle.template_id}</span>
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div>
          {figure && figure.groups.some((g) => g.n > 0) ? (
            <PrismFigure figure={figure} caption={figure.note} />
          ) : (
            <EmptyState icon={<FileText />} title="No graph for this layout" compact>
              {template.layout === "nested"
                ? "Nested tables (technical replicates as rows) are drawn by Prism itself; the table shows what it gets."
                : "This gene has no values to draw; the table shows what Prism gets."}
            </EmptyState>
          )}
        </div>
        <TableHead gene={gene} preview={preview} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="prism-test-title">
          <h3 id="prism-test-title" className="mb-2 text-[13px] font-semibold text-fg">
            The test and the graph
          </h3>
          <KeyValues
            rows={(
              [
                ["Test", preview.bundle.test || template.test],
                ["Graph", template.graph || info.graph],
                ["Values", info.scale],
                ["Groups", info.groups],
                ["Reference genes", info.refs],
                ["Technical replicates", info.technical_replicates],
                ["About the groups", info.design_note],
              ] as [string, string | undefined][]
            )
              .filter(([, v]) => Boolean(v))
              .map(([k, v]) => [k, v])}
          />
          {template.available === false ? (
            <p className="mt-3 flex items-start gap-2 rounded-lg border border-warn/30 bg-warn-soft p-2.5 text-[12.5px] text-fg">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
              <span>
                The Prism template <span className="font-mono">{template.file}</span> has not been made in Prism yet. The
                bundle is still written; its README says how to build the template, and Prism then applies this test and
                graph.
              </span>
            </p>
          ) : null}
        </section>

        <section aria-labelledby="prism-choices-title">
          <h3 id="prism-choices-title" className="mb-2 text-[13px] font-semibold text-fg">
            Exported at these analysis choices
          </h3>
          <ChoicesTable preview={preview} />
        </section>
      </div>

      {preview.caption ? (
        <section aria-labelledby="prism-caption-title">
          <h3 id="prism-caption-title" className="mb-1.5 text-[13px] font-semibold text-fg">
            Caption
          </h3>
          <p className="max-w-prose text-[13px] leading-relaxed text-fg">{preview.caption}</p>
          <p className="mt-1 text-[12px] text-muted">Every number in it is a fact of this study, filled in by qPilot.</p>
        </section>
      ) : null}

      {preview.would_write.length ? (
        <section aria-labelledby="prism-files-title">
          <h3 id="prism-files-title" className="mb-1.5 text-[13px] font-semibold text-fg">
            Files Send to Prism will write
          </h3>
          <ul className="flex flex-wrap gap-1.5">
            {preview.would_write.map((f) => (
              <li key={f} className="rounded-md border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-fg">
                {f}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function TableHead({ gene, preview }: { gene: string; preview: PrismPreview }) {
  const table = preview.tables.find((t) => t.gene === gene);
  if (!table) return null;
  const csv = `${gene}.csv`;
  return (
    <section aria-labelledby="prism-table-title" className="min-w-0">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 id="prism-table-title" className="font-mono text-[13px] font-semibold text-fg">
          {csv}
        </h3>
        <span className="text-[12px] text-muted">
          {count(table.n_rows)} rows × {count(table.columns.length)} columns
        </span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-line">
        <Table caption={`First rows of ${csv}`}>
          <THead>
            <TR>
              {table.columns.map((c, i) => (
                <TH key={`${i}:${c}`} numeric={i > 0}>
                  {c}
                </TH>
              ))}
            </TR>
          </THead>
          <TBody>
            {table.rows.map((row, ri) => (
              <TR key={ri}>
                {table.columns.map((_, ci) => {
                  const cell = row[ci] ?? "";
                  if (ci === 0)
                    return (
                      <TD key={ci} className="font-mono text-[12.5px]">
                        {cell}
                      </TD>
                    );
                  const v = cellNumber(cell);
                  return (
                    <TD key={ci} numeric className={v == null ? "text-faint" : undefined}>
                      {v == null ? cell || "·" : log2Text(v)}
                    </TD>
                  );
                })}
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      <p className="mt-1.5 text-[12px] text-muted">
        {table.rows.length < table.n_rows ? `First ${count(table.rows.length)} of ${count(table.n_rows)} rows. ` : null}
        Shown to 2 decimals; the file holds every digit. An empty cell (·) is a unit of the other group.
      </p>
    </section>
  );
}

function ChoicesTable({ preview }: { preview: PrismPreview }) {
  if (!preview.choices.length) {
    return <p className="text-[13px] text-muted">This analysis has no Decision Cards: the tables follow the confirmed design.</p>;
  }
  const open = preview.choices.filter((c) => c.actor == null).length;
  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-line">
        <Table caption="Analysis choices the tables are exported at">
          <THead>
            <TR>
              <TH>Choice</TH>
              <TH>Exported at</TH>
              <TH>Decided by</TH>
            </TR>
          </THead>
          <TBody>
            {preview.choices.map((c) => (
              <TR key={c.card_id}>
                <TD>{c.title ?? cardWords(c.card_id)}</TD>
                <TD className="text-[12.5px]">{c.option_label ?? <span className="font-mono">{c.option}</span>}</TD>
                <TD className="text-[12.5px]">
                  {c.actor == null ? <Badge tone="warn">not decided</Badge> : <span className="text-muted">{c.decided_by}</span>}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      {open ? (
        <p className="mt-1.5 text-[12px] text-muted">
          {plural(open, "card")} still open: exported at the recommended option. Deciding later changes the analysis, and
          the bundle has to be sent again.
        </p>
      ) : null}
    </>
  );
}
