/**
 * The timeline scrubber: every point the map can show (the analysis this one replaced, then
 * each step of the decision chain, from the study as analysed to its head) with the Studio's
 * stage runs between them. ← / → (and Home / End) move between points; each point shows who
 * acted (person, agent, qPilot) and what it changed. Play replays the chain from the start.
 */
import {
  Activity,
  ArrowRight,
  Bot,
  ChevronLeft,
  ChevronRight,
  Cog,
  FileDigit,
  Hourglass,
  LayoutGrid,
  ListChecks,
  Pause,
  Play,
  Send,
  ShieldCheck,
  Undo2,
  Unlink,
  User,
  History as HistoryIcon,
} from "lucide-react";
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { count, plural } from "@/lib/format";
import { Button, Card, CardHeader, IconButton, Tooltip } from "@/ui";
import type { StudioMilestone } from "./api";
import { pointsOf, type Point, type TrackItem } from "./model";
import { pointTitle, STAGE_WORD } from "./words";

const ACTOR_ICON: Record<string, ReactNode> = {
  human: <User aria-hidden />,
  agent: <Bot aria-hidden />,
  system: <Cog aria-hidden />,
};

const STAGE_ICON: Record<string, ReactNode> = {
  design: <LayoutGrid aria-hidden />,
  curves: <Activity aria-hidden />,
  choices: <ListChecks aria-hidden />,
  prism: <Send aria-hidden />,
  other: <ListChecks aria-hidden />,
};

function pointIcon(point: Point): ReactNode {
  if (point.kind === "earlier") return <HistoryIcon aria-hidden />;
  if (point.step.kind === "start") return <FileDigit aria-hidden />;
  return ACTOR_ICON[point.step.actor ?? "system"];
}

/** What a point changed, as a short chip under it (calls first, then folds). */
function changeChip(point: Point): { text: string; tone: "warn" | "info" | "faint" } | null {
  if (point.kind === "earlier") return null;
  const c = point.step.conclusions;
  if (!c) return point.step.kind === "start" ? null : { text: "not replayable", tone: "faint" };
  if (c.n_changed) return { text: plural(c.n_changed, "call") + " changed", tone: "warn" };
  if (c.n_moved) return { text: plural(c.n_moved, "fold") + " moved", tone: "info" };
  return point.step.kind === "start" ? null : { text: "no change", tone: "faint" };
}

function shortLabel(point: Point): string {
  if (point.kind === "earlier") return "Earlier analysis";
  const s = point.step;
  if (s.kind === "start") return "As analysed";
  return s.option_label ?? s.option ?? "";
}

