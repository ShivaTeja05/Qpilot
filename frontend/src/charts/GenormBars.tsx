/**
 * Reference-gene stability (geNorm): M per candidate against its cut-off (lower is steadier), and
 * V for each step of adding one more reference gene against its cut-off (below: enough genes).
 */
import { fmtNum } from "./core/format";
import { HBars, type BarRow } from "./HBars";

export interface GenormBarsProps {
  /** geNorm M per candidate reference gene. */
  m: Record<string, number>;
  /** The candidates' order (steadiest first); default by M. */
  order?: string[];
  cutoffM: number;
  /** Pairwise variation V ("V2/3" → value); omit to leave the V chart out. */
  v?: Record<string, number> | null;
  cutoffV?: number;
  /** The reference genes the analysis uses (marked "used"). */
  used?: readonly string[];
  /** Candidates whose level differs between the groups (audit), marked. */
  differs?: ReadonlySet<string>;
  /** Show only the M chart or only the V chart. */
  only?: "m" | "v";
}

export function genormRows(m: Record<string, number>, cutoff: number, order?: string[], used?: readonly string[], differs?: ReadonlySet<string>): BarRow[] {
  const genes = order?.filter((g) => g in m) ?? Object.keys(m).sort((a, b) => m[a]! - m[b]!);
  return genes.map((g) => {
    const value = m[g]!;
    const above = value > cutoff;
    const notes = [used?.includes(g) ? "used" : null, above ? `above ${fmtNum(cutoff, 1)}` : null, differs?.has(g) ? "differs between groups" : null].filter(Boolean);
    return {
      key: g,
      label: g,
      value,
      valueText: fmtNum(value, 2),
      note: notes.join(" · ") || undefined,
      tone: above || differs?.has(g) ? "var(--warn)" : "var(--accent)",
      strong: Boolean(used?.includes(g)),
    };
  });
}

export function GenormBars({ m, order, cutoffM, v, cutoffV, used, differs, only }: GenormBarsProps) {
  const mRows = genormRows(m, cutoffM, order, used, differs);
  const nStable = mRows.filter((r) => r.value <= cutoffM).length;
  const vRows: BarRow[] = Object.entries(v ?? {}).map(([pair, value]) => ({
    key: pair,
    label: pair,
    value,
    valueText: fmtNum(value, 3),
    note: cutoffV != null && value > cutoffV ? `above ${fmtNum(cutoffV, 2)}` : undefined,
    tone: cutoffV != null && value > cutoffV ? "var(--warn)" : "var(--accent)",
  }));
  const nVOk = cutoffV != null ? vRows.filter((r) => r.value <= cutoffV).length : 0;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {only !== "v" && (
        <div className="min-w-0">
          <p className="mb-1 text-[13px] font-semibold text-fg">Stability of each candidate (geNorm M)</p>
          <HBars
            rows={mRows}
            valueHeader="geNorm M"
            ref_={{ value: cutoffM, label: `M ${fmtNum(cutoffM, 1)}` }}
            summary={`geNorm M for ${mRows.length} candidate reference genes: ${nStable} of ${mRows.length} at or below the cut-off of ${fmtNum(cutoffM, 1)} (lower is steadier).`}
            caption={`Lower is steadier. Genes above M ${fmtNum(cutoffM, 1)} are commonly considered unstable as references.`}
          />
        </div>
      )}
      {only !== "m" && vRows.length > 0 && cutoffV != null && (
        <div className="min-w-0">
          <p className="mb-1 text-[13px] font-semibold text-fg">Adding one more reference gene (geNorm V)</p>
          <HBars
            rows={vRows}
            valueHeader="geNorm V"
            ref_={{ value: cutoffV, label: `V ${fmtNum(cutoffV, 2)}` }}
            summary={`geNorm pairwise variation for ${vRows.length} steps: ${nVOk} of ${vRows.length} at or below ${fmtNum(cutoffV, 2)}.`}
            caption={`Below V ${fmtNum(cutoffV, 2)}, adding the next reference gene changes little.`}
          />
        </div>
      )}
    </div>
  );
}
