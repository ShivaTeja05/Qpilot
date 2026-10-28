/**
 * Curves (docs/app.md §4) — blind. Check the curves (a job), the Curve Judge's disagreements and
 * the call-rule proposal to decide, then confirm; the plate heatmap (call, Cq, efficiency, R² or
 * sample type, by gene), the curve viewer for the wells picked on it, and their melt curves
 * (−dF/dT, peaks and the assay's product Tm: rule G-MELT, `./melt`). Nothing here shows a
 * group, a fold change or a p-value: the server withholds them until the design and the curves
 * are confirmed, and the plate map has no group field.
 *
 * Route: `#/s/<sid>/curves[/<plate>[/<well,well,…>]]` — the plate and the chosen wells, so a link
 * from elsewhere (a proposal's evidence, a sample in Gene) opens the well's curve.
 */
import { CheckCircle2, Lock } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useLocation } from "wouter";
import type { PlateLayer } from "@/charts/plate";
import { cn } from "@/lib/cn";
import { useMediaQuery } from "@/lib/hooks";
import { pathOf, useGo } from "@/shell/route";
import type { SectionProps } from "@/shell/sections";
import { Button, EmptyState, JobCard, LoadingBlock, PageHeader } from "@/ui";
import type { Proposal } from "@/lib/vocab";
import { ConfirmStage, StageInbox, useStageProposals, type InboxFilter } from "@/ui/proposal";
import { usePlate } from "./api";
import { CheckCurvesJob, CheckCurvesPanel, useCheckCurves } from "./CheckCurves";
import { CurvePanel } from "./CurvePanel";
import { MeltPanel } from "./melt";
import { ALL_GENES, PlatePanel } from "./PlatePanel";
import { StageBar } from "./StageBar";

export default function CurvesSection({ workspace, rest }: SectionProps) {
  const go = useGo();
  if (!workspace) return null;
  if (workspace.kind !== "session") {
    return (
      <>
        <PageHeader title="Curves" />
        <EmptyState icon={<Lock />} title="Curves belong to a Studio session">
          This study was analysed outside Studio (by <code>qpilot run</code> or an agent), so there
          is no curves stage to decide here. Open the file in Studio to check its curves.
        </EmptyState>
      </>
    );
  }
  if (workspace.warming) {
    // Stages come with the file's facts; until the first read is done nothing is known yet.
    const job = workspace.active_jobs.find((j) => j.kind === "warm");
    return (
      <>
        <PageHeader eyebrow="Studio · blind" title="Curves" />
        {job ? (
          <JobCard job={job} />
        ) : (
          <LoadingBlock
            label="Reading the file for the first time since qPilot started"
            lines={4}
          />
        )}
      </>
    );
  }
  const design = workspace.stages.find((s) => s.stage === "design");
  if (!design?.confirmed) {
    return (
      <>
        <PageHeader
          eyebrow="Studio · blind"
          title="Curves"
          hint="Which wells amplified, and where the Curve Judge reads a curve differently."
        />
        <EmptyState
          icon={<Lock />}
          title="Confirm the design first"
          action={
            <Button variant="primary" onClick={() => go("design")}>
              Go to Design
            </Button>
          }
        >
          The curves are checked against the design: which wells are study samples, standards and
          controls. Once the design is confirmed, Check the curves runs here.
        </EmptyState>
      </>
    );
  }
  return <CurvesStage workspace={workspace} rest={rest} />;
}

