/**
 * A preview of the study passport, drawn here from the same report the server writes into the
 * file: the identifiers that bind it, how to verify it, the key numbers, the robustness map, the
 * audit's verdicts, every gene and the decision log. (The file itself is offline HTML with its
 * charts drawn on the server; this page never renders server HTML.)
 */
import { useMemo, useState } from "react";
import { Link } from "wouter";
import {
  CALLS,
  CALL_ORDER,
  LineSwatch,
  RobustnessMap,
  VerdictStrip,
  resultsMapPoints,
  type LegendItem,
} from "@/charts";
import { ci, count, dateTime, fold, percent, pValue } from "@/lib/format";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { Button, CommandLine, ConclusionTag, Hash, KeyValues, LevelTag, Table, TBody, TD, TH, THead, TR } from "@/ui";
import type { ReportExported, ReportGene, ReportView } from "./api";
import { Cited } from "./Cited";

const FIRST = 12;

export function PassportPreview({
  view,
  passport,
  workspace,
}: {
  view: ReportView;
  /** The latest passport written (binds the preview to its record), if any. */
  passport: ReportExported | null;
  workspace: SectionProps["workspace"];
}) {
  const h = view.header;
  const bound = passport && passport.chain_head === h.chain_head ? passport : null;
  return (
    <article
      aria-label="Study passport preview"
      className="overflow-hidden rounded-2xl border border-line-strong bg-surface shadow-sm"
    >
      <header className="border-b border-line bg-sunken/60 px-5 py-4 sm:px-7">
        <p className="text-[11.5px] font-semibold tracking-wider text-accent-strong uppercase">qPilot · Study passport</p>
        <h3 className="mt-1 text-[18px] leading-snug font-semibold text-fg [text-wrap:balance]">{h.title}</h3>
        <p className="mt-0.5 text-[12.5px] text-muted">{h.research_use}</p>
        <KeyValues
          className="mt-3"
          rows={[
            ["Study", <span key="s" className="font-mono text-[12.5px]">{h.study_id}</span>],
            ...(h.source_name ? [["Input file", h.source_name] as [string, string]] : []),
            ["Input SHA-256", <Hash key="i" value={h.input_sha256} length={16} />],
            ["Decision log head", <Hash key="c" value={h.chain_head} length={16} />],
            [
              "Analysis Record",
              bound?.record ? (
                <Hash key="r" value={bound.record.record_id} length={16} />
              ) : (
                <span key="r" className="text-muted">written with the passport</span>
              ),
            ],
          ]}
        />
      </header>

      <div className="flex flex-col gap-6 px-5 py-5 sm:px-7">
        <Verify passport={bound} />

        <section aria-label="Summary" className="flex flex-col gap-3">
          <p className="text-[13.5px] leading-relaxed text-muted">
            <Cited text={view.summary} facts={view.facts} />
          </p>
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Key numbers">
            {view.key_numbers.map((k) => {
              const f = view.facts[k.fact];
              return f ? (
                <li key={k.label} className="rounded-lg border border-line px-3 py-2" title={`${f.id}: ${f.path}`}>
                  <p className="tabular text-[18px] font-semibold text-fg">{f.text}</p>
                  <p className="text-[11.5px] text-muted">{k.label}</p>
                </li>
              ) : null;
            })}
          </ul>
        </section>

        <MapPreview view={view} />

        {view.audit.status === "ready" ? (
          <section aria-labelledby="pp-verdicts">
            <h4 id="pp-verdicts" className="mb-2 text-[13px] font-semibold text-fg">
              The audit's verdicts
              <span className="ml-1.5 font-normal text-muted">
                {view.audit.reasonable ? `in its reasonable set of ${count(view.audit.reasonable)} analyses` : null}
                {view.audit.current ? "" : " · run at an earlier decision log"}
              </span>
            </h4>
            <VerdictStrip
              rules={false}
              counts={Object.entries(view.audit.verdict_counts).map(([verdict, n]) => ({
                verdict,
                count: n,
                label: view.audit.verdict_labels[verdict],
              }))}
            />
          </section>
        ) : null}

        <GenesPreview genes={view.genes} rule={view.rule} workspace={workspace} />
        <DecisionsPreview view={view} />

        <p className="text-[12px] text-muted">
          The file also carries the reviewer's report, the Methods with their references, the MIQE 2.0 checklist, the
          limitations and every number with where it comes from, exactly as on this page.
        </p>
      </div>
    </article>
  );
}

function Verify({ passport }: { passport: ReportExported | null }) {
  if (!passport?.record) {
    return (
      <div className="rounded-xl border border-line bg-sunken/50 px-4 py-3 text-[13px] leading-relaxed text-muted">
        <span className="font-medium text-fg">How it is verified.</span> Writing the passport also writes a fresh
        Analysis Record beside it; the passport names that record's id, and <code className="font-mono">qpilot verify</code>{" "}
        checks the record anywhere.
      </div>
    );
  }
  const r = passport.record;
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-accent-soft/70 px-4 py-3">
      <p className="text-[13px] font-medium text-fg">
        How to verify this passport{" "}
        <span className="font-normal text-muted">(written {dateTime(passport.written_at)})</span>
      </p>
      <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-[13px] text-muted marker:text-muted">
        <li>
          Get <span className="font-mono text-[12.5px] text-fg">{r.download.name}</span>, written with it.
        </li>
        <li>
          Check every checksum and both hash chains:
          <CommandLine className="mt-1" command={r.verify} />
        </li>
        <li>
          Its record id must be <Hash value={r.record_id} length={16} />.
        </li>
        <li>
          Recompute every number from the input file:
          <CommandLine className="mt-1" command={r.rerun} />
        </li>
      </ol>
    </div>
  );
}

