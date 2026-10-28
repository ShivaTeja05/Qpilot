/**
 * A study with several comparisons (or a paired one): pick the comparison the rest of the page
 * shows, and see every gene across every comparison in one compact table. Every number is the
 * engine's (GET /api/studies/{id}/comparisons); the page only formats.
 */
import { CALLS } from "@/charts";
import { cn } from "@/lib/cn";
import { ci, count, fold, pValue, percent } from "@/lib/format";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  ConclusionTag,
  SegmentedControl,
  Select,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import type { ComparisonCell, ComparisonTab, ComparisonsView } from "./api";

/** Up to this many comparisons show as tabs; more as a list to choose from. */
const MAX_TABS = 4;

/** The calls of one comparison in words, e.g. "2 up, 1 down". */
export function callWords(tab: { n_up: number; n_down: number }): string {
  if (!tab.n_up && !tab.n_down) return "no call";
  const parts = [];
  if (tab.n_up) parts.push(`${count(tab.n_up)} up`);
  if (tab.n_down) parts.push(`${count(tab.n_down)} down`);
  return parts.join(", ");
}

/** Which comparison the gene table, the map and the flip matrix show. */
export function ComparisonPicker({
  tabs,
  value,
  onChange,
}: {
  tabs: ComparisonTab[];
  value: string;
  onChange: (id: string) => void;
}) {
  if (tabs.length < 2) return null;
  if (tabs.length > MAX_TABS)
    return (
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <span className="font-medium text-fg">Comparison shown</span>
        <Select
          label="Comparison shown"
          size="sm"
          value={value}
          onValueChange={onChange}
          options={tabs.map((t) => ({
            value: t.id,
            label: `${t.label}${t.primary ? " (first)" : ""}: ${callWords(t)}`,
          }))}
        />
      </div>
    );
  // A choice of what the page below shows, not tabs of panels: one radio group (tabs would
  // point at panels that do not exist, axe aria-valid-attr-value).
  return (
    <SegmentedControl
      label="Comparison shown"
      value={value}
      onValueChange={onChange}
      className="max-w-full flex-wrap"
      options={tabs.map((t) => ({
        value: t.id,
        label: (
          <>
            {t.label}{" "}
            <span className="rounded-full bg-bg-subtle px-1.5 text-xs text-muted tabular">
              {count(t.n_up + t.n_down)}
            </span>
          </>
        ),
        title: `${t.label}: ${callWords(t)}`,
      }))}
    />
  );
}

function Cell({ cell }: { cell: ComparisonCell | null | undefined }) {
  if (!cell) return <span className="text-faint">not tested</span>;
  const yours = cell.at_your_choices && cell.at_your_choices !== cell.conclusion;
  return (
    <span className="flex flex-col gap-0.5">
      <span className="flex items-center gap-1.5">
        <ConclusionTag conclusion={cell.conclusion} />
        <span className="tabular text-fg">{fold(cell.fc)}</span>
      </span>
      <span className="tabular text-[12px] text-muted">
        p<sub>corr</sub> {pValue(cell.p_adjusted)} · q {pValue(cell.q)}
      </span>
      {yours ? (
        <span className="text-[12px] text-warn">
          with your choices: {CALLS[cell.at_your_choices!].label.toLowerCase()}
        </span>
      ) : null}
    </span>
  );
}

function cellTitle(label: string, cell: ComparisonCell | null | undefined): string {
  if (!cell) return `${label}: not tested`;
  const call = cell.conclusion === "none" ? "no call" : cell.conclusion;
  return (
    `${label}: ${call}, ${fold(cell.fc)} ${ci(cell.ci[0], cell.ci[1])}, ` +
    `p ${pValue(cell.p)}, corrected p ${pValue(cell.p_adjusted)}, q ${pValue(cell.q)}` +
    (cell.holds != null ? `, holds in ${percent(cell.holds)} of the analyses` : "")
  );
}

/** Every gene across every comparison: call, fold change, corrected p and q. */
export function ComparisonsPanel({
  view,
  shown,
  onShow,
  onOpen,
}: {
  view: ComparisonsView;
  shown: string;
  onShow: (id: string) => void;
  onOpen: (gene: string) => void;
}) {
  const comparisons = view.comparisons;
  const omnibus = view.omnibus_groups.length > 0;
  const headline = view.genes.filter((g) => g.headline);
  const rest = view.genes.filter((g) => !g.headline);
  const rows = [...headline, ...rest];
  const paired = view.pair_by ? ` Paired by ${view.pair_by}.` : "";
  return (
    <Card as="section" aria-labelledby="comparisons-title">
      <CardHeader
        id="comparisons-title"
        title={`All ${count(comparisons.length)} comparisons`}
        hint={`Each gene in every comparison, tested with ${view.test_words}, with ${view.correction_words}.${paired} A call: ${view.rule_text}.`}
      />
      <CardBody className="space-y-3">
        <div
          className="overflow-x-auto"
          tabIndex={0}
          role="region"
          aria-label="Every gene across every comparison"
        >
          <Table caption="Every gene across every comparison: call, fold change, corrected p-value and q-value">
            <THead>
              <TR>
                <TH>Gene</TH>
                {comparisons.map((c) => (
                  <TH key={c.id}>
                    <button
                      type="button"
                      onClick={() => onShow(c.id)}
                      className={cn(
                        "inline-flex items-center gap-1.5 hover:text-fg",
                        c.id === shown && "text-fg underline decoration-accent underline-offset-4",
                      )}
                      aria-pressed={c.id === shown}
                      title={`Show ${c.label} in the gene table, the map and the flip matrix`}
                    >
                      {c.label}
                      {c.primary && <Badge tone="accent">first</Badge>}
                    </button>
                    <span className="block font-normal text-faint">
                      n = {count(c.n_a)} vs {count(c.n_b)}
                      {c.n_pairs != null ? ` (${count(c.n_pairs)} pairs)` : ""} · {callWords(c)}
                    </span>
                  </TH>
                ))}
                <TH numeric>Called in</TH>
                {omnibus && (
                  <TH
                    numeric
                    title={`Welch's one-way ANOVA across ${view.omnibus_groups.join(", ")}`}
                  >
                    Any difference
                    <span className="block font-normal text-faint">ANOVA p</span>
                  </TH>
                )}
              </TR>
            </THead>
            <TBody>
              {rows.map((g) => (
                <TR key={g.gene}>
                  <TD>
                    <button
                      type="button"
                      onClick={() => onOpen(g.gene)}
                      className="flex items-center gap-1.5 font-medium text-fg hover:underline"
                    >
                      {g.gene}
                      {g.headline && <Badge tone="accent">headline</Badge>}
                    </button>
                  </TD>
                  {g.cells.map((cell, i) => (
                    <TD key={comparisons[i]!.id} title={cellTitle(comparisons[i]!.label, cell)}>
                      <Cell cell={cell} />
                    </TD>
                  ))}
                  <TD numeric>
                    {count(g.n_called)} of {count(comparisons.length)}
                  </TD>
                  {omnibus && <TD numeric>{pValue(g.omnibus_p)}</TD>}
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
        <ul className="space-y-1 text-[12.5px] text-muted">
          {view.notes.map((n) => (
            <li key={n.kind}>{n.text}</li>
          ))}
          {Object.entries(view.not_measured).map(([gene, units]) => (
            <li key={gene}>
              Not measured for <span className="font-medium text-fg">{gene}</span>: {units}.
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
