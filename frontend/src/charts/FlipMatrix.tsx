/**
 * The flip matrix: decisions (rows) × genes (columns). A cell's shade is how far that decision
 * alone moves the gene's fold change; a cross marks where it alone changes the gene's call.
 * Genes that flip most come first. Click a column to open the gene.
 */
import { scaleLinear } from "d3-scale";
import { useMemo, type ReactNode } from "react";
import { ChartFrame, type LegendItem } from "./core/ChartFrame";
import { DataTable, type Column } from "./core/DataTable";
import { fmtNum } from "./core/format";
import { useTip, usePointNav, useWidth } from "./core/hooks";
import { Tooltip } from "./core/Tooltip";

export interface FlipCell {
  flips: boolean;
  /** Largest |change in log2 fold| this decision alone makes (for the shade). */
  delta?: number | null;
}

export interface FlipMatrixProps {
  decisions: { id: string; label: string }[];
  genes: string[];
  cell: (decision: string, gene: string) => FlipCell | undefined;
  summary: string;
  caption?: ReactNode;
  onSelectGene?: (gene: string) => void;
}

/** Genes ordered by how many decisions flip them, then by the largest move, then by name. */
export function flipOrder(genes: readonly string[], decisions: readonly { id: string }[], cell: FlipMatrixProps["cell"]): string[] {
  const score = (g: string) => decisions.reduce((n, d) => n + (cell(d.id, g)?.flips ? 1 : 0), 0);
  const move = (g: string) => Math.max(0, ...decisions.map((d) => cell(d.id, g)?.delta ?? 0));
  return [...genes].sort((a, b) => score(b) - score(a) || move(b) - move(a) || a.localeCompare(b));
}

