/**
 * What a blind stage's accepted proposals add up to, in words: for the design, the preset or
 * the comparison, the groups as accepted (with how many samples each), the reference genes,
 * the sample types, the dilution series; for the curves, the call rule and the wells a person
 * set. Built only from proposals a person accepted (design inputs, never a result).
 */
import type { ReactNode } from "react";
import { count, plural } from "@/lib/format";
import { PRESET_WORDS, ROLE_SHORT, effectivePayload, ruleWords, type Proposal } from "@/lib/vocab";

type Dict = Record<string, unknown>;

const settled = (p: Proposal) => p.status === "accepted" || p.status === "edited";

/**
 * The decision in force for each item: a later acceptance on the same kind and subject (a
 * person who changed a group or the comparison) replaces the earlier one, as the engine reads
 * them (in decision order, the latest wins). The list order breaks ties within one second.
 */
export function inForce(accepted: Proposal[]): Proposal[] {
  const ordered = accepted
    .map((p, i) => ({ p, i }))
    .sort((a, b) => (a.p.decided_at ?? "").localeCompare(b.p.decided_at ?? "") || a.i - b.i);
  const out = new Map<string, Proposal>();
  for (const { p } of ordered) {
    const key = `${p.kind}\u0000${p.subject}`;
    out.delete(key);
    out.set(key, p);
  }
  return [...out.values()];
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-fg">{children}</dd>
    </div>
  );
}

function tally(values: string[]): [string, number][] {
  const n = new Map<string, number>();
  for (const v of values) n.set(v, (n.get(v) ?? 0) + 1);
  return [...n].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** The design the accepted design proposals give (rows for a definition list). */
function designRows(accepted: Proposal[]): [string, ReactNode][] {
  const of = (kind: Proposal["kind"]) =>
    accepted.filter((p) => p.kind === kind).map((p) => ({ p, d: effectivePayload(p) as Dict }));
  const rows: [string, ReactNode][] = [];
  const preset = of("design.preset")[0];
  if (preset) {
    const id = String(preset.d.preset);
    rows.push([
      "Design",
      <>
        Built-in design “{id}”{PRESET_WORDS[id] ? `: ${PRESET_WORDS[id]}` : ""}
      </>,
    ]);
  }
  const comparison = of("design.comparison")[0];
  if (comparison) {
    const a = String(comparison.d.group_a);
    const b = String(comparison.d.group_b);
    rows.push([
      "Comparison",
      <>
        “{a}” compared with “{b}” (fold change = {a} relative to {b})
      </>,
    ]);
  }
  const groups = tally(
    of("design.group")
      .filter(({ d }) => d.group != null && d.group !== "") // a cleared group is in no group
      .map(({ d }) => String(d.group)),
  );
  if (groups.length) {
    rows.push(["Groups", groups.map(([g, n]) => `“${g}”: ${plural(n, "sample")}`).join(" · ")]);
  }
  const units = of("design.bio_unit");
  if (units.length) {
    const distinct = new Set(units.map(({ d }) => String(d.biological_unit))).size;
    rows.push([
      "Biological units",
      `${plural(units.length, "sample")} grouped into ${plural(distinct, "unit")} (technical replicates are never counted as n)`,
    ]);
  }
  const targets = of("design.target_role");
  const refs = targets.filter(({ d }) => d.role === "ref").map(({ p }) => p.subject);
  if (refs.length) rows.push(["Reference genes", refs.join(", ")]);
  const toi = targets.filter(({ d }) => d.role === "toi").length;
  if (toi) rows.push(["Genes of interest", plural(toi, "target")]);
  const roles = tally(of("design.well_role").map(({ d }) => String(d.role)));
  if (roles.length) {
    rows.push([
      "Sample types",
      roles.map(([r, n]) => `${ROLE_SHORT[r] ?? r} ${count(n)}`).join(" · "),
    ]);
  }
  const series = of("design.dilution_series");
  if (series.length) {
    rows.push([
      "Dilution series",
      series
        .map(({ p, d }) => {
          const n =
            d.samples && typeof d.samples === "object" ? Object.keys(d.samples as Dict).length : 0;
          return `${p.subject} (${plural(n, "sample")})`;
        })
        .join(" · "),
    ]);
  }
  const symbols = of("design.gene_symbol").length;
  if (symbols)
    rows.push(["Gene symbols", `${plural(symbols, "target")} named by an approved HGNC symbol`]);
  return rows;
}

/** The curve calls the accepted curve proposals give. */
function curveRows(accepted: Proposal[]): [string, ReactNode][] {
  const rows: [string, ReactNode][] = [];
  const rule = accepted.find((p) => p.kind === "curve.call_rule");
  if (rule)
    rows.push([
      "Amplification call",
      `A well counts as amplified by ${ruleWords(effectivePayload(rule).rule)}`,
    ]);
  const calls = accepted
    .filter((p) => p.kind === "curve.well_call")
    .map((p) => effectivePayload(p).amplified === true);
  if (calls.length) {
    const yes = calls.filter(Boolean).length;
    rows.push([
      "Wells set by a person",
      `${plural(calls.length, "well")}: ${count(yes)} counted as amplified, ${count(calls.length - yes)} as not amplified`,
    ]);
  }
  return rows;
}

/** "The design this gives" / "The curve calls this gives", from the accepted proposals. */
export function StageSummary({
  stage,
  proposals,
  className,
}: {
  stage: "design" | "curves";
  /** The stage's proposals (any status; only accepted and edited ones count). */
  proposals: Proposal[];
  className?: string;
}) {
  const accepted = inForce(proposals.filter((p) => settled(p) && p.kind !== "stage.confirm"));
  const rows = stage === "design" ? designRows(accepted) : curveRows(accepted);
  if (!rows.length) return <p className="text-[13px] text-muted">No accepted proposal yet.</p>;
  return (
    <dl
      className={
        className ?? "grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[13px]"
      }
    >
      {rows.map(([label, value]) => (
        <Row key={label} label={label}>
          {value}
        </Row>
      ))}
    </dl>
  );
}