function MapPreview({ view }: { view: ReportView }) {
  const genes = useMemo(
    () => view.genes.filter((g): g is ReportGene & { holds: number } => g.holds != null && g.fc > 0),
    [view.genes],
  );
  const cells = genes[0]?.n_cells ?? 0;
  const legend: LegendItem[] = useMemo(
    () => [
      ...CALL_ORDER.map((c) => ({
        mark: CALLS[c],
        label: CALLS[c].label,
        count: genes.filter((g) => g.conclusion === c).length,
      })).filter((i) => i.count),
      { swatch: <LineSwatch dashed />, label: "2-fold line" },
    ],
    [genes],
  );
  if (!genes.length) return null;
  const setWords = cells ? `of the ${count(cells)} analyses qPilot checks` : "of the analyses qPilot checks";
  return (
    <section aria-labelledby="pp-map">
      <h4 id="pp-map" className="mb-1 text-[13px] font-semibold text-fg">
        Robustness map
      </h4>
      <RobustnessMap
        points={resultsMapPoints(genes, "conclusion")}
        line={1}
        lineLabel="2-fold line"
        legend={legend}
        setWords={setWords}
        yLabel={cells ? `Same call in qPilot's choice grid (${count(cells)} analyses)` : "Same call in qPilot's choice grid"}
        summary={`Robustness map of ${count(genes.length)} genes: fold change across, and up, the share ${setWords} that give the same call.`}
      />
    </section>
  );
}

function GenesPreview({
  genes,
  rule,
  workspace,
}: {
  genes: ReportGene[];
  rule: string;
  workspace: SectionProps["workspace"];
}) {
  const [all, setAll] = useState(false);
  const shown = all ? genes : genes.slice(0, FIRST);
  return (
    <section aria-labelledby="pp-genes">
      <h4 id="pp-genes" className="text-[13px] font-semibold text-fg">
        Every gene <span className="font-normal text-muted">· headline genes first · {rule}</span>
      </h4>
      <div
        className="relative mt-2 overflow-x-auto rounded-lg border border-line qp-scroll"
        tabIndex={0}
        role="region"
        aria-label="Every gene (scrolls sideways)"
      >
        <Table caption="Every gene: call, fold change with its 95 % confidence interval, p, n per group, how often the call holds, confidence and the audit's verdict">
          <THead>
            <TR>
              <TH>Gene</TH>
              <TH>Call</TH>
              <TH numeric>Fold [95 % CI]</TH>
              <TH numeric>p</TH>
              <TH numeric>n</TH>
              <TH numeric>Holds</TH>
              <TH>Confidence</TH>
              <TH>Audit</TH>
            </TR>
          </THead>
          <TBody>
            {shown.map((g) => (
              <TR key={g.gene} className={g.headline ? "bg-accent-soft/40" : undefined}>
                <TD>
                  {workspace ? (
                    <Link href={sectionPath(workspace, "gene", g.gene)} className="font-medium text-fg hover:underline">
                      {g.gene}
                    </Link>
                  ) : (
                    g.gene
                  )}
                </TD>
                <TD>
                  <ConclusionTag conclusion={g.conclusion} compact />
                </TD>
                <TD numeric>
                  {fold(g.fc)} <span className="text-muted">{ci(g.ci_lo, g.ci_hi)}</span>
                </TD>
                <TD numeric>{pValue(g.p)}</TD>
                <TD numeric>
                  {count(g.n_hi)} / {count(g.n_lo)}
                </TD>
                <TD numeric>{percent(g.holds)}</TD>
                <TD>{g.level ? <LevelTag level={g.level} /> : "—"}</TD>
                <TD className="text-muted">{g.verdict_label ?? "—"}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      {genes.length > FIRST ? (
        <Button size="sm" variant="ghost" className="mt-1" onClick={() => setAll((v) => !v)}>
          {all ? `Show the first ${FIRST}` : `Show all ${count(genes.length)} genes`}
        </Button>
      ) : null}
    </section>
  );
}

const ACTOR: Record<string, string> = { human: "a person", agent: "an agent", system: "automatically" };

function DecisionsPreview({ view }: { view: ReportView }) {
  if (!view.decisions.length) return null;
  return (
    <section aria-labelledby="pp-decisions">
      <h4 id="pp-decisions" className="text-[13px] font-semibold text-fg">
        Decisions <span className="font-normal text-muted">· the hash-chained log, then the choices still open</span>
      </h4>
      <div
        className="relative mt-2 overflow-x-auto rounded-lg border border-line qp-scroll"
        tabIndex={0}
        role="region"
        aria-label="Decisions (scrolls sideways)"
      >
        <Table caption="The decision log and the choices still open">
          <THead>
            <TR>
              <TH numeric>#</TH>
              <TH>Choice</TH>
              <TH>Option</TH>
              <TH>By</TH>
              <TH>Status</TH>
              <TH>Reason</TH>
            </TR>
          </THead>
          <TBody>
            {view.decisions.map((d, i) => (
              <TR key={`${d.card_id}-${d.seq ?? `open-${i}`}`}>
                <TD numeric className="text-muted">
                  {d.seq ?? "—"}
                </TD>
                <TD>{d.card_title}</TD>
                <TD>{d.option_label ?? d.option ?? "—"}</TD>
                <TD className="text-muted">{d.actor ? (ACTOR[d.actor] ?? d.actor) : "—"}</TD>
                <TD>
                  <span className={d.seq == null && d.can_flip ? "font-medium text-warn" : "text-muted"}>
                    {d.status}
                    {d.seq == null && d.can_flip ? " · can change a call" : ""}
                  </span>
                </TD>
                <TD className="max-w-[320px] text-muted">{d.reason ?? ""}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
    </section>
  );
}
