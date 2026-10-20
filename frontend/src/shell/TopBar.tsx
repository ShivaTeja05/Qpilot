/**
 * The top bar: the study's title and short input SHA, the chain-head pill, the model chip, the
 * autonomy switch, the agent bell, ⌘K, the theme toggle and the live dot. On narrow screens the
 * secondary controls move into one menu.
 */
import {
  Bell,
  Bot,
  GitBranch,
  Keyboard,
  Laptop,
  Loader2,
  Menu as MenuIcon,
  MessageSquareText,
  Moon,
  Search,
  Sun,
} from "lucide-react";
import { Link, useLocation } from "wouter";
import type { JobView } from "@/api/client";
import { useLiveState } from "@/api/live";
import { cn } from "@/lib/cn";
import { count, duration, shortHash } from "@/lib/format";
import { MOD } from "@/lib/hooks";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import {
  Button,
  Dot,
  Hash,
  IconButton,
  Kbd,
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
  Popover,
  ProgressBar,
  Tooltip,
} from "@/ui";
import { openPalette, openShortcuts, toggleAsk, useAskOpen } from "./actions";
import { Mark } from "./Brand";
import { useJobs, useWorkspaces, type SystemView, type WorkspaceView } from "./data";
import { workspacePath } from "./Rail";
import { pathOf, type Route } from "./route";
import { SECTION } from "./sections";
import { AutonomyChip, AutonomySwitch } from "./Autonomy";
import { modelChip, ModelChip } from "./ModelChip";

// ---------------------------------------------------------------------------------------------
// The agent bell

