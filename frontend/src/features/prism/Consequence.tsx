/**
 * What accepting a round-trip question does, in numbers the engine computed: the gene's fold
 * change, p and call before and after leaving the value out, how many of all conclusions change,
 * and (with several exclusions) what all of them do together. A changed value shows what qPilot
 * wrote and what came back.
 */
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { ConclusionTag } from "@/ui";
import { cn } from "@/lib/cn";
import { count, fold, MISSING, ofTotal, pValue } from "@/lib/format";
import type { GeneChange, Proposal } from "./api";

type Dict = Record<string, unknown>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const pair = (v: unknown): [number, number] | null =>
  Array.isArray(v) && v.length === 2 && v.every((x) => typeof x === "number") ? [v[0] as number, v[1] as number] : null;

/** A call word that may be "withheld" (the engine then shows no numbers). */
function Call({ value }: { value: unknown }) {
  if (value === "withheld") return <span className="font-medium text-warn">withheld</span>;
  return <ConclusionTag conclusion={str(value) ?? "none"} />;
}

function Row({ label, before, after, changed }: { label: string; before: ReactNode; after: ReactNode; changed?: boolean }) {
  return (
    <div className="contents">
      <dt className="text-muted">{label}</dt>
      <dd className="flex min-w-0 flex-wrap items-center gap-1.5 tabular">
        <span>{before}</span>
        <ArrowRight className="size-3.5 text-faint" aria-label="becomes" />
        <span className={cn(changed && "font-semibold text-fg")}>{after}</span>
      </dd>
    </div>
  );
}

/** One gene's numbers before → after. */
export function GeneChangeRows({ change }: { change: GeneChange | Dict }) {
  const c = change as Dict;
  const nb = pair(c.n_units_before);
  const na = pair(c.n_units_after);
  const callChanged = c.conclusion_before !== c.conclusion_after;
  return (
    <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
      <Row label="Call" before={<Call value={c.conclusion_before} />} after={<Call value={c.conclusion_after} />} changed={callChanged} />
      <Row label="Fold change" before={fold(num(c.fc_before))} after={c.fc_after == null ? MISSING : fold(num(c.fc_after))} />
      <Row label="p" before={pValue(num(c.p_before))} after={c.p_after == null ? MISSING : pValue(num(c.p_after))} />
      {nb ? (
        <Row
          label="Units per group"
          before={`${count(nb[0])} vs ${count(nb[1])}`}
          after={na ? `${count(na[0])} vs ${count(na[1])}` : MISSING}
        />
      ) : null}
    </dl>
  );
}

function Changed({ n, total, genes }: { n: number | null; total: number | null; genes: string[] }) {
  return (
    <p className="text-[13px] text-fg">
      Changes{" "}
      <strong className={cn("tabular", n ? "text-danger" : "text-ok")}>{ofTotal(n, total)}</strong>{" "}
      conclusions{genes.length ? <span className="text-muted"> ({genes.join(", ")})</span> : null}.
    </p>
  );
}

/** The consequence block of a `prism.exclusion_reason` or `prism.value_edit` proposal. */
export function PrismConsequence({ proposal, stale }: { proposal: Pick<Proposal, "kind" | "consequence" | "check">; stale?: string | null }) {
  const c = (proposal.consequence ?? null) as Dict | null;
  if (proposal.kind === "prism.value_edit") {
    const exported = c?.exported ?? proposal.check.details?.exported;
    const returned = c?.returned ?? proposal.check.details?.returned;
    return (
      <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
        <dt className="text-muted">qPilot wrote</dt>
        <dd className="font-mono tabular">{exported == null ? MISSING : String(exported)}</dd>
        <dt className="text-muted">Prism sent back</dt>
        <dd className="font-mono tabular text-danger">{returned == null || returned === "" ? "(empty)" : String(returned)}</dd>
      </dl>
    );
  }
  if (!c || !("fc_before" in c)) {
    return (
      <p className="text-[13px] text-muted">
        {proposal.check.note || "The consequence could not be computed for this value."}
      </p>
    );
  }
  const all = (c.with_all_pending ?? null) as Dict | null;
  const withheld = str(c.withheld_after);
  return (
    <div className={cn("flex flex-col gap-3", stale && "opacity-60")}>
      {stale ? (
        <p className="rounded-md border border-warn/30 bg-warn-soft p-2 text-[12.5px] text-fg">
          Out of date: {stale} Read what came back from Prism again to recompute it.
        </p>
      ) : null}
      <div>
        <p className="mb-1.5 text-[12px] font-medium text-muted">
          {str(c.gene) ?? "This gene"} without this value
        </p>
        <GeneChangeRows change={c} />
        {withheld ? <p className="mt-1.5 text-[12.5px] text-warn">The engine then withholds this gene: {withheld}</p> : null}
      </div>
      <Changed n={num(c.n_conclusions_changed)} total={num(c.n_genes)} genes={Array.isArray(c.changed_genes) ? c.changed_genes.map(String) : []} />
      {all ? (
        <div className="rounded-md border border-line bg-surface-2 p-2.5">
          <p className="mb-1.5 text-[12px] font-medium text-muted">
            With all {count(num(all.n_exclusions))} values Prism left out, together
          </p>
          <GeneChangeRows change={all} />
          <div className="mt-1.5">
            <Changed
              n={num(all.n_conclusions_changed)}
              total={num(c.n_genes)}
              genes={Array.isArray(all.changed_genes) ? all.changed_genes.map(String) : []}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
