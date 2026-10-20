/**
 * The page's sections, in workflow order. This registry is the one shared file between the
 * feature owners: each section's component lives in `src/features/<id>/index.tsx` (default
 * export) and receives {@link SectionProps}. Change entries here only through the coordinator.
 */
import {
  Activity,
  CalendarRange,
  FileText,
  History,
  Quote,
  Route,
  BookCheck,
  Bot,
  FlaskConical,
  FolderOpen,
  GitBranch,
  LayoutGrid,
  Microscope,
  Send,
  Settings as SettingsIcon,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import type { Schemas } from "@/api/client";

export type SectionId =
  | "home"
  | "design"
  | "curves"
  | "results"
  | "gene"
  | "audit"
  | "trace"
  | "claims"
  | "prism"
  | "report"
  | "record"
  | "history"
  | "planner"
  | "agents"
  | "settings";

export interface SectionProps {
  /** The workspace frame (null on the global sections: home, settings). */
  workspace: Schemas["WorkspaceView"] | null;
  /** Path segments after the section (e.g. the gene name on `gene/ODC1`). */
  rest: string[];
}

export interface Section {
  id: SectionId;
  label: string;
  /** One line under the label in the rail and the palette. */
  hint: string;
  icon: LucideIcon;
  /** `global`: no workspace; `workspace`: needs one. */
  scope: "global" | "workspace";
  /** The Studio stage this section shows (design / curves are blind stages). */
  stage?: "design" | "curves" | "prism";
  /** Hidden until the design and the curves are confirmed (results stay blind until then). */
  needsResults?: boolean;
  /** Not reachable for a study analysed outside a Studio session. */
  sessionOnly?: boolean;
  /** Not listed in the rail (reached from other sections). */
  hidden?: boolean;
  component: LazyExoticComponent<ComponentType<SectionProps>>;
}

export const SECTIONS: Section[] = [
  {
    id: "home",
    label: "Open",
    hint: "Open a file, the demo or a recent study",
    icon: FolderOpen,
    scope: "global",
    component: lazy(() => import("@/features/home")),
  },
  {
    id: "design",
    label: "Design",
    hint: "What the samples are, the groups, the reference genes (blind)",
    icon: LayoutGrid,
    scope: "workspace",
    stage: "design",
    sessionOnly: true,
    component: lazy(() => import("@/features/design")),
  },
  {
    id: "curves",
    label: "Curves",
    hint: "Which wells amplified, and where the AI disagrees (blind)",
    icon: Activity,
    scope: "workspace",
    stage: "curves",
    sessionOnly: true,
    component: lazy(() => import("@/features/curves")),
  },
  {
    id: "results",
    label: "Results",
    hint: "Every gene, how robust it is, and the choices to decide",
    icon: FlaskConical,
    scope: "workspace",
    needsResults: true,
    component: lazy(() => import("@/features/results")),
  },
  {
    id: "gene",
    label: "Gene",
    hint: "One gene: result, robustness, audit, samples, curves",
    icon: Microscope,
    scope: "workspace",
    needsResults: true,
    hidden: true,
    component: lazy(() => import("@/features/gene")),
  },
  {
    id: "audit",
    label: "Audit",
    hint: "Every combination of eight decisions: one verdict per gene",
    icon: ShieldCheck,
    scope: "workspace",
    needsResults: true,
    component: lazy(() => import("@/features/audit")),
  },
  {
    id: "trace",
    label: "Trace",
    hint: "Follow any number down to the samples and wells that drive it",
    icon: Route,
    scope: "workspace",
    needsResults: true,
    component: lazy(() => import("@/features/trace")),
  },
  {
    id: "claims",
    label: "Claims",
    hint: "Paste what your paper says: every claim checked against this study",
    icon: Quote,
    scope: "workspace",
    needsResults: true,
    component: lazy(() => import("@/features/claims")),
  },
  {
    id: "prism",
    label: "Prism",
    hint: "Tables and figures for GraphPad Prism, and what came back",
    icon: Send,
    scope: "workspace",
    stage: "prism",
    needsResults: true,
    sessionOnly: true,
    component: lazy(() => import("@/features/prism")),
  },
  {
    id: "report",
    label: "Report",
    hint: "Methods paragraph, MIQE checklist and a study passport to share",
    icon: FileText,
    scope: "workspace",
    needsResults: true,
    component: lazy(() => import("@/features/report")),
  },
  {
    id: "record",
    label: "Record",
    hint: "The hash-chained Analysis Record anyone can re-run",
    icon: BookCheck,
    scope: "workspace",
    component: lazy(() => import("@/features/record")),
  },
  {
    id: "history",
    label: "History",
    hint: "Replay every decision and see what each one changed",
    icon: History,
    scope: "workspace",
    needsResults: true,
    component: lazy(() => import("@/features/history")),
  },
  {
    id: "planner",
    label: "Plan next",
    hint: "Samples needed, what you could detect, and a plate layout",
    icon: CalendarRange,
    scope: "workspace",
    needsResults: true,
    component: lazy(() => import("@/features/planner")),
  },
  {
    id: "agents",
    label: "Agents",
    hint: "What AI agents asked, and how to connect one",
    icon: Bot,
    scope: "workspace",
    component: lazy(() => import("@/features/agents")),
  },
  {
    id: "settings",
    label: "Settings",
    hint: "The model, autonomy, and what never leaves this machine",
    icon: SettingsIcon,
    scope: "global",
    component: lazy(() => import("@/features/settings")),
  },
];

export const SECTION = Object.fromEntries(SECTIONS.map((s) => [s.id, s])) as Record<
  SectionId,
  Section
>;

/** The hash path of a section of a workspace (`/s/<key>/results`, `/r/<key>/gene/ODC1`). */
export function sectionPath(
  workspace: Pick<Schemas["WorkspaceView"], "key" | "kind"> | null,
  id: SectionId,
  ...rest: string[]
): string {
  if (SECTION[id].scope === "global" || !workspace) return id === "home" ? "/" : `/${id}`;
  const prefix = workspace.kind === "session" ? "s" : "r";
  return ["", prefix, workspace.key, id, ...rest.map(encodeURIComponent)].join("/");
}

export { GitBranch as ChainIcon };
