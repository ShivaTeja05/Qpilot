/**
 * One analysis decision as a dropdown whose options are grouped by tier: your planned analysis,
 * reasonable alternatives, common shortcuts. A choice moved off the plan is marked (border and
 * words, not colour alone). Local to the audit; the kit's `Select` has no groups.
 */
import { Select as S } from "radix-ui";
import { Check, ChevronDown } from "lucide-react";
import { useId } from "react";
import { cn } from "@/lib/cn";
import type { DecisionView } from "./types";
import { TIERS, tierOf } from "./words";

export function ChoiceSelect({
  decision,
  value,
  onValueChange,
}: {
  decision: DecisionView;
  value: string;
  onValueChange: (option: string) => void;
}) {
  const id = useId();
  const moved = value !== decision.baseline;
  const planned = decision.options.find((o) => o.id === decision.baseline);
  const groups = TIERS.map((t) => ({
    ...t,
    options: decision.options.filter((o) => tierOf(o.tier)?.key === t.key),
  })).filter((g) => g.options.length);
  const current = decision.options.find((o) => o.id === value);
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label
        htmlFor={id}
        className="flex flex-wrap items-baseline gap-x-1.5 text-[13px] font-medium text-fg"
      >
        {decision.name}
        {decision.changes_claim ? (
          <span className="text-xs font-normal text-muted">· changes the question</span>
        ) : null}
      </label>
      <S.Root value={value} onValueChange={onValueChange}>
        <S.Trigger
          id={id}
          aria-describedby={`${id}-hint`}
          className={cn(
            "inline-flex h-auto min-h-8 w-full items-center justify-between gap-2 rounded-lg border bg-surface px-3 py-1.5 text-left text-sm text-fg shadow-sm transition-colors hover:border-faint focus-visible:border-focus focus-visible:outline-2 focus-visible:outline-offset-0",
            moved ? "border-warn bg-warn-soft/50" : "border-line-strong",
          )}
        >
          <span className="min-w-0 leading-snug">
            <S.Value>{current?.label ?? value}</S.Value>
          </span>
          <S.Icon>
            <ChevronDown className="size-4 shrink-0 text-muted" aria-hidden />
          </S.Icon>
        </S.Trigger>
        <S.Portal>
          <S.Content
            position="popper"
            sideOffset={4}
            collisionPadding={12}
            className="qp-pop z-50 max-h-[min(420px,var(--radix-select-content-available-height))] w-[var(--radix-select-trigger-width)] min-w-[260px] overflow-hidden rounded-xl border border-line bg-surface p-1 text-sm text-fg shadow-lg"
          >
            <S.Viewport>
              {groups.map((g, i) => (
                <S.Group key={g.key}>
                  {i > 0 ? <S.Separator className="my-1 h-px bg-line" /> : null}
                  <S.Label className="px-2 pt-1.5 pb-1 text-[11px] font-semibold uppercase tracking-wider text-faint">
                    {g.label}
                  </S.Label>
                  {g.options.map((o) => (
                    <S.Item
                      key={o.id}
                      value={o.id}
                      className="relative flex cursor-default select-none rounded-md py-1.5 pr-2 pl-7 leading-snug outline-none data-[highlighted]:bg-bg-subtle"
                    >
                      <S.ItemIndicator className="absolute top-2 left-2">
                        <Check className="size-3.5 text-accent" aria-hidden />
                      </S.ItemIndicator>
                      <S.ItemText>{o.label}</S.ItemText>
                    </S.Item>
                  ))}
                </S.Group>
              ))}
            </S.Viewport>
          </S.Content>
        </S.Portal>
      </S.Root>
      <p id={`${id}-hint`} className="text-xs text-muted">
        {moved ? (
          <>
            <span className="font-medium text-warn">Changed</span> · planned:{" "}
            {planned?.label ?? decision.baseline}
            {current ? ` · this is a ${tierOf(current.tier)?.key ?? current.tier}` : ""}
          </>
        ) : (
          decision.question
        )}
      </p>
    </div>
  );
}
