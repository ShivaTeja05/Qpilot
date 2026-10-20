import { Link } from "wouter";
import { Dot, Tooltip } from "@/ui";
import { cn } from "@/lib/cn";
import { modelChip } from "@/shell/TopBar";
import type { ModelStatus } from "./system";

/**
 * The model chip, worded by the shell's `modelChip` (`no model` / `local qwen2.5:7b` /
 * `REMOTE — names pseudonymised`, a status dot, the status on hover). It opens Settings.
 */
export function ModelChip({ model, className }: { model: ModelStatus; className?: string }) {
  const chip = modelChip(model);
  const remote = model.configured && !model.local;
  return (
    <Tooltip content={chip.status}>
      <Link
        href="/settings"
        aria-label={`Model: ${chip.label}. ${chip.status}. Open settings`}
        className={cn(
          "inline-flex h-6 max-w-full items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors hover:bg-bg-subtle",
          remote ? "border-warn/40 bg-warn-soft text-warn" : "border-line text-muted hover:text-fg",
          className,
        )}
      >
        <Dot tone={chip.tone} pulse={chip.pulse} />
        <span className="truncate">{chip.label}</span>
      </Link>
    </Tooltip>
  );
}
