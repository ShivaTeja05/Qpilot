/**
 * A finished audit: the page header (what was audited, when), a notice when decisions were made
 * since, and the four tabs. The tab and the what-if choices live in the URL.
 */
import { History, RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";
import type { SectionProps } from "@/shell/sections";
import { count, relativeTime, shortHash } from "@/lib/format";
import {
  Button,
  ErrorPanel,
  PageHeader,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tooltip,
} from "@/ui";
import { useAuditOverview, useRunAudit, type AuditTarget } from "./api";
import { HowTab } from "./HowTab";
import { StudyTab } from "./StudyTab";
import type { AuditStatus, Changes } from "./types";
import { TABS, type AuditPlace, type AuditTab } from "./url";
import { VerifyTab } from "./VerifyTab";
import { WhatifTab } from "./WhatifTab";
import { PAGE } from "./layout";

const TAB_LABEL: Record<AuditTab, string> = {
  study: "Study",
  whatif: "What-if lab",
  how: "How it works",
  verify: "Verify",
};

export function AuditReady({
  workspace,
  target,
  status,
  place,
  go,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  target: AuditTarget;
  status: AuditStatus;
  place: AuditPlace;
  go: (next: AuditPlace, replace?: boolean) => void;
}) {
  const manifest = status.manifest ?? {};
  const overview = useAuditOverview(target);
  // Coming back to the lab restores the choices it last showed.
  const lastChanges = useRef<Changes>(place.changes);
  useEffect(() => {
    if (place.tab === "whatif") lastChanges.current = place.changes;
  });

  const audited = manifest.chain_head ?? null;
  const current = workspace.decisions_head ?? null;
  const behind = Boolean(audited && current && audited !== current);
  const analyses = manifest.analyses ?? overview.data?.study.analyses;

  return (
    <div className={PAGE}>
      <PageHeader
        title="Audit"
        hint={
          overview.data ? (
            <>
              {count(analyses)} analyses of {count(overview.data.study.genes)} genes in{" "}
              {count(overview.data.study.samples)} samples: {overview.data.study.group} (
              {overview.data.study.group_def}) against the rest.
            </>
          ) : (
            "Your confirmed study under every combination of eight analysis decisions, and one verdict per gene."
          )
        }
        actions={
          status.created != null ? (
            <Tooltip
              content={`Decision chain ${shortHash(audited, 12)} · lock ${shortHash(manifest.lock_sha256, 12)}`}
            >
              <span
                tabIndex={0}
                className="inline-flex items-center gap-1.5 text-[13px] text-muted"
              >
                <History className="size-3.5" aria-hidden />
                Audited {relativeTime(status.created)}
              </span>
            </Tooltip>
          ) : null
        }
      />

      {behind ? <BehindNotice target={target} /> : null}

      <Tabs
        value={place.tab}
        onValueChange={(v) => {
          const tab = (TABS as readonly string[]).includes(v) ? (v as AuditTab) : "study";
          go({ tab, changes: tab === "whatif" ? lastChanges.current : {} });
        }}
      >
        <TabsList label="Audit views">
          {TABS.map((t) => (
            <TabsTrigger key={t} value={t}>
              {TAB_LABEL[t]}
            </TabsTrigger>
          ))}
        </TabsList>
        {overview.isError ? (
          <ErrorPanel
            className="mt-4"
            error={overview.error}
            title="The audit's views could not be read"
            onRetry={() => void overview.refetch()}
          />
        ) : null}
        <TabsContent value="study">
          <StudyTab
            workspace={workspace}
            target={target}
            overview={overview.data}
            onOpenLab={() => go({ tab: "whatif", changes: {} })}
          />
        </TabsContent>
        <TabsContent value="whatif">
          <WhatifTab
            workspace={workspace}
            target={target}
            overview={overview.data}
            manifest={manifest}
            changes={place.changes}
            onChanges={(changes) => go({ tab: "whatif", changes }, true)}
          />
        </TabsContent>
        <TabsContent value="how">
          <HowTab target={target} manifest={manifest} />
        </TabsContent>
        <TabsContent value="verify">
          <VerifyTab workspace={workspace} target={target} manifest={manifest} dir={status.dir} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Decisions were made after the audit ran: it describes an earlier state of the study. */
function BehindNotice({ target }: { target: AuditTarget }) {
  const run = useRunAudit(target);
  return (
    <div
      role="status"
      className="mb-5 flex flex-wrap items-start gap-3 rounded-xl border border-info/30 bg-info-soft/50 p-4 text-sm"
    >
      <History className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-fg">Decided since this audit</p>
        <p className="mt-0.5 text-[13px] text-muted">
          The audit describes the study as it was before the latest decisions. Its verdicts still
          hold for that state; run it again to include what was decided since. The Verify tab shows
          the chain it is bound to.
        </p>
        {run.isError ? (
          <ErrorPanel compact className="mt-3" error={run.error} title="The audit did not start" />
        ) : null}
      </div>
      <Button
        size="sm"
        variant="secondary"
        icon={<RefreshCw />}
        loading={run.isPending}
        onClick={() => run.mutate()}
      >
        Run the audit again
      </Button>
    </div>
  );
}
