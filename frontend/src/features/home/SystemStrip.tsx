/**
 * The system strip at the foot of the Open screen (`GET /api/system`): the version, the curve
 * method and its commit, what leaves this machine, whether the audit is installed, the model.
 */
import { Cpu, Network, ShieldCheck, ShieldOff } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import { ErrorPanel, Skeleton } from "@/ui";
import { ModelChip } from "@/features/settings/ModelChip";
import type { SystemView } from "@/shell/data";

function Item({ label, icon, children }: { label: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <dt className="sr-only">{label}</dt>
      {icon ? (
        <span className="shrink-0 text-faint [&_svg]:size-3.5" aria-hidden>
          {icon}
        </span>
      ) : null}
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

export function SystemStrip({
  system,
  error,
  onRetry,
}: {
  system: SystemView | undefined;
  error: unknown;
  onRetry: () => void;
}) {
  if (error && !system) {
    return (
      <ErrorPanel
        compact
        error={error}
        title="What this install is could not be read"
        onRetry={onRetry}
      />
    );
  }
  return (
    <footer className="border-t border-line pt-5 text-xs text-muted" aria-label="This install">
      {system ? (
        <>
          <dl className="flex flex-wrap items-center gap-x-6 gap-y-2.5">
            <Item label="Version">
              <span className="font-medium text-fg">qPilot {system.version}</span>
            </Item>
            <Item label="Model">
              <span className="inline-flex items-center gap-2">
                <ModelChip model={system.model} />
                <Link href="/settings" className="text-accent underline-offset-2 hover:underline">
                  Settings
                </Link>
              </span>
            </Item>
            <Item label="Curve method" icon={<Cpu />}>
              <span className="font-mono">{system.method}</span>
            </Item>
            <Item label="What leaves this machine" icon={<Network />}>
              {system.model.outbound}
            </Item>
            <Item
              label="Robustness audit"
              icon={system.simulator ? <ShieldCheck /> : <ShieldOff />}
            >
              {system.simulator
                ? "Robustness audit installed"
                : "Robustness audit not installed (pip install -e '.[sim]')"}
            </Item>
          </dl>
          <ul className="mt-3 flex flex-col gap-0.5 text-faint sm:flex-row sm:flex-wrap sm:gap-x-4">
            {system.never.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      ) : (
        <div className="flex flex-wrap gap-6" role="status">
          <span className="sr-only">Loading…</span>
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-56" />
          <Skeleton className="h-4 w-64" />
        </div>
      )}
    </footer>
  );
}