function PointNode({
  point,
  selected,
  focusable,
  onSelect,
  onKeyDown,
  setRef,
}: {
  point: Point;
  selected: boolean;
  focusable: boolean;
  onSelect: () => void;
  onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void;
  setRef: (el: HTMLButtonElement | null) => void;
}) {
  const step = point.kind === "step" ? point.step : null;
  const broken = step ? !step.link_ok : false;
  const pending = step?.status === "pending_human";
  const turnedDown = step?.status === "rejected";
  const chip = changeChip(point);
  return (
    <li className="relative flex w-[132px] shrink-0 flex-col items-center text-center">
      <span aria-hidden className="absolute top-[22px] left-0 right-0 h-px bg-line-strong" />
      <button
        ref={setRef}
        type="button"
        tabIndex={focusable ? 0 : -1}
        aria-current={selected ? "step" : undefined}
        aria-label={pointTitle(point)}
        onClick={onSelect}
        onKeyDown={onKeyDown}
        className={cn(
          "group relative z-10 flex flex-col items-center gap-1.5 rounded-lg px-1 pb-1 outline-none",
          "focus-visible:ring-2 focus-visible:ring-focus",
        )}
      >
        <span
          className={cn(
            "relative grid size-11 place-items-center rounded-full border-2 bg-surface transition-[border-color,background-color,box-shadow] duration-150 ease-out [&_svg]:size-[18px]",
            selected
              ? "border-accent bg-accent-soft text-accent-strong shadow-[0_0_0_4px_var(--accent-soft)]"
              : "border-line-strong text-muted group-hover:border-accent/60 group-hover:text-fg",
            point.kind === "earlier" && "border-dashed",
            pending && "border-dashed border-warn text-warn",
            broken && "border-danger text-danger",
          )}
        >
          {broken ? <Unlink aria-hidden /> : pointIcon(point)}
          {step?.undo ? (
            <span className="absolute -bottom-1 -left-1 grid size-5 place-items-center rounded-full border border-line bg-surface text-muted [&_svg]:size-3">
              <Undo2 aria-hidden />
            </span>
          ) : null}
          {pending ? (
            <span className="absolute -bottom-1 -left-1 grid size-5 place-items-center rounded-full border border-warn/40 bg-warn-soft text-warn [&_svg]:size-3">
              <Hourglass aria-hidden />
            </span>
          ) : null}
          {step?.audited ? (
            <span className="absolute -top-1 -right-1 grid size-5 place-items-center rounded-full border border-ok/40 bg-ok-soft text-ok [&_svg]:size-3">
              <ShieldCheck aria-hidden />
            </span>
          ) : null}
        </span>
        <span className="font-mono text-[11px] text-faint tabular">
          {point.kind === "earlier" ? point.study.study_id.slice(0, 8) : `#${point.step.seq}`}
        </span>
        <span
          className={cn(
            "line-clamp-2 max-w-[124px] text-[12px] leading-4",
            selected ? "font-semibold text-fg" : "text-muted",
            turnedDown && "line-through",
          )}
        >
          {shortLabel(point)}
        </span>
      </button>
      {chip ? (
        <span
          className={cn(
            "mt-0.5 rounded-md px-1.5 text-[11px] leading-5",
            chip.tone === "warn" && "bg-warn-soft text-warn",
            chip.tone === "info" && "bg-info-soft text-info",
            chip.tone === "faint" && "text-faint",
          )}
        >
          {chip.text}
        </span>
      ) : null}
    </li>
  );
}

function MilestoneNode({
  milestone,
  open,
  onOpen,
}: {
  milestone: StudioMilestone;
  open: boolean;
  onOpen: () => void;
}) {
  const range =
    milestone.first_seq === milestone.last_seq
      ? `#${milestone.first_seq}`
      : `#${milestone.first_seq}–${milestone.last_seq}`;
  return (
    <li className="relative flex w-[108px] shrink-0 flex-col items-center text-center">
      <span
        aria-hidden
        className="absolute top-[22px] left-0 right-0 h-px border-t border-dashed border-line-strong"
      />
      <Tooltip content={milestone.title}>
        <button
          type="button"
          onClick={onOpen}
          aria-expanded={open}
          aria-label={`Studio, ${milestone.title}. Show what happened.`}
          className={cn(
            "relative z-10 mt-[11px] flex h-6 items-center gap-1 rounded-md border bg-surface-2 px-2 text-[11px] font-medium outline-none [&_svg]:size-3",
            "focus-visible:ring-2 focus-visible:ring-focus",
            open ? "border-accent text-fg" : "border-line text-muted hover:text-fg",
            !milestone.chain_intact && "border-danger text-danger",
          )}
        >
          {STAGE_ICON[milestone.stage]}
          {STAGE_WORD[milestone.stage]}
          {milestone.confirmed ? <span aria-hidden>✓</span> : null}
        </button>
      </Tooltip>
      <span className="mt-[18px] font-mono text-[11px] text-faint tabular">{range}</span>
      <span className="text-[11px] text-faint">Studio log</span>
    </li>
  );
}

