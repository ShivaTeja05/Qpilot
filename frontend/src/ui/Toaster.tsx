import { Toaster as Sonner, toast } from "sonner";
import { useTheme } from "@/lib/theme";

/**
 * The toast layer (mount once, in the shell), themed with the page's tokens. Use `toast` from
 * here for every write: `toast.success("Accepted 12 proposals", { action: { label: "Undo", onClick } })`.
 * Toasts stay 6 s; give one with an action `duration: 10_000` and an error `duration: Infinity`
 * (it stays until closed) — `useWrite` in `@/shell/writes` does both.
 */
export function Toaster() {
  const { theme } = useTheme();
  return (
    <Sonner
      theme={theme}
      position="bottom-right"
      closeButton
      offset={16}
      mobileOffset={{ bottom: 72 }}
      toastOptions={{
        // Long enough to read and to reach Undo; errors are given Infinity by their callers.
        duration: 6000,
        classNames: {
          toast:
            "!rounded-xl !border !border-line !bg-surface !text-fg !shadow-lg !font-sans !text-sm !gap-2",
          description: "!text-muted !text-[13px]",
          actionButton: "!bg-accent !text-accent-fg !rounded-md !font-medium",
          cancelButton: "!bg-bg-subtle !text-muted !rounded-md",
          closeButton: "!bg-surface !border-line !text-muted",
          success: "[&_[data-icon]]:!text-ok",
          error: "[&_[data-icon]]:!text-danger",
          warning: "[&_[data-icon]]:!text-warn",
          info: "[&_[data-icon]]:!text-info",
        },
      }}
    />
  );
}

export { toast };
