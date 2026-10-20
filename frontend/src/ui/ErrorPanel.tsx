import { AlertTriangle, KeyRound, RefreshCw, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { Button } from "./Button";

/** The plain words for an error: `ApiError.message` verbatim, anything else generically. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong while reading this.";
}

/**
 * A calm panel for a failed request. Understands {@link ApiError}: `needsKey` (401) says to open
 * the link qPilot printed; `stale` (409) says the view was re-read; `offline` says the server is
 * not answering. `onRetry` adds a "Try again" button.
 */
export function ErrorPanel({
  error,
  title,
  onRetry,
  className,
  children,
  compact,
}: {
  error: unknown;
  /** Overrides the heading (default: chosen from the error). */
  title?: ReactNode;
  onRetry?: () => void;
  className?: string;
  /** Extra actions or text under the message. */
  children?: ReactNode;
  compact?: boolean;
}) {
  const api = error instanceof ApiError ? error : null;
  let icon = <AlertTriangle aria-hidden />;
  let heading: ReactNode = title ?? "This could not be done";
  let message = errorMessage(error);
  let tone = "border-danger/30 bg-danger-soft/50";
  if (api?.needsKey) {
    icon = <KeyRound aria-hidden />;
    heading = title ?? "Open the link qPilot printed in your terminal";
    message =
      "This page needs this launch's key. Use the link `qpilot app` printed when it started (it ends in ?token=…). If qPilot was restarted, its new link has a new key.";
    tone = "border-warn/30 bg-warn-soft/50";
  } else if (api?.stale) {
    icon = <RefreshCw aria-hidden />;
    heading = title ?? "Something was decided since you loaded this";
    message =
      "Another tab or an agent wrote to this study. Here is the current state; look again before you decide.";
    tone = "border-info/30 bg-info-soft/50";
  } else if (api?.code === "offline") {
    icon = <WifiOff aria-hidden />;
    heading = title ?? "qPilot is not answering";
    tone = "border-warn/30 bg-warn-soft/50";
  }
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-xl border text-sm",
        compact ? "p-3" : "p-4",
        tone,
        className,
      )}
    >
      <div className="mt-0.5 shrink-0 text-muted [&_svg]:size-4">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-fg">{heading}</p>
        <p className="mt-1 break-words text-[13px] text-muted">{message}</p>
        {children}
        {onRetry ? (
          <Button size="sm" className="mt-3" icon={<RefreshCw />} onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </div>
    </div>
  );
}
