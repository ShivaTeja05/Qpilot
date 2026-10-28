/**
 * The page: one hash router, the rail, the top bar, the next-step banner and the current
 * section, plus the palette (⌘K), the shortcut sheet (?), the Ask drawer (⌘J) and the toasts.
 * Workspace routes are `/s/<session id>/<section>/...` (a Studio session) and
 * `/r/<study id>/<section>/...` (a study analysed outside one).
 */
import { useQueryClient } from "@tanstack/react-query";
import { FolderX } from "lucide-react";
import { MotionConfig } from "motion/react";
import { Suspense, useEffect, useRef, useState } from "react";
import { Link, Router, useLocation } from "wouter";
import { useHashLocation } from "wouter/use-hash-location";
import { ApiError, type JobView } from "@/api/client";
import { onLiveEvent, useLiveEvents } from "@/api/live";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { useHotkeys, useNow } from "@/lib/hooks";
import {
  Button,
  EmptyState,
  ErrorPanel,
  JobCard,
  LoadingBlock,
  Skeleton,
  Toaster,
  TooltipProvider,
  toast,
} from "@/ui";
import { openShortcuts, requestOpenFile, setPaletteOpen, toggleAsk, useAskOpen } from "./actions";
import { AskFrame } from "./AskFrame";
import { useSystem, useWorkspaceFrame, useWorkspaces, type WorkspaceView } from "./data";
import { LockedSection } from "./Guard";
import { sectionStates, type SectionState } from "./nav";
import { NeedsKey } from "./NeedsKey";
import { HostedBanner } from "./HostedBanner";
import { NextStepBanner } from "./NextStep";
import { G_KEY, Palette } from "./Palette";
import { BottomBar, Rail } from "./Rail";
import { notFoundWords, pathOf, useRoute, type Route } from "./route";
import { SECTION, type SectionId } from "./sections";
import { SectionBoundary } from "./SectionBoundary";
import { ShortcutSheet } from "./Shortcuts";
import { TopBar } from "./TopBar";

/** The section a bare workspace link opens: the next step's, else Design / Results. */
function defaultSection(frame: WorkspaceView): SectionId {
  if (frame.kind !== "session") return "results";
  if (frame.results_visible) return "results";
  const next = frame.next_step?.section;
  if (next && next in SECTION && SECTION[next as SectionId].scope === "workspace")
    return next as SectionId;
  return "design";
}

function SectionSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy>
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Skeleton className="h-72" />
        <Skeleton className="h-72 max-lg:hidden" />
      </div>
      <LoadingBlock className="sr-only" label="Loading this section" lines={1} />
    </div>
  );
}

/**
 * While a workspace's frame loads: the skeleton, then (after 1.5 s) what is happening in words,
 * then (after 15 s) that it is still working and a way back to Open.
 */
function FrameLoading({
  fileName,
  warmJob,
}: {
  fileName?: string | null;
  /** The server's `warm` job: the study is open but its file is being read once after a start. */
  warmJob?: JobView | null;
}) {
  const [started] = useState(() => Date.now());
  const now = useNow(500);
  const waited = (now - started) / 1000;
  const warming = warmJob !== undefined;
  return (
    <div className="flex flex-col gap-4">
      {warming || waited >= 1.5 ? (
        <div role="status" className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight text-fg">Opening the study…</h1>
          <p className="text-[13px] text-muted">
            {warming
              ? `Reading ${fileName ?? "the file"} once after qPilot started (usually a few seconds; on a busy computer up to a minute). This page fills in by itself; nothing about the study is decided or hidden yet.`
              : `${fileName ? `Reading ${fileName}` : "Reading the study"} (usually a few seconds; a large file or a busy computer can take a minute).`}
          </p>
          {waited >= 15 ? (
            <p className="mt-1 text-[13px] text-muted">
              Still working.{" "}
              <Link href="/" className="font-medium text-accent underline-offset-4 hover:underline">
                Back to Open
              </Link>
            </p>
          ) : null}
        </div>
      ) : null}
      {warmJob ? <JobCard job={warmJob} className="max-w-xl" /> : null}
      <SectionSkeleton />
    </div>
  );
}

