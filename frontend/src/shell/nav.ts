/**
 * Where each section stands for the open workspace: reachable or locked (with the reason in
 * words), done, how many proposals wait. The rail, the bottom bar, the palette and the section
 * guard all read this one function, so they never disagree.
 */
import type { Schemas } from "@/api/client";
import { SECTIONS, type Section, type SectionId } from "./sections";

type Frame = Schemas["WorkspaceView"];
type Stage = Schemas["StageView"];

export interface SectionState {
  section: Section;
  /** Not offered at all for this workspace (a Studio-only section of a plain study). */
  absent: boolean;
  /** Can be opened. */
  reachable: boolean;
  /** Why not, in words ("Confirm the design first"). */
  lockReason?: string;
  /** The stage is confirmed (or the audit has run). */
  done: boolean;
  /** Proposals or requests waiting for a person. */
  count: number;
  /**
   * The study's file is still being read after a server start (`frame.warming`): its stages are
   * not known yet, so nothing is shown as locked or confirmed.
   */
  unknown: boolean;
}

const stageOf = (frame: Frame, name: Stage["stage"]) => frame.stages.find((s) => s.stage === name);

const BLIND_REASON = "Blind until the design and the curves are confirmed";

/** The state of every section for a workspace frame (or the global sections without one). */
export function sectionStates(
  frame: Frame | null | undefined,
  pendingRequests = 0,
): Record<SectionId, SectionState> {
  const out = {} as Record<SectionId, SectionState>;
  for (const section of SECTIONS) {
    const s: SectionState = {
      section,
      absent: false,
      reachable: true,
      done: false,
      count: 0,
      unknown: false,
    };
    out[section.id] = s;
    if (section.scope === "global") continue;
    if (!frame) {
      s.absent = true;
      s.reachable = false;
      continue;
    }
    const isSession = frame.kind === "session";
    if (section.sessionOnly && !isSession) {
      s.absent = true;
      s.reachable = false;
      s.lockReason = "Only for files opened in Studio";
      continue;
    }
    if (frame.warming) {
      s.unknown = true;
      if (section.id === "agents") s.count = pendingRequests;
      continue;
    }
    if (section.needsResults && !frame.results_visible) {
      s.reachable = false;
      s.lockReason = isSession ? BLIND_REASON : "No results for this study yet";
    }
    switch (section.id) {
      case "design": {
        const st = stageOf(frame, "design");
        s.done = Boolean(st?.confirmed);
        s.count = st?.pending ?? 0;
        break;
      }
      case "curves": {
        const st = stageOf(frame, "curves");
        s.done = Boolean(st?.confirmed);
        s.count = st?.pending ?? 0;
        if (st && !st.open) {
          s.reachable = false;
          s.lockReason = st.blockers[0] ?? "Confirm the design first";
        }
        break;
      }
      case "results": {
        const st = stageOf(frame, "choices");
        s.done = Boolean(st?.confirmed);
        s.count = st?.pending ?? 0;
        break;
      }
      case "audit":
        s.done = frame.has_audit;
        break;
      case "prism": {
        // Reachable with the results (docs/app.md §2): its routes table and preview help before
        // the choices are locked; Draft / Send wait for that step and the server says so.
        const st = stageOf(frame, "prism");
        const rt = stageOf(frame, "roundtrip");
        s.done = Boolean(st?.confirmed);
        s.count = (st?.pending ?? 0) + (rt?.pending ?? 0);
        break;
      }
      case "agents":
        s.count = pendingRequests;
        break;
      default:
        break;
    }
  }
  return out;
}

/** The workflow sections shown in the rail for a workspace, in order. */
export const WORKFLOW: SectionId[] = ["design", "curves", "results", "audit", "prism", "record"];

/** The tools on a study's results, shown in the rail under the workflow. */
export const TOOLS: SectionId[] = ["trace", "claims", "history", "report", "planner"];
