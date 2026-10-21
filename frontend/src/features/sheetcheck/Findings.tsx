/**
 * What the check found: the headline and the counts of fold changes, the first place to look and
 * every place that differs on its own (column, step, gene, rows, status, the known slips in words),
 * and every recomputed column. Numbers in sentences are the check's facts; counts are the check's
 * own counts, written by `@/lib/format`.
 */
import {
  Check,
  CircleHelp,
  CornerDownRight,
  Minus,
  Search,
  ShieldCheck,
  Split,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { useId } from "react";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  NumberCell,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  type Tone,
} from "@/ui";
import { count, MISSING, ofTotal, plural } from "@/lib/format";
import type { SheetColumnCheckView, SheetCheckView, SheetFindingView } from "./api";
import { FactText } from "./FactText";
import { COLUMN_STATUS, FINDING_STATUS, slipWords } from "./words";

const FINDING_LOOK: Record<SheetFindingView["status"], { tone: Tone; icon: LucideIcon }> = {
  explained: { tone: "info", icon: Search },
  ambiguous: { tone: "warn", icon: Split },
  unexplained: { tone: "warn", icon: CircleHelp },
};

const COLUMN_LOOK: Record<SheetColumnCheckView["status"], { tone: Tone; icon: LucideIcon }> = {
  reproduced: { tone: "ok", icon: Check },
  differs: { tone: "warn", icon: TriangleAlert },
  follows: { tone: "neutral", icon: CornerDownRight },
  not_checked: { tone: "neutral", icon: Minus },
};

export function FindingStatus({ status }: { status: SheetFindingView["status"] }) {
  const look = FINDING_LOOK[status];
  const Icon = look.icon;
  return (
    <Badge tone={look.tone} icon={<Icon aria-hidden />} title={FINDING_STATUS[status].detail}>
      {FINDING_STATUS[status].word}
    </Badge>
  );
}

function ColumnStatus({ status }: { status: SheetColumnCheckView["status"] }) {
  const look = COLUMN_LOOK[status];
  const Icon = look.icon;
  return (
    <Badge tone={look.tone} icon={<Icon aria-hidden />}>
      {COLUMN_STATUS[status]}
    </Badge>
  );
}

/** "fold change for MYC" — a step and its gene. */
function stepOf(f: { step_word: string; gene: string | null }): string {
  return f.gene ? `${f.step_word} for ${f.gene}` : f.step_word;
}

