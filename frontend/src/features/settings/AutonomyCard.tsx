/**
 * Settings → what agents may do on their own. Autonomy is set per study, with the switch in that
 * study's top bar (coordinator decision #0234), so Settings explains the two levels and shows the
 * policy lines the server serves; it does not set anything.
 */
import { Bot, UserCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardBody, CardHeader } from "@/ui";
import { AUTONOMY_WORDS } from "@/shell/Autonomy";
import type { SystemView } from "@/shell/data";
import { policyParts, type Autonomy } from "./system";

const LEVELS: { value: Autonomy; icon: ReactNode; detail: string }[] = [
  {
    value: "suggest",
    icon: <UserCheck />,
    detail: "Agents only suggest. Every request from an agent waits for you.",
  },
  {
    value: "decide_and_tell",
    icon: <Bot />,
    detail:
      "Agents may apply choices that cannot change any conclusion, and tell you. Everything else still waits for you.",
  },
];

export function AutonomyCard({ system }: { system: SystemView }) {
  return (
    <Card as="section" aria-labelledby="settings-autonomy">
      <CardHeader
        id="settings-autonomy"
        title="What agents may do on their own"
        hint="Set for each study, with the switch in that study's top bar. A new study starts at Suggest."
      />
      <CardBody className="flex flex-col gap-4">
        <ul className="grid gap-2 sm:grid-cols-2">
          {LEVELS.map((l) => (
            <li
              key={l.value}
              className="flex gap-3 rounded-xl border border-line bg-surface-2 p-3.5"
            >
              <span
                className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-strong [&_svg]:size-4"
                aria-hidden
              >
                {l.icon}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-fg">
                  {AUTONOMY_WORDS[l.value]}
                </span>
                <span className="mt-0.5 block text-[13px] text-muted">{l.detail}</span>
              </span>
            </li>
          ))}
        </ul>
        {system.policy.length ? (
          <div>
            <h3 className="text-xs font-medium tracking-wide text-muted uppercase">
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