function AgentBell({ route }: { route: Route }) {
  const workspaces = useWorkspaces();
  const jobs = useJobs();
  const [, navigate] = useLocation();
  const waiting = (workspaces.data ?? []).filter((w) => w.pending_requests > 0);
  const total = waiting.reduce((n, w) => n + w.pending_requests, 0);
  const running = (jobs.data ?? []).filter((j) => j.status === "queued" || j.status === "running");
  const label =
    total > 0
      ? `${count(total)} agent request${total === 1 ? "" : "s"} waiting for you`
      : running.length
        ? `${running.length} running`
        : "Agent requests and running work";
  return (
    <Popover
      label="Agent requests and running work"
      trigger={
        <IconButton label={label} className="relative">
          {running.length && !total ? <Loader2 className="animate-spin" /> : <Bell />}
          {total > 0 ? (
            <span
              aria-hidden
              className="absolute -top-0.5 -right-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-fg tabular"
            >
              {total > 99 ? "99+" : total}
            </span>
          ) : null}
        </IconButton>
      }
      className="w-[22rem] p-0"
    >
      <div className="border-b border-line px-3 py-2.5">
        <p className="text-sm font-semibold">Waiting for you</p>
        <p className="text-xs text-muted">
          Agents propose and ask; a choice that can change a conclusion always waits for a person.
        </p>
      </div>
      <div className="max-h-80 overflow-y-auto p-1.5 qp-scroll">
        {waiting.length === 0 ? (
          <p className="px-2 py-3 text-[13px] text-muted">
            No agent request is waiting. Connect an agent from Agents.
          </p>
        ) : (
          <ul>
            {waiting.map((w) => (
              <li key={w.key}>
                <button
                  type="button"
                  onClick={() => navigate(`${workspacePath(w)}/agents`)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left hover:bg-bg-subtle"
                >
                  <Bot className="size-4 shrink-0 text-accent" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium">{w.title}</span>
                    <span className="block text-xs text-muted">
                      {count(w.pending_requests)} request{w.pending_requests === 1 ? "" : "s"} to
                      approve or turn down
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {running.length ? (
          <>
            <p className="px-2 pt-2 pb-1 text-xs font-medium text-muted">Running</p>
            <ul className="flex flex-col gap-1">
              {running.map((j) => (
                <RunningJob key={j.id} job={j} />
              ))}
            </ul>
          </>
        ) : null}
      </div>
      {route.key ? (
        <div className="border-t border-line p-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            onClick={() => navigate(pathOf(route.kind, route.key, "agents"))}
          >
            Open Agents
          </Button>
        </div>
      ) : null}
    </Popover>
  );
}

function RunningJob({ job }: { job: JobView }) {
  return (
    <li className="rounded-lg px-2 py-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[13px] font-medium">{job.title}</span>
        <span className="shrink-0 text-xs text-muted tabular">
          {duration(job.elapsed_s)}
          {job.typical_s ? <span className="text-muted"> / ~{duration(job.typical_s)}</span> : null}
        </span>
      </div>
      {job.step ? <p className="truncate text-xs text-muted">{job.step}</p> : null}
      <ProgressBar className="mt-1" label={job.title} value={job.fraction} />
    </li>
  );
}

// ---------------------------------------------------------------------------------------------
// Theme and live dot

const THEME_ICON = { system: Laptop, light: Sun, dark: Moon } as const;

function ThemeMenu() {
  const { choice, setTheme } = useTheme();
  const Icon = THEME_ICON[choice];
  return (
    <Menu>
      <Tooltip content="Theme">
        <MenuTrigger asChild>
          <IconButton label={`Theme: ${choice}`}>
            <Icon />
          </IconButton>
        </MenuTrigger>
      </Tooltip>
      <MenuContent>
        <MenuLabel>Theme</MenuLabel>
        {(["system", "light", "dark"] as ThemeChoice[]).map((t) => {
          const I = THEME_ICON[t];
          return (
            <MenuItem
              key={t}
              icon={<I />}
              onSelect={() => setTheme(t)}
              className={cn(choice === t && "font-semibold")}
            >
              {t === "system" ? "Same as the system" : t === "light" ? "Light" : "Dark"}
              {choice === t ? <span className="sr-only"> (current)</span> : null}
            </MenuItem>
          );
        })}
      </MenuContent>
    </Menu>
  );
}

function LiveDot() {
  const state = useLiveState();
  const words =
    state === "live"
      ? "Live: changes by agents and other tabs appear within a second"
      : state === "connecting"
        ? "Connecting to qPilot"
        : "Reconnecting: qPilot is not answering";
  return (
    <Tooltip content={words}>
      <span
        tabIndex={0}
        role="status"
        aria-label={words}
        className="inline-flex size-8 items-center justify-center rounded-lg"
      >
        <Dot
          tone={state === "live" ? "ok" : state === "connecting" ? "warn" : "danger"}
          pulse={state !== "live"}
        />
      </span>
    </Tooltip>
  );
}

// ---------------------------------------------------------------------------------------------
// The bar

export function TopBar({
  route,
  frame,
  system,
}: {
  route: Route;
  frame: WorkspaceView | null | undefined;
  system: SystemView | undefined;
}) {
  const askOpen = useAskOpen();
  const { choice, setTheme } = useTheme();
  const [, navigate] = useLocation();
  const title =
    frame?.title ?? (route.key ? "" : route.section === "settings" ? "Settings" : "Open a study");
  const sha = frame?.facts?.input_sha256 ?? frame?.summary?.input_sha256 ?? null;
  const head = frame?.decisions_head ?? null;
  return (
    <header className="sticky top-0 z-30 flex h-[52px] shrink-0 items-center gap-2 border-b border-line bg-surface/90 px-3 backdrop-blur supports-[backdrop-filter]:bg-surface/75 sm:px-4">
      <Link href="/" aria-label="qPilot: Open" className="shrink-0 rounded-md md:hidden">
        <Mark className="size-6" />
      </Link>
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {title ? (
          <p className="truncate text-sm font-semibold text-fg sm:text-[15px]" title={title}>
            {title}
          </p>
        ) : (
          <p className="truncate text-sm font-medium text-muted">Opening the study…</p>
        )}
        {sha ? (
          <Hash
            value={sha}
            prefix="sha"
            length={8}
            className="hidden shrink-0 min-[1600px]:inline-flex"
          />
        ) : null}
        {frame ? (
          <Tooltip
            content={
              head
                ? "The head of the hash-chained decision log. Open the Record."
                : "No decision is recorded yet. Open the Record."
            }
          >
            <Link
              href={pathOf(route.kind, route.key, "record")}
              className="hidden h-6 shrink-0 items-center gap-1 rounded-full border border-line px-2 font-mono text-[11.5px] text-muted transition-colors hover:border-line-strong hover:text-fg md:inline-flex"
            >
              <GitBranch className="size-3" aria-hidden />
              <span className="font-sans">chain</span> {head ? `${shortHash(head, 4)}…` : "empty"}
              <span className="sr-only"> (the decision log's head; open the Record)</span>
            </Link>
          </Tooltip>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-1 sm:gap-1.5">
        <div className="hidden lg:block">
          <ModelChip model={system?.model} />
        </div>
        <div className="hidden min-[1440px]:block">
          <AutonomySwitch system={system} />
        </div>
        <div className="hidden lg:block min-[1440px]:hidden">
          <AutonomyChip system={system} />
        </div>
        <AgentBell route={route} />
        {frame ? (
          <Tooltip
            content={
              <span>
                Ask your data{" "}
                <Kbd className="ml-1 border-transparent bg-transparent text-bg/80">{MOD} J</Kbd>
              </span>
            }
          >
            <IconButton
              label="Ask your data"
              onClick={toggleAsk}
              aria-pressed={askOpen}
              className={cn(askOpen && "bg-accent-soft text-accent-strong")}
            >
              <MessageSquareText />
            </IconButton>
          </Tooltip>
        ) : null}
        <button
          type="button"
          onClick={openPalette}
          aria-keyshortcuts="Meta+K Control+K"
          className="hidden h-8 w-44 items-center gap-2 rounded-lg border border-line bg-surface-2 pr-1.5 pl-2.5 text-[13px] text-muted transition-colors hover:border-line-strong hover:text-muted xl:inline-flex"
        >
          <Search className="size-4" aria-hidden />
          <span className="flex-1 text-left">
            Go to…<span className="sr-only"> (search and commands)</span>
          </span>
          <span aria-hidden>
            <Kbd>{MOD}K</Kbd>
          </span>
        </button>
        <IconButton label="Search and commands" onClick={openPalette} className="xl:hidden">
          <Search />
        </IconButton>
        <div className="hidden sm:block">
          <ThemeMenu />
        </div>
        <LiveDot />
        {/* Narrow screens: the controls that do not fit, in one menu. */}
        <Menu>
          <MenuTrigger asChild>
            <IconButton label="More controls" className="min-[1440px]:hidden">
              <MenuIcon />
            </IconButton>
          </MenuTrigger>
          <MenuContent className="w-72">
            <MenuLabel>Model</MenuLabel>
            <MenuItem icon={<Bot />} onSelect={() => navigate("/settings")}>
              {modelChip(system?.model).label}
              <span className="block text-xs text-muted">{modelChip(system?.model).status}</span>
            </MenuItem>
            <MenuSeparator />
            <div className="px-2 py-1.5">
              <p className="mb-1.5 text-xs font-medium text-muted">Agents may</p>
              <AutonomySwitch system={system} withTooltip={false} />
            </div>
            <MenuSeparator />
            <MenuLabel>Theme</MenuLabel>
            {(["system", "light", "dark"] as ThemeChoice[]).map((t) => {
              const I = THEME_ICON[t];
              return (
                <MenuItem
                  key={t}
                  icon={<I />}
                  onSelect={() => setTheme(t)}
                  className={cn(choice === t && "font-semibold")}
                >
                  {t === "system" ? "Same as the system" : t === "light" ? "Light" : "Dark"}
                </MenuItem>
              );
            })}
            <MenuSeparator />
            <MenuItem icon={<Keyboard />} shortcut="?" onSelect={openShortcuts}>
              Keyboard shortcuts
            </MenuItem>
            <MenuItem icon={<SECTION.settings.icon />} onSelect={() => navigate("/settings")}>
              Settings
            </MenuItem>
          </MenuContent>
        </Menu>
      </div>
    </header>
  );
}
