/** The summary strip: the study's size, the groups, the call rule, the reference genes, the audit. */
import { ShieldCheck } from "lucide-react";
import { Link } from "wouter";
import { CALLS, CALL_ORDER, VERDICTS, VERDICT_ORDER, Glyph, isVerdict } from "@/charts";
import { count, fixed } from "@/lib/format";
import { Card } from "@/ui";
import type { ResultsView } from "./api";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[12px] text-muted">{label}</div>
      <div className="tabular text-xl font-semibold tracking-tight text-fg">{value}</div>
      {sub && <div className="truncate text-[12px] text-faint">{sub}</div>}
    </div>
  );
}

export function Summary({ view, auditHref }: { view: ResultsView; auditHref: string }) {
  const s = view.summary;
  const g = view.references.genorm;
  const used = view.references.used;
  const steady = used.filter((r) => (g.M_initial[r] ?? Infinity) <= g.cutoff_M).length;
  const calls = CALL_ORDER.map((c) => ({ c, n: view.genes.filter((x) => x.conclusion === c).length }));
  const verdicts = view.audit?.verdict_counts ?? null;
  return (
    <Card className="p-4">
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Plates" value={count(s.n_plates)} />
        <Stat label="Reactions" value={count(s.n_reactions)} />
        <Stat label="Samples" value={count(s.n_samples)} />
        {s.groups.slice(0, 2).map((grp) => (
          <Stat key={grp.label} label="Group" value={count(grp.n)} sub={grp.label} />
        ))}
        <Stat label="Genes compared" value={count(view.genes.length)} />
      </div>
      <div className="mt-4 grid gap-4 border-t border-line pt-4 lg:grid-cols-3">
        <div className="min-w-0">
          <div className="text-[12px] text-muted">Calls under the rule</div>
          <p className="mt-0.5 text-[13px] text-fg">{view.rule.text}</p>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
            {calls.map(({ c, n }) => (
              <li key={c} className="inline-flex items-center gap-1.5">
                <Glyph mark={CALLS[c]} size={11} />
                <span className="tabular font-semibold text-fg">{count(n)}</span>
                <span className="text-muted">{CALLS[c].label.toLowerCase()}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="min-w-0">
          <div className="text-[12px] text-muted">Reference genes</div>
          <p className="mt-0.5 text-[13px] text-fg">{used.join(", ")}</p>
          <p className="mt-1 text-[12px] text-muted">
            {steady === used.length
              ? `All ${count(used.length)} at or below the geNorm stability cut-off (M ${fixed(g.cutoff_M, 1)}).`
              : steady === 0
                ? `None is below the commonly used geNorm cut-off (M ${fixed(g.cutoff_M, 1)}): treat normalisation as a weak point.`
                : `${count(steady)} of ${count(used.length)} at or below the geNorm cut-off (M ${fixed(g.cutoff_M, 1)}).`}
          </p>
        </div>
        <div className="min-w-0">
          <div className="text-[12px] text-muted">Robustness audit</div>
          {verdicts && view.audit?.status === "ready" ? (
            <>
              <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[13px]">
                {VERDICT_ORDER.filter((v) => (verdicts[v] ?? 0) > 0).map((v) => (
                  <li key={v} className="inline-flex items-center gap-1" title={VERDICTS[v].label}>
                    <Glyph mark={VERDICTS[v]} size={11} />
                    <span className="tabular font-semibold text-fg">{count(verdicts[v])}</span>
                    <span className="text-muted">{VERDICTS[v].label.toLowerCase()}</span>
                  </li>
                ))}
                {Object.keys(verdicts)
                  .filter((v) => !isVerdict(v))
                  .map((v) => (
                    <li key={v} className="text-muted">
                      {count(verdicts[v])} {v}
                    </li>
                  ))}
              </ul>
              <Link href={auditHref} className="mt-1 inline-block text-[12px] font-medium text-accent hover:underline">
                Open the audit
              </Link>
            </>
          ) : (
            <p className="mt-0.5 text-[13px] text-fg">
              {view.audit?.status === "running" ? "Running now." : "Not run yet."}{" "}
              <Link href={auditHref} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                <ShieldCheck size={13} aria-hidden />
                {view.audit?.status === "running" ? "Follow it" : "Test every reasonable analysis"}
              </Link>
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
