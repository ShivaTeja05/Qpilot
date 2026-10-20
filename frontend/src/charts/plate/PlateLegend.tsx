/** The plate map's legend: what each mark means under the layer, with counts from the wells shown. */
import { count } from "@/lib/format";
import { cn } from "@/lib/cn";
import {
  CALL_STYLE,
  NUMERIC,
  PLATE_LAYER_LABEL,
  ROLE_ORDER,
  callKey,
  isNumericLayer,
  numberText,
  rampColor,
  roleStyle,
  type CallKey,
  type Domain,
  type PlateLayer,
  type PlateWell,
} from "./layers";
import { WellGlyph } from "./WellGlyph";

interface Item {
  key: string;
  glyph: PlateWell;
  layer: PlateLayer;
  label: string;
  n: number;
}

const SWATCH = 14;

export function PlateLegend({
  wells,
  layer,
  domain,
  className,
}: {
  wells: readonly PlateWell[];
  layer: PlateLayer;
  domain: Domain | null;
  className?: string;
}) {
  const shown = wells.filter((w) => !w.dimmed);
  const items: Item[] = [];

  if (layer === "role") {
    const by = new Map<string, number>();
    for (const w of shown) by.set(w.role ?? "", (by.get(w.role ?? "") ?? 0) + 1);
    const order = (r: string) => {
      const i = (ROLE_ORDER as readonly string[]).indexOf(r);
      return i < 0 ? 99 : i;
    };
    for (const [role, n] of [...by].sort((a, b) => order(a[0]) - order(b[0]))) {
      items.push({ key: `role-${role}`, glyph: { well: "A1", role }, layer, label: roleStyle(role).label, n });
    }
  } else if (layer === "call") {
    const n: Record<CallKey, number> = { amplified: 0, not_amplified: 0, no_call: 0 };
    for (const w of shown) n[callKey(w.amplified)] += 1;
    for (const k of ["amplified", "not_amplified", "no_call"] as CallKey[]) {
      if (k === "no_call" && !n[k]) continue;
      const amplified = k === "amplified" ? true : k === "not_amplified" ? false : null;
      items.push({ key: k, glyph: { well: "A1", amplified }, layer, label: CALL_STYLE[k].label, n: n[k] });
    }
  }

  const disagree = shown.filter((w) => w.disagree).length;
  const person = shown.filter((w) => w.personCall).length;
  const flagged = shown.filter((w) => w.flagged).length;
  const missing = isNumericLayer(layer) ? shown.filter((w) => !Number.isFinite(NUMERIC[layer].get(w) ?? NaN)).length : 0;
  const dimmed = wells.length - shown.length;

  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-muted", className)}>
      {items.map((it) => (
        <li key={it.key} className="inline-flex items-center gap-1.5">
          <WellGlyph well={it.glyph} layer={it.layer} domain={null} size={SWATCH} />
          <span>{it.label}</span>
          <span className="text-faint tabular">{count(it.n)}</span>
        </li>
      ))}
      {isNumericLayer(layer) && domain ? (
        <li className="inline-flex items-center gap-2">
          <span className="text-fg">{PLATE_LAYER_LABEL[layer]}</span>
          <span className="font-mono tabular">
            {domain.clippedLo ? "≤ " : ""}
            {numberText(layer, domain.lo)}
          </span>
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-24 rounded-full border border-line"
            style={{
              background: `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map((t) => `${rampColor(t)} ${t * 100}%`).join(", ")})`,
            }}
          />
          <span className="font-mono tabular">
            {domain.clippedHi ? "≥ " : ""}
            {numberText(layer, domain.hi)}
          </span>
        </li>
      ) : null}
      {isNumericLayer(layer) && missing ? (
        <li className="inline-flex items-center gap-1.5">
          <WellGlyph well={{ well: "A1" }} layer={layer} domain={null} size={SWATCH} />
          <span>No value</span>
          <span className="text-faint tabular">{count(missing)}</span>
        </li>
      ) : null}
      {disagree ? (
        <li className="inline-flex items-center gap-1.5">
          <WellGlyph well={{ well: "A1", disagree: true }} layer="call" domain={null} size={SWATCH} />
          <span>Curve Judge disagrees</span>
          <span className="text-faint tabular">{count(disagree)}</span>
        </li>
      ) : null}
      {person ? (
        <li className="inline-flex items-center gap-1.5">
          <WellGlyph well={{ well: "A1", personCall: true }} layer="call" domain={null} size={SWATCH} />
          <span>Call set by a person</span>
          <span className="text-faint tabular">{count(person)}</span>
        </li>
      ) : null}
      {flagged ? (
        <li className="inline-flex items-center gap-1.5">
          <WellGlyph well={{ well: "A1", flagged: true }} layer="call" domain={null} size={SWATCH} />
          <span>Names read like instructions</span>
          <span className="text-faint tabular">{count(flagged)}</span>
        </li>
      ) : null}
      {dimmed ? (
        <li className="inline-flex items-center gap-1.5 text-faint">
          <span>{count(dimmed)} filtered out (faded)</span>
        </li>
      ) : null}
    </ul>
  );
}
