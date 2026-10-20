/**
 * The Audit section (docs/app.md §4 "Audit"): the robustness audit of the open study. Not run →
 * what it is and Run the audit; running → the job; refused / not applicable / unavailable → the
 * reason in words and what to do; done → Study, What-if lab, How it works and Verify.
 */
import { ShieldCheck } from "lucide-react";
import { useCallback } from "react";
import { useLocation } from "wouter";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { EmptyState, ErrorPanel, LoadingBlock, PageHeader, TooltipProvider } from "@/ui";
import { useAuditStatus, type AuditTarget } from "./api";
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
  // TODO(audit): drop this provider once the shell (which mounts one) is merged.
  return (
    <TooltipProvider>
      <AuditBody
        workspace={workspace}
        target={{ workspaceKey: workspace.key, studyId }}
        place={place}
        go={go}
      />
    </TooltipProvider>
  );
}

function AuditBody({
  workspace,
  target,
  place,
  go,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  target: AuditTarget;
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
        <PageHeader title="Audit" hint={HINT} />
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
    return <AuditReady workspace={workspace} target={target} status={s} place={place} go={go} />;
  }
  return (
    <div className={PAGE}>
      <PageHeader title="Audit" hint={HINT} />
      {s.status === "none" || s.status === "running" ? (
        <NotRun workspace={workspace} target={target} status={s} />
      ) : (
        <CannotRun workspace={workspace} status={s} />
      )}
    </div>
  );
}
