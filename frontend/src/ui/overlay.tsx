/**
 * Floating layers on Radix: Dialog, Sheet (a side drawer), Popover, Tooltip, DropdownMenu.
 * Focus is trapped and returned, Escape closes, and every layer has a shadow (the only things
 * on the page that do).
 */
import { Dialog as D, DropdownMenu as M, Popover as P, Tooltip as T } from "radix-ui";
import { X } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { IconButton } from "./Button";

const LAYER = "z-50 rounded-xl border border-line bg-surface text-fg shadow-lg";

// ---------------------------------------------------------------------------------------------
// Dialog

export interface DialogProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** The element that opens it (optional when controlled). */
  trigger?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Buttons, right-aligned at the bottom. */
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  /** Hide the close button (e.g. a confirmation that must be answered). */
  hideClose?: boolean;
}

const DIALOG_SIZE = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };

/** A modal dialog with a title, an optional description, a body and a footer. */
export function Dialog({
  open,
  onOpenChange,
  trigger,
  title,
  description,
  children,
  footer,
  size = "md",
  hideClose,
}: DialogProps) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      {trigger ? <D.Trigger asChild>{trigger}</D.Trigger> : null}
      <D.Portal>
        <D.Overlay className="qp-fade fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px]" />
        <D.Content
          className={cn(
            LAYER,
            "qp-pop fixed top-1/2 left-1/2 flex max-h-[min(88dvh,820px)] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col outline-none",
            DIALOG_SIZE[size],
          )}
          {...(description ? {} : { "aria-describedby": undefined })}
        >
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 pt-4 pb-3">
            <div className="min-w-0">
              <D.Title className="text-base font-semibold tracking-tight">{title}</D.Title>
              {description ? (
                <D.Description className="mt-1 text-[13px] text-muted">{description}</D.Description>
              ) : null}
            </div>
            {hideClose ? null : (
              <D.Close asChild>
                <IconButton label="Close" size="sm" className="-mr-1.5">
                  <X />
                </IconButton>
              </D.Close>
            )}
          </div>
          {children ? (
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm">{children}</div>
          ) : null}
          {footer ? (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line bg-surface-2 px-5 py-3 rounded-b-xl">
              {footer}
            </div>
          ) : null}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

export const DialogClose = D.Close;

// ---------------------------------------------------------------------------------------------
// Sheet (drawer)

export interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  side?: "right" | "left" | "bottom";
  /** Width of a side sheet (px); a bottom sheet takes the full width. */
  width?: number;
  children: ReactNode;
  footer?: ReactNode;
  /** Extra buttons next to the close button. */
  actions?: ReactNode;
  /** Keep the page behind usable (no overlay, no focus trap): e.g. the Ask drawer on wide screens. */
  modal?: boolean;
  /** Start a side sheet this many px below the top (e.g. under a top bar). */
  offsetTop?: number;
}

/** A drawer from the side (Ask, details) or the bottom (phones). */
export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  side = "right",
  width = 420,
  children,
  footer,
  actions,
  modal = true,
  offsetTop,
}: SheetProps) {
  const place =
    side === "bottom"
      ? "inset-x-0 bottom-0 max-h-[88dvh] rounded-t-2xl border-t qp-slide-up"
      : side === "left"
        ? "inset-y-0 left-0 border-r qp-slide-left"
        : "inset-y-0 right-0 border-l qp-slide-right";
  return (
    <D.Root open={open} onOpenChange={onOpenChange} modal={modal}>
      <D.Portal>
        {modal ? <D.Overlay className="qp-fade fixed inset-0 z-40 bg-black/30" /> : null}
        <D.Content
          className={cn(
            "fixed z-40 flex flex-col border-line bg-surface text-fg shadow-lg outline-none",
            place,
          )}
          style={
            side === "bottom" ? undefined : { width: `min(${width}px, 100vw)`, top: offsetTop }
          }
          onInteractOutside={modal ? undefined : (e) => e.preventDefault()}
          {...(description ? {} : { "aria-describedby": undefined })}
        >
          <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
            <div className="min-w-0">
              <D.Title className="text-[15px] font-semibold tracking-tight">{title}</D.Title>
              {description ? (
                <D.Description className="mt-0.5 text-[13px] text-muted">
                  {description}
                </D.Description>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {actions}
              <D.Close asChild>
                <IconButton label="Close" size="sm">
                  <X />
                </IconButton>
              </D.Close>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          {footer ? <div className="border-t border-line px-4 py-3">{footer}</div> : null}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

// ---------------------------------------------------------------------------------------------
// Popover

export function Popover({
  trigger,
  children,
  align = "end",
  side = "bottom",
  className,
  open,
  onOpenChange,
  label,
}: {
  trigger: ReactNode;
  children: ReactNode;
  align?: "start" | "center" | "end";
  side?: "top" | "bottom" | "left" | "right";
  className?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Accessible name of the popover's content. */
  label?: string;
}) {
  return (
    <P.Root open={open} onOpenChange={onOpenChange}>
      <P.Trigger asChild>{trigger}</P.Trigger>
      <P.Portal>
        <P.Content
          align={align}
          side={side}
          sideOffset={6}
          collisionPadding={12}
          aria-label={label}
          className={cn(
            LAYER,
            "qp-pop w-80 max-w-[calc(100vw-24px)] p-3 text-sm outline-none",
            className,
          )}
        >
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  );
}

export const PopoverClose = P.Close;

// ---------------------------------------------------------------------------------------------
// Tooltip

/** Mount once at the root: tooltips open after a short delay and move together. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <T.Provider delayDuration={350} skipDelayDuration={200}>
      {children}
    </T.Provider>
  );
}

/** A short hint on hover and focus. Never the only place a meaning is said. */
export function Tooltip({
  content,
  children,
  side = "top",
  align = "center",
  className,
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  className?: string;
}) {
  if (content == null || content === "") return <>{children}</>;
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
          className={cn(
            "qp-fade z-[60] max-w-xs rounded-md bg-fg px-2 py-1 text-xs leading-snug text-bg shadow-md",
            className,
          )}
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}

// ---------------------------------------------------------------------------------------------
// Dropdown menu

export const Menu = M.Root;
export const MenuTrigger = M.Trigger;

export function MenuContent({
  className,
  align = "end",
  ...rest
}: ComponentProps<typeof M.Content>) {
  return (
    <M.Portal>
      <M.Content
        align={align}
        sideOffset={6}
        collisionPadding={12}
        className={cn(LAYER, "qp-pop min-w-48 p-1 text-sm outline-none", className)}
        {...rest}
      />
    </M.Portal>
  );
}

export function MenuItem({
  className,
  icon,
  shortcut,
  children,
  danger,
  ...rest
}: ComponentProps<typeof M.Item> & { icon?: ReactNode; shortcut?: ReactNode; danger?: boolean }) {
  return (
    <M.Item
      className={cn(
        "flex cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-bg-subtle [&_svg]:size-4 [&_svg]:text-muted",
        danger && "text-danger [&_svg]:text-danger",
        className,
      )}
      {...rest}
    >
      {icon}
      <span className="min-w-0 flex-1">{children}</span>
      {shortcut ? <span className="ml-4 text-xs text-muted">{shortcut}</span> : null}
    </M.Item>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <M.Label className="px-2 pt-1.5 pb-1 text-xs font-medium text-muted">{children}</M.Label>;
}

export function MenuSeparator() {
  return <M.Separator className="my-1 h-px bg-line" />;
}
