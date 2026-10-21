/**
 * The Methods section, ready to paste: one paragraph per step, every number a fact (hover for
 * where it comes from), two copies (plain text, or with [n] citations and the reference list).
 */
import { CopyButton } from "@/ui";
import type { Facts, ReportView } from "./api";
import { Cited } from "./Cited";

export function MethodsPanel({ methods, facts }: { methods: ReportView["methods"]; facts: Facts }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <CopyButton text={methods.plain} label="Copy as plain text" showLabel />
        <CopyButton text={methods.with_citations} label="Copy with citations" showLabel />
        <span className="text-[12px] text-muted">Hover a number to see where it comes from.</span>
      </div>
      <div className="flex flex-col gap-4 rounded-xl border border-line bg-surface px-5 py-4">
        {methods.paragraphs.map((p) => (
          <section key={p.id} aria-labelledby={`methods-${p.id}`}>
            <h3 id={`methods-${p.id}`} className="text-[13px] font-semibold tracking-wide text-fg">
              {p.title}
            </h3>
            <p className="mt-1 text-[14px] leading-[1.7] text-muted [text-wrap:pretty]">
              <Cited text={p.text} facts={facts} cites />
            </p>
          </section>
        ))}
      </div>
      {methods.citations.length ? (
        <div>
          <h3 className="text-[13px] font-semibold text-fg">References</h3>
          <ol className="mt-1.5 flex list-decimal flex-col gap-1 pl-5 text-[12.5px] leading-relaxed text-muted marker:text-muted">
            {methods.citations.map((c) => (
              <li key={c.id}>{c.text}</li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}
