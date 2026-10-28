/**
 * What one option of a quantification study's card reports differently: each sample result
 * whose class changes (quantified, below the LOQ or the LOD, not detected …) or whose number
 * moves by more than 2-fold, from the recommended option to this one. The API's numbers.
 */
import { useState } from "react";
import type { Schemas } from "@/api/client";
import { fmtQuantity } from "./format";

type Option = Pick<Schemas["CardOptionView"], "quantities" | "n_quantities_changed">;

const SHOWN = 6;

function reading(words: string, q: number | null | undefined, cls: string): string {
  const numbered = cls === "quantified" || cls === "above_top" || cls === "below_lowest";
  return numbered && q != null ? `${words} (${fmtQuantity(q)})` : words;
}

export function QuantityChanges({ option }: { option: Option }) {
  const [all, setAll] = useState(false);
  const rows = option.quantities ?? [];
  const n = option.n_quantities_changed ?? rows.length;
  if (!n) return null;
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <span className="flex flex-col gap-0.5 pl-6 text-[12px]" data-testid="quantity-changes">
      <span className="font-medium text-warn">
        Reports {n} sample result{n === 1 ? "" : "s"} differently:
      </span>
      {shown.map((c) => (
        <span key={`${c.target}·${c.unit}`} className="text-fg">
          <span className="font-medium">
            {c.target} · {c.unit}
          </span>
          : {reading(c.words_from, c.quantity_from, c.class_from)} →{" "}
          {reading(c.words_to, c.quantity_to, c.class_to)}
        </span>
      ))}
      {rows.length > SHOWN && (
        <button
          type="button"
          className="self-start text-[12px] font-medium text-accent hover:underline"
          onClick={(e) => {
            e.preventDefault();
            setAll((v) => !v);
          }}
        >
          {all ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
      {n > rows.length && <span className="text-muted">The first {rows.length} are listed.</span>}
    </span>
  );
}
