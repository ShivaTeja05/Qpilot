import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Eye } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { useReducedMotion } from "@/lib/hooks";
import { CopyButton, ErrorPanel, Hash, LoadingBlock } from "@/ui";
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
  const data = seen.data;
  const text = data?.state === "shown" ? (data.payload_text ?? "") : "";
  // Opening it (or the payload arriving) brings the panel into view in the conversation.
  const box = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (open)
      box.current?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }, [open, data, reduced]);
  return (
    <div ref={box} className="rounded-lg border border-line">
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
          {seen.isPending ? (
            <LoadingBlock label="Reading the last payload" lines={2} />
          ) : seen.error ? (
            <ErrorPanel compact error={seen.error} onRetry={() => void seen.refetch()} />
          ) : !data || data.state !== "shown" || !text ? (
            <p className="text-muted">
              {data?.state === "none" && model && !model.configured
                ? "No model is configured, so nothing is sent to one: qPilot's templates write every answer."
                : (data?.message ?? "No model call yet in this qPilot process.")}
              {data?.state === "none" && model?.configured
                ? " Payloads are kept in memory only."
                : null}
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs text-muted">
                  {data.message}
                  {data.sha256 ? (
                    <>
                      {" "}
                      <Hash value={data.sha256} prefix="sha256 " />
                    </>
                  ) : null}
                </p>
                <CopyButton text={text} label="Copy the payload" />
              </div>
              <pre className="qp-scroll max-h-72 overflow-auto rounded-md border border-line bg-sunken p-2.5 font-mono text-[11.5px] leading-relaxed break-words whitespace-pre-wrap text-fg">
                {text.length > MAX_SHOWN ? `${text.slice(0, MAX_SHOWN)}\n…` : text}
              </pre>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
