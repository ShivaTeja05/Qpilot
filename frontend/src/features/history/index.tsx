/**
 * History (docs/app.md §7, owner: history): the decision chain as a time machine. A timeline of
 * every point — the analysis this one replaced, the study as analysed, then each decision —
 * with the robustness map gliding between them so the genes a decision moved are seen moving;
 * what each step changed; a diff of any two steps; and the comparison with another analysis of
 * the same file. Every number is the server's, read from the study's own grid.
 */
import { History as HistoryIcon, Link2, ShieldCheck, Unlink } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "wouter";
import { CALLS, CALL_ORDER, LineSwatch, type LegendItem } from "@/charts";
import { count, plural } from "@/lib/format";
import { useReducedMotion } from "@/lib/hooks";
import { sectionPath, type SectionProps } from "@/shell/sections";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  Hash,
  PageHeader,
  Skeleton,
  Switch,
} from "@/ui";
import { AnimatedMap } from "./AnimatedMap";
import { ComparePanel } from "./ComparePanel";
import { DiffPanel } from "./DiffPanel";
import { StepPanel } from "./StepPanel";
import { StudioLog } from "./StudioLog";
import { Timeline } from "./Timeline";
import { useShownComparison } from "@/features/results/comparison";
import { ComparisonPicker } from "@/features/results/ComparisonsPanel";
import { isWarming, useHistory, type HistoryView } from "./api";
import {
  buildTrack,
  earlierStudy,
  flippedGenes,
  mapPoints,
  movedGenes,
  pointsOf,
  stepId,
  type Point,
} from "./model";
import { pointTitle } from "./words";

/** How long Play stays on each point. */
const PLAY_MS = 1800;

function HistorySkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading the history">
      <Skeleton className="h-44 w-full rounded-xl" />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px] [&>*]:min-w-0">
        <Skeleton className="h-[460px] w-full rounded-xl" />
        <Skeleton className="h-[460px] w-full rounded-xl" />
      </div>
    </div>
  );
}

function MapCard({
  view,
  point,
  previous,
  fade,
  onFade,
  onGene,
}: {
  view: HistoryView;
  point: Point;
  previous: Point | null;
  fade: boolean;
  onFade: (on: boolean) => void;
  onGene: (gene: string) => void;
}) {
  const points = useMemo(
    () => mapPoints(point.analysis, point.genes, view.headline),
    [point, view.headline],
  );
  const before = useMemo(
    () => (previous ? mapPoints(previous.analysis, previous.genes, view.headline) : []),
    [previous, view.headline],
  );
  const moved = useMemo(() => movedGenes(before, points), [before, points]);
  const flipped = useMemo(() => flippedGenes(before, points), [before, points]);
  // what to pick out: the genes whose call changed, else every gene that moved
  const focus = flipped.size ? flipped : moved;
  const listed = [...focus].slice(0, 6).join(", ") + (focus.size > 6 ? "…" : "");
  const line = view.min_log2fc;
  const lineFold = `${Number((2 ** line).toPrecision(3))}×`;
  const counts = point.analysis?.counts ?? {};
  const legend: LegendItem[] = [
    ...CALL_ORDER.filter((c) => counts[c]).map((c) => ({
      mark: CALLS[c],
      label: CALLS[c].label,
      count: counts[c] ?? 0,
    })),
    { swatch: <LineSwatch dashed />, label: `${lineFold} line` },
  ];
  const cells = view.n_cells;
  const setWords = cells
    ? `of the ${count(cells)} analyses qPilot checks`
    : "of the analyses qPilot checks";
  const group = view.groups[0];
  const title = pointTitle(point);
  const summary =
    `Robustness map at this point (${title}): ${count(counts.up ?? 0)} genes called up, ` +
    `${count(counts.down ?? 0)} down, ${count(counts.none ?? 0)} with no call` +
    (previous && moved.size
      ? `; since the point before, ${plural(flipped.size, "call")} changed and ${plural(moved.size, "gene")} moved.`
      : ".");

  return (
    <Card as="section" aria-labelledby="history-map-title">
      <CardHeader
        id="history-map-title"
        title="Robustness map at this point"
        hint={`Every gene under the choices in force at the selected point: fold change across, and up, the share ${setWords} that give the same call. Move along the timeline and the genes move with it.`}
        actions={
          <Switch
            checked={fade && Boolean(previous) && focus.size > 0}
            onCheckedChange={onFade}
            label={flipped.size ? "Fade genes whose call stayed" : "Fade genes that did not move"}
            disabled={!previous || !focus.size}
          />
        }
      />
      <CardBody>
        {point.analysis ? (
          <AnimatedMap
            points={points}
            line={line}
            lineLabel={`${lineFold} line`}
            lower={group ? `lower in ${group}` : "lower"}
            higher={group ? `higher in ${group}` : "higher"}
            legend={legend}
            summary={summary}
            setWords={setWords}
            yLabel={
              cells
                ? `Same call in qPilot's choice grid (${count(cells)} analyses)`
                : "Same call in qPilot's choice grid"
            }
            highlight={fade && previous && focus.size ? focus : null}
            onSelect={onGene}
            caption={
              !previous
                ? "Click a gene to open it."
                : flipped.size
                  ? `${plural(flipped.size, "call")} changed since the point before (${listed}); ${plural(moved.size, "gene")} moved. Click a gene to open it.`
                  : moved.size
                    ? `No call changed; ${plural(moved.size, "gene")} moved since the point before (${listed}). Click a gene to open it.`
                    : "No gene moved since the point before. Click a gene to open it."
            }
          />
        ) : (
          <EmptyState
            icon={<HistoryIcon />}
            title="This point cannot be shown on the map"
            compact
            headingLevel={3}
          >
            {view.note ?? "The study's grid of analyses does not hold the analysis in force here."}
          </EmptyState>
        )}
      </CardBody>
    </Card>
  );
}

