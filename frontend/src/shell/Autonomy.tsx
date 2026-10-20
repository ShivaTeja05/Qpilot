/**
 * What agents may do on their own: Suggest · Decide and tell me (PUT /api/settings). The switch
 * sits in the top bar on wide screens; narrower, a chip shows the state and opens the switch.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { cn } from "@/lib/cn";
import { Popover, SegmentedControl, Tooltip } from "@/ui";
import type { SystemView } from "./data";
import { useWrite } from "./writes";

type Autonomy = "suggest" | "decide_and_tell";

export const AUTONOMY_WORDS: Record<Autonomy, string> = {
  suggest: "Suggest",
  decide_and_tell: "Decide and tell me",
};

function useAutonomy(system: SystemView | undefined) {
  const qc = useQueryClient();
  const write = useWrite<Autonomy, unknown>({
    mutationFn: (autonomy) => unwrap(api.PUT("/api/settings", { body: { autonomy } })),
    success: (_r, a) =>
      a === "suggest"
        ? { title: "Agents now only suggest", description: "Every agent request waits for you." }
        : {
            title: "Agents may now decide and tell you",
            description:
              "Only choices that cannot change any conclusion; the rest still wait for you.",
          },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["system"] }),
  });
  const value: Autonomy =
    write.isPending && write.variables ? write.variables : (system?.autonomy ?? "suggest");
  return { value, set: (v: Autonomy) => write.mutate(v) };
}

function Policy({ system }: { system: SystemView | undefined }) {
  return (
    <span className="flex max-w-xs flex-col gap-1">
      <span className="font-medium">What agents may do on their own</span>
      {(system?.policy ?? []).map((line) => (
        <span key={line} className="opacity-85">
          {line}
        </span>
      ))}
    </span>
  );
}

/** The switch itself (Settings may use it too). */
export function AutonomySwitch({
  system,
  size = "sm",
  withTooltip = true,
}: {
  system: SystemView | undefined;
  size?: "sm" | "md";
  withTooltip?: boolean;
}) {
  const { value, set } = useAutonomy(system);
  const control = (
    <span>
      <SegmentedControl
        size={size}
        label="What agents may do on their own"
        value={value}
        onValueChange={set}
        options={[
          { value: "suggest", label: AUTONOMY_WORDS.suggest },
          { value: "decide_and_tell", label: AUTONOMY_WORDS.decide_and_tell },
        ]}
      />
    </span>
  );
  return withTooltip ? <Tooltip content={<Policy system={system} />}>{control}</Tooltip> : control;
}

/** The collapsed form: a chip with the current state that opens the switch and the policy. */
export function AutonomyChip({
  system,
  className,
}: {
  system: SystemView | undefined;
  className?: string;
}) {
  const value = system?.autonomy ?? "suggest";
  return (
    <Popover
      label="What agents may do on their own"
      align="end"
      className="w-80"
      trigger={
        <button
          type="button"
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors hover:bg-bg-subtle",
            value === "decide_and_tell"
              ? "border-accent/40 bg-accent-soft text-accent-strong"
              : "border-line text-muted",
            className,
          )}
        >
          <Bot className="size-3.5" aria-hidden />
          Agents: {value === "suggest" ? "suggest" : "decide and tell"}
          <ChevronDown className="size-3" aria-hidden />
        </button>
      }
    >
      <div className="flex flex-col gap-3 text-[13px]">
        <AutonomySwitch system={system} withTooltip={false} />
        <div className="text-muted">
          <Policy system={system} />
        </div>
      </div>
    </Popover>
  );
}
