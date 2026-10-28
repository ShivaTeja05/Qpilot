/** "View as table" for the curve viewer: one row per cycle, one column per well. */
import { useMemo } from "react";
import { fixed } from "@/lib/format";
import { NumberCell, Table, TBody, TD, TH, THead, TR } from "@/ui";
import { align, type CurveSeries } from "./data";

export function CurveTable({
  series,
  label,
  decimals,
}: {
  series: readonly CurveSeries[];
  label: string;
  decimals: number;
}) {
  const { x, ys } = useMemo(() => align(series, "linear"), [series]);
  if (!series.length) return <p className="text-[13px] text-muted">No curve to show.</p>;
  return (
    <div
      className="max-h-[420px] overflow-auto rounded-lg border border-line"
      tabIndex={0}
      role="region"
      aria-label={`${label}: fluorescence by cycle`}
    >
      <Table caption={`${label}: fluorescence by cycle`}>
        <THead>
          <TR>
            <TH numeric>Cycle</TH>
            {series.map((s) => (
              <TH key={s.id} numeric>
                {s.label}
                {s.role === "context" ? (
                  <span className="ml-1 font-normal text-faint">(same sample)</span>
                ) : null}
              </TH>
            ))}
          </TR>
        </THead>
        <TBody>
          {series.some((s) => s.cq != null) ? (
            <TR>
              <TD className="text-muted">Cq</TD>
              {series.map((s) => (
                <TD key={s.id} numeric>
                  <NumberCell>{fixed(s.cq, 2)}</NumberCell>
                </TD>
              ))}
            </TR>
          ) : null}
          {series.some((s) => s.baseline != null) ? (
            <TR>
              <TD className="text-muted">Baseline</TD>
              {series.map((s) => (
                <TD key={s.id} numeric>
                  <NumberCell>{fixed(s.baseline, decimals)}</NumberCell>
                </TD>
              ))}
            </TR>
          ) : null}
          {x.map((c, r) => (
            <TR key={c}>
              <TD numeric>
                <NumberCell>{c}</NumberCell>
              </TD>
              {ys.map((y, i) => (
                <TD key={series[i]!.id} numeric>
                  <NumberCell>{fixed(y[r], decimals)}</NumberCell>
                </TD>
              ))}
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
