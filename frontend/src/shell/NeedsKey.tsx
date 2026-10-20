import { KeyRound, RefreshCw } from "lucide-react";
import { Button, CommandLine } from "@/ui";
import { Brand } from "./Brand";

/**
 * The one screen for a page opened without this launch's key (401 `no_token`): qPilot serves
 * your studies only to the browser that opened its printed link.
 */
export function NeedsKey({ onRetry, retrying }: { onRetry: () => void; retrying?: boolean }) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg px-4 py-10">
      <main className="w-full max-w-lg rounded-2xl border border-line bg-surface p-6 shadow-md sm:p-8">
        <Brand />
        <div
          className="mt-6 flex size-11 items-center justify-center rounded-full bg-warn-soft text-warn"
          aria-hidden
        >
          <KeyRound className="size-5" />
        </div>
        <h1 className="mt-4 text-xl font-semibold tracking-tight">
          Open the link qPilot printed in your terminal
        </h1>
        <p className="mt-2 text-sm text-muted">
          This page needs the key of this launch of qPilot. When{" "}
          <code className="font-mono text-[12.5px]">qpilot app</code> starts it prints a link that
          ends in <code className="font-mono text-[12.5px]">?token=…</code>; open that link and this
          page remembers the key until qPilot stops. It keeps your studies private to this browser,
          even from other pages on this computer.
        </p>
        <p className="mt-4 text-[13px] font-medium text-fg">
          Not running any more? Start it again:
        </p>
        <CommandLine className="mt-2" command="qpilot app" />
        <p className="mt-2 text-xs text-muted">
          A restart prints a new link with a new key; the old link stops working.
        </p>
        <Button className="mt-6" icon={<RefreshCw />} onClick={onRetry} loading={retrying}>
          I opened the link — try again
        </Button>
        <p className="mt-6 text-[11px] text-faint">
          Research use only. Not for clinical or diagnostic use.
        </p>
      </main>
    </div>
  );
}
