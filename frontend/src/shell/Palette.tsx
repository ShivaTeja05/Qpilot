/**
 * The command palette (⌘K): go to a section, a workspace or a gene; run an action (Propose,
 * Check the curves, Run the audit, Export the record, Ask, Open a file, theme, shortcuts).
 */
import { Command } from "cmdk";
import {
  CornerDownLeft,
  FileUp,
  FlaskConical,
  FolderOpen,
  Keyboard,
  Lock,
  MessageSquareText,
  Microscope,
  Moon,
  Play,
  Sun,
  Zap,
} from "lucide-react";
import type { ReactNode } from "react";
import { useLocation } from "wouter";
import { count } from "@/lib/format";
import { MOD } from "@/lib/hooks";
import { useTheme } from "@/lib/theme";
import { Kbd } from "@/ui";
import {
  focusAction,
  openAsk,
  openShortcuts,
  requestOpenFile,
  setPaletteOpen,
  usePaletteOpen,
} from "./actions";
import type { WorkspaceSummary, WorkspaceView } from "./data";
import type { SectionState } from "./nav";
import { workspacePath } from "./Rail";
import { pathOf, type Route } from "./route";
import { SECTION, SECTIONS, type SectionId } from "./sections";

/** The second key of each `g` shortcut (docs/app.md §5 Keyboard). */
export const G_KEY: Partial<Record<SectionId, string>> = {
  design: "d",
  curves: "c",
  results: "r",
  audit: "a",
  prism: "p",
  record: "e",
};

/** Actions a section shows as a button, offered in the palette (go there, focus the button). */
const SECTION_ACTIONS: { section: SectionId; label: string; keywords: string[] }[] = [
  {
    section: "design",
    label: "Propose the design",
    keywords: ["design", "interpret", "proposals"],
  },
  { section: "design", label: "Confirm this stage", keywords: ["design", "confirm"] },
  { section: "curves", label: "Check the curves", keywords: ["curve judge", "amplification"] },
  { section: "audit", label: "Run the audit", keywords: ["robustness", "simulator", "verdicts"] },
  { section: "prism", label: "Send to Prism", keywords: ["graphpad", "export"] },
  {
    section: "record",
    label: "Export the Analysis Record",
    keywords: ["zip", "download", "record"],
  },
  { section: "record", label: "Verify a record", keywords: ["checksum", "chain"] },
];

/**
 * Plain matching instead of cmdk's fuzzy score: "ODC" should find ODC1, not every hint with an
 * o, a d and a c in it. Whole value first, then a word start, then anywhere; keywords count less.
 */
export function paletteFilter(value: string, search: string, keywords?: string[]): number {
  const q = search.trim().toLowerCase();
  if (!q) return 1;
  const v = value.toLowerCase().replace(/^(go|gene|study) /, "");
  if (v.startsWith(q)) return 1;
  if (v.split(/[\s/·:-]+/).some((w) => w.startsWith(q))) return 0.8;
  if (v.includes(q)) return 0.6;
  const k = (keywords ?? []).join(" ").toLowerCase();
  if (k.split(/[\s/·:-]+/).some((w) => w.startsWith(q))) return 0.4;
  return 0;
}

function Item({
  value,
  keywords,
  onSelect,
  icon,
  children,
  hint,
  shortcut,
  disabled,
}: {
  value: string;
  keywords?: string[];
  onSelect: () => void;
  icon: ReactNode;
  children: ReactNode;
  hint?: ReactNode;
  shortcut?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <Command.Item
      value={value}
      keywords={keywords}
      onSelect={onSelect}
      disabled={disabled}
      className="group flex cursor-default items-center gap-3 rounded-lg px-2.5 py-2 text-sm text-fg outline-none data-[disabled=true]:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted"
    >
      {icon}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate">{children}</span>
        {hint ? <span className="truncate text-xs text-muted">{hint}</span> : null}
      </span>
      {shortcut ? <span className="flex gap-1">{shortcut}</span> : null}
      <CornerDownLeft className="hidden !size-3.5 group-data-[selected=true]:block" aria-hidden />
    </Command.Item>
  );
}