function ChainWords({ view }: { view: HistoryView }) {
  const entries = view.steps.length - 1;
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted">
      <span className="inline-flex items-center gap-1.5">
        Head <Hash value={view.head} prefix="chain" />
      </span>
      <span>
        <span className="font-mono text-fg tabular">{count(entries)}</span>{" "}
        {entries === 1 ? "decision entry" : "decision entries"}
      </span>
      {view.chain_intact ? (
        <Badge tone="ok" icon={<Link2 />}>
          Intact: every hash checks out
        </Badge>
      ) : (
        <Badge tone="danger" icon={<Unlink />}>
          Broken at entry {view.broken_at ?? "?"}: a line was changed
        </Badge>
      )}
      {view.audit ? (
        <Badge tone={view.audit.current ? "ok" : "warn"} icon={<ShieldCheck />}>
          {view.audit.step != null
            ? `Audited at step ${view.audit.step}${view.audit.current ? "" : " (not the head)"}`
            : "Audited at a head not in this chain"}
        </Badge>
      ) : null}
    </span>
  );
}

function HistoryBody({
  wkey,
  view,
  earlier,
  onGene,
  onOpenStudy,
}: {
  wkey: string;
  view: HistoryView;
  earlier: HistoryView | null;
  onGene: (gene: string) => void;
  onOpenStudy: (id: string) => void;
}) {
  const reduced = useReducedMotion();
  const track = useMemo(() => buildTrack(view, earlier), [view, earlier]);
  const points = useMemo(() => pointsOf(track), [track]);
  const headId = stepId(view.steps[view.steps.length - 1]?.seq ?? 0);
  // null follows the head: a decision made elsewhere moves the map as it lands
  const [chosen, setChosen] = useState<string | null>(null);
  const selected = chosen && points.some((p) => p.id === chosen) ? chosen : headId;
  const index = Math.max(
    0,
    points.findIndex((p) => p.id === selected),
  );
  const point = points[index]!;
  const previous = index > 0 ? points[index - 1]! : null;
  const [playing, setPlaying] = useState(false);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [fade, setFade] = useState(true);
  const head = view.steps[view.steps.length - 1]?.seq ?? 0;
  const [pair, setPair] = useState<[number, number] | null>(null);
  const [from, to] = pair && pair[0] <= head && pair[1] <= head ? pair : [0, head];

  const select = useCallback((id: string) => setChosen(id === headId ? null : id), [headId]);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(
      () => {
        const next = points[index + 1];
        if (next) select(next.id);
        if (!next || index + 1 >= points.length - 1) setPlaying(false);
      },
      reduced ? PLAY_MS / 2 : PLAY_MS,
    );
    return () => window.clearTimeout(timer);
  }, [playing, index, points, select, reduced]);

  return (
    <div className="space-y-6">
      <Timeline
        track={track}
        selected={selected}
        onSelect={select}
        openMilestone={openRun}
        onMilestone={(id) => setOpenRun((open) => (open === id ? null : id))}
        onOpenStudy={onOpenStudy}
        playing={playing}
        onPlay={setPlaying}
        chainWords={<ChainWords view={view} />}
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px] [&>*]:min-w-0">
        <MapCard
          view={view}
          point={point}
          previous={previous}
          fade={fade}
          onFade={setFade}
          onGene={onGene}
        />
        <StepPanel
          wkey={wkey}
          view={view}
          point={point}
          previous={previous}
          onGene={onGene}
          onOpenStudy={onOpenStudy}
        />
      </div>
      {view.steps.length > 1 ? (
        <DiffPanel
          wkey={wkey}
          view={view}
          from={from}
          to={to}
          onChange={(a, b) => setPair([a, b])}
          onGene={onGene}
        />
      ) : null}
      <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
        <ComparePanel wkey={wkey} view={view} onGene={onGene} onOpenStudy={onOpenStudy} />
        <StudioLog
          view={view}
          open={openRun}
          onToggle={(id) => setOpenRun((open) => (open === id ? null : id))}
        />
      </div>
    </div>
  );
}

