/**
 * The plate map of the Design stage: one plate's wells by sample type (as declared in the file,
 * or as the design assembled so far has them), the wells of the proposal in focus outlined,
 * and each well's names as quoted text. Never a group label while the stages are blind (the
 * server sends none).
 */
import { useQuery } from "@tanstack/react-query";
import { Table2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { ROLE_SHORT, ROLE_WORDS } from "@/lib/vocab";
import { Badge, Button, Card, CardBody, CardHeader, ErrorPanel, IconButton, LoadingBlock, Select, Table, TBody, TD, TH, THead, TR } from "@/ui";
import { Quote, type QuoteLookup } from "@/ui/proposal";

export type PlateWell = Schemas["PlateWell"];
type PlateView = Schemas["PlateView"];

/** Fill and letter per sample type: colour reinforces, the letter and the legend carry it. */
const ROLE_STYLE: Record<string, { fill: string; stroke: string; letter: string }> = {
  unkn: { fill: "var(--surface-2)", stroke: "var(--line-strong)", letter: "" },
  std: { fill: "var(--info-soft)", stroke: "var(--info)", letter: "S" },
  ntc: { fill: "var(--warn-soft)", stroke: "var(--warn)", letter: "N" },
  nrt: { fill: "var(--warn-soft)", stroke: "var(--warn)", letter: "R" },
  nac: { fill: "var(--warn-soft)", stroke: "var(--warn)", letter: "A" },
  pos: { fill: "var(--ok-soft)", stroke: "var(--ok)", letter: "P" },
  opt: { fill: "var(--bg-subtle)", stroke: "var(--text-faint)", letter: "O" },
  ntp: { fill: "var(--bg-subtle)", stroke: "var(--text-faint)", letter: "T" },
};
const style = (role: string) => ROLE_STYLE[role] ?? { fill: "var(--bg-subtle)", stroke: "var(--text-faint)", letter: "?" };
const roleOf = (w: PlateWell) => w.role ?? w.declared_type;
const ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

export function usePlate(sid: string, run: string | null) {
  return useQuery({
    queryKey: ["w", sid, "plate", run ?? ""],
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/plate", { params: { path: { sid }, query: run ? { run } : {} } })),
    placeholderData: (prev) => prev,
  });
}

function WellDetail({ well, quotes, onShowProposals, onClose }: {
  well: PlateWell;
  quotes: QuoteLookup;
  onShowProposals?: (w: PlateWell) => void;
  onClose: () => void;
}) {
  const sampleQuote = well.sample_text_id ? quotes(well.sample_text_id) : null;
  const targetQuote = well.target_text_id ? quotes(well.target_text_id) : null;
  const role = roleOf(well);
  return (
    <div className="flex flex-col gap-2.5 rounded-lg border border-line bg-surface-2 p-3 text-[13px]" aria-live="polite">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-fg">
          Well <span className="font-mono">{well.well}</span>
        </p>
        <IconButton label="Close the well" size="sm" onClick={onClose}>
          <X />
        </IconButton>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5">
        <dt className="text-muted">Sample</dt>
        <dd className="min-w-0">{sampleQuote ? <Quote entry={sampleQuote} /> : <span className="font-mono">{well.sample}</span>}</dd>
        <dt className="text-muted">Target</dt>
        <dd className="min-w-0">{targetQuote ? <Quote entry={targetQuote} /> : <span className="font-mono">{well.target}</span>}</dd>
        <dt className="text-muted">Declared</dt>
        <dd>{ROLE_WORDS[well.declared_type] ?? well.declared_type}</dd>
        {well.role && well.role !== well.declared_type ? (
          <>
            <dt className="text-muted">In the design</dt>
            <dd>{ROLE_WORDS[well.role] ?? well.role}</dd>
          </>
        ) : null}
        {well.excluded_by_person || well.excluded_note ? (
          <>
            <dt className="text-muted">Excluded</dt>
            <dd>{well.excluded_by_person ? "by a person's decision" : well.excluded_note}</dd>
          </>
        ) : null}
      </dl>
      <p className="text-xs text-faint">{role === "unkn" ? "A study sample." : ROLE_WORDS[role]}</p>
      {onShowProposals ? (
        <Button size="sm" variant="secondary" onClick={() => onShowProposals(well)} className="self-start">
          Show proposals about this sample
        </Button>
      ) : null}
    </div>
  );
}

/** The plate map card: plate picker, the grid, the legend, a well's details, and a table view. */
export function DesignPlate({
  sid,
  runs,
  quotes,
  highlight,
  onShowProposals,
}: {
  sid: string;
  /** Every plate in the file (from the workspace summary), for the picker. */
  runs: Schemas["InspectRun"][];
  quotes: QuoteLookup;
  /** Which wells the proposal in focus is about. */
  highlight?: ((w: PlateWell) => boolean) | null;
  onShowProposals?: (w: PlateWell) => void;
}) {
  const [run, setRun] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [asTable, setAsTable] = useState(false);
  const plate = usePlate(sid, run);
  const data: PlateView | undefined = plate.data;
  const wells = useMemo(() => data?.wells ?? [], [data]);
  const legend = useMemo(() => {
    const n = new Map<string, number>();
    for (const w of wells) n.set(roleOf(w), (n.get(roleOf(w)) ?? 0) + 1);
    return [...n].sort((a, b) => b[1] - a[1]);
  }, [wells]);
  const lit = useMemo(() => (highlight ? new Set(wells.filter(highlight).map((w) => w.key)) : new Set<string>()), [wells, highlight]);
  const chosen = wells.find((w) => w.key === selected) ?? null;

  const experiments = useMemo(() => {
    const by = new Map<string, Schemas["InspectRun"][]>();
    for (const r of runs) by.set(r.experiment_id, [...(by.get(r.experiment_id) ?? []), r]);
    return by;
  }, [runs]);
  const options = runs.map((r) => ({
    value: r.run_id,
    label: r.run_id,
    hint: `${experiments.size > 1 ? `${r.experiment_id} · ` : ""}${count(r.n_wells)} wells · ${r.targets.join(", ")}`,
  }));

  const rows = data?.n_rows ?? 0;
  const cols = data?.n_cols ?? 0;
  const cell = 16;
  const gap = 2;
  const pad = 14;
  const width = pad + cols * (cell + gap);
  const height = pad + rows * (cell + gap);
  const roleWords = data?.wells.some((w) => w.role) ? "as the design assembled so far has them" : "as declared in the file";

  return (
    <Card as="section" aria-labelledby={`plate-${sid}`}>
      <CardHeader
        id={`plate-${sid}`}
        title="Plate map"
        hint={`Wells by sample type, ${roleWords}.`}
        actions={
          <Button size="sm" variant="ghost" icon={<Table2 />} aria-pressed={asTable} onClick={() => setAsTable((t) => !t)}>
            {asTable ? "View as plate" : "View as table"}
          </Button>
        }
      />
      <CardBody className="flex flex-col gap-3">
        {runs.length > 1 ? (
          <Select
            label="Plate"
            value={run ?? data?.run.run_id}
            onValueChange={(v) => {
              setRun(v);
              setSelected(null);
            }}
            options={options}
            size="sm"
          />
        ) : null}
        {plate.error ? <ErrorPanel error={plate.error} compact onRetry={() => void plate.refetch()} /> : null}
        {!data && plate.isPending ? <LoadingBlock label="Reading the plate" lines={5} /> : null}
        {data ? (
          <>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
              <span className="font-mono text-fg">{data.run.run_id}</span>
              <span>·</span>
              <span>{data.targets.join(", ")}</span>
              {data.runs.some((r) => r.in_design) ? (
                data.run.in_design ? <Badge tone="accent">in the analysed experiment</Badge> : <Badge>not in the analysed experiment</Badge>
              ) : null}
            </div>
            {asTable ? (
              <div className="max-h-96 overflow-auto rounded-lg border border-line qp-scroll">
                <Table>
                  <THead>
                    <TR>
                      <TH>Well</TH>
                      <TH>Sample</TH>
                      <TH>Type</TH>
                      <TH>
                        <span className="sr-only">Proposals</span>
                      </TH>
                    </TR>
                  </THead>
                  <TBody>
                    {wells.map((w) => (
                      <TR key={w.key} className={cn(lit.has(w.key) && "bg-accent-soft/50")}>
                        <TD className="font-mono">{w.well}</TD>
                        <TD className="font-mono">{w.sample}</TD>
                        <TD>{ROLE_SHORT[roleOf(w)] ?? roleOf(w)}</TD>
                        <TD>
                          {onShowProposals ? (
                            <Button size="sm" variant="link" onClick={() => onShowProposals(w)}>
                              Proposals
                            </Button>
                          ) : null}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
            ) : (
              <div className="overflow-x-auto qp-scroll">
                <svg
                  viewBox={`0 0 ${width} ${height}`}
                  className="block w-full min-w-[320px]"
                  role="img"
                  aria-label={`Plate ${data.run.run_id}: ${count(wells.length)} wells; ${legend.map(([r, n]) => `${count(n)} ${ROLE_SHORT[r] ?? r}`).join(", ")}${lit.size ? `; ${count(lit.size)} wells outlined for the proposal in focus` : ""}. The table view lists every well.`}
                >
                  {Array.from({ length: cols }, (_, c) =>
                    cols <= 24 && (cols <= 12 || c % 2 === 0) ? (
                      <text key={`c${c}`} x={pad + c * (cell + gap) + cell / 2} y={9} textAnchor="middle" fontSize={7} fill="var(--text-faint)">
                        {c + 1}
                      </text>
                    ) : null,
                  )}
                  {Array.from({ length: rows }, (_, r) => (
                    <text key={`r${r}`} x={5} y={pad + r * (cell + gap) + cell / 2 + 2.5} textAnchor="middle" fontSize={7} fill="var(--text-faint)">
                      {ROW_LETTERS[r] ?? r + 1}
                    </text>
                  ))}
                  {wells.map((w) => {
                    if (!w.row || !w.col) return null;
                    const s = style(roleOf(w));
                    const x = pad + (w.col - 1) * (cell + gap);
                    const y = pad + (w.row - 1) * (cell + gap);
                    const on = lit.has(w.key);
                    const sel = w.key === selected;
                    return (
                      <g key={w.key} onClick={() => setSelected(sel ? null : w.key)} className="cursor-pointer">
                        <title>{`${w.well} · ${w.sample} · ${w.target} · ${ROLE_SHORT[roleOf(w)] ?? roleOf(w)}`}</title>
                        <rect
                          x={x}
                          y={y}
                          width={cell}
                          height={cell}
                          rx={3}
                          fill={s.fill}
                          stroke={sel ? "var(--text)" : on ? "var(--accent)" : s.stroke}
                          strokeWidth={sel || on ? 2 : 0.8}
                        />
                        {s.letter ? (
                          <text x={x + cell / 2} y={y + cell / 2 + 3} textAnchor="middle" fontSize={8.5} fontWeight={600} fill={s.stroke} pointerEvents="none">
                            {s.letter}
                          </text>
                        ) : null}
                        {w.excluded_by_person ? (
                          <line x1={x + 2} y1={y + cell - 2} x2={x + cell - 2} y2={y + 2} stroke="var(--danger)" strokeWidth={1.4} pointerEvents="none" />
                        ) : null}
                      </g>
                    );
                  })}
                </svg>
              </div>
            )}
            <ul className="flex flex-wrap gap-x-3 gap-y-1.5 text-xs text-muted" aria-label="Legend">
              {legend.map(([r, n]) => {
                const s = style(r);
                return (
                  <li key={r} className="inline-flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className="inline-flex size-3.5 items-center justify-center rounded-[3px] border text-[8px] font-semibold"
                      style={{ background: s.fill, borderColor: s.stroke, color: s.stroke }}
                    >
                      {s.letter}
                    </span>
                    {ROLE_SHORT[r] ?? r} <span className="font-mono tabular text-faint">{count(n)}</span>
                  </li>
                );
              })}
              {lit.size ? (
                <li className="inline-flex items-center gap-1.5">
                  <span aria-hidden className="size-3.5 rounded-[3px] border-2 border-accent" /> in focus{" "}
                  <span className="font-mono tabular text-faint">{count(lit.size)}</span>
                </li>
              ) : null}
            </ul>
            {chosen ? (
              <WellDetail well={chosen} quotes={quotes} onShowProposals={onShowProposals} onClose={() => setSelected(null)} />
            ) : (
              <p className="text-xs text-faint">Click a well for its names (quoted from the file) and the proposals about it.</p>
            )}
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}
