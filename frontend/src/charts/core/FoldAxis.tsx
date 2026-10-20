/** The shared fold-change axis: × ticks, recessive gridlines, the call lines and which way is up. */
import type { FoldScale } from "./fold";

export function FoldAxis({
  scale,
  top,
  bottom,
  line,
  lineLabel,
  lower = "lower",
  higher = "higher",
  labels = true,
}: {
  scale: FoldScale;
  top: number;
  bottom: number;
  /** The call rule's minimum |log2 fold| (1 = at least 2-fold); 0 or undefined: no lines. */
  line?: number;
  lineLabel?: string;
  /** Direction words under the axis ("lower in MYCN-high" / "higher in MYCN-high"). */
  lower?: string;
  higher?: string;
  labels?: boolean;
}) {
  const { x, lo, hi, ticks } = scale;
  const x0 = x(lo);
  const x1 = x(hi);
  const lines = line ? [-line, line].filter((v) => v > lo && v < hi) : [];
  // two line labels that would touch: name only the right-hand one
  const crowded = lines.length === 2 && x(lines[1]!) - x(lines[0]!) < 70;
  // direction words that would touch: drop the group name
  const short = x1 - x0 < 150 + 6 * (lower.length + higher.length);
  const lowerText = short ? lower.split(" ")[0] : lower;
  const higherText = short ? higher.split(" ")[0] : higher;
  return (
    <g aria-hidden="true" className="select-none">
      {ticks.map((t) => (
        <g key={t.log2}>
          <line
            x1={x(t.log2)}
            x2={x(t.log2)}
            y1={top}
            y2={bottom}
            stroke={t.log2 === 0 ? "var(--line-strong)" : "var(--line)"}
            strokeWidth={1}
          />
          <text
            x={x(t.log2)}
            y={bottom + 15}
            textAnchor="middle"
            fontSize={11}
            fill="var(--text-muted)"
            className="tabular"
          >
            {t.label}
          </text>
        </g>
      ))}
      <line x1={x0} x2={x1} y1={bottom} y2={bottom} stroke="var(--line-strong)" />
      {lines.map((v) => (
        <g key={v}>
          <line
            x1={x(v)}
            x2={x(v)}
            y1={top - 4}
            y2={bottom}
            stroke="var(--text-faint)"
            strokeWidth={1.25}
            strokeDasharray="4 3"
          />
          {lineLabel && !(crowded && v < 0) && (
            <text x={x(v)} y={top - 8} textAnchor="middle" fontSize={11} fill="var(--text-muted)">
              {lineLabel}
            </text>
          )}
        </g>
      ))}
      {labels && (
        <>
          <text x={x0} y={bottom + 31} fontSize={11} fill="var(--text-muted)">
            ← {lowerText}
          </text>
          <text x={x1} y={bottom + 31} fontSize={11} fill="var(--text-muted)" textAnchor="end">
            {higherText} →
          </text>
        </>
      )}
    </g>
  );
}

/** Pixels the axis needs below `bottom` (ticks + direction words). */
export const FOLD_AXIS_BELOW = 38;
