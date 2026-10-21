import { Globe } from "lucide-react";

/** Shown on a hosted public sandbox (QPILOT_HOSTED=1): what this server is, and what it is not. */
export function HostedBanner() {
  return (
    <div
      role="note"
      className="flex items-start gap-2 border-b border-line bg-warn-soft px-4 py-2 text-[13px] text-fg"
    >
      <Globe className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <p>
        <strong className="font-semibold">Public sandbox.</strong> Shared with every visitor and
        reset when the server restarts — don&apos;t upload confidential data. To keep your data on
        your computer, install qPilot (github.com/ShivaTeja05/Qpilot) and run{" "}
        <code className="font-mono">qpilot app</code>. Research use only.
      </p>
    </div>
  );
}
