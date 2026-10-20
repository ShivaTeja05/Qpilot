/**
 * Genes at two points, side by side: the call (arrow + word), the fold change and the share of
 * analyses with the same call, before → after. Used by every "what changed" view of History.
 */
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { foldFromLog2, percent } from "@/lib/format";
import { Badge, ConclusionTag, Table, TBody, TD, TH, THead, TR, VerdictTag } from "@/ui";
import type { ChoiceChange, GeneChange } from "./api";
import { CAUSE_WORD } from "./words";

function FromTo({
  from,
  to,
  changed,
  wrap = false,
}: {
  from: ReactNode;
  to: ReactNode;
  changed?: boolean;
  wrap?: boolean;
}) {
  return (
    <span
      className={cn("inline-flex items-center gap-1.5", wrap ? "flex-wrap" : "whitespace-nowrap")}
    >
      <span className={cn(changed && "text-muted")}>{from}</span>
      <ArrowRight aria-label="to" className="size-3.5 shrink-0 text-faint" />
      <span className={cn(changed && "font-semibold text-fg")}>{to}</span>
    </span>
  );
}

function signedFold(delta: number | null | undefined): string {
  if (delta == null || !Number.isFinite(delta)) return "";
  return `${foldFromLog2(Math.abs(delta))} ${delta > 0 ? "higher" : "lower"}`;
}

export function GeneChanges({
  rows,
  caption,
  onGene,
  showCause = false,
  showVerdict = false,
  empty,
}: {
  rows: GeneChange[];
  caption: string;
  onGene?: (gene: string) => void;
  showCause?: boolean;
  showVerdict?: boolean;
  empty?: ReactNode;
}) {
  if (!rows.length) return empty ? <p className="text-[13px] text-muted">{empty}</p> : null;
  return (
    <div className="-mx-1 overflow-x-auto">
      <Table caption={caption} className="text-[13px]">
        <THead>
          <TR>
            <TH>Gene</TH>
            <TH>Call</TH>
            <TH numeric>Fold change</TH>
            <TH numeric>Same call</TH>
            {showCause ? <TH>Changed by</TH> : null}
            {showVerdict ? <TH>Audit</TH> : null}
          </TR>
        </THead>
        <TBody>
          {rows.map((r) => (
            <TR key={r.gene}>
              <TD>
                {onGene ? (
                  <button
                    type="button"
                    onClick={() => onGene(r.gene)}
                    className="rounded font-medium text-fg underline decoration-line-strong underline-offset-2 outline-none hover:decoration-accent focus-visible:ring-2 focus-visible:ring-focus"
                  >
                    {r.gene}
                  </button>
                ) : (
                  <span className="font-medium text-fg">{r.gene}</span>
                )}
                {r.headline ? (
                  <Badge tone="accent" className="ml-1.5">
                    headline
                  </Badge>
                ) : null}
              </TD>
              <TD>
                {r.call_changed ? (
                  <FromTo
                    changed
                    from={<ConclusionTag conclusion={r.from_conclusion} compact />}
                    to={<ConclusionTag conclusion={r.to_conclusion} compact />}
                  />
                ) : (
                  <ConclusionTag conclusion={r.to_conclusion} compact />
                )}
              </TD>
              <TD numeric className="font-mono tabular">
                <FromTo
                  from={foldFromLog2(r.from_log2fc)}
                  to={foldFromLog2(r.to_log2fc)}
                  changed={r.delta_log2fc != null && Math.abs(r.delta_log2fc) > 1e-9}
                />
                {r.delta_log2fc != null && Math.abs(r.delta_log2fc) > 1e-9 ? (
                  <span className="block text-[11px] text-faint">{signedFold(r.delta_log2fc)}</span>
                ) : null}
              </TD>
              <TD numeric className="font-mono tabular">
                <FromTo
                  from={percent(r.from_holds)}
                  to={percent(r.to_holds)}
                  changed={r.from_holds !== r.to_holds}
                />
              </TD>
              {showCause ? (
                <TD className="text-muted">{r.cause ? CAUSE_WORD[r.cause] : "—"}</TD>
              ) : null}
              {showVerdict ? <TD>{r.verdict ? <VerdictTag verdict={r.verdict} /> : "—"}</TD> : null}
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

export function ChoiceChanges({ rows }: { rows: ChoiceChange[] }) {
  if (!rows.length) return null;
  return (
    <ul className="space-y-1.5 text-[13px]">
      {rows.map((c) => (
        <li key={c.card_id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="text-muted">{c.title}:</span>
          <FromTo wrap changed from={c.from_label} to={c.to_label} />
        </li>
      ))}
    </ul>
  );
}
