/** The charts' tooltip: text only (React escaping), kept inside the chart, never gating a value. */
import type { Tip } from "./hooks";

export function Tooltip({ tip, width }: { tip: Tip | null; width: number }) {
  if (!tip) return null;
  const left = tip.x > width - 240;
  const { title, value, lines = [] } = tip.content;
  return (
    <div
      role="presentation"
      className="pointer-events-none absolute z-20 max-w-[260px] rounded-lg border border-line bg-surface px-3 py-2 text-[12px] leading-snug text-fg shadow-md"
      style={{
        left: left ? undefined : tip.x + 14,
        right: left ? width - tip.x + 14 : undefined,
        top: Math.max(0, tip.y - 12),
      }}
    >
      <div className="font-semibold">{title}</div>
      {value && <div className="tabular text-[13px] font-medium">{value}</div>}
      {lines.filter(Boolean).map((l, i) => (
        <div key={i} className="text-muted">
          {l}
        </div>
      ))}
    </div>
  );
}