export function FlipMatrix({ decisions, genes, cell, summary, caption, onSelectGene }: FlipMatrixProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTip();
  const narrow = width < 560;
  const labelW = narrow ? 104 : 168;
  const ordered = useMemo(() => flipOrder(genes, decisions, cell), [genes, decisions, cell]);
  const cw = Math.max(13, Math.min(26, Math.floor((width - labelW - 8) / Math.max(1, ordered.length))));
  const ch = 26;
  const headH = 72;
  const innerW = labelW + cw * ordered.length + 8;
  const height = headH + ch * decisions.length + 4;
  const maxDelta = useMemo(
    () => Math.max(0.01, ...decisions.flatMap((d) => genes.map((g) => cell(d.id, g)?.delta ?? 0))),
    [decisions, genes, cell],
  );
  const shade = scaleLinear().domain([0, maxDelta]).range([0.04, 0.85]).clamp(true);

  const flat = useMemo(
    () => decisions.flatMap((d, ri) => ordered.map((g, ci) => ({ d, g, ri, ci, c: cell(d.id, g) }))),
    [decisions, ordered, cell],
  );
  const nav = usePointNav(flat.length, (i) => onSelectGene?.(flat[i]!.g));
  const active = nav.active != null ? flat[nav.active] : null;
  const flipsPer = (g: string) => decisions.filter((d) => cell(d.id, g)?.flips).length;

  const tipFor = (f: (typeof flat)[number]) => ({
    title: `${f.g} · ${f.d.label}`,
    value: f.c?.flips ? "This choice alone changes the call" : "The call holds under this choice alone",
    lines: [f.c?.delta != null ? `Fold change moves by up to ${fmtNum(2 ** f.c.delta, 2)}×` : null],
  });

  const legend: LegendItem[] = [
    {
      swatch: (
        <svg width="14" height="14" aria-hidden="true">
          <rect x="1" y="1" width="12" height="12" rx="2" fill="var(--accent)" fillOpacity="0.2" />
          <path d="M4 4 L10 10 M10 4 L4 10" stroke="var(--text)" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      ),
      label: "This choice alone changes the call",
    },
    {
      swatch: (
        <svg width="40" height="12" aria-hidden="true">
          {[0.08, 0.3, 0.55, 0.85].map((o, i) => (
            <rect key={o} x={i * 10} y="1" width="9" height="10" rx="1.5" fill="var(--accent)" fillOpacity={o} />
          ))}
        </svg>
      ),
      label: "How far the fold change moves (darker: further)",
    },
  ];

  const columns: Column<string>[] = [
    { key: "gene", header: "Gene", cell: (g) => g, sort: (g) => g },
    { key: "n", header: "Choices that alone change the call", cell: (g) => String(flipsPer(g)), sort: (g) => flipsPer(g), numeric: true },
    ...decisions.map((d) => ({
      key: d.id,
      header: d.label,
      cell: (g: string) => (cell(d.id, g)?.flips ? "changes the call" : ""),
      sort: (g: string) => Number(Boolean(cell(d.id, g)?.flips)),
    })),
  ];

  return (
    <ChartFrame
      summary={summary}
      legend={legend}
      caption={caption}
      live={active ? `${tipFor(active).title}: ${tipFor(active).value}` : undefined}
      table={() => <DataTable columns={columns} rows={ordered} rowKey={(g) => g} onRowClick={onSelectGene} caption={summary} />}
    >
      <div ref={ref} className="relative">
        <div
          className="overflow-x-auto rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-focus"
          tabIndex={flat.length ? 0 : -1}
          role="group"
          aria-label={`${summary} Use the arrow keys to move between cells${onSelectGene ? " and Enter to open the gene" : ""}.`}
          onKeyDown={nav.onKeyDown}
          onBlur={() => {
            nav.onBlur();
            hide();
          }}
        >
          <svg width={innerW} height={height} role="img" aria-label={summary} className="block" onPointerLeave={hide}>
            {ordered.map((g, ci) => {
              const x = labelW + ci * cw + cw / 2;
              const n = flipsPer(g);
              return (
                <g key={g} className={onSelectGene ? "cursor-pointer" : undefined} onClick={onSelectGene ? () => onSelectGene(g) : undefined}>
                  <text
                    transform={`translate(${x + 3},${headH - 6}) rotate(-60)`}
                    fontSize={11}
                    fill={n ? "var(--text)" : "var(--text-faint)"}
                    fontWeight={n ? 600 : 400}
                  >
                    {g}
                  </text>
                </g>
              );
            })}
            {decisions.map((d, ri) => (
              <text key={d.id} x={labelW - 8} y={headH + ri * ch + ch / 2 + 4} textAnchor="end" fontSize={12} fill="var(--text)">
                {d.label}
              </text>
            ))}
            {flat.map((f, i) => {
              const x = labelW + f.ci * cw;
              const y = headH + f.ri * ch;
              const on = nav.active === i;
              const delta = f.c?.delta ?? 0;
              return (
                <g
                  key={`${f.d.id}:${f.g}`}
                  onPointerEnter={() => show(x + cw / 2, y + ch / 2, tipFor(f))}
                  onClick={onSelectGene ? () => onSelectGene(f.g) : undefined}
                  className={onSelectGene ? "cursor-pointer" : undefined}
                >
                  <rect x={x + 1} y={y + 1} width={cw - 2} height={ch - 2} rx={2} fill="var(--surface-sunken)" />
                  <rect x={x + 1} y={y + 1} width={cw - 2} height={ch - 2} rx={2} fill="var(--accent)" fillOpacity={f.c ? shade(delta) : 0} />
                  {f.c?.flips && (
                    <path
                      d={`M${x + cw / 2 - 3.5} ${y + ch / 2 - 3.5} L${x + cw / 2 + 3.5} ${y + ch / 2 + 3.5} M${x + cw / 2 + 3.5} ${y + ch / 2 - 3.5} L${x + cw / 2 - 3.5} ${y + ch / 2 + 3.5}`}
                      stroke={delta / maxDelta > 0.5 ? "var(--surface)" : "var(--text)"}
                      strokeWidth={2}
                      strokeLinecap="round"
                    />
                  )}
                  {on && <rect x={x} y={y} width={cw} height={ch} rx={3} fill="none" stroke="var(--focus)" strokeWidth={2} />}
                </g>
              );
            })}
          </svg>
        </div>
        <Tooltip
          tip={active ? { x: Math.min(width - 20, labelW + active.ci * cw + cw / 2), y: headH + active.ri * ch + ch / 2, content: tipFor(active) } : tip}
          width={width}
        />
      </div>
    </ChartFrame>
  );
}
