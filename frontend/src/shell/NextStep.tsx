import { ArrowRight, Compass } from "lucide-react";
import { useLocation } from "wouter";
import { Button } from "@/ui";
import { focusAction } from "./actions";
import type { WorkspaceView } from "./data";
import { pathOf, type Route } from "./route";
import { SECTION, type SectionId } from "./sections";

/**
 * The next-step banner under the top bar (workspace sections): `WorkspaceView.next_step` with a
 * button that goes to its section and focuses the named action.
 */
export function NextStepBanner({ frame, route }: { frame: WorkspaceView; route: Route }) {
  const [, navigate] = useLocation();
  const step = frame.next_step;
  if (!step?.title) return null;
  const target = (step.section in SECTION ? step.section : null) as SectionId | null;
  const here = target === route.section;
  const label = step.action || (target && !here ? `Go to ${SECTION[target].label}` : null);
  const go = () => {
    if (target && !here)
      navigate(
        target === "home" || target === "settings"
          ? pathOf(null, null, target)
          : pathOf(route.kind, route.key, target),
      );
    focusAction(step.action);
  };
  return (
    <div role="region" aria-label="Next step" className="border-b border-line bg-accent-soft/40">
      <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2 sm:px-6 lg:px-8">
        <Compass className="size-4 shrink-0 text-accent" aria-hidden />
        <p className="min-w-0 flex-1 text-[13px] leading-snug">
          <span className="font-semibold text-fg">Next: {step.title}</span>
          {step.detail ? <span className="text-muted max-sm:hidden"> — {step.detail}</span> : null}
        </p>
        {label ? (
          <Button
            size="sm"
            variant={here ? "secondary" : "primary"}
            onClick={go}
            className="shrink-0"
          >
            {label}
            {!here ? <ArrowRight aria-hidden /> : null}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
