/**
 * How it works: the audit's steps (with this audit's own numbers), what it varies at each stage
 * of the analysis, how each verdict is decided, the method checks (known answers, planted
 * faults, small experiments) and the limits, stated plainly.
 */
import { ArrowRight } from "lucide-react";
import { HBars, VERDICT_ORDER } from "@/charts";
import { cn } from "@/lib/cn";
import { count, plural, shortHash } from "@/lib/format";
import { Badge, Card, CardBody, CardHeader, ErrorPanel, LoadingBlock } from "@/ui";
import { useAuditHow, type AuditTarget } from "./api";
import type { AuditHow, AuditManifest, HowDecision } from "./types";
import { AUDIT_STEPS, LIMITS, NOT_RUN_WORDS, tierOf } from "./words";
import { VerdictMark } from "./VerdictMark";

/** A tiny number as the page writes it: `5.3 × 10⁻¹⁵`. */
export function scientific(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  if (x === 0) return "0";
  const [m, e] = x.toExponential(1).split("e");
  const sup: Record<string, string> = {
    "-": "⁻",
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
  };
  const exp = String(Number(e)).replace(/[-0-9]/g, (c) => sup[c] ?? c);
  return `${m} × 10${exp}`;
}

export function HowTab({ target, manifest }: { target: AuditTarget; manifest: AuditManifest }) {
  const how = useAuditHow(target);
  if (how.isError)
    return (
      <ErrorPanel
        error={how.error}
        title="How the audit works could not be read"
        onRetry={() => void how.refetch()}
      />
    );
  if (!how.data) return <LoadingBlock label="Reading how the audit works" lines={8} />;
  const h = how.data;
  return (
    <div className="space-y-5">
      <Steps how={h} manifest={manifest} />
      <Stages how={h} />
      <div className="grid gap-5 lg:grid-cols-2">
        <Rules how={h} />
        <Reading />
      </div>
      <Tested how={h} />
      <Limits how={h} />
    </div>
  );
}

