import { EyeOff, Lock } from "lucide-react";
import { useLocation } from "wouter";
import { Button, EmptyState } from "@/ui";
import { focusAction } from "./actions";
import type { WorkspaceView } from "./data";
import type { SectionState } from "./nav";
import { pathOf, type Route } from "./route";
import { SECTION, type SectionId } from "./sections";

/**
 * Shown instead of a section that is not reachable yet: why, in words, and the step that opens
 * it. The server refuses blind data anyway (403 `blind`); this only says so kindly.
 */
export function LockedSection({
  state,
  frame,
  route,
}: {
  state: SectionState;
  frame: WorkspaceView;
  route: Route;
}) {
  const [, navigate] = useLocation();
  const s = state.section;
  const step = frame.next_step;
  const target = (step?.section in SECTION ? step.section : null) as SectionId | null;
  const blind = s.needsResults && !frame.results_visible && frame.kind === "session";
  if (state.absent) {
    return (
      <EmptyState
        className="mx-auto mt-10 max-w-xl"
        icon={<Lock />}
        title={`${s.label} is for files opened in Studio`}
        action={
          <Button
            variant="primary"
            onClick={() => navigate(pathOf(route.kind, route.key, "results"))}
          >
            Go to Results
          </Button>
        }
      >
        This study was analysed outside a Studio session (by{" "}
        <code className="font-mono text-[12px]">qpilot run</code> or an agent), so it has no design
        or curves stage to review here.
      </EmptyState>
    );
  }
  return (
    <EmptyState
      className="mx-auto mt-10 max-w-xl"
      icon={blind ? <EyeOff /> : <Lock />}
      title={
        blind
          ? `${s.label} stays hidden until the design and the curves are confirmed`
          : `${s.label} is not open yet`
      }
      action={
        target && target !== route.section ? (
          <Button
            variant="primary"
            onClick={() => {
              navigate(pathOf(route.kind, route.key, target));
              focusAction(step.action);
            }}
          >
            {step.action ?? `Go to ${SECTION[target].label}`}
          </Button>
        ) : null
      }
    >
      <p>{state.lockReason}.</p>
      {blind ? (
        <p className="mt-2">
          Studio is blind on purpose: no fold change, p-value or group difference is shown or sent
          before then, so the design and the curves are decided on the evidence, not on the answer
          they give.
        </p>
      ) : null}
      {step?.title ? <p className="mt-2 font-medium text-fg">Next: {step.title}</p> : null}
    </EmptyState>
  );
}
