/**
 * The Audit section (docs/app.md §4 "Audit"): the robustness audit of the open study. Not run →
 * what it is and Run the audit; running → the job; refused / not applicable / unavailable → the
 * reason in words and what to do; done → Study, What-if lab, How it works and Verify.
 */
import { ShieldCheck } from "lucide-react";
import { useCallback, type ReactNode } from "react";
import { useLocation } from "wouter";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { Button, EmptyState, ErrorPanel, LoadingBlock, PageHeader } from "@/ui";
import {
  attachedAudit,
  studyAudit,
  useAttachedAudits,
  useAuditStatus,
  type AuditTarget,
} from "./api";
import { AuditSources } from "./AuditSources";
import { AuditReady } from "./AuditReady";
import { CannotRun } from "./CannotRun";
import { NotRun } from "./NotRun";
import { parsePlace, placeSegments, type AuditPlace } from "./url";
import { DECISION_ORDER } from "./words";
import { PAGE } from "./layout";

const HINT =
  "Your confirmed study under every combination of eight analysis decisions, and one verdict per gene.";

export default function AuditSection({ workspace, rest }: SectionProps) {
  const [, navigate] = useLocation();
  const studyId = workspace
    ? workspace.kind === "study"
      ? workspace.key
      : workspace.study_id
    : null;
  const place = parsePlace(rest);

  const go = useCallback(
    (next: AuditPlace, replace = false) => {
      if (!workspace) return;
      navigate(sectionPath(workspace, "audit", ...placeSegments(next, DECISION_ORDER)), {
        replace,
      });
    },
    [navigate, workspace],
  );

  if (!workspace || !studyId) {
    return (
      <div className={PAGE}>
        <PageHeader title="Audit" hint={HINT} />
        <EmptyState icon={<ShieldCheck />} title="Nothing to audit yet">
          The audit reads a study's results. Confirm the design and the curves first; the results,
          and then the audit, follow.
        </EmptyState>
      </div>
    );
  }
  return <AuditBody workspace={workspace} studyId={studyId} place={place} go={go} />;
}

function AuditBody({
  workspace,
  studyId,
  place,
  go,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  studyId: string;
  place: AuditPlace;
  go: (next: AuditPlace, replace?: boolean) => void;
}) {
  const attached = useAttachedAudits();
  const sources = attached.data ?? [];
  const switcher = (
    <AuditSources
      sources={sources}
      studyId={studyId}
      value={place.attached}
      onChange={(name) =>
        go({ tab: place.tab === "whatif" ? "study" : place.tab, changes: {}, attached: name })
      }
    />
  );

  if (place.attached) {
    const info = sources.find((a) => a.name === place.attached);
    const back = () => go({ tab: "study", changes: {} });
    if (attached.isPending) {
      return (
        <div className={PAGE}>
          <PageHeader title="Audit" hint={HINT} />
          <LoadingBlock label="Reading the attached audit" lines={4} />
        </div>
      );
    }
    if (!info) {
      return (
        <div className={PAGE}>
          <PageHeader title="Audit" hint={HINT} actions={switcher} />
          <EmptyState
            icon={<ShieldCheck />}
            title={`No audit called “${place.attached}” is attached`}
            action={
              <Button variant="secondary" size="sm" onClick={back}>
                Show this study's audit
              </Button>
            }
          >
            Folders are attached when qPilot starts (qpilot app --audit FOLDER). This one is not, or
            qPilot was restarted without it.
          </EmptyState>
        </div>
      );
    }
    if (!info.available) {
      return (
        <div className={PAGE}>
          <PageHeader title="Audit" hint={HINT} actions={switcher} />
          <CannotRun
            workspace={workspace}
            status={{ status: "not_applicable", reason: info.reason }}
            title={`The attached audit “${info.name}” cannot be shown`}
          />
        </div>
      );
    }
    return (
      <AuditReady
        workspace={workspace}
        target={attachedAudit(workspace.key, studyId, info.name)}
        status={{ views_ready: true }}
        attached={info}
        switcher={switcher}
        place={place}
        go={go}
      />
    );
  }
  return (
    <OwnAudit
      workspace={workspace}
      target={studyAudit(workspace.key, studyId)}
      switcher={switcher}
      place={place}
      go={go}
    />
  );
}

function OwnAudit({
  workspace,
  target,
  switcher,
  place,
  go,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  target: AuditTarget;
  switcher: ReactNode;
  place: AuditPlace;
  go: (next: AuditPlace, replace?: boolean) => void;
}) {
  const status = useAuditStatus(target);

  if (status.isPending) {
    return (
      <div className={PAGE}>
        <PageHeader title="Audit" hint={HINT} />
        <LoadingBlock label="Reading the audit" lines={4} />
      </div>
    );
  }
  if (status.isError) {
    return (
      <div className={PAGE}>
        <PageHeader title="Audit" hint={HINT} actions={switcher} />
        <ErrorPanel
          error={status.error}
          title="The audit could not be read"
          onRetry={() => void status.refetch()}
        />
      </div>
    );
  }
  const s = status.data;
  if (s.status === "ready") {
    return (
      <AuditReady
        workspace={workspace}
        target={target}
        status={s}
        switcher={switcher}
        place={place}
        go={go}
      />
    );
  }
  return (
    <div className={PAGE}>
      <PageHeader title="Audit" hint={HINT} actions={switcher} />
      {s.status === "none" || s.status === "running" || s.status === "failed" ? (
        <NotRun workspace={workspace} target={target} status={s} />
      ) : (
        <CannotRun workspace={workspace} status={s} />
      )}
    </div>
  );
}