export function Timeline({
  track,
  selected,
  onSelect,
  openMilestone,
  onMilestone,
  onOpenStudy,
  playing,
  onPlay,
  chainWords,
}: {
  track: TrackItem[];
  selected: string;
  onSelect: (id: string) => void;
  openMilestone: string | null;
  onMilestone: (id: string) => void;
  onOpenStudy: (studyId: string) => void;
  playing: boolean;
  onPlay: (play: boolean) => void;
  chainWords: ReactNode;
}) {
  const points = pointsOf(track);
  const index = Math.max(
    0,
    points.findIndex((p) => p.id === selected),
  );
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const scroller = useRef<HTMLDivElement>(null);

  // keep the selected point in view (a long chain scrolls sideways)
  useEffect(() => {
    const el = refs.current.get(selected);
    const box = scroller.current;
    if (!el || !box) return;
    const at = el.getBoundingClientRect();
    const frame = box.getBoundingClientRect();
    const left = box.scrollLeft + at.left - frame.left - box.clientWidth / 2 + at.width / 2;
    box.scrollTo?.({ left: Math.max(0, left) });
  }, [selected, track.length]);

  const go = (i: number, focus: boolean) => {
    const p = points[Math.max(0, Math.min(points.length - 1, i))];
    if (!p) return;
    onSelect(p.id);
    if (focus) refs.current.get(p.id)?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const keys: Record<string, number> = {
      ArrowLeft: index - 1,
      ArrowRight: index + 1,
      Home: 0,
      End: points.length - 1,
    };
    if (e.key in keys) {
      e.preventDefault();
      onPlay(false);
      go(keys[e.key]!, true);
    }
  };

  const atEnd = index >= points.length - 1;
  return (
    <Card as="section" aria-labelledby="timeline-title">
      <CardHeader
        id="timeline-title"
        title="Timeline"
        hint="Every point of this analysis' history: pick one (or use ← and →) and the map shows the calls in force then. Studio runs show what happened to the file between them."
        actions={
          <div className="flex items-center gap-1">
            <IconButton
              label="Previous point"
              size="sm"
              variant="secondary"
              disabled={index === 0}
              onClick={() => {
                onPlay(false);
                go(index - 1, false);
              }}
            >
              <ChevronLeft />
            </IconButton>
            <Button
              size="sm"
              variant={playing ? "secondary" : "primary"}
              icon={playing ? <Pause /> : <Play />}
              disabled={points.length < 2}
              onClick={() => {
                if (playing) return onPlay(false);
                if (atEnd) onSelect(points[0]!.id);
                onPlay(true);
              }}
            >
              {playing ? "Pause" : atEnd ? "Replay from the start" : "Play"}
            </Button>
            <IconButton
              label="Next point"
              size="sm"
              variant="secondary"
              disabled={atEnd}
              onClick={() => {
                onPlay(false);
                go(index + 1, false);
              }}
            >
              <ChevronRight />
            </IconButton>
          </div>
        }
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-y border-line bg-sunken/60 px-4 py-2 text-[13px]">
        <span className="text-muted">
          Point <span className="font-mono text-fg tabular">{count(index + 1)}</span> of{" "}
          <span className="font-mono text-fg tabular">{count(points.length)}</span>
        </span>
        {chainWords}
      </div>
      <div ref={scroller} className="overflow-x-auto overscroll-x-contain">
        <ol
          aria-label="History of this analysis"
          className="flex min-w-max items-start px-3 pt-4 pb-3"
        >
          {track.map((item) => {
            if (item.kind === "point")
              return (
                <PointNode
                  key={item.id}
                  point={item.point}
                  selected={item.id === selected}
                  focusable={item.id === selected}
                  onSelect={() => {
                    onPlay(false);
                    onSelect(item.id);
                  }}
                  onKeyDown={onKeyDown}
                  setRef={(el) => {
                    if (el) refs.current.set(item.id, el);
                    else refs.current.delete(item.id);
                  }}
                />
              );
            if (item.kind === "milestone")
              return (
                <MilestoneNode
                  key={item.id}
                  milestone={item.milestone}
                  open={openMilestone === item.id}
                  onOpen={() => onMilestone(item.id)}
                />
              );
            return (
              <li
                key={item.id}
                className="relative flex w-[150px] shrink-0 flex-col items-center text-center"
              >
                <span
                  aria-hidden
                  className="absolute top-[22px] left-0 right-1/2 h-px border-t border-dashed border-line-strong"
                />
                <Button
                  size="sm"
                  variant="ghost"
                  className="relative z-10 mt-[7px] bg-surface"
                  icon={<ArrowRight />}
                  onClick={() => onOpenStudy(item.study.study_id)}
                >
                  Later analysis
                </Button>
                <span className="mt-2 line-clamp-2 max-w-[144px] text-[11px] leading-4 text-faint">
                  {item.study.after ? `After: ${item.study.after}` : item.study.study_id}
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    </Card>
  );
}
