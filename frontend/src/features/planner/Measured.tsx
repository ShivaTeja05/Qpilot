/** What this study measured that a plan needs: groups, noise, the rule, efficiencies, plates. */
import { Info } from "lucide-react";
import { count, fixed } from "@/lib/format";
import { Card, CardBody, Tooltip } from "@/ui";
import type { PlannerView } from "./api";
import { GROUP_TONES } from "./words";

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[12px] text-muted">{label}</div>
      <div className="mt-0.5 text-[16px] font-semibold text-fg">{value}</div>
      {sub ? <div className="mt-0.5 text-[12px] leading-snug text-muted">{sub}</div> : null}
    </div>
  );
}

export function Measured({ view }: { view: PlannerView }) {
  const s = view.sigma;
  return (
    <Card as="section" aria-labelledby="planner-measured">
      <CardBody className="grid gap-x-8 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
        <h2 id="planner-measured" className="sr-only">
          What this study measured
        </h2>
        <Stat
          label="Groups compared"
          value={
            <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              {view.groups.map((g, i) => (
                <span key={g.label} className="inline-flex items-baseline gap-1.5">
                  <span
                    aria-hidden
                    className="inline-block size-2.5 translate-y-[-1px] rounded-full"
                    style={{ background: GROUP_TONES[i % GROUP_TONES.length] }}
                  />
                  <span>{g.label}</span>
                  <span className="font-mono tabular">{count(g.n)}</span>
                </span>
              ))}
            </span>
          }
          sub={`As precise as ${count(Math.floor(view.n_equivalent))} per group in a balanced design.`}
        />
        <Stat
          label={`Noise between samples (σ, log2) across ${count(s.n)} genes`}
          value={
            <span className="inline-flex items-center gap-1.5">
              <span className="font-mono tabular">median {fixed(s.median, 2)}</span>
              <Tooltip content={view.sigma_source}>
                <button
                  type="button"
                  className="inline-flex size-5 items-center justify-center rounded text-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-focus"
                  aria-label="How σ is measured"
                >
                  <Info size={14} aria-hidden />
                </button>
              </Tooltip>
            </span>
          }
          sub={
            <span className="font-mono tabular">
              {fixed(s.min, 2)} to {fixed(s.max, 2)} · middle half {fixed(s.q1, 2)}–{fixed(s.q3, 2)}
            </span>
          }
        />
        <Stat
          label="The conclusion rule"
          value={`at least ${view.min_fold}-fold, p < ${view.alpha}`}
          sub={view.rule_text}
        />
        <Stat
          label="How it was run"
          value={
            view.plates ? (
              <span className="font-mono tabular">
                {count(view.plates.n_plates)} × {count(view.plates.wells_per_plate)} wells
              </span>
            ) : (
              "—"
            )
          }
          sub={
            view.plates?.text.replace(/^This study: /, "") ?? "The per-well table is not available."
          }
        />
        <p className="text-[12px] leading-snug text-muted sm:col-span-2 xl:col-span-4">
          {view.efficiency.text}
        </p>
      </CardBody>
    </Card>
  );
}
