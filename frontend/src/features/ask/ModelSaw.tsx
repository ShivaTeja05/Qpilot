import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Eye } from "lucide-react";
import { useId, useState } from "react";
import type { Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { CopyButton, ErrorPanel, LoadingBlock } from "@/ui";
import { getModelSeen } from "./askApi";

/** Longest payload text shown (characters); the copy button copies all of it. */
const MAX_SHOWN = 20_000;

/**
 * "What the model saw": the exact last payload this qPilot process sent to a model, read when
 * the fold-out opens (the server keeps it in memory only and withholds it while a study is blind).
 */
export function ModelSaw({
  workspaceKey,
  model,
  asked,
}: {
  workspaceKey: string;
  model: Schemas["ModelStatus"] | undefined;
  /** Answers so far in this conversation (re-reads the payload after each one). */
  asked: number;
}) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const seen = useQuery({
    queryKey: ["w", workspaceKey, "ask", "model-seen", asked],
    enabled: open,
    queryFn: () => getModelSeen(workspaceKey),
    staleTime: 0,
  });
  const text = seen.data?.payload != null ? JSON.stringify(seen.data.payload, null, 2) : "";
  return (
    <div className="rounded-lg border border-line">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] font-medium text-fg hover:bg-surface-2"
      >
        <ChevronRight
          className={cn("size-4 text-muted transition-transform duration-150", open && "rotate-90")}
          aria-hidden
        />
        <Eye className="size-4 text-muted" aria-hidden />
        What the model saw
        <span className="ml-auto text-xs font-normal text-faint">the last call</span>
      </button>
      {open ? (
        <div id={panel} className="border-t border-line px-3 py-2.5 text-[13px]">
          {model && !model.configured ? (
            <p className="text-muted">
              No model is configured, so nothing is sent to one: qPilot's templates write every
              answer.
            </p>
          ) : seen.isPending ? (
            <LoadingBlock label="Reading the last payload" lines={2} />
          ) : seen.error ? (
            <ErrorPanel compact error={seen.error} onRetry={() => void seen.refetch()} />
          ) : seen.data?.hidden ? (
            <p className="text-muted">
              {seen.data.reason ?? "Withheld until the design and the curves are confirmed."}
            </p>
          ) : !text ? (
            <p className="text-muted">
              No model call yet in this qPilot process. Payloads are kept in memory only.
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs text-muted">
                  {seen.data?.note ??
                    "The exact system prompt and messages of the most recent model call."}
                </p>
                <CopyButton text={text} label="Copy the payload" />
              </div>
              <pre className="qp-scroll max-h-72 overflow-auto rounded-md border border-line bg-sunken p-2.5 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap break-words text-fg">
                {text.length > MAX_SHOWN ? `${text.slice(0, MAX_SHOWN)}\n…` : text}
              </pre>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
