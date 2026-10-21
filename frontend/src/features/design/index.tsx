/**
 * Design (blind): what each sample is, the groups, the biological units, the reference genes
 * and the gene symbols, decided proposal by proposal. Left: the inbox (contradicted first).
 * Right, sticky: the plate map of the selected plate and the file's facts. No result, fold
 * change or p-value is shown here; the server refuses them until both blind stages are
 * confirmed.
 */
import { EyeOff, GitCompareArrows } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { count } from "@/lib/format";
import type { Proposal } from "@/lib/vocab";
import { useGo } from "@/shell/route";
import type { SectionProps } from "@/shell/sections";
import { refreshWorkspace, reportWriteError } from "@/shell/writes";
import { Button, Card, CardBody, CardHeader, EmptyState, JobCard, PageHeader, toast } from "@/ui";
import {
  BulkActions,
  ConfirmStage,
  StageInbox,
  StageSummary,
  Warming,
  isWarming,
  useQuotes,
  useStageProposals,
  type InboxFilter,
} from "@/ui/proposal";
import { DesignNeeds } from "./DesignNeeds";
import { comparisonState, concerns } from "./logic";
import { DesignPlate, type PlateWell } from "./DesignPlate";
import { FileFacts } from "./FileFacts";
import { ImportCard } from "./ImportCard";
import { ProposeAgain, ProposeDesignPanel, ProposeReportView } from "./ProposeDesign";
import { WellCurveDialog } from "./WellCurve";

