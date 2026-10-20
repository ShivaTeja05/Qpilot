/**
 * The rail (248 px from 1024 px, icons only from 768 px) and, on phones, the bottom bar. The
 * workflow in order with each section's live state (✓ confirmed, a count waiting, a lock with
 * the reason), then Agents and Settings; the workspace switcher at the top.
 */
import {
  Check,
  ChevronsUpDown,
  FileUp,
  FolderOpen,
  Library,
  Lock,
  MoreHorizontal,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { Link, useLocation } from "wouter";
import { cn } from "@/lib/cn";
import { count, relativeTime } from "@/lib/format";
import {
  Badge,
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
  Sheet,
  Tooltip,
} from "@/ui";
import { requestOpenFile } from "./actions";
import { Brand, Mark } from "./Brand";
import type { WorkspaceSummary, WorkspaceView } from "./data";
import { TOOLS, WORKFLOW, type SectionState } from "./nav";
import { pathOf, type Route } from "./route";
import { SECTION, type SectionId } from "./sections";
import { MOD } from "@/lib/hooks";

interface RailProps {
  route: Route;
  frame: WorkspaceView | null | undefined;
  states: Record<SectionId, SectionState>;
  workspaces: WorkspaceSummary[] | undefined;
}

/** Path to a workspace's first useful section. */
export function workspacePath(w: Pick<WorkspaceSummary, "kind" | "key">): string {
  return `/${w.kind === "session" ? "s" : "r"}/${w.key}`;
}

function StateMark({ state, compact }: { state: SectionState; compact?: boolean }) {
  if (!state.reachable && state.lockReason) {
    return (
      <Lock
        className={cn(
          "size-3.5 shrink-0 text-faint",
          compact && "absolute -right-0.5 -bottom-0.5 size-3 rounded-full bg-surface p-px",
        )}
        aria-hidden
      />
    );
  }
  if (state.count > 0) {
    return (
      <span
        className={cn(
          "inline-flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full bg-accent px-1 text-[11px] font-semibold text-accent-fg tabular",
          compact && "absolute -top-1 -right-1.5 h-4 min-w-4 text-[10px]",
        )}
        aria-hidden
      >
        {state.count > 99 ? "99+" : state.count}
      </span>
    );
  }
  if (state.done) {
    return (
      <Check
        className={cn(
          "size-3.5 shrink-0 text-ok",
          compact && "absolute -right-1 -bottom-1 size-3.5 rounded-full bg-surface p-px",
        )}
        strokeWidth={3}
        aria-hidden
      />
    );
  }
  return null;
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Words for screen readers and tooltips: "Curves — locked: Confirm the design first". */
function stateWords(state: SectionState): string {
  const parts: string[] = [];
  if (!state.reachable && state.lockReason) parts.push(`locked: ${state.lockReason}`);
  else {
    if (state.done) parts.push(state.section.id === "audit" ? "done" : "confirmed");
    if (state.count > 0)
      parts.push(
        state.section.id === "agents"
          ? `${count(state.count)} waiting for you`
          : `${count(state.count)} to review`,
      );
  }
  return parts.join(", ");
}

function NavItem({
  href,
  icon: Icon,
  label,
  state,
  active,
  hint,
}: {
  href: string;
  icon: LucideIcon;
  label: string;
  state?: SectionState;
  active: boolean;
  hint?: string;
}) {
  const words = state ? stateWords(state) : "";
  const locked = state && !state.reachable;
  const tooltip = (
    <span className="flex flex-col">
      <span className="font-medium">{label}</span>
      {words ? (
        <span className="opacity-80">{capitalise(words)}</span>
      ) : hint ? (
        <span className="opacity-80">{hint}</span>
      ) : null}
    </span>
  );
  return (
    <li>
      <Tooltip content={tooltip} side="right">
        <Link
          href={href}
          aria-current={active ? "page" : undefined}
          aria-label={words ? `${label} (${words})` : label}
          className={cn(
            "group relative flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium transition-colors duration-150 lg:px-3",
            "justify-center lg:justify-start",
            active
              ? "bg-accent-soft text-accent-strong"
              : "text-muted hover:bg-bg-subtle hover:text-fg",
            locked && !active && "text-muted",
          )}
        >
          {active ? (
            <span
              className="absolute top-2 bottom-2 left-0 w-[3px] rounded-r-full bg-accent max-lg:hidden"
              aria-hidden
            />
          ) : null}
          <span className="relative flex">
            <Icon className="size-[18px] shrink-0" aria-hidden />
            {state ? (
              <span className="lg:hidden">
                <StateMark state={state} compact />
              </span>
            ) : null}
          </span>
          <span className="hidden min-w-0 flex-1 truncate lg:block">{label}</span>
          {state ? (
            <span className="hidden lg:flex">
              <StateMark state={state} />
            </span>
          ) : null}
        </Link>
      </Tooltip>
    </li>
  );
}

function stageChips(w: WorkspaceSummary): string {
  if (w.warming) return "Opening…";
  if (w.kind !== "session") return w.results_visible ? "Analysed" : "Study";
  const design = w.stages.find((s) => s.stage === "design");
  const curves = w.stages.find((s) => s.stage === "curves");
  if (w.results_visible) return "Results";
  if (curves?.open) return "Curves";
  return design?.confirmed ? "Curves" : "Design";
}

/** The workspace switcher: recent workspaces, Open a file (⌘O), all workspaces. */
function WorkspaceSwitcher({
  frame,
  workspaces,
}: {
  frame: WorkspaceView | null | undefined;
  workspaces: WorkspaceSummary[] | undefined;
}) {
  const [, navigate] = useLocation();
  const recent = (workspaces ?? []).slice(0, 8);
  return (
    <Menu>
      <MenuTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2.5 rounded-lg border border-line bg-surface-2 p-2 text-left transition-colors hover:border-line-strong hover:bg-bg-subtle max-lg:justify-center max-lg:border-transparent max-lg:bg-transparent max-lg:p-1.5"
        >
          <span
            className="flex size-7 shrink-0 items-center justify-center rounded-md bg-bg-subtle text-muted lg:size-8"
            aria-hidden
          >
            <Library className="size-4" />
          </span>
          <span className="sr-only">Switch study. Open: </span>
          <span className="sr-only lg:hidden">{frame?.title ?? "none"}</span>
          <span className="hidden min-w-0 flex-1 lg:block">
            <span className="block truncate text-[13px] font-semibold text-fg" title={frame?.title}>
              {frame?.title ?? "No study open"}
            </span>
            <span className="block truncate text-xs text-muted">
              {frame
                ? (frame.kind === "session" ? "Studio session" : "Study") +
                  (frame.is_demo ? " · demo" : "")
                : "Open a file or the demo"}
            </span>
          </span>
          <ChevronsUpDown className="hidden size-4 shrink-0 text-faint lg:block" aria-hidden />
        </button>
      </MenuTrigger>
      <MenuContent align="start" className="w-72">
        {recent.length ? <MenuLabel>Recent</MenuLabel> : null}
        {recent.map((w) => (
          <MenuItem
            key={w.key}
            onSelect={() => navigate(workspacePath(w))}
            className={cn(frame?.key === w.key && "bg-accent-soft/50")}
          >
            <span className="flex min-w-0 flex-col">
              <span className="truncate font-medium">{w.title}</span>
              <span className="truncate text-xs text-muted">
                {stageChips(w)} · {relativeTime(w.updated_at)}
                {w.pending_requests ? ` · ${count(w.pending_requests)} waiting` : ""}
              </span>
            </span>
          </MenuItem>
        ))}
        {recent.length ? <MenuSeparator /> : null}
        <MenuItem
          icon={<FileUp />}
          shortcut={`${MOD} O`}
          onSelect={() => {
            navigate("/");
            requestOpenFile();
          }}
        >
          Open a file…
        </MenuItem>
        <MenuItem icon={<FolderOpen />} onSelect={() => navigate("/")}>
          All workspaces
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}

/** The left rail (hidden on phones). */
export function Rail({ route, frame, states, workspaces }: RailProps) {
  const inWorkspace = Boolean(route.key && frame);
  const workflow = WORKFLOW.filter((id) => !states[id].absent);
  const tools = TOOLS.filter((id) => !states[id].absent);
  const href = (id: SectionId) => pathOf(route.kind, route.key, id);
  return (
    <aside
      aria-label="Sections"
      className="sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-line bg-surface md:flex md:w-16 lg:w-[248px]"
    >
      <div className="flex h-[52px] shrink-0 items-center px-4 max-lg:justify-center max-lg:px-0">
        <Link href="/" aria-label="qPilot: Open" className="rounded-md">
          <span className="hidden lg:inline">
            <Brand />
          </span>
          <span className="lg:hidden">
            <Mark />
          </span>
        </Link>
      </div>
      <div className="px-3 pb-2 max-lg:px-2">
        <WorkspaceSwitcher frame={frame} workspaces={workspaces} />
      </div>
      <nav
        aria-label="Workflow"
        className="qp-scroll flex min-h-0 flex-1 flex-col overflow-y-auto px-3 pt-2 max-lg:px-2"
      >
        <ul className="flex flex-col gap-0.5">
          <NavItem
            href="/"
            icon={SECTION.home.icon}
            label="Open"
            active={route.section === "home"}
            hint={SECTION.home.hint}
          />
        </ul>
        {inWorkspace ? (
          <>
            <p className="mt-4 mb-1.5 hidden px-3 text-[11px] font-semibold tracking-wider text-muted uppercase lg:block">
              Workflow
            </p>
            <div className="my-2 h-px bg-line lg:hidden" aria-hidden />
            <ol className="flex flex-col gap-0.5">
              {workflow.map((id) => (
                <NavItem
                  key={id}
                  href={href(id)}
                  icon={SECTION[id].icon}
                  label={SECTION[id].label}
                  hint={SECTION[id].hint}
                  state={states[id]}
                  active={route.section === id || (id === "results" && route.section === "gene")}
                />
              ))}
            </ol>
            {tools.length ? (
              <>
                <p className="mt-4 mb-1.5 hidden px-3 text-[11px] font-semibold tracking-wider text-muted uppercase lg:block">
                  Tools
                </p>
                <div className="my-2 h-px bg-line lg:hidden" aria-hidden />
                <ul className="flex flex-col gap-0.5">
                  {tools.map((id) => (
                    <NavItem
                      key={id}
                      href={href(id)}
                      icon={SECTION[id].icon}
                      label={SECTION[id].label}
                      hint={SECTION[id].hint}
                      state={states[id]}
                      active={route.section === id}
                    />
                  ))}
                </ul>
              </>
            ) : null}
            <div className="my-3 h-px bg-line" aria-hidden />
            <ul className="flex flex-col gap-0.5">
              <NavItem
                href={href("agents")}
                icon={SECTION.agents.icon}
                label={SECTION.agents.label}
                hint={SECTION.agents.hint}
                state={states.agents}
                active={route.section === "agents"}
              />
            </ul>
          </>
        ) : route.key ? null : (
          <RecentList workspaces={workspaces} />
        )}
        <div className="mt-auto pt-3 pb-3">
          <ul className="flex flex-col gap-0.5">
            <NavItem
              href="/settings"
              icon={SECTION.settings.icon}
              label="Settings"
              hint={SECTION.settings.hint}
              active={route.section === "settings"}
            />
          </ul>
          <p className="mt-3 hidden px-3 text-[11px] leading-snug text-muted lg:block">
            Research use only. Not for clinical or diagnostic use.
          </p>
        </div>
      </nav>
    </aside>
  );
}

function RecentList({ workspaces }: { workspaces: WorkspaceSummary[] | undefined }) {
  const recent = (workspaces ?? []).slice(0, 6);
  if (!recent.length) return null;
  return (
    <div className="mt-4 hidden lg:block">
      <p className="mb-1.5 px-3 text-[11px] font-semibold tracking-wider text-muted uppercase">
        Recent
      </p>
      <ul className="flex flex-col gap-0.5">
        {recent.map((w) => (
          <li key={w.key}>
            <Link
              href={workspacePath(w)}
              className="flex flex-col rounded-lg px-3 py-1.5 transition-colors hover:bg-bg-subtle"
            >
              <span className="truncate text-[13px] font-medium text-fg">{w.title}</span>
              <span className="truncate text-xs text-muted">
                {stageChips(w)} · {relativeTime(w.updated_at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Phones: the bottom bar

function BarItem({
  href,
  icon: Icon,
  label,
  state,
  active,
}: {
  href: string;
  icon: LucideIcon;
  label: string;
  state?: SectionState;
  active: boolean;
}) {
  const words = state ? stateWords(state) : "";
  return (
    <li className="min-w-0 flex-1">
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        aria-label={words ? `${label} (${words})` : label}
        className={cn(
          "flex h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
          active ? "text-accent-strong" : state && !state.reachable ? "text-muted" : "text-muted",
        )}
      >
        <span className="relative flex">
          <Icon className="size-5" aria-hidden />
          {state ? <StateMark state={state} compact /> : null}
        </span>
        <span className="max-w-full truncate">{label}</span>
      </Link>
    </li>
  );
}

/** The bottom bar on phones (< 768 px): up to four sections and More. */
export function BottomBar({ route, frame, states, workspaces }: RailProps) {
  const [more, setMore] = useState(false);
  const [, navigate] = useLocation();
  const inWorkspace = Boolean(route.key && frame);
  const loading = Boolean(route.key && !frame);
  const all = inWorkspace
    ? [
        ...WORKFLOW.filter((id) => !states[id].absent),
        "agents" as SectionId,
        ...TOOLS.filter((id) => !states[id].absent),
      ]
    : [];
  const shown = inWorkspace ? all.slice(0, 4) : [];
  const rest = all.slice(4);
  const href = (id: SectionId) => pathOf(route.kind, route.key, id);
  return (
    <>
      <nav
        aria-label="Sections"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      >
        <ul className={cn("flex", loading && "invisible")}>
          {!inWorkspace ? (
            <BarItem
              href="/"
              icon={SECTION.home.icon}
              label="Open"
              active={route.section === "home"}
            />
          ) : null}
          {shown.map((id) => (
            <BarItem
              key={id}
              href={href(id)}
              icon={SECTION[id].icon}
              label={SECTION[id].label}
              state={states[id]}
              active={route.section === id || (id === "results" && route.section === "gene")}
            />
          ))}
          {!inWorkspace ? (
            <BarItem
              href="/settings"
              icon={SECTION.settings.icon}
              label="Settings"
              active={route.section === "settings"}
            />
          ) : (
            <li className="min-w-0 flex-1">
              <button
                type="button"
                onClick={() => setMore(true)}
                className={cn(
                  "flex h-14 w-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-muted",
                  rest.some((id) => id === route.section) && "text-accent-strong",
                )}
              >
                <MoreHorizontal className="size-5" aria-hidden />
                More
              </button>
            </li>
          )}
        </ul>
      </nav>
      <Sheet open={more} onOpenChange={setMore} side="bottom" title="More">
        <ul className="flex flex-col p-2">
          {[...rest, "home" as SectionId, "settings" as SectionId].map((id) => {
            const st = states[id];
            return (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => {
                    setMore(false);
                    navigate(
                      id === "home" || id === "settings" ? pathOf(null, null, id) : href(id),
                    );
                  }}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left text-sm hover:bg-bg-subtle"
                >
                  {(() => {
                    const Icon = SECTION[id].icon;
                    return <Icon className="size-5 text-muted" aria-hidden />;
                  })()}
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="font-medium text-fg">
                      {id === "home" ? "Open another study" : SECTION[id].label}
                    </span>
                    <span className="truncate text-xs text-muted">
                      {st && stateWords(st) ? capitalise(stateWords(st)) : SECTION[id].hint}
                    </span>
                  </span>
                  {st && st.count > 0 ? <Badge tone="accent">{count(st.count)}</Badge> : null}
                </button>
              </li>
            );
          })}
        </ul>
        {workspaces?.length ? (
          <div className="border-t border-line p-2">
            <p className="px-3 pt-2 pb-1 text-[11px] font-semibold tracking-wider text-muted uppercase">
              Recent
            </p>
            {workspaces.slice(0, 5).map((w) => (
              <button
                key={w.key}
                type="button"
                onClick={() => {
                  setMore(false);
                  navigate(workspacePath(w));
                }}
                className="flex w-full flex-col rounded-lg px-3 py-2 text-left hover:bg-bg-subtle"
              >
                <span className="truncate text-sm font-medium text-fg">{w.title}</span>
                <span className="text-xs text-muted">
                  {stageChips(w)} · {relativeTime(w.updated_at)}
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </Sheet>
    </>
  );
}
