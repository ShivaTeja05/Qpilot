/** The summary strip: the study's size, the groups and how they were made, the call rule, the reference genes, the audit. */
import { ShieldCheck } from "lucide-react";
import { Link } from "wouter";
import { CALLS, CALL_ORDER, VERDICTS, VERDICT_ORDER, Glyph } from "@/charts";
import { count, fixed } from "@/lib/format";
import { Card } from "@/ui";
import type { ResultsView } from "./api";
import { FactText } from "./FactText";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[12px] text-muted">{label}</div>
      <div className="tabular text-xl font-semibold tracking-tight text-fg">{value}</div>
      {sub && (
        <div className="truncate text-[12px] text-faint" title={sub}>
          {sub}
        </div>
      )}
    </div>
  );
}

export function Summary({ view, auditHref }: { view: ResultsView; auditHref: string }) {
  const s = view.summary;
  const g = view.references;
  const steady = g.used.filter((r) => g.stable.includes(r)).length;
  const verdicts = view.audit.verdict_counts;
  const audited = view.audit.status === "ready";
  return (
    <Card className="p-4">
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Plates" value={count(s.n_plates)} />
        <Stat label="Reactions" value={count(s.n_reactions)} />
        <Stat label="Samples" value={count(s.n_samples)} />
        {s.groups.slice(0, 2).map((grp, i) => (
          <Stat key={grp.label} label={i === 0 ? "Compared group" : "Against"} value={count(grp.n)} sub={grp.label} />
        ))}
        <Stat label="Genes compared" value={count(s.n_genes)} />
      </div>
      <p className="mt-3 text-[13px] text-muted">{s.text ? <FactText text={s.text} /> : s.design_line}</p>
      {s.text && s.design_line && <p className="mt-1 text-[12px] text-faint">{s.design_line}</p>}
      <div className="mt-4 grid gap-4 border-t border-line pt-4 lg:grid-cols-3">
        <div className="min-w-0">
          <div className="text-[12px] text-muted">Calls under the rule</div>
          <p className="mt-0.5 text-[13px] text-fg">{view.rule.text}</p>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
            {CALL_ORDER.map((c) => (
              <li key={c} className="inline-flex items-center gap-1.5">
                <Glyph mark={CALLS[c]} size={11} />
                <span className="tabular font-semibold text-fg">{count(view.counts[c] ?? 0)}</span>
                <span className="text-muted">{CALLS[c].label.toLowerCase()}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="min-w-0">
          <div className="text-[12px] text-muted">Reference genes</div>
          <p className="mt-0.5 text-[13px] text-fg">{g.used.join(", ")}</p>
          <p className="mt-1 text-[12px] text-muted">
            {steady === g.used.length
              ? `All ${count(g.used.length)} below the geNorm stability cut-off (M ${fixed(g.cutoff_m, 1)}).`
              : steady === 0
                ? `None is below the commonly used geNorm cut-off (M ${fixed(g.cutoff_m, 1)}): normalisation is a weak point of this study.`
                : `${count(steady)} of ${count(g.used.length)} below the geNorm cut-off (M ${fixed(g.cutoff_m, 1)}).`}
          </p>
        </div>
        <div className="min-w-0">
          <div className="text-[12px] text-muted">Robustness audit</div>
          {audited ? (
            <>
              <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[13px]">
                {VERDICT_ORDER.filter((v) => (verdicts[v] ?? 0) > 0).map((v) => (
                  <li key={v} className="inline-flex items-center gap-1">
                    <Glyph mark={VERDICTS[v]} size={11} />
                    <span className="tabular font-semibold text-fg">{count(verdicts[v])}</span>
                    <span className="text-muted">{VERDICTS[v].label.toLowerCase()}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-[12px] text-muted">
                {view.audit.current ? "Audited at the current decisions." : "Decisions changed since the audit: run it again to bring it up to date."}{" "}
                <Link href={auditHref} className="font-medium text-accent hover:underline">
                  Open the audit
                </Link>
              </p>
            </>
          ) : (
            <p className="mt-0.5 text-[13px] text-fg">
              Not run yet.{" "}
              <Link href={auditHref} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                <ShieldCheck size={13} aria-hidden />
                Test every reasonable analysis
              </Link>
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