function Steps({ how, manifest }: { how: AuditHow; manifest: AuditManifest }) {
  const r = manifest.reproduces_qpilot;
  const facts: Record<string, string | null> = {
    "Reproduce qPilot": r
      ? r.ok
        ? `Reproduced ${r.genes != null ? plural(r.genes, "gene") : "every gene"} exactly: the largest difference was ${scientific(r.max_abs_diff_log2fc)} in log2 fold change and ${scientific(r.max_abs_diff_p)} in p (allowed: ${scientific(r.tolerance)}).`
        : "Did not reproduce qPilot's result."
      : null,
    "Lock the plan": manifest.lock_sha256 ? `lock ${shortHash(manifest.lock_sha256, 12)}` : null,
    "Every combination": `${how.total.replace(/,/g, " ")} analyses${how.seconds && how.seconds !== "0" ? `, ${how.seconds} s` : ""}.`,
    Verdicts: `${count(how.reasonable)} reasonable analyses per gene decide the verdict; shortcuts are shown, never counted.`,
    Bind: manifest.chain_head ? `chain ${shortHash(manifest.chain_head, 12)}` : null,
  };
  return (
    <Card as="section" aria-labelledby="how-steps">
      <CardHeader id="how-steps" title="The audit, step by step" hint={how.call_rule} />
      <CardBody>
        <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          {AUDIT_STEPS.map((s, i) => (
            <li key={s.title} className="relative rounded-lg border border-line p-3">
              <p className="flex items-center gap-2 text-[13px] font-semibold text-fg">
                <span className="inline-flex size-5 items-center justify-center rounded-full bg-fg text-[11px] font-semibold text-surface tabular">
                  {i + 1}
                </span>
                {s.title}
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-muted">{s.text}</p>
              {facts[s.title] ? (
                <p className="mt-2 text-xs font-medium break-words text-fg tabular">
                  {facts[s.title]}
                </p>
              ) : null}
              {i < AUDIT_STEPS.length - 1 ? (
                <ArrowRight
                  aria-hidden
                  className="absolute top-1/2 -right-3 hidden size-3.5 -translate-y-1/2 text-faint xl:block"
                />
              ) : null}
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}

function Stages({ how }: { how: AuditHow }) {
  return (
    <Card as="section" aria-labelledby="how-stages">
      <CardHeader
        id="how-stages"
        title="What it varies, stage by stage"
        hint={`${how.total.replace(/,/g, " ")} analyses in all: every combination of the options below.`}
      />
      <CardBody>
        <ol className="space-y-4">
          {how.stages.map((stage, i) => (
            <li key={stage.title} className="grid gap-3 md:grid-cols-[200px_minmax(0,1fr)]">
              <div>
                <p className="text-[13px] font-semibold text-fg">
                  <span className="mr-1.5 text-faint tabular">{i + 1}.</span>
                  {stage.title}
                </p>
                <p className="mt-0.5 text-xs text-muted">{stage.text}</p>
              </div>
              <div className="space-y-3">
                {stage.decisions.map((d) => (
                  <StageDecision key={d.name} d={d} />
                ))}
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-3 text-xs text-muted">
          <OptionChip tier="prespecified" label="Planned" />
          <OptionChip tier="defensible" label="Reasonable alternative" />
          <OptionChip
            tier="common_practice"
            label="Common shortcut (shown, not counted in verdicts)"
          />
        </p>
      </CardBody>
    </Card>
  );
}

function StageDecision({ d }: { d: HowDecision }) {
  return (
    <div className="rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <p className="text-sm font-medium text-fg">{d.name}</p>
        {d.changes_question ? (
          <Badge tone="info">changes the question; reported separately</Badge>
        ) : null}
        {d.alone != null ? (
          <span className="ml-auto text-xs text-muted tabular">
            {d.alone
              ? `on its own changes ${plural(d.alone, "call")}`
              : "changes no call on its own"}
          </span>
        ) : null}
      </div>
      <p className="mt-0.5 text-xs text-muted">
        {d.question} {plural(d.n_options, "option")}:{" "}
        {plural(d.n_reasonable, "reasonable alternative")},{" "}
        {plural(d.n_shortcut, "common shortcut")}.
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {d.options.map((o) => (
          <OptionChip key={o.label} tier={o.tier} label={o.label} />
        ))}
        {d.more ? (
          <span className="self-center text-xs text-faint">and {count(d.more)} more</span>
        ) : null}
      </div>
    </div>
  );
}

function OptionChip({ tier, label }: { tier: string; label: string }) {
  const t = tierOf(tier)?.raw;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs",
        t === "prespecified" && "border-fg font-semibold text-fg",
        t === "defensible" && "border-line-strong text-fg",
        t === "common_practice" && "border-dashed border-line-strong text-muted",
        !t && "border-line text-muted",
      )}
    >
      {label}
    </span>
  );
}

function Rules({ how }: { how: AuditHow }) {
  return (
    <Card as="section" aria-labelledby="how-rules">
      <CardHeader
        id="how-rules"
        title="How each verdict is decided"
        hint="Read in this order: the first rule that fits is the verdict."
      />
      <CardBody>
        <dl className="space-y-3">
          {VERDICT_ORDER.filter((v) => how.rules[v]).map((v) => (
            <div key={v}>
              <dt>
                <VerdictMark verdict={v} />
              </dt>
              <dd className="mt-0.5 pl-[18px] text-[13px] text-muted">{how.rules[v]}</dd>
            </div>
          ))}
        </dl>
      </CardBody>
    </Card>
  );
}

function Reading() {
  const terms: [string, string][] = [
    [
      "Reasonable analyses",
      "Every combination of choices a careful lab could defend, with your question fixed. Common shortcuts are shown but kept out of verdicts.",
    ],
    [
      "Same call in N of 100",
      "How often reasonable analyses give the same call as your planned analysis, per hundred.",
    ],
    [
      "Fewest samples that change it",
      "The smallest set of samples whose removal changes the call.",
    ],
    ["The fold-change line", "The size a change must reach before it is called."],
    [
      "Planned analysis",
      "The analysis fixed before results were seen. With every choice as planned, the audit reproduces qPilot exactly.",
    ],
  ];
  return (
    <Card as="section" aria-labelledby="how-read">
      <CardHeader id="how-read" title="How to read the audit" />
      <CardBody>
        <dl className="space-y-2.5 text-[13px]">
          {terms.map(([t, d]) => (
            <div key={t}>
              <dt className="font-medium text-fg">{t}</dt>
              <dd className="text-muted">{d}</dd>
            </div>
          ))}
        </dl>
      </CardBody>
    </Card>
  );
}

function Tested({ how }: { how: AuditHow }) {
  const known = how.known;
  return (
    <Card as="section" aria-labelledby="how-tested">
      <CardHeader
        id="how-tested"
        title="Has the method been tested?"
        hint="Checks of the audit itself, against known answers, planted faults and data with no real difference."
      />
      <CardBody className="space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          {known ? (
            <TestCard label="Known answers" value={known.efficiency[0]?.error_text ?? "—"}>
              median error against true dilution ratios with the best efficiency choice (
              {known.efficiency[0]?.label}), over {plural(known.cases, "comparison")}. When
              reasonable analyses disagree most, the planned answer is off by{" "}
              {known.spread_warns.top} %, against {known.spread_warns.other} % otherwise.
            </TestCard>
          ) : null}
          {how.faults ? (
            <TestCard
              label="Planted faults"
              value={`${count(how.faults.caught)} of ${count(how.faults.changed)}`}
            >
              faults that changed a call were caught, out of {plural(how.faults.trials, "fault")}{" "}
              planted in real data.
            </TestCard>
          ) : null}
          {how.small.length ? (
            <TestCard
              label="No real difference"
              value={`${how.small[0]!.single} % → ${how.small[0]!.filtered} %`}
            >
              false calls in {how.small[0]!.size} vs {how.small[0]!.size} experiments drawn from
              real data: one analysis, against requiring the call to hold across reasonable
              analyses.
            </TestCard>
          ) : null}
        </div>
        {how.not_run.length ? (
          <div className="rounded-lg bg-sunken p-3 text-[13px]">
            <p className="font-medium text-fg">Not run on this audit</p>
            <p className="mt-0.5 text-muted">
              These checks test the method on this data rather than audit the study, and take
              several minutes, so a study's audit leaves them out. The Decision Simulator's own
              benchmark runs them.
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
              {how.not_run.map((n) => (
                <li key={n}>{NOT_RUN_WORDS[n] ?? n}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {known ? (
          <div>
            <h3 className="mb-1 text-[13px] font-semibold text-fg">
              Known answers: error by efficiency choice
            </h3>
            <p className="mb-2 text-xs text-muted">
              {known.dataset}. Median error of the computed ratio against the known one; lower is
              better.
            </p>
            <HBars
              rows={known.efficiency.map((e) => ({
                key: e.label,
                label: e.label,
                value: e.error,
                valueText: e.error_text,
                note: e.planned ? "planned" : undefined,
                strong: e.planned,
              }))}
              valueHeader="Median error"
              summary={`Median error by efficiency choice: ${known.efficiency.map((e) => `${e.label} ${e.error_text}`).join(", ")}.`}
            />
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function TestCard({
  label,
  value,
  children,
}: {
  label: string;
  value: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-0.5 font-mono text-2xl font-semibold text-fg tabular">{value}</p>
      <p className="mt-1 text-[13px] text-muted">{children}</p>
    </div>
  );
}

function Limits({ how }: { how: AuditHow }) {
  const lines = [
    ...(how.known
      ? [
          `The true dilution ratio fell inside the range of reasonable analyses in ${how.known.inside_range} of 100 cases, and inside the planned analysis's likely range in ${how.known.inside_ci} of 100.`,
          "The truth used is the nominal amount of DNA pipetted, not a digital-PCR count.",
        ]
      : []),
    ...LIMITS,
  ];
  return (
    <Card as="section" aria-labelledby="how-limits">
      <CardHeader id="how-limits" title="Limits, stated plainly" />
      <CardBody>
        <ul className="list-disc space-y-1.5 pl-5 text-[13px] text-muted">
          {lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
