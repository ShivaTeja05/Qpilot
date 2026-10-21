/**
 * Small pieces of the Controls section: a rule's verdict chip (glyph + word, never colour alone),
 * a consequence's class chip, the verdict counts, and the plate strip (one button per plate that
 * filters the rule list to it).
 */
import { CircleCheck, CircleMinus, CircleX, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { Badge } from "@/ui";
import type { ConsequenceClass, Plate, Verdict } from "./api";
import {
  CLASS_TONE,
  CLASS_WORD,
  VERDICTS,
  VERDICT_TONE,
  VERDICT_WORD,
  plateLabel,
  plateSummary,
} from "./words";

const VERDICT_ICON: Record<Verdict, ReactNode> = {
  fail: <CircleX aria-hidden />,
  warn: <TriangleAlert aria-hidden />,
  pass: <CircleCheck aria-hidden />,
  not_applicable: <CircleMinus aria-hidden />,
};

export function VerdictChip({ verdict, className }: { verdict: Verdict; className?: string }) {
  return (
    <Badge tone={VERDICT_TONE[verdict]} icon={VERDICT_ICON[verdict]} className={className}>
      {VERDICT_WORD[verdict]}
    </Badge>
  );
}

export function ClassChip({ value }: { value: ConsequenceClass }) {
  return <Badge tone={CLASS_TONE[value]}>{CLASS_WORD[value]}</Badge>;
}

/** Rule evaluations per verdict, as words with counts. */
export function VerdictCounts({ counts }: { counts: Record<string, number> }) {
  return (
    <ul className="flex flex-wrap items-center gap-2" aria-label="Rule checks by verdict">
      {VERDICTS.map((v) => (
        <li key={v} className="inline-flex items-center gap-1.5 text-[13px] text-muted">
          <VerdictChip verdict={v} />
          <span className="tabular font-medium text-fg">{count(counts[v] ?? 0)}</span>
        </li>
      ))}
    </ul>
  );
}

const WORST_CLASS: Record<Verdict, string> = {
  fail: "border-danger/40 bg-danger-soft text-danger",
  warn: "border-warn/40 bg-warn-soft text-warn",
  pass: "border-line bg-surface text-fg",
  not_applicable: "border-line bg-sunken text-muted",
};

/** One button per plate: its worst verdict (glyph + colour) and status; pressing one filters. */
export function PlateStrip({
  plates,
  selected,
  onSelect,
}: {
  plates: readonly Plate[];
  selected: string | null;
  onSelect: (plate: string | null) => void;
}) {
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Plates">
      {plates.map((p) => {
        const on = selected === p.plate;
        return (
          <li key={p.plate}>
            <button
              type="button"
              aria-pressed={on}
              aria-label={plateSummary(p)}
              title={plateSummary(p)}
              onClick={() => onSelect(on ? null : p.plate)}
              className={cn(
                "inline-flex h-7 max-w-[11rem] items-center gap-1 rounded-md border px-2 text-[12px] font-medium transition-colors duration-150 [&_svg]:size-3.5 [&_svg]:shrink-0",
                WORST_CLASS[p.worst],
                p.status === "ungated" && "border-dashed",
                on && "ring-2 ring-accent ring-offset-1 ring-offset-bg",
              )}
            >
              {VERDICT_ICON[p.worst]}
              <span className="truncate">{plateLabel(p.plate)}</span>
              {p.status === "ungated" && <span className="font-normal">(ungated)</span>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
