/** The four steps to Prism and back, each with its state; a step jumps to its card. */
import { Check } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Flow } from "./flow";

export const STEP_ANCHOR: Record<Flow["steps"][number]["id"], string> = {
  choices: "prism-step-project",
  draft: "prism-step-project",
  send: "prism-step-send",
  roundtrip: "prism-step-roundtrip",
};

export function Steps({ flow }: { flow: Flow }) {
  return (
    <nav aria-label="Steps to Prism and back">
      <ol className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {flow.steps.map((step, i) => {
          const current = step.state === "current";
          return (
            <li key={step.id}>
              <a
                href={`#${STEP_ANCHOR[step.id]}`}
                onClick={(e) => {
                  // the page is hash-routed: scroll to the card without touching the route
                  e.preventDefault();
                  const el = document.getElementById(STEP_ANCHOR[step.id]);
                  el?.scrollIntoView({ behavior: "smooth", block: "start" });
                  el?.focus({ preventScroll: true });
                }}
                aria-current={current ? "step" : undefined}
                className={cn(
                  "flex h-full items-start gap-2.5 rounded-xl border p-3 transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                  current
                    ? "border-accent/50 bg-accent-soft"
                    : "border-line bg-surface hover:border-line-strong",
                )}
              >
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold",
                    step.state === "done"
                      ? "border border-ok/40 bg-ok-soft text-ok"
                      : current
                        ? "bg-accent text-accent-fg"
                        : "border border-line-strong text-muted",
                  )}
                  aria-hidden
                >
                  {step.state === "done" ? <Check className="size-3.5" /> : i + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium text-fg">{step.title}</span>
                  <span className="block text-[12px] text-muted">
                    <span className="sr-only">
                      {step.state === "done" ? "Done: " : current ? "Next: " : "Later: "}
                    </span>
                    {step.detail}
                  </span>
                </span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
