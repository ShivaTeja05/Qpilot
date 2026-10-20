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

const HEADING: Record<string, string> = {
  blind: "Hidden until the design and the curves are confirmed",
  studio: "Not yet",
  refused: "Not allowed",
  not_found: "Not found",
  bad_request: "Check what you entered",
  too_large: "The file is too large",
  bad_file: "qPilot cannot read this file",
  empty_file: "The file is empty",
  no_model: "No model answers",
  cross_origin: "Refused: this request came from another page",
};

/** A heading for an error, from its code (a refusal reads differently from a failure). */
export function errorHeading(error: unknown): string {
  if (error instanceof ApiError && HEADING[error.code]) return HEADING[error.code]!;
  return "Something went wrong";
}

/**
 * Text with `backticks` as code: server messages name commands that way
 * ("Is `qpilot app` still running?"). Text only, never HTML.
 */
export function TickText({ text }: { text: string }) {
  const parts = text.split("`");
  if (parts.length < 3) return <>{text}</>;
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 && i < parts.length - 1 ? (
          <code key={i} className="rounded bg-bg-subtle px-1 font-mono text-[0.92em]">
            {part}
          </code>
        ) : (
          <span key={i}>{i % 2 === 1 ? `\`${part}` : part}</span>
        ),
      )}
    </>
  );
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
  let heading: ReactNode = title ?? errorHeading(error);
  let message = errorMessage(error);
  let tone = "border-danger/30 bg-danger-soft/50";
  if (api?.needsKey) {
    icon = <KeyRound aria-hidden />;
    heading = title ?? "Open the link qPilot printed in your terminal";
    message =
      "This page needs this launch's key. Use the link `qpilot app` printed when it started (it ends in `?token=…`). If qPilot was restarted, its new link has a new key.";
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
        <p className="mt-1 break-words text-[13px] text-muted">
          <TickText text={message} />
        </p>
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
