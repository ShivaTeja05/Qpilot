/** Form controls and tabs, on Radix where keyboard behaviour matters. */
import { Select as S, Switch as Sw, Tabs as Tb, ToggleGroup as TG } from "radix-ui";
import { Check, ChevronDown } from "lucide-react";
import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";

const FIELD =
  "w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-fg placeholder:text-faint shadow-sm transition-colors hover:border-faint focus-visible:border-focus focus-visible:outline-2 focus-visible:outline-offset-0 disabled:opacity-55 aria-[invalid=true]:border-danger";

// ---------------------------------------------------------------------------------------------
// Field

/** A label, the control, and a hint or an error under it. */
export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
  className,
  optional,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
  className?: string;
  optional?: boolean;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-[13px] font-medium text-fg">
        {label}
        {optional ? <span className="ml-1 font-normal text-faint">(optional)</span> : null}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cn(FIELD, "h-8", className)} {...rest} />;
});

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Shows `n / max` under the box; turns to a warning near the limit. */
  showCount?: boolean;
}

/** A text box; with `maxLength` and `showCount`, a live character counter. */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, showCount, maxLength, value, ...rest },
  ref,
) {
  const length = typeof value === "string" ? value.length : 0;
  const near = maxLength != null && length > maxLength * 0.9;
  return (
    <div className="relative">
      <textarea
        ref={ref}
        maxLength={maxLength}
        value={value}
        className={cn(FIELD, "min-h-20 resize-y py-2 leading-relaxed", showCount && "pb-6", className)}
        {...rest}
      />
      {showCount && maxLength != null ? (
        <span
          aria-live="polite"
          className={cn(
            "pointer-events-none absolute right-2.5 bottom-1.5 font-mono text-[11px] tabular",
            near ? "text-warn" : "text-faint",
          )}
        >
          {count(length)} / {count(maxLength)}
        </span>
      ) : null}
    </div>
  );
});

// ---------------------------------------------------------------------------------------------
// Select

export interface SelectOption<V extends string = string> {
  value: V;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
}

/** A single-choice dropdown. */
export function Select<V extends string = string>({
  value,
  onValueChange,
  options,
  placeholder,
  label,
  className,
  size = "md",
  id,
  disabled,
}: {
  value: V | undefined;
  onValueChange: (value: V) => void;
  options: SelectOption<V>[];
  placeholder?: string;
  /** Accessible name when there is no visible label. */
  label?: string;
  className?: string;
  size?: "sm" | "md";
  id?: string;
  disabled?: boolean;
}) {
  return (
    <S.Root value={value} onValueChange={(v) => onValueChange(v as V)} disabled={disabled}>
      <S.Trigger
        id={id}
        aria-label={label}
        className={cn(
          FIELD,
          "inline-flex items-center justify-between gap-2 text-left data-[placeholder]:text-faint",
          size === "sm" ? "h-7 px-2.5 text-[13px]" : "h-8",
          className,
        )}
      >
        <S.Value placeholder={placeholder} />
        <S.Icon>
          <ChevronDown className="size-4 text-muted" aria-hidden />
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content
          position="popper"
          sideOffset={4}
          collisionPadding={12}
          className="qp-pop z-50 max-h-[min(360px,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border border-line bg-surface p-1 text-sm text-fg shadow-lg"
        >
          <S.Viewport>
            {options.map((o) => (
              <S.Item
                key={o.value}
                value={o.value}
                disabled={o.disabled}
                className="relative flex cursor-default select-none flex-col rounded-md py-1.5 pr-2 pl-7 outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-bg-subtle"
              >
                <S.ItemIndicator className="absolute top-2 left-2">
                  <Check className="size-3.5 text-accent" aria-hidden />
                </S.ItemIndicator>
                <S.ItemText>{o.label}</S.ItemText>
                {o.hint ? <span className="text-xs text-muted">{o.hint}</span> : null}
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  );
}

// ---------------------------------------------------------------------------------------------
// Switch

/** An on/off switch with its label (the label is clickable). */
export function Switch({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
  className,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <Sw.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className="relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent bg-line-strong transition-colors duration-150 data-[state=checked]:bg-accent disabled:opacity-55"
      >
        <Sw.Thumb className="block size-4 translate-x-0.5 rounded-full bg-surface shadow-sm transition-transform duration-150 data-[state=checked]:translate-x-[18px]" />
      </Sw.Root>
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-fg">
          {label}
        </label>
        {hint ? <p className="text-xs text-muted">{hint}</p> : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Segmented control

/** A small set of mutually exclusive options shown side by side (Linear · Log, Cq · Efficiency). */
export function SegmentedControl<V extends string>({
  value,
  onValueChange,
  options,
  label,
  size = "md",
  className,
}: {
  value: V;
  onValueChange: (value: V) => void;
  options: { value: V; label: ReactNode; title?: string; disabled?: boolean }[];
  /** Accessible name of the group. */
  label: string;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <TG.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onValueChange(v as V)}
      aria-label={label}
      className={cn("inline-flex items-center gap-0.5 rounded-lg border border-line bg-sunken p-0.5", className)}
    >
      {options.map((o) => (
        <TG.Item
          key={o.value}
          value={o.value}
          title={o.title}
          disabled={o.disabled}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2.5 font-medium whitespace-nowrap text-muted transition-colors duration-150 hover:text-fg disabled:opacity-50 data-[state=on]:bg-surface data-[state=on]:text-fg data-[state=on]:shadow-sm [&_svg]:size-3.5",
            size === "sm" ? "h-6 text-xs" : "h-7 text-[13px]",
          )}
        >
          {o.label}
        </TG.Item>
      ))}
    </TG.Root>
  );
}

// ---------------------------------------------------------------------------------------------
// Tabs

export const Tabs = Tb.Root;

export function TabsList({ className, children, label }: { className?: string; children: ReactNode; label?: string }) {
  return (
    <Tb.List aria-label={label} className={cn("flex items-center gap-1 overflow-x-auto border-b border-line", className)}>
      {children}
    </Tb.List>
  );
}

export function TabsTrigger({ value, children, count: n }: { value: string; children: ReactNode; count?: number }) {
  return (
    <Tb.Trigger
      value={value}
      className="relative -mb-px inline-flex h-9 items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent px-3 text-sm font-medium text-muted transition-colors hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg"
    >
      {children}
      {n != null ? (
        <span className="rounded-full bg-bg-subtle px-1.5 text-xs text-muted tabular">{count(n)}</span>
      ) : null}
    </Tb.Trigger>
  );
}

export function TabsContent({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <Tb.Content value={value} className={cn("pt-4 outline-none", className)}>
      {children}
    </Tb.Content>
  );
}