export default function HistorySection({ workspace }: SectionProps) {
  const [, navigate] = useLocation();
  const key = workspace?.key ?? "";
  const studyId = workspace?.results_visible ? workspace.study_id : null;
  // A study with several comparisons replays one at a time (shared with Results and Trace).
  const [comparison, setComparison] = useShownComparison(studyId);
  const history = useHistory(key, studyId, comparison);
  const view = history.data;
  const prior = view ? earlierStudy(view) : null;
  const earlier = useHistory(key, prior?.study_id ?? null);

  const onGene = useCallback(
    (gene: string) => navigate(sectionPath(workspace, "gene", gene)),
    [navigate, workspace],
  );
  const onOpenStudy = useCallback(
    (id: string) => navigate(sectionPath({ key: id, kind: "study" }, "history")),
    [navigate],
  );

  const header = (
    <PageHeader
      title="History"
      hint="Replay every decision and see what each one changed: the calls in force at every point of the chain, read from this study's own grid of analyses."
    />
  );

  if (!studyId) {
    return (
      <div>
        {header}
        <EmptyState icon={<HistoryIcon />} title="Nothing to replay yet">
          The history shows once this study has results: confirm the design and the curves first.
        </EmptyState>
      </div>
    );
  }
  if (history.isPending || isWarming(history)) {
    return (
      <div>
        {header}
        <HistorySkeleton />
      </div>
    );
  }
  if (history.error || !view) {
    return (
      <div>
        {header}
        <ErrorPanel error={history.error} onRetry={() => history.refetch()} />
      </div>
    );
  }
  return (
    <div>
      {header}
      {!view.replayable && view.note ? (
        <p
          role="note"
          className="mb-4 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-[13px] text-fg"
        >
          {view.note}
        </p>
      ) : null}
      {(view.comparisons ?? []).length > 1 ? (
        <div className="mb-4 flex flex-col gap-1.5" data-testid="history-comparisons">
          <ComparisonPicker
            tabs={view.comparisons}
            value={view.comparison ?? view.comparisons[0]!.id}
            onChange={setComparison}
          />
          {view.comparison_note ? (
            <p className="text-[12.5px] text-muted" role="status">
              {view.comparison_note}
            </p>
          ) : null}
        </div>
      ) : null}
      <HistoryBody
        wkey={key}
        view={view}
        earlier={prior ? (earlier.data ?? null) : null}
        onGene={onGene}
        onOpenStudy={onOpenStudy}
      />
    </div>
  );
}
