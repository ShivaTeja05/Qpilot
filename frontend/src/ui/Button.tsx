import { Slot } from "radix-ui";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "link";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-accent-fg shadow-sm hover:bg-accent-strong active:translate-y-px disabled:bg-line-strong disabled:text-faint",
  secondary:
    "border border-line-strong bg-surface text-fg shadow-sm hover:bg-surface-2 hover:border-faint active:translate-y-px",
  ghost: "text-muted hover:bg-bg-subtle hover:text-fg",
  danger:
    "border border-danger/30 bg-danger-soft text-danger hover:border-danger/60 active:translate-y-px",
  link: "h-auto px-0 text-accent underline-offset-4 hover:underline",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "h-7 gap-1.5 rounded-md px-2.5 text-[13px]",
  md: "h-8 gap-2 rounded-lg px-3 text-sm",
  lg: "h-10 gap-2 rounded-lg px-4 text-[15px]",
};

// On touch screens icon buttons grow to a 40 px target (WCAG 2.5.8 asks 24, phones want more).
const ICON_SIZE: Record<ButtonSize, string> = {
  sm: "size-7 rounded-md pointer-coarse:size-9",
  md: "size-8 rounded-lg pointer-coarse:size-10",
  lg: "size-10 rounded-lg",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner, keeps the width, and disables the button. */
  loading?: boolean;
  /** An icon before the label (a lucide icon element). */
  icon?: ReactNode;
  /** Render the child element (e.g. an `<a>`) with the button's look. */
  asChild?: boolean;
}

/** The page's button. Primary for the one main action of a view; secondary otherwise. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading,
    icon,
    asChild,
    className,
    children,
    disabled,
    type,
    ...rest
  },
  ref,
) {
  const classes = cn(
    "relative inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap font-medium transition-[background-color,border-color,color,transform] duration-150 ease-out disabled:pointer-events-none disabled:opacity-55 [&_svg]:size-4 [&_svg]:shrink-0",
    SIZE[size],
    VARIANT[variant],
    className,
  );
  if (asChild) {
    return (
      <Slot.Root ref={ref} className={classes} {...rest}>
        {children}
      </Slot.Root>
    );
  }
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className="animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonProps, "icon" | "children"> {
  /** The accessible name (also the tooltip, via `title`, when no tooltip wraps it). */
  label: string;
  children: ReactNode;
}

/** A square button with only an icon; `label` is required for screen readers. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = "ghost", size = "md", className, children, loading, ...rest },
  ref,
) {
  return (
    <Button
      ref={ref}
      variant={variant}
      size={size}
      aria-label={label}
      loading={loading}
      className={cn(ICON_SIZE[size], "px-0", className)}
      {...rest}
    >
      {loading ? null : children}
    </Button>
  );
});