function SectionView({
  route,
  frame,
  frameError,
  state,
  fileName,
}: {
  route: Route;
  frame: WorkspaceView | undefined;
  frameError: unknown;
  state: SectionState;
  /** The workspace's file (from the list), to say what is being read while the frame loads. */
  fileName?: string | null;
}) {
  const [, navigate] = useLocation();
  const qc = useQueryClient();
  const Component = SECTION[route.section].component;
  const missing =
    route.notFound ??
    (route.key && frameError instanceof ApiError && frameError.status === 404
      ? route.kind === "s"
        ? "session"
        : "study"
      : null);
  if (missing) {
    const words = notFoundWords(missing);
    return (
      <EmptyState
        headingLevel={1}
        className="mx-auto mt-10 max-w-xl"
        icon={<FolderX />}
        title={words.title}
        action={
          <Button variant="primary" onClick={() => navigate("/")}>
            Back to Open
          </Button>
        }
      >
        {words.body}
      </EmptyState>
    );
  }
  if (route.key) {
    if (frameError) {
      return (
        <ErrorPanel
          error={frameError}
          onRetry={() => void qc.invalidateQueries({ queryKey: ["w", route.key, "frame"] })}
        />
      );
    }
    if (frame?.warming)
      return (
        <FrameLoading
          fileName={frame.facts?.file_name ?? fileName}
          warmJob={frame.active_jobs.find((j) => j.kind.startsWith("warm")) ?? null}
        />
      );
    if (!frame || route.bare) return <FrameLoading fileName={fileName} />;
    if (!state.reachable) return <LockedSection state={state} frame={frame} route={route} />;
  }
  return (
    <SectionBoundary label={SECTION[route.section].label} resetKey={route.path}>
      <Suspense fallback={<SectionSkeleton />}>
        <Component workspace={frame ?? null} rest={route.rest} />
      </Suspense>
    </SectionBoundary>
  );
}

/** Toast when an agent's request arrives for any workspace (pending requests go up). */
function useAgentRequestToasts(workspaces: ReturnType<typeof useWorkspaces>["data"]) {
  const [, navigate] = useLocation();
  const seen = useRef<Map<string, number> | null>(null);
  useEffect(() => {
    if (!workspaces) return;
    const now = new Map(workspaces.map((w) => [w.key, w.pending_requests]));
    if (seen.current) {
      for (const w of workspaces) {
        const before = seen.current.get(w.key) ?? 0;
        if (w.pending_requests > before) {
          const n = w.pending_requests - before;
          toast.info(
            n === 1
              ? "An agent is asking you to decide"
              : `${count(n)} agent requests are waiting for you`,
            {
              description: w.title,
              duration: 10_000,
              action: {
                label: "Review",
                onClick: () => navigate(`/${w.kind === "session" ? "s" : "r"}/${w.key}/agents`),
              },
            },
          );
        }
      }
    }
    seen.current = now;
  }, [workspaces, navigate]);
}

