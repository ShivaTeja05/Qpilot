/**
 * A finished audit: the page header (what was audited, when), a notice when decisions were made
 * since, and the four tabs. The tab and the what-if choices live in the URL.
 */
import { History, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { count, plural, relativeTime, shortHash } from "@/lib/format";
import { useSystem } from "@/shell/data";
import {
  Button,
  ErrorPanel,
  PageHeader,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tooltip,
  JobCard,
} from "@/ui";
import type { JobView } from "@/api/client";
import { useJob } from "@/api/jobs";
import {
  useAuditOverview,
  useInvalidateAudit,
  useRunAudit,
  useSeedJob,
  type AuditTarget,
} from "./api";
import { HowTab } from "./HowTab";
import { StudyTab } from "./StudyTab";
import type { AttachedAudit, AuditStatus, Changes } from "./types";
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
  attached,
  switcher,
  place,
  go,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  target: AuditTarget;
  status: AuditStatus;
  /** Set when the audit shown is an attached folder, not the study's own. */
  attached?: AttachedAudit;
  /** Chooses between the study's audit and attached ones. */
  switcher?: ReactNode;
  place: AuditPlace;
  go: (next: AuditPlace, replace?: boolean) => void;
}) {
  const manifest = status.manifest ?? {};
  // Genes open the Gene section only when the audit is about this study.
  const ownStudy = !attached || attached.study_id === target.studyId;
  const geneHref = ownStudy ? (gene: string) => sectionPath(workspace, "gene", gene) : null;
  const goTo = (next: AuditPlace, replace?: boolean) =>
    go({ ...next, attached: attached?.name }, replace);
  const overview = useAuditOverview(target);
  // Coming back to the lab restores the choices it last showed.
  const lastChanges = useRef<Changes>(place.changes);
  useEffect(() => {
    if (place.tab === "whatif") lastChanges.current = place.changes;
  });

  const system = useSystem();
  const audited = manifest.chain_head ?? null;
  const head = workspace.decisions_head ?? null;
  const behind =
    !attached &&
    (status.current != null ? !status.current : Boolean(audited && head && audited !== head));
  const analyses = manifest.analyses ?? overview.data?.study.analyses;
  const dir = system.data?.studies_dir
    ? `${system.data.studies_dir}/simulator_audits/${target.studyId}`
    : null;
  const invalidateAll = useInvalidateAudit(target);
  const invalidate = useCallback(() => void invalidateAll(), [invalidateAll]);
  const loading = !status.views_ready && status.loading ? status.loading : null;

  return (
    <div className={PAGE}>
      <PageHeader
        title="Audit"
        eyebrow={attached ? `Attached: ${attached.name} · ${attached.source}` : undefined}
        hint={
          overview.data ? (
            <>
              {count(analyses)} analyses of {count(overview.data.study.genes)} genes in{" "}
              {count(overview.data.study.samples)} samples: {overview.data.study.group} (
              {overview.data.study.group_def}) against {overview.data.study.rest ?? "the rest"}.
            </>
          ) : (
            "Your confirmed study under every combination of eight analysis decisions, and one verdict per gene."
          )
        }
        actions={
          <>
            {switcher}
            {status.created_at != null ? (
              <Tooltip
                content={`Decision chain ${shortHash(audited, 12)} · lock ${shortHash(manifest.lock_sha256, 12)}`}
              >
                <span
                  tabIndex={0}
                  className="inline-flex items-center gap-1.5 text-[13px] text-muted"
                >
                  <History className="size-3.5" aria-hidden />
                  Audited {relativeTime(status.created_at)}
                </span>
              </Tooltip>
            ) : null}
          </>
        }
      />

      {behind ? <BehindNotice target={target} since={status.decisions_since} /> : null}
      {loading ? (
        <div className="mb-5 space-y-2">
          <p className="text-[13px] text-muted">
            The first look at an audit rebuilds the study it describes and runs the audit's
            reasonable set once; the views open when that is done.
          </p>
          <LoadingViews job={loading} onDone={invalidate} />
        </div>
      ) : null}

      <Tabs
        value={place.tab}
        onValueChange={(v) => {
          const tab = (TABS as readonly string[]).includes(v) ? (v as AuditTab) : "study";
          goTo({ tab, changes: tab === "whatif" ? lastChanges.current : {} });
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
            target={target}
            overview={overview.data}
            geneHref={geneHref}
            onOpenLab={() => goTo({ tab: "whatif", changes: {} })}
          />
        </TabsContent>
        <TabsContent value="whatif">
          <WhatifTab
            target={target}
            overview={overview.data}
            manifest={manifest}
            changes={place.changes}
            geneHref={geneHref}
            onChanges={(changes) => goTo({ tab: "whatif", changes }, true)}
          />
        </TabsContent>
        <TabsContent value="how">
          <HowTab target={target} manifest={manifest} />
        </TabsContent>
        <TabsContent value="verify">
          <VerifyTab
            workspace={workspace}
            target={target}
            manifest={manifest}
            dir={attached ? null : dir}
            attached={Boolean(attached)}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** The job loading the audit's live views; the views are re-read when it is done. */
function LoadingViews({ job: given, onDone }: { job: JobView; onDone: () => void }) {
  useSeedJob(given);
  const id = given.id;
  const job = useJob(id);
  const done = job.data?.status === "done";
  useEffect(() => {
    if (done) onDone();
  }, [done, onDone]);
  return <JobCard id={id} />;
}

/** Decisions were made after the audit ran: it describes an earlier state of the study. */
function BehindNotice({ target, since }: { target: AuditTarget; since?: number }) {
  const run = useRunAudit(target);
  return (
    <div
      role="status"
      className="mb-5 flex flex-wrap items-start gap-3 rounded-xl border border-info/30 bg-info-soft/50 p-4 text-sm"
    >
      <History className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-fg">
          {since ? `${plural(since, "decision")} since this audit` : "Decided since this audit"}
        </p>
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
        onClick={() => run.mutate(true)}
      >
        Run the audit again
      </Button>
    </div>
  );
}
