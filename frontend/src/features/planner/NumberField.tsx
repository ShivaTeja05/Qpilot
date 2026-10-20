/**
 * A whole-number box that lets a person type freely and takes the number when they leave the box
 * or press Enter (clamped to its range then, never while typing: "15" is never cut to "2" at its
 * first digit). Empty means "none" when `allowEmpty`.
 */
import { useState } from "react";

export interface NumberFieldProps {
  value: number | null;
  onCommit: (value: number | null) => void;
  min: number;
  max: number;
  allowEmpty?: boolean;
  placeholder?: string;
  id?: string;
  "aria-describedby"?: string;
}

export function NumberField({
  value,
  onCommit,
  min,
  max,
  allowEmpty,
  placeholder,
  id,
  "aria-describedby": describedBy,
}: NumberFieldProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (value == null ? "" : String(value));

  const commit = () => {
    if (draft == null) return;
    const text = draft.trim();
    setDraft(null);
    if (text === "") {
      if (allowEmpty) onCommit(null);
      return;
    }
    const v = Math.round(Number(text));
    if (Number.isFinite(v)) onCommit(Math.max(min, Math.min(max, v)));
  };

  return (
    <input
      id={id}
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      step={1}
      value={shown}
      placeholder={placeholder}
      aria-describedby={describedBy}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setDraft(null);
      }}
      className="h-8 w-24 rounded-lg border border-line bg-surface px-2 font-mono tabular text-fg focus-visible:outline-2 focus-visible:outline-focus"
    />
  );
}