function Shell() {
  const route = useRoute();
  const [, navigate] = useLocation();
  const qc = useQueryClient();
  const system = useSystem();
  const workspaces = useWorkspaces();
  const frameQuery = useWorkspaceFrame(route.kind ?? undefined, route.key ?? undefined);
  const frame = route.key ? frameQuery.data : undefined;
  const summary = route.key ? workspaces.data?.find((w) => w.key === route.key) : undefined;
  const states = sectionStates(frame, summary?.pending_requests ?? 0);
  const askOpen = useAskOpen();
  const mainRef = useRef<HTMLElement>(null);

  useAgentRequestToasts(workspaces.data);

  // A bare workspace link (#/s/<id>) opens the useful section.
  useEffect(() => {
    // While the file warms the stages are unknown: wait for them before choosing.
    if (route.bare && frame && !frame.warming)
      navigate(pathOf(route.kind, route.key, defaultSection(frame)), { replace: true });
  }, [route.bare, route.kind, route.key, frame, navigate]);

  // Running work: keep the bell's list current as jobs report.
  useEffect(
    () =>
      onLiveEvent((e) => {
        if (e.type === "job.updated") {
          void qc.invalidateQueries({ queryKey: ["jobs"] });
          if (e.job?.key) void qc.invalidateQueries({ queryKey: ["w", e.job.key, "jobs"] });
        }
      }),
    [qc],
  );

  // The window title names the section and the study; a link that leads nowhere says so (not
  // "Open", the page it falls back to).
  const gone =
    route.notFound != null ||
    (route.key != null && frameQuery.error instanceof ApiError && frameQuery.error.status === 404);
  useEffect(() => {
    const label = SECTION[route.section].label;
    document.title = gone
      ? "Not found — qPilot"
      : frame
        ? `${label} · ${frame.title} — qPilot`
        : `${label} — qPilot`;
  }, [route.section, frame, gone]);

  // After moving to another section, start reading at its top (focus follows for screen readers).
  // Keyed on the section, not its `rest`: a section that keeps state in the path (the Audit's
  // tab and what-if choices, the Gene page's gene) is not remounted or scrolled when it changes.
  const sectionKey = `${route.kind}/${route.key}/${route.section}`;
  useEffect(() => {
    const main = mainRef.current;
    if (!main) return;
    window.scrollTo({ top: 0 });
    if (!main.contains(document.activeElement)) main.focus({ preventScroll: true });
  }, [sectionKey]);

  const go = (id: SectionId) => {
    if (!route.key) return;
    navigate(pathOf(route.kind, route.key, id));
  };
  const gBindings = Object.fromEntries(
    Object.entries(G_KEY).map(([id, k]) => [`g ${k}`, () => go(id as SectionId)]),
  ) as Record<string, () => void>;
  useHotkeys({
    "mod+k": () => setPaletteOpen(true),
    "mod+j": () => {
      if (route.key) toggleAsk();
    },
    "mod+o": () => {
      navigate("/");
      requestOpenFile();
    },
    "?": openShortcuts,
    ...gBindings,
  });

  if (!__QPILOT_STATIC_DEMO__ && system.error instanceof ApiError && system.error.needsKey) {
    return <NeedsKey onRetry={() => void system.refetch()} retrying={system.isFetching} />;
  }

  const offline = system.error instanceof ApiError && system.error.code === "offline";
  const showBanner = Boolean(
    frame &&
    !frame.warming &&
    route.key &&
    SECTION[route.section].scope === "workspace" &&
    !route.bare,
  );

  return (
    <div className="flex min-h-dvh bg-bg text-fg">
      <a
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          mainRef.current?.focus();
        }}
        className="sr-only z-50 rounded-md bg-surface px-3 py-2 text-sm font-medium shadow-md focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <Rail route={route} frame={frame} states={states} workspaces={workspaces.data} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar route={route} frame={frame} system={system.data} />
        <div
          className={cn(
            "flex min-w-0 flex-1 flex-col transition-[padding] duration-200",
            askOpen && frame && "xl:pr-[420px]",
          )}
        >
          {offline ? (
            <div
              role="alert"
              className="border-b border-warn/30 bg-warn-soft px-4 py-2 text-[13px] text-fg sm:px-6 lg:px-8"
            >
              <span className="font-semibold">qPilot is not answering.</span>{" "}
              <span className="text-muted">
                Is <code className="font-mono">qpilot app</code> still running? The page reconnects
                on its own.
              </span>
            </div>
          ) : null}
          {system.data?.hosted ? <HostedBanner /> : null}
          {showBanner && frame ? <NextStepBanner frame={frame} route={route} /> : null}
          <main
            id="main"
            ref={mainRef}
            tabIndex={-1}
            aria-label={SECTION[route.section].label}
            className="mx-auto w-full max-w-[1600px] flex-1 px-4 pt-6 pb-24 outline-none sm:px-6 md:pb-10 lg:px-8"
          >
            {/*
              Keyed on the workspace and the section, so another study or section swaps at once.
              The entrance is a CSS animation (time-based, no exit to wait for): a tab that is not
              painting can never hold the previous section on screen, as an exit animation could.
            */}
            <div key={sectionKey} className="qp-section-in">
              <SectionView
                route={route}
                frame={frame}
                frameError={route.key ? frameQuery.error : null}
                state={states[route.section]}
                fileName={summary?.file_name}
              />
            </div>
          </main>
        </div>
      </div>
      <BottomBar route={route} frame={frame} states={states} workspaces={workspaces.data} />
      <Palette route={route} frame={frame} states={states} workspaces={workspaces.data} />
      <ShortcutSheet />
      <AskFrame frame={frame} />
    </div>
  );
}

export function App() {
  useLiveEvents();
  return (
    <TooltipProvider>
      <MotionConfig reducedMotion="user">
        <Router hook={useHashLocation}>
          <Shell />
        </Router>
      </MotionConfig>
      <Toaster />
    </TooltipProvider>
  );
}