export function Palette({
  route,
  frame,
  states,
  workspaces,
}: {
  route: Route;
  frame: WorkspaceView | null | undefined;
  states: Record<SectionId, SectionState>;
  workspaces: WorkspaceSummary[] | undefined;
}) {
  const open = usePaletteOpen();
  const [, navigate] = useLocation();
  const { theme, setTheme } = useTheme();
  const close = () => setPaletteOpen(false);
  const run = (fn: () => void) => () => {
    close();
    fn();
  };
  const inWorkspace = Boolean(frame && route.key);
  const goSection = (id: SectionId) => navigate(pathOf(route.kind, route.key, id));
  const genes =
    inWorkspace && frame?.results_visible
      ? (frame.summary?.targets ?? []).map((t) => t.target).sort((a, b) => a.localeCompare(b))
      : [];

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setPaletteOpen}
      label="Search and commands"
      loop
      filter={paletteFilter}
      overlayClassName="qp-fade fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px]"
      contentClassName="qp-pop fixed top-[12vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-2xl border border-line bg-surface text-fg shadow-lg outline-none"
    >
      <div className="flex items-center gap-2 border-b border-line px-4">
        <Command.Input
          placeholder={
            inWorkspace
              ? "Go to a section, a gene, or run an action…"
              : "Open a study, or run an action…"
          }
          className="h-12 w-full bg-transparent text-[15px] text-fg outline-none placeholder:text-faint"
        />
        <Kbd>Esc</Kbd>
      </div>
      <Command.List className="qp-scroll max-h-[min(60vh,440px)] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-8 text-center text-sm text-muted">
          Nothing matches. Try a section name or a gene.
        </Command.Empty>

        {inWorkspace ? (
          <Command.Group heading="Go to">
            {SECTIONS.filter(
              (s) => s.scope === "workspace" && !s.hidden && !states[s.id].absent,
            ).map((s) => {
              const st = states[s.id];
              return (
                <Item
                  key={s.id}
                  value={`go ${s.label}`}
                  onSelect={run(() => goSection(s.id))}
                  icon={st.reachable ? <s.icon /> : <Lock />}
                  hint={st.reachable ? s.hint : st.lockReason}
                  shortcut={
                    G_KEY[s.id] ? (
                      <>
                        <Kbd>g</Kbd>
                        <Kbd>{G_KEY[s.id]}</Kbd>
                      </>
                    ) : null
                  }
                >
                  {s.label}
                  {st.count > 0 ? (
                    <span className="ml-2 text-xs text-accent">{count(st.count)} waiting</span>
                  ) : null}
                </Item>
              );
            })}
          </Command.Group>
        ) : null}

        {inWorkspace ? (
          <Command.Group heading="Actions">
            {SECTION_ACTIONS.filter(
              (a) => states[a.section].reachable && !states[a.section].absent,
            ).map((a) => (
              <Item
                key={a.label}
                value={a.label}
                keywords={a.keywords}
                icon={<Play />}
                hint={SECTION[a.section].label}
                onSelect={run(() => {
                  goSection(a.section);
                  focusAction(a.label);
                })}
              >
                {a.label}…
              </Item>
            ))}
            <Item
              value="Ask your data"
              keywords={["question", "model", "chat"]}
              icon={<MessageSquareText />}
              onSelect={run(openAsk)}
              shortcut={
                <>
                  <Kbd>{MOD}</Kbd>
                  <Kbd>J</Kbd>
                </>
              }
            >
              Ask your data
            </Item>
          </Command.Group>
        ) : null}

        {genes.length ? (
          <Command.Group heading="Genes">
            {genes.map((g) => (
              <Item
                key={g}
                value={`gene ${g}`}
                icon={<Microscope />}
                onSelect={run(() => navigate(pathOf(route.kind, route.key, "gene", g)))}
              >
                {g}
              </Item>
            ))}
          </Command.Group>
        ) : null}

        {workspaces?.length ? (
          <Command.Group heading="Studies">
            {workspaces.slice(0, 12).map((w) => (
              <Item
                key={w.key}
                value={`study ${w.title} ${w.key}`}
                keywords={[w.file_name ?? ""]}
                icon={<FlaskConical />}
                hint={[
                  w.file_name,
                  w.n_plates != null ? `${count(w.n_plates)} plates` : null,
                  w.n_samples != null ? `${count(w.n_samples)} samples` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
                onSelect={run(() => navigate(workspacePath(w)))}
              >
                {w.title}
              </Item>
            ))}
          </Command.Group>
        ) : null}

        <Command.Group heading="General">
          <Item
            value="Open a file"
            keywords={["rdml", "upload", "import"]}
            icon={<FileUp />}
            onSelect={run(() => {
              navigate("/");
              requestOpenFile();
            })}
            shortcut={
              <>
                <Kbd>{MOD}</Kbd>
                <Kbd>O</Kbd>
              </>
            }
          >
            Open a file…
          </Item>
          <Item
            value="All studies"
            keywords={["home", "open", "demo", "recent"]}
            icon={<FolderOpen />}
            onSelect={run(() => navigate("/"))}
          >
            All studies and the demo
          </Item>
          <Item
            value="Settings"
            keywords={["model", "autonomy", "theme"]}
            icon={<SECTION.settings.icon />}
            onSelect={run(() => navigate("/settings"))}
          >
            Settings
          </Item>
          <Item
            value={theme === "dark" ? "Light theme" : "Dark theme"}
            keywords={["theme", "dark", "light", "appearance"]}
            icon={theme === "dark" ? <Sun /> : <Moon />}
            onSelect={run(() => setTheme(theme === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
          </Item>
          <Item
            value="Keyboard shortcuts"
            keywords={["keys", "help"]}
            icon={<Keyboard />}
            onSelect={run(openShortcuts)}
            shortcut={<Kbd>?</Kbd>}
          >
            Keyboard shortcuts
          </Item>
          {route.key && route.section !== "agents" ? (
            <Item
              value="Agents"
              keywords={["mcp", "claude", "requests"]}
              icon={<Zap />}
              onSelect={run(() => goSection("agents"))}
            >
              Agents and requests
            </Item>
          ) : null}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