function CurvesStage({
  workspace,
  rest,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  rest: string[];
}) {
  const sid = workspace.key;
  const go = useGo();
  const [, navigate] = useLocation();
  const curves = workspace.stages.find((s) => s.stage === "curves");
  const confirmed = Boolean(curves?.confirmed);
  const waiting = curves?.pending ?? 0;
  const check = useCheckCurves(workspace);
  const inbox = useStageProposals(sid, "curves");
  const proposals = inbox.data?.proposals;

  // The plate and the chosen wells live in the address, so links and reloads keep them.
  const runParam = rest[0] ?? null;
  const wells = (rest[1] ?? "").split(",").filter(Boolean);
  const plate = usePlate(sid, runParam);
  // The address wins: while another plate loads, the one still on screen is not the one chosen.
  const run = runParam ?? plate.data?.run.run_id ?? null;
  const setPlace = useCallback(
    (nextRun: string | null, nextWells: readonly string[]) => {
      const parts = nextRun ? [nextRun, ...(nextWells.length ? [nextWells.join(",")] : [])] : [];
      navigate(pathOf("s", sid, "curves", ...parts), { replace: true });
    },
    [navigate, sid],
  );

  const [gene, setGene] = useState<string>(ALL_GENES);
  const [layer, setLayer] = useState<PlateLayer>("call");
  const [filter, setFilter] = useState<InboxFilter | null>(null);
  const curveRef = useRef<HTMLDivElement>(null);
  const wide = useMediaQuery("(min-width: 1440px)");

  // A plate opened by a link (or a proposal) shows under its own gene when a gene is chosen.
  const targets = plate.data?.run.targets ?? [];
  const shownGene =
    gene !== ALL_GENES && targets.length && !targets.includes(gene) ? targets[0]! : gene;

  /** Show one well: its plate, the well chosen, its curve (scrolled into view when asked). */
  const showWell = useCallback(
    (key: string, scroll: boolean) => {
      const at = key.lastIndexOf("/");
      if (at < 0) return;
      setPlace(key.slice(0, at), [key.slice(at + 1)]);
      if (scroll)
        requestAnimationFrame(() =>
          curveRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }),
        );
    },
    [setPlace],
  );
  const openWell = useCallback((key: string) => showWell(key, true), [showWell]);

  // Moving through the inbox (j / k, or a click on a card) shows that card's well and curve.
  const lastFocus = useRef<string | null>(null);
  const focusProposal = useCallback(
    (p: Proposal | null) => {
      const id = p?.id ?? null;
      if (id === lastFocus.current) return;
      lastFocus.current = id;
      if (p?.kind === "curve.well_call") showWell(p.subject, false);
    },
    [showWell],
  );

  // The chosen well's waiting proposal, so the curve panel can show it in the inbox.
  const waitingFor = useMemo(() => {
    const m = new Map<string, Proposal>();
    for (const p of proposals ?? [])
      if (p.status === "proposed" && p.kind === "curve.well_call") m.set(p.subject, p);
    return m;
  }, [proposals]);
  const showProposalOf = useCallback(
    (key: string) =>
      setFilter({
        label: `well ${key.slice(key.lastIndexOf("/") + 1)}`,
        match: (p) => p.kind === "curve.well_call" && p.subject === key,
      }),
    [],
  );

  /** One plate with its waiting proposals: the plate on the call layer, the inbox filtered to it. */
  const showPlate = useCallback(
    (runId: string) => {
      setPlace(runId, []);
      setLayer("call");
      setFilter({
        label: `plate ${runId}`,
        match: (p) => p.kind === "curve.well_call" && p.subject.startsWith(`${runId}/`),
      });
    },
    [setPlace],
  );

  const reviewing = waiting > 0 && wide;
  const workbench = (
    <div
      className={cn(
        "grid grid-cols-[minmax(0,1fr)] gap-6",
        !reviewing && "min-[1440px]:grid-cols-[minmax(0,7fr)_minmax(0,6fr)]",
      )}
    >
      <PlatePanel
        plate={plate.data}
        loading={plate.isPending}
        fetching={plate.isFetching && plate.isPlaceholderData}
        error={plate.error}
        onRetry={() => void plate.refetch()}
        gene={shownGene}
        onGeneChange={setGene}
        onRunChange={(r) => setPlace(r, [])}
        layer={layer}
        onLayerChange={setLayer}
        selected={plate.isPlaceholderData ? [] : wells}
        onSelectedChange={(w) => setPlace(run, w)}
        onActivate={() =>
          curveRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
        }
      />
      <div
        ref={curveRef}
        className={cn("flex min-w-0 scroll-mt-20 flex-col gap-6", reviewing && "order-first")}
      >
        <CurvePanel
          sid={sid}
          run={run}
          wells={wells}
          onClear={() => setPlace(run, [])}
          waitingProposal={(key) => waitingFor.has(key)}
          onShowProposal={showProposalOf}
        />
        <MeltPanel
          sid={sid}
          run={run}
          wells={plate.isPlaceholderData ? [] : wells}
          onPickWells={(w) => setPlace(run, w)}
        />
      </div>
    </div>
  );

  return (
    <div className="min-w-0">
      <PageHeader
        eyebrow="Studio · blind"
        title="Curves"
        hint="Which wells amplified, and where the Curve Judge reads a curve differently from LinRegPCR. No group, fold change or p-value is shown until the design and the curves are confirmed."
        actions={
          proposals?.length ? <ConfirmStage sid={sid} stage="curves" status={curves} /> : null
        }
      />
      <div className="flex min-w-0 flex-col gap-6">
        <StageBar workspace={workspace} check={check} onShowPlate={showPlate} />
        {proposals?.length ? <CheckCurvesJob state={check} /> : null}
        <div
          className={cn(
            "grid grid-cols-[minmax(0,1fr)] gap-6",
            reviewing && "grid-cols-[minmax(0,1fr)_600px] items-start",
          )}
        >
          <section aria-label="Curves proposals" className="min-w-0">
            <StageInbox
              sid={sid}
              stage="curves"
              resultsVisible={workspace.results_visible}
              onOpenWell={openWell}
              onFocusProposal={focusProposal}
              filter={filter}
              onClearFilter={() => setFilter(null)}
              label="Curves proposals waiting for you"
              empty={
                confirmed ? (
                  <EmptyState compact icon={<CheckCircle2 />} title="No curves proposals">
                    The curves stage was confirmed with LinRegPCR’s calls; nothing was proposed.
                  </EmptyState>
                ) : (
                  <CheckCurvesPanel state={check} />
                )
              }
              allDecided={
                confirmed ? null : (
                  <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
                    <p className="text-[13px] text-muted">
                      Next: confirm the curves. It shows exactly what it covers first; then the
                      results are shown.
                    </p>
                    <div className="ml-auto">
                      <ConfirmStage sid={sid} stage="curves" status={curves} size="sm" />
                    </div>
                  </div>
                )
              }
            />
            {confirmed && proposals?.length ? (
              <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
                <p className="text-[13px] text-muted">
                  The design and the curves are confirmed: the results are shown now.
                </p>
                <Button className="ml-auto" variant="primary" onClick={() => go("results")}>
                  Go to Results
                </Button>
              </div>
            ) : null}
          </section>
          {/* One tree in both layouts, so switching never remounts the plate or the curve. */}
          <div
            className={cn(
              "min-w-0",
              reviewing && "sticky top-[68px] max-h-[calc(100dvh-84px)] overflow-y-auto",
            )}
          >
            {workbench}
          </div>
        </div>
      </div>
    </div>
  );
}
