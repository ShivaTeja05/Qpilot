/**
 * Curves (docs/app.md §4) — blind. Check the curves (a job), the Curve Judge's disagreements and
 * the call-rule proposal to decide, then confirm; the plate heatmap (call, Cq, efficiency, R² or
 * sample type, by gene) and the curve viewer for the wells picked on it. Nothing here shows a
 * group, a fold change or a p-value: the server withholds them until the design and the curves
 * are confirmed, and the plate map has no group field.
 *
 * Route: `#/s/<sid>/curves[/<plate>[/<well,well,…>]]` — the plate and the chosen wells, so a link
 * from elsewhere (a proposal's evidence, a sample in Gene) opens the well's curve.
 */
import { CheckCircle2, Lock } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useLocation } from "wouter";
import type { PlateLayer } from "@/charts/plate";
import { cn } from "@/lib/cn";
import { useMediaQuery } from "@/lib/hooks";
import { pathOf, useGo } from "@/shell/route";
import type { SectionProps } from "@/shell/sections";
import { Button, EmptyState, PageHeader } from "@/ui";
import { usePlate } from "./api";
import { CheckCurves } from "./CheckCurves";
import { CurvePanel } from "./CurvePanel";
import { ALL_GENES, PlatePanel } from "./PlatePanel";
import { StageSummary } from "./StageSummary";

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
  const [, navigate] = useLocation();
  const curves = workspace.stages.find((s) => s.stage === "curves");
  const waiting = curves?.pending ?? 0;

  // The plate and the chosen wells live in the address, so links and reloads keep them.
  const runParam = rest[0] ?? null;
  const wells = (rest[1] ?? "").split(",").filter(Boolean);
  const plate = usePlate(sid, runParam);
  const run = plate.data?.run.run_id ?? runParam;
  const setPlace = useCallback(
    (nextRun: string | null, nextWells: readonly string[]) => {
      const parts = nextRun ? [nextRun, ...(nextWells.length ? [nextWells.join(",")] : [])] : [];
      navigate(pathOf("s", sid, "curves", ...parts), { replace: true });
    },
    [navigate, sid],
  );

  const [gene, setGene] = useState<string>(ALL_GENES);
  const [layer, setLayer] = useState<PlateLayer>("call");
  const curveRef = useRef<HTMLDivElement>(null);
  const wide = useMediaQuery("(min-width: 1440px)");

  // A plate opened by a link (or a proposal) shows under its own gene when a gene is chosen.
  const targets = plate.data?.run.targets ?? [];
  const shownGene =
    gene !== ALL_GENES && targets.length && !targets.includes(gene) ? targets[0]! : gene;

  /** Show one well (from a proposal's evidence): its plate, selected, its curve in view. */
  const openWell = useCallback(
    (key: string) => {
      const at = key.lastIndexOf("/");
      if (at < 0) return;
      setPlace(key.slice(0, at), [key.slice(at + 1)]);
      requestAnimationFrame(() =>
        curveRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }),
      );
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
        selected={wells}
        onSelectedChange={(w) => setPlace(run, w)}
        onActivate={() =>
          curveRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
        }
      />
      <div ref={curveRef} className={cn("min-w-0 scroll-mt-20", reviewing && "order-first")}>
        <CurvePanel sid={sid} run={run} wells={wells} onClear={() => setPlace(run, [])} />
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
          curves?.confirmed ? (
            <span className="inline-flex items-center gap-1.5 text-sm font-medium text-ok">
              <CheckCircle2 className="size-4" aria-hidden /> Curves confirmed
            </span>
          ) : null
        }
      />
      <div className="flex min-w-0 flex-col gap-6">
        <CheckCurves workspace={workspace} />
        <div
          className={cn(
            "grid grid-cols-[minmax(0,1fr)] gap-6",
            reviewing && "grid-cols-[minmax(0,5fr)_minmax(560px,7fr)] items-start",
          )}
        >
          <StageSummary workspace={workspace} onOpenWell={openWell} />
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
