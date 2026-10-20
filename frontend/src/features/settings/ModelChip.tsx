import { Dot, Tooltip } from "@/ui";
import { cn } from "@/lib/cn";
import { modelWords, type ModelStatus } from "./system";

/**
 * The model chip: `no model` / `local qwen2.5:7b` / `REMOTE — names pseudonymised`, with a dot
 * (answers / checking / not answering) and the reason on hover and focus.
 */
export function ModelChip({ model, className }: { model: ModelStatus; className?: string }) {
  const w = modelWords(model);
  const detail = w.reason ? `${w.state}: ${w.reason}` : w.state;
  return (
    <Tooltip content={<span className="block max-w-xs">{detail}</span>}>
      <button
        type="button"
        aria-label={`Model: ${w.label}, ${detail}`}
        className={cn(
          "inline-flex h-6 max-w-full items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors",
          w.remote
            ? "border-warn/40 bg-warn-soft text-warn"
            : "border-line bg-surface text-muted hover:text-fg",
          className,
        )}
      >
        <Dot tone={w.tone} pulse={w.pulse} />
        <span className="truncate">{w.label}</span>
      </button>
    </Tooltip>
  );
}
