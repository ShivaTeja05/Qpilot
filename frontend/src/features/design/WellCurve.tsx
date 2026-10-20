/**
 * A cited well's raw curve, in a dialog (from a check's wells or well evidence). Fluorescence
 * by cycle as the file has it, the other wells of the same sample and target on the plate in
 * grey, and LinRegPCR's Cq and baseline only when the server includes them.
 */
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { fixed } from "@/lib/format";
import { ROLE_WORDS } from "@/lib/vocab";
import { Dialog, ErrorPanel, KeyValues, LoadingBlock } from "@/ui";

type Curve = Schemas["CurveView"];

const W = 560;
const H = 260;
const M = { l: 48, r: 12, t: 10, b: 30 };

function niceTicks(lo: number, hi: number, n = 5): number[] {
  if (!(hi > lo)) return [lo];
  const step = 10 ** Math.floor(Math.log10((hi - lo) / n));
  const err = ((hi - lo) / n) / step;
  const mult = err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1;
  const s = step * mult;
  const out: number[] = [];
  for (let v = Math.ceil(lo / s) * s; v <= hi + 1e-9; v += s) out.push(Number(v.toPrecision(10)));
  return out;
}

function CurvePlot({ curve }: { curve: Curve }) {
  const series = useMemo(() => [...curve.replicates.map((r) => ({ ...r, main: false })), { ...curve, main: true }], [curve]);
  const values = series.flatMap((s) => s.fluorescence.filter((v): v is number => v != null && Number.isFinite(v)));
  const cycles = series.flatMap((s) => s.cycle);
  if (!values.length || !cycles.length) return <p className="text-[13px] text-muted">This well has no fluorescence values in the file.</p>;
  const x0 = Math.min(...cycles);
  const x1 = Math.max(...cycles);
  const y0 = Math.min(...values, curve.baseline ?? Infinity);
  const y1 = Math.max(...values);
  const sx = (c: number) => M.l + ((c - x0) / Math.max(1, x1 - x0)) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - ((v - y0) / Math.max(1e-12, y1 - y0)) * (H - M.t - M.b);
  const line = (s: { cycle: number[]; fluorescence: (number | null)[] }) =>
    s.cycle
      .map((c, i) => [c, s.fluorescence[i]] as const)
      .filter((pt): pt is readonly [number, number] => pt[1] != null && Number.isFinite(pt[1]))
      .map(([c, v], i) => `${i ? "L" : "M"}${sx(c).toFixed(1)},${sy(v).toFixed(1)}`)
      .join("");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Raw fluorescence of well ${curve.well} by cycle, ${curve.replicates.length} other wells of the same sample and target in grey`}>
      {niceTicks(y0, y1).map((t) => (
        <g key={`y${t}`}>
          <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} stroke="var(--line)" />
          <text x={M.l - 6} y={sy(t) + 3} textAnchor="end" fontSize={10} fill="var(--text-faint)">
            {Math.abs(t) >= 1000 ? t.toExponential(1) : t}
          </text>
        </g>
      ))}
      {niceTicks(x0, x1, 8).map((t) => (
        <text key={`x${t}`} x={sx(t)} y={H - M.b + 14} textAnchor="middle" fontSize={10} fill="var(--text-faint)">
          {t}
        </text>
      ))}
      <text x={(M.l + W - M.r) / 2} y={H - 3} textAnchor="middle" fontSize={10} fill="var(--text-muted)">
        cycle
      </text>
      {curve.baseline != null ? (
        <line x1={M.l} x2={W - M.r} y1={sy(curve.baseline)} y2={sy(curve.baseline)} stroke="var(--text-faint)" strokeDasharray="4 3" />
      ) : null}
      {curve.cq != null ? <line x1={sx(curve.cq)} x2={sx(curve.cq)} y1={M.t} y2={H - M.b} stroke="var(--accent)" strokeDasharray="3 3" /> : null}
      {series.map((s) => (
        <path key={s.key} d={line(s)} fill="none" stroke={s.main ? "var(--accent)" : "var(--line-strong)"} strokeWidth={s.main ? 2 : 1.2} />
      ))}
    </svg>
  );
}

export function WellCurveDialog({ sid, well, onClose }: { sid: string; well: string | null; onClose: () => void }) {
  const curve = useQuery({
    queryKey: ["w", sid, "curve", well],
    enabled: Boolean(well),
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}/curve", { params: { path: { sid }, query: { well: well! } } })),
  });
  const c = curve.data;
  return (
    <Dialog open={Boolean(well)} onOpenChange={(o) => !o && onClose()} size="lg" title={`Curve of well ${well ?? ""}`} description={c?.note}>
      {curve.isPending ? <LoadingBlock label="Reading the curve" lines={5} /> : null}
      {curve.error ? <ErrorPanel error={curve.error} compact onRetry={() => void curve.refetch()} /> : null}
      {c ? (
        <div className="flex flex-col gap-3">
          <KeyValues
            rows={[
              ["Sample", <span className="font-mono">{c.sample}</span>],
              ["Target", <span className="font-mono">{c.target}</span>],
              ["Declared", ROLE_WORDS[c.declared_type] ?? c.declared_type],
              ...(c.numbers_shown
                ? ([
                    ["Cq (LinRegPCR)", c.cq != null ? fixed(c.cq, 2) : "none"],
                    ["Amplified (LinRegPCR)", c.amplified == null ? "—" : c.amplified ? "yes" : "no"],
                  ] as [string, string][])
                : []),
            ]}
          />
          <CurvePlot curve={c} />
          <p className="text-xs text-faint">
            Raw fluorescence as in the file. Grey: the other wells of this sample and target on the plate
            {c.numbers_shown ? "; dashed: LinRegPCR's baseline and its Cq." : "."}
          </p>
        </div>
      ) : null}
    </Dialog>
  );
}