export default function DesignSection({ workspace }: SectionProps) {
  const qc = useQueryClient();
  const go = useGo();
  const sid = workspace?.kind === "session" ? workspace.key : null;
  const list = useStageProposals(sid, "design");
  const quotes = useQuotes(sid);
  const [focus, setFocus] = useState<Proposal | null>(null);
  const [filter, setFilter] = useState<InboxFilter | null>(null);
  const [proposingComparison, setProposingComparison] = useState(false);
  const [well, setWell] = useState<string | null>(null);

  const all = useMemo(() => list.data?.proposals ?? [], [list.data]);
  const comparison = useMemo(() => comparisonState(all), [all]);
  const highlight = useMemo(() => (focus ? (w: PlateWell) => concerns(focus, w) : null), [focus]);
  const onFocusProposal = useCallback((p: Proposal | null) => setFocus(p), []);
  const showWell = useCallback(
    (w: PlateWell) =>
      setFilter({ label: `sample ${w.sample} (well ${w.well})`, match: (p) => concerns(p, w) }),
    [],
  );
  const editOptions = useMemo(() => {
    const groups = new Set<string>();
    const units = new Set<string>();
    for (const p of all) {
      const d = { ...p.payload, ...(p.edits ?? {}) } as Record<string, unknown>;
      if (p.kind === "design.group" && typeof d.group === "string") groups.add(d.group);
      if (p.kind === "design.bio_unit" && typeof d.biological_unit === "string")
        units.add(d.biological_unit);
    }
    return { groups: [...groups].sort(), units: [...units].sort() };
  }, [all]);

  if (!workspace) return null;
  if (!sid) {
    return (
      <EmptyState icon={<EyeOff />} title="Design belongs to a Studio session">
        This study was analysed outside Studio (by <code className="font-mono">qpilot run</code> or
        an agent), so its design was given, not proposed here. Open its file from Open to review a
        design proposal by proposal.
      </EmptyState>
    );
  }

  if (workspace.warming) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader eyebrow="Blind stage 1 of 2" title="Design" />
        <Warming message="qPilot is reading this file for the first time since it started (every name quarantined, every curve fitted once). The design appears here by itself when that is done." />
        {workspace.active_jobs.map((j) => (
          <JobCard key={j.id} id={j.id} />
        ))}
        <div className="max-w-2xl">
          <ImportCard capture={workspace.capture} />
        </div>
      </div>
    );
  }

  const status = workspace.stages.find((s) => s.stage === "design");
  const pending = all.filter((p) => p.status === "proposed" && p.kind !== "stage.confirm").length;
  const confirmed = Boolean(status?.confirmed);
  const proposeJob = workspace.active_jobs.find(
    (j) => j.kind === "propose.design" && (j.status === "queued" || j.status === "running"),
  );
  const otherJobs = workspace.active_jobs.filter(
    (j) =>
      j.key === sid &&
      j.kind !== "propose.design" &&
      (j.status === "queued" || j.status === "running"),
  );
  const summary = workspace.summary;

  const proposeComparison = async () => {
    setProposingComparison(true);
    try {
      const r = await unwrap(
        api.POST("/api/sessions/{sid}/propose/comparison", { params: { path: { sid } } }),
      );
      await refreshWorkspace(qc, sid);
      toast.info(r.message);
    } catch (err) {
      reportWriteError(qc, err, sid);
    } finally {
      setProposingComparison(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Blind stage 1 of 2"
        title="Design"
        hint="What each sample is, the groups, the biological units, the reference genes and the gene symbols. No result is shown until the design and the curves are confirmed, so the design is decided on the evidence, not on the answer it gives."
        actions={
          // One confirm button at a time: here while proposals wait (or once confirmed), under
          // the inbox when everything is decided.
          all.length && (confirmed || pending > 0) ? (
            <ConfirmStage sid={sid} stage="design" status={status} />
          ) : null
        }
      />

      {all.length && status && !confirmed ? (
        <DesignNeeds
          blockers={status.blockers}
          proposals={all}
          onOpen={() => go("home")}
          onSettings={() => go("settings")}
        />
      ) : null}

      {otherJobs.map((j) => (
        <JobCard key={j.id} id={j.id} />
      ))}

      {all.length ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-[13px] text-muted">
            {pending ? (
              <>
                <span className="font-semibold text-fg">{count(pending)}</span> waiting ·{" "}
                <span className="font-semibold text-danger">
                  {count(list.data?.counts.contradicted ?? 0)}
                </span>{" "}
                contradicted
              </>
            ) : confirmed ? (
              "The design is confirmed; it is summarised below. A later decision on a design proposal re-opens this stage."
            ) : (
              "Every design proposal is decided: confirm the stage to open the curves."
            )}
          </p>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {comparison.ready && !confirmed ? (
              <Button
                variant="secondary"
                icon={<GitCompareArrows />}
                loading={proposingComparison}
                onClick={() => void proposeComparison()}
              >
                Propose the comparison
              </Button>
            ) : null}
            {!confirmed ? <BulkActions sid={sid} stage="design" /> : null}
            {!confirmed ? <ProposeAgain sid={sid} disabled={Boolean(proposeJob)} /> : null}
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(340px,420px)]">
        <div className="flex min-w-0 flex-col gap-4">
          {confirmed && all.length ? (
            <Card as="section" aria-labelledby="confirmed-design">
              <CardHeader
                id="confirmed-design"
                title="The confirmed design"
                hint="What the accepted proposals add up to. The engine runs from this and from nothing else."
                level={2}
              />
              <CardBody>
                <StageSummary stage="design" proposals={all} />
              </CardBody>
            </Card>
          ) : null}
          {proposeJob && all.length ? (
            <JobCard id={proposeJob.id}>
              {(result) => <ProposeReportView result={result} />}
            </JobCard>
          ) : null}
          <StageInbox
            sid={sid}
            stage="design"
            resultsVisible={workspace.results_visible}
            empty={<ProposeDesignPanel sid={sid} running={proposeJob} />}
            allDecided={
              confirmed ? null : (
                <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
                  <p className="text-[13px] text-muted">
                    Next: confirm the design. It shows exactly what it covers first.
                  </p>
                  <div className="ml-auto">
                    <ConfirmStage sid={sid} stage="design" status={status} size="sm" />
                  </div>
                </div>
              )
            }
            filter={filter}
            onClearFilter={() => setFilter(null)}
            onFocusProposal={onFocusProposal}
            onOpenWell={setWell}
            editOptions={editOptions}
            label="Design proposals waiting for you"
            arriving={Boolean(proposeJob)}
          />
          {confirmed && all.length ? (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
              <p className="text-[13px] text-muted">
                The curves stage is open: check which wells amplified.
              </p>
              <Button className="ml-auto" variant="primary" onClick={() => go("curves")}>
                Go to Curves
              </Button>
            </div>
          ) : null}
        </div>
        <aside
          className="flex min-w-0 flex-col gap-4 xl:sticky xl:top-20 xl:max-h-[calc(100dvh-6rem)] xl:self-start xl:overflow-y-auto xl:pb-2 qp-scroll"
          aria-label="Plate and file"
        >
          <DesignPlate
            sid={sid}
            runs={summary?.runs ?? []}
            quotes={quotes.lookup}
            highlight={highlight}
            onShowProposals={showWell}
          />
          <FileFacts
            facts={workspace.facts}
            summary={summary}
            analysed={workspace.results_visible}
            warming={isWarming(list.error)}
          />
          <ImportCard capture={workspace.capture} />
        </aside>
      </div>
      <WellCurveDialog sid={sid} well={well} onClose={() => setWell(null)} />
    </div>
  );
}
