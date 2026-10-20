/**
 * A slider over a list of stops (a native range input: keyboard, screen readers and touch for
 * free), with its value written beside the label.
 */
import { useId, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface StopSliderProps {
  label: string;
  stops: readonly number[];
  /** The index of the chosen stop. */
  index: number;
  onIndexChange: (index: number) => void;
  /** How a stop reads ("3.00×", "80 %", "12 per group"). */
  format: (value: number) => string;
  hint?: ReactNode;
  /** Shown instead of the stop's own words (e.g. "auto · 27"). */
  valueText?: string;
  dimmed?: boolean;
  className?: string;
}

export function StopSlider({
  label,
  stops,
  index,
  onIndexChange,
  format,
  hint,
  valueText,
  dimmed,
  className,
}: StopSliderProps) {
  const id = useId();
  const hintId = useId();
  const text = valueText ?? format(stops[index]!);
  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-[13px] font-medium text-fg">
          {label}
        </label>
        <output
          htmlFor={id}
          className={cn("font-mono text-[13px] tabular", dimmed ? "text-muted" : "text-fg")}
        >
          {text}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={0}
        max={stops.length - 1}
        step={1}
        value={index}
        aria-valuetext={text}
        aria-describedby={hint ? hintId : undefined}
        onChange={(e) => onIndexChange(Number(e.target.value))}
        className="mt-1.5 block h-6 w-full cursor-pointer [accent-color:var(--accent)]"
      />
      <div className="flex justify-between font-mono text-[10.5px] text-faint tabular" aria-hidden>
        <span>{format(stops[0]!)}</span>
        <span>{format(stops[stops.length - 1]!)}</span>
      </div>
      {hint ? (
        <p id={hintId} className="mt-1 text-[12px] leading-snug text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