/** The headline and the counts of fold changes. */
export function Overview({ view }: { view: SheetCheckView }) {
  const c = view.counts;
  const titleId = useId();
  const tiles: [string, string][] = [
    ["Fold changes reproduced", ofTotal(c.reproduced, c.fold_changes)],
    ["Differ", count(c.differ)],
    ["With a named cause", count(c.named)],
    ["More than one cause fits", count(c.ambiguous)],
    ["No known cause", count(c.unexplained)],
  ];
  return (
    <Card as="section" aria-labelledby={titleId}>
      <CardHeader id={titleId} title="What the check found" />
      <CardBody className="flex flex-col gap-4">
        <p className="text-[15px] leading-relaxed text-fg">
          <FactText text={view.headline} />
        </p>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))] gap-2">
          {tiles.map(([label, value]) => (
            <div key={label} className="rounded-lg border border-line bg-surface-2 px-3 py-2">
              <dt className="text-xs text-muted">{label}</dt>
              <dd className="mt-0.5 font-mono text-[15px] font-medium text-fg tabular">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="flex items-start gap-2 text-xs text-muted">
          <ShieldCheck className="mt-px size-3.5 shrink-0 text-accent" aria-hidden />
          <span>
            {view.never_edited} Method: <span className="font-mono">{view.method_card}</span>.
          </span>
        </p>
      </CardBody>
    </Card>
  );
}

/** What reproduces a finding, in words. */
function Paths({ finding }: { finding: SheetFindingView }) {
  if (!finding.paths.length)
    return <span className="text-muted">No known slip reproduces it.</span>;
  return (
    <ul className="flex flex-col gap-0.5" aria-label="What reproduces it">
      {finding.paths.map((p) => (
        <li key={p}>{slipWords(p)}</li>
      ))}
    </ul>
  );
}

/** The first place to look, the findings in words, and every place that differs on its own. */
export function FirstPlace({ view }: { view: SheetCheckView }) {
  const titleId = useId();
  const first = view.findings[0];
  if (!first) return null;
  return (
    <Card as="section" aria-labelledby={titleId}>
      <CardHeader
        id={titleId}
        title="First place to look"
        hint="The first column, in the order the sheet computes, that differs on its own."
      />
      <CardBody className="flex flex-col gap-4">
        <div className="flex flex-wrap items-start gap-4 rounded-lg border border-line bg-surface-2 p-3">
          <div className="flex flex-col items-center">
            <span className="text-[11px] tracking-wide text-muted uppercase">Column</span>
            <span className="font-mono text-2xl font-semibold text-fg">{first.column}</span>
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-fg">{stepOf(first)}</p>
            <p className="text-[13px] text-muted">
              First at row <span className="tabular">{count(first.first_row)}</span>;{" "}
              <span className="tabular">{plural(first.n_rows, "row")}</span> differ.
            </p>
            <div className="mt-2 text-[13px] text-fg">
              <span className="text-muted">
                {first.paths.length > 1 ? "Each of these reproduces it:" : "Consistent with:"}
              </span>{" "}
              <Paths finding={first} />
            </div>
          </div>
          <FindingStatus status={first.status} />
        </div>
        <p className="text-[13px] leading-relaxed text-fg">
          <FactText text={view.findings_text} />
        </p>
        {view.findings.length > 1 ? (
          <div className="overflow-x-auto rounded-lg border border-line">
            <Table caption="Every place that differs on its own">
              <THead>
                <tr>
                  <TH>Column</TH>
                  <TH>Step</TH>
                  <TH>Gene</TH>
                  <TH numeric>First row</TH>
                  <TH numeric>Rows</TH>
                  <TH>Status</TH>
                  <TH>What reproduces it</TH>
                </tr>
              </THead>
              <TBody>
                {view.findings.map((f) => (
                  <TR key={f.id}>
                    <TD className="font-mono font-medium">{f.column}</TD>
                    <TD>{f.step_word}</TD>
                    <TD className="font-mono text-[12.5px]">{f.gene ?? MISSING}</TD>
                    <TD numeric>{count(f.first_row)}</TD>
                    <TD numeric>{count(f.n_rows)}</TD>
                    <TD>
                      <FindingStatus status={f.status} />
                    </TD>
                    <TD className="py-1.5">
                      <Paths finding={f} />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

/** Every recomputed column and how it compares with the textbook path. */
export function ColumnsChecked({ view }: { view: SheetCheckView }) {
  const titleId = useId();
  return (
    <Card as="section" aria-labelledby={titleId}>
      <CardHeader
        id={titleId}
        title="Columns checked"
        hint={
          view.columns.length
            ? `${ofTotal(view.counts.columns_reproduced, view.counts.columns_checked)} recomputed columns reproduce from the sheet's own Cq values.`
            : "No column could be recomputed from the sheet's Cq values."
        }
      />
      {view.columns.length ? (
        <div className="overflow-x-auto border-t border-line">
          <Table caption="Each recomputed column and its result">
            <THead>
              <tr>
                <TH>Column</TH>
                <TH>Step</TH>
                <TH>Gene</TH>
                <TH>Result</TH>
                <TH numeric>Reproduced</TH>
                <TH numeric>Differ</TH>
              </tr>
            </THead>
            <TBody>
              {view.columns.map((c, i) => (
                <TR key={`${c.column}:${c.step}:${c.gene ?? ""}:${i}`}>
                  <TD className="font-mono font-medium">{c.column}</TD>
                  <TD>{c.step_word}</TD>
                  <TD className="font-mono text-[12.5px]">{c.gene ?? MISSING}</TD>
                  <TD>
                    <ColumnStatus status={c.status} />
                  </TD>
                  <TD numeric>
                    <NumberCell>{ofTotal(c.n_reproduced, c.n_cells)}</NumberCell>
                  </TD>
                  <TD numeric>
                    <NumberCell muted={!c.n_differ}>{count(c.n_differ)}</NumberCell>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      ) : null}
    </Card>
  );
}
