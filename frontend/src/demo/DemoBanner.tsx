/** The online demo's strip above the top bar: what this is, whose data, and how to get qPilot. */
import { ExternalLink, Eye } from "lucide-react";
import { Dot, Tooltip } from "@/ui";
import { GITHUB, QUICKSTART } from "./words";

export function DemoBanner() {
  return (
    <div
      role="note"
      aria-label="About this online demo"
      className="flex min-h-8 items-center gap-2 border-b border-accent/25 bg-accent-soft px-3 py-1 text-[12.5px] leading-snug text-fg sm:px-4"
    >
      <Eye className="size-3.5 shrink-0 text-accent-strong" aria-hidden />
      <p className="min-w-0 flex-1">
        <span className="font-semibold">Read-only demo</span> on the public Vermeulen 2013
        neuroblastoma study{" "}
        <span className="text-muted">(Vermeulen et al. 2009, Ruijter et al. 2013; CC BY 4.0)</span>{" "}
        —{" "}
        <a
          href={QUICKSTART}
          target="_blank"
          rel="noreferrer noopener"
          className="font-medium text-accent-strong underline underline-offset-2"
        >
          install qPilot
        </a>{" "}
        to analyse your own data.
      </p>
      <a
        href={GITHUB}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-accent-strong underline-offset-2 hover:underline"
      >
        GitHub
        <ExternalLink className="size-3" aria-hidden />
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
    </div>
  );
}

/** The top bar's live dot in the demo: a recording, so nothing arrives live. */
export function DemoDot() {
  const words = "Demo: a recording of qPilot on the demo study; nothing here changes";
  return (
    <Tooltip content={words}>
      <span
        tabIndex={0}
        role="status"
        aria-label={words}
        className="inline-flex h-6 items-center gap-1.5 rounded-full border border-line px-2 text-[11.5px] font-medium text-muted"
      >
        <Dot tone="info" />
        Demo
      </span>
    </Tooltip>
  );
}
