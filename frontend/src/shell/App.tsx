/**
 * The page: one hash router, the rail, the top bar, the next-step banner and the current
 * section, plus the palette (⌘K), the shortcut sheet (?), the Ask drawer (⌘J) and the toasts.
 * Workspace routes are `/s/<session id>/<section>/...` (a Studio session) and
 * `/r/<study id>/<section>/...` (a study analysed outside one).
 */
import { useQueryClient } from "@tanstack/react-query";
import { FolderX } from "lucide-react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { Suspense, useEffect, useRef } from "react";
import { Router, useLocation } from "wouter";
import { useHashLocation } from "wouter/use-hash-location";
import { ApiError } from "@/api/client";
import { onLiveEvent, useLiveEvents } from "@/api/live";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { useHotkeys } from "@/lib/hooks";
import {
  Button,
  EmptyState,
  ErrorPanel,
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
import { NextStepBanner } from "./NextStep";
import { G_KEY, Palette } from "./Palette";
import { BottomBar, Rail } from "./Rail";
import { pathOf, useRoute, type Route } from "./route";
import { SECTION, type SectionId } from "./sections";
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

function SectionView({
  route,
  frame,
  frameError,
  state,
}: {
  route: Route;
  frame: WorkspaceView | undefined;
  frameError: unknown;
  state: SectionState;
}) {
  const [, navigate] = useLocation();
  const qc = useQueryClient();
  const Component = SECTION[route.section].component;
  if (route.key) {
    if (frameError) {
      if (frameError instanceof ApiError && frameError.status === 404) {
        return (
          <EmptyState
            className="mx-auto mt-10 max-w-xl"
            icon={<FolderX />}
            title="This study is not in this qPilot's store"
            action={
              <Button variant="primary" onClick={() => navigate("/")}>
                Open a study
              </Button>
            }
          >
            The link names a study that this qPilot has not opened (or it was moved aside by “Start
            a fresh demo”). Open the file again, or pick a study you have.
          </EmptyState>
        );
      }
      return (
        <ErrorPanel
          error={frameError}
          onRetry={() => void qc.invalidateQueries({ queryKey: ["w", route.key, "frame"] })}
        />
      );
    }
    if (!frame || route.bare) return <SectionSkeleton />;
    if (!state.reachable) return <LockedSection state={state} frame={frame} route={route} />;
  }
  return (
    <Suspense fallback={<SectionSkeleton />}>
      <Component workspace={frame ?? null} rest={route.rest} />
    </Suspense>
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
    if (route.bare && frame)
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

  // The window title names the section and the study.
  useEffect(() => {
    const label = SECTION[route.section].label;
    document.title = frame ? `${label} · ${frame.title} — qPilot` : `${label} — qPilot`;
  }, [route.section, frame]);

  // After moving to another section, start reading at its top (focus follows for screen readers).
  const sectionKey = `${route.kind}/${route.key}/${route.section}/${route.rest.join("/")}`;
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

  if (system.error instanceof ApiError && system.error.needsKey) {
    return <NeedsKey onRetry={() => void system.refetch()} retrying={system.isFetching} />;
  }

  const offline = system.error instanceof ApiError && system.error.code === "offline";
  const showBanner = Boolean(
    frame && route.key && SECTION[route.section].scope === "workspace" && !route.bare,
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
          {showBanner && frame ? <NextStepBanner frame={frame} route={route} /> : null}
          <main
            id="main"
            ref={mainRef}
            tabIndex={-1}
            aria-label={SECTION[route.section].label}
            className="mx-auto w-full max-w-[1600px] flex-1 px-4 pt-6 pb-24 outline-none sm:px-6 md:pb-10 lg:px-8"
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={sectionKey}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, transition: { duration: 0.08 } }}
                transition={{ duration: 0.18, ease: "easeOut" }}
              >
                <SectionView
                  route={route}
                  frame={frame}
                  frameError={route.key ? frameQuery.error : null}
                  state={states[route.section]}
                />
              </motion.div>
            </AnimatePresence>
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
