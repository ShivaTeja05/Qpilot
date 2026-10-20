/**
 * Settings → Autonomy: what agents may do on their own (`PUT /api/settings`), with the policy
 * lines the server serves. The same setting as the top bar's switch; both read `["system"]`.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useId } from "react";
import { api, unwrap } from "@/api/client";
import { Card, CardBody, CardHeader } from "@/ui";
import { cn } from "@/lib/cn";
import type { SystemView } from "@/shell/data";
import { useWrite } from "@/shell/writes";
import { policyParts, type Autonomy } from "./system";

const OPTIONS: { value: Autonomy; title: string; detail: string }[] = [
  {
    value: "suggest",
    title: "Suggest",
    detail: "Agents only suggest. Every request from an agent waits for you.",
  },
  {
    value: "decide_and_tell",
    title: "Decide and tell me",
    detail:
      "Agents may apply choices that cannot change any conclusion, and tell you. Everything else still waits for you.",
  },
];

export function AutonomyCard({ system }: { system: SystemView }) {
  const qc = useQueryClient();
  const name = useId();
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
  const value = write.isPending && write.variables ? write.variables : system.autonomy;

  return (
    <Card as="section" aria-labelledby="settings-autonomy">
      <CardHeader
        id="settings-autonomy"
        title="What agents may do on their own"
        hint="For this launch of qpilot app. A choice that can change a conclusion always waits for a person."
      />
      <CardBody className="flex flex-col gap-4">
        <fieldset className="grid gap-2 sm:grid-cols-2">
          <legend className="sr-only">Autonomy for agents</legend>
          {OPTIONS.map((o) => {
            const checked = value === o.value;
            return (
              <label
                key={o.value}
                className={cn(
                  "relative flex cursor-pointer gap-3 rounded-xl border p-3.5 transition-colors duration-150 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus",
                  checked
                    ? "border-accent bg-accent-soft/50"
                    : "border-line bg-surface hover:border-line-strong",
                )}
              >
                <input
                  type="radio"
                  name={name}
                  value={o.value}
                  checked={checked}
                  aria-labelledby={`${name}-${o.value}`}
                  aria-describedby={`${name}-${o.value}-detail`}
                  // Never disabled while saving: that would drop keyboard focus.
                  onChange={() => !write.isPending && write.mutate(o.value)}
                  className="mt-0.5 size-4 shrink-0 accent-accent"
                />
                <span className="min-w-0">
                  <span id={`${name}-${o.value}`} className="block text-sm font-semibold text-fg">
                    {o.title}
                  </span>
                  <span
                    id={`${name}-${o.value}-detail`}
                    className="mt-0.5 block text-[13px] text-muted"
                  >
                    {o.detail}
                  </span>
                </span>
              </label>
            );
          })}
        </fieldset>
        {system.policy.length ? (
          <div>
            <h3 className="text-xs font-medium tracking-wide text-faint uppercase">
              The policy, whatever the setting
            </h3>
            <ul className="mt-2 flex flex-col gap-1.5 text-[13px]">
              {system.policy.map((line) => {
                const [head, rest] = policyParts(line);
                return (
                  <li key={line} className="flex gap-2">
                    <span
                      aria-hidden
                      className="mt-[7px] size-1.5 shrink-0 rounded-full bg-faint"
                    />
                    <span>
                      {head ? <span className="font-semibold text-fg">{head}: </span> : null}
                      <span className="text-muted">{rest}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
