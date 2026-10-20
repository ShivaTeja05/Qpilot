/**
 * Where the session stands on its way to Prism, read from the workspace frame (the Studio stages)
 * and the Prism draft inbox: choices locked → project accepted → sent → round trip. The server
 * enforces every step; this only says which one is next and why a button waits.
 */
import { effectivePayload } from "@/lib/vocab";
import type { Proposal, Workspace } from "./api";

export type StepState = "done" | "current" | "waiting";

export interface ProjectState {
  /** The project accepted for the analysis shown now. */
  accepted: Proposal | null;
  /** A project waiting for a person. */
  waiting: Proposal | null;
  /** A project accepted for an earlier analysis (the decisions changed since). */
  earlier: Proposal | null;
}

export interface Flow {
  choicesConfirmed: boolean;
  project: ProjectState;
  /** The analysis shown now has been sent to Prism. */
  sent: boolean;
  /** Questions from a round trip waiting for a person. */
  roundTripWaiting: number;
  /** Why Draft waits, in words (null: it can run). */
  draftBlocked: string | null;
  /** Why Send waits, in words (null: it can run). */
  sendBlocked: string | null;
  steps: { id: "choices" | "draft" | "send" | "roundtrip"; title: string; state: StepState; detail: string }[];
}

function stage(workspace: Workspace, name: string) {
  return workspace.stages.find((s) => s.stage === name);
}

/** The project proposals of the Prism stage, split by whether they hold for the analysis shown. */
export function projectState(proposals: Proposal[], studyId: string | null | undefined): ProjectState {
  const projects = proposals.filter((p) => p.kind === "prism.project");
  const forStudy = (p: Proposal) => effectivePayload(p).study_id === studyId;
  const accepted = projects.filter((p) => (p.status === "accepted" || p.status === "edited") && forStudy(p));
  const waiting = projects.filter((p) => p.status === "proposed");
  const earlier = projects.filter((p) => (p.status === "accepted" || p.status === "edited") && !forStudy(p));
  return {
    accepted: accepted.at(-1) ?? null,
    waiting: waiting.at(-1) ?? null,
    earlier: accepted.length ? null : (earlier.at(-1) ?? null),
  };
}

export function flowOf(workspace: Workspace, prismInbox: Proposal[], roundTripInbox: Proposal[]): Flow {
  const choicesConfirmed = Boolean(stage(workspace, "choices")?.confirmed);
  const sent = Boolean(stage(workspace, "prism")?.confirmed);
  const project = projectState(prismInbox, workspace.study_id);
  const roundTripWaiting = roundTripInbox.filter((p) => p.status === "proposed").length;

  const draftBlocked = choicesConfirmed
    ? null
    : "Confirm the analysis choices in Results first: the project is drafted for exactly those choices.";
  const sendBlocked = !choicesConfirmed
    ? "Confirm the analysis choices in Results first."
    : project.accepted
      ? null
      : project.waiting
        ? "Accept the drafted Prism project first."
        : "Draft the Prism project and accept it first.";

  const at = !choicesConfirmed ? 0 : !project.accepted ? 1 : !sent ? 2 : 3;
  const state = (i: number): StepState => (i < at ? "done" : i === at ? "current" : "waiting");
  const steps: Flow["steps"] = [
    {
      id: "choices",
      title: "Lock the choices",
      state: state(0),
      detail: choicesConfirmed ? "Confirmed in Results" : "Decide and confirm in Results",
    },
    {
      id: "draft",
      title: "Draft the project",
      state: state(1),
      detail: project.accepted ? "Accepted" : project.waiting ? "Waiting for you" : "Not drafted yet",
    },
    {
      id: "send",
      title: "Send to Prism",
      state: state(2),
      detail: sent ? "Sent for this analysis" : "Writes the bundle",
    },
    {
      id: "roundtrip",
      title: "Round trip",
      // never "done": tables can come back from Prism again after any edit
      state: at === 3 ? "current" : "waiting",
      detail: roundTripWaiting ? `${roundTripWaiting} question${roundTripWaiting === 1 ? "" : "s"} waiting` : "What changed in Prism",
    },
  ];
  return { choicesConfirmed, project, sent, roundTripWaiting, draftBlocked, sendBlocked, steps };
}
