/** Open's file card in the online demo: opening a file needs qPilot on your own computer. */
import { FileUp, Lock } from "lucide-react";
import { useId } from "react";
import { Button } from "@/ui";
import { QUICKSTART } from "./words";

export function DemoOpenFile() {
  const titleId = useId();
  const whyId = useId();
  return (
    <section
      aria-labelledby={titleId}
      className="relative flex h-full flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-line-strong bg-surface px-6 py-10 text-center sm:py-12"
    >
      <div
        className="flex size-14 items-center justify-center rounded-2xl border border-line bg-surface-2 text-muted [&_svg]:size-6"
        aria-hidden
      >
        <Lock />
      </div>
      <div className="max-w-md">
        <h2 id={titleId} className="text-lg font-semibold tracking-tight text-fg">
          Open your instrument's files
        </h2>
        <p id={whyId} className="mt-1.5 text-[13px] leading-relaxed text-muted">
          This online demo is read-only: it shows qPilot on the public demo study. To open an RDML
          file or an instrument export (Bio-Rad CFX, QuantStudio, LightCycler 480, a tidy table),
          install qPilot; it runs on your computer and your files stay there.
        </p>
      </div>
      <Button variant="primary" size="lg" icon={<FileUp />} disabled aria-describedby={whyId}>
        Choose files…
      </Button>
      <a
        href={QUICKSTART}
        target="_blank"
        rel="noreferrer noopener"
        className="text-[13px] font-medium text-accent-strong underline underline-offset-2"
      >
        Install qPilot (Quickstart)<span className="sr-only"> (opens in a new tab)</span>
      </a>
    </section>
  );
}
