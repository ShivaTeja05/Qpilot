/**
 * The middle parts of a proposal card: the fold-out row, a quoted file text, the evidence list,
 * an engine check with its numbers, the consequence and the level. Every string from a file,
 * a sheet, a model or an agent is rendered as text.
 */
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  CircleCheck,
  EyeOff,
  FileText,
  Grid3x3,
  Loader2,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { count, fold, MISSING, plural, pValue } from "@/lib/format";
import { CHECK, CONCLUSION, asConclusion, type Proposal } from "@/lib/vocab";
import { Button } from "../Button";
import { CheckTag, ConclusionTag } from "../tags";
import { Tooltip } from "../overlay";
import {
  FLAG_WORDS,
  INSTRUCTION_TEXT,
  RULE_TITLE,
  RULE_WORDS,
  SIGNAL_CLASS,
  detailLabel,
  detailValue,
  originWords,
  visibleText,
  type QuarantineEntry,
} from "./words";

type Dict = Record<string, unknown>;
type Evidence = Proposal["evidence"][number];
export type ProposalCheck = Proposal["check"];

const isDict = (v: unknown): v is Dict => typeof v === "object" && v !== null && !Array.isArray(v);
const isScalar = (v: unknown) => v === null || ["string", "number", "boolean"].includes(typeof v);

// ---------------------------------------------------------------------------------------------
// The file is being read (503 `warming`): a calm wait, not an error

/** While the server reads the file for the first time: what is happening; it fills in by itself. */
export function Warming({ message, className }: { message: string; className?: string }) {
  return (
    <div role="status" className={cn("flex items-start gap-3 rounded-xl border border-line bg-surface p-4", className)}>
      <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-accent" aria-hidden />
      <div className="min-w-0">
        <p className="text-sm font-medium text-fg">Reading the file</p>
        <p className="mt-0.5 text-[13px] text-muted">{message}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// A part of the card: label, one-line summary, optional fold-out

/** One row of the card: its label, a summary that is always visible, and details on demand. */
export function Part({
  label,
  summary,
  children,
  defaultOpen = false,
  side,
  tone,
}: {
  label: string;
  summary: ReactNode;
  /** The fold-out; without it the row does not open. */
  children?: ReactNode;
  defaultOpen?: boolean;
  /** Controls at the right of the summary (a button that is not the fold toggle). */
  side?: ReactNode;
  tone?: "danger" | "warn";
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  const foldable = children != null && children !== false;
  return (
    <div className="grid grid-cols-1 gap-x-4 gap-y-1 py-2.5 sm:grid-cols-[112px_minmax(0,1fr)]">
      <div
        className={cn(
          "pt-0.5 text-xs font-medium uppercase tracking-wider",
          tone === "danger" ? "text-danger" : tone === "warn" ? "text-warn" : "text-faint",
        )}
      >
        {label}
      </div>
      <div className="min-w-0">
        <div className="flex min-w-0 items-start gap-2">
          <div className="min-w-0 flex-1 text-[13px] leading-relaxed text-fg">{summary}</div>
          {side ? <div className="flex shrink-0 items-center gap-1.5">{side}</div> : null}
          {foldable ? (
            <button
              type="button"
              aria-expanded={open}
              aria-controls={id}
              aria-label={`${open ? "Less" : "More"} about the ${label.toLowerCase()}`}
              onClick={() => setOpen((o) => !o)}
              className="inline-flex h-6 shrink-0 items-center gap-0.5 rounded-md px-1.5 text-xs font-medium text-muted transition-colors hover:bg-bg-subtle hover:text-fg"
            >
              {open ? "Less" : "More"}
              <ChevronRight
                aria-hidden
                className={cn("size-3.5 transition-transform duration-150", open && "rotate-90")}
              />
            </button>
          ) : null}
        </div>
        {foldable && open ? (
          <div id={id} className="mt-2.5">
            {children}
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Quoted text

const LONG_QUOTE = 600;

/** A quoted file text: the original in a quote block, where it came from, and its flags. */
export function Quote({ entry }: { entry: QuarantineEntry }) {
  const [all, setAll] = useState(false);
  const text = visibleText(entry.value);
  const long = text.length > LONG_QUOTE;
  const instruction = entry.flags.includes("instruction_like");
  const others = entry.flags.filter((f) => f !== "instruction_like").map((f) => FLAG_WORDS[f] ?? f.replace(/_/g, " "));
  return (
    <figure className="min-w-0">
      <blockquote
        className={cn(
          "rounded-md border-l-2 bg-sunken px-3 py-1.5 font-mono text-[12.5px] leading-relaxed break-words whitespace-pre-wrap text-fg",
          instruction ? "border-warn" : "border-line-strong",
        )}
      >
        {long && !all ? `${text.slice(0, LONG_QUOTE)}…` : text}
      </blockquote>
      {long ? (
        <button type="button" className="mt-1 text-xs text-accent hover:underline" onClick={() => setAll((a) => !a)}>
          {all ? "Show less" : `Show all ${count(text.length)} characters`}
        </button>
      ) : null}
      <figcaption className="mt-1 text-xs text-muted">
        Original text from {originWords(entry.origin)}
        {others.length ? <> · {others.join(" · ")}</> : null}
      </figcaption>
      {instruction ? (
        <p className="mt-1.5 flex items-start gap-1.5 rounded-md border border-warn/30 bg-warn-soft px-2 py-1.5 text-xs text-warn">
          <ShieldAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          <span>{INSTRUCTION_TEXT}</span>
        </p>
      ) : null}
    </figure>
  );
}

// ---------------------------------------------------------------------------------------------
// Evidence

/** Looks a quoted text up by its `text_id`; `undefined` while loading, `null` when unknown. */
export type QuoteLookup = (textId: string) => QuarantineEntry | null | undefined;

const TEXT_ID = /^t_[0-9a-f]{12}$/;
const EVIDENCE_SHOWN = 8;

const KIND_ICON: Record<string, LucideIcon> = {
  text: FileText,
  cell: Grid3x3,
  well: Activity,
  curve: Activity,
};

const KIND_WORD: Record<string, string> = {
  text: "quoted text",
  cell: "sheet cell",
  well: "well",
  curve: "curve",
  sample: "sample",
  target: "target",
  fact: "fact",
  rule: "rule",
  pattern: "pattern",
  file: "file",
};

function cellText(ref: string, sheetCells: Record<string, string> | undefined): string | undefined {
  if (!sheetCells) return undefined;
  if (sheetCells[ref]) return sheetCells[ref];
  const hit = Object.keys(sheetCells).find((cell) => ref.endsWith(cell));
  return hit ? sheetCells[hit] : undefined;
}

/** What the evidence list says on one line: "1 quoted text", "2 wells · 1 rule". */
export function evidenceSummary(evidence: Evidence[]): string {
  if (!evidence.length) return "No source is cited.";
  const kinds = new Map<string, number>();
  for (const e of evidence) kinds.set(e.kind, (kinds.get(e.kind) ?? 0) + 1);
  return [...kinds].map(([k, n]) => plural(n, KIND_WORD[k] ?? k)).join(" · ");
}

function EvidenceItem({
  item,
  quotes,
  sheetCells,
  onOpenWell,
}: {
  item: Evidence;
  quotes?: QuoteLookup;
  sheetCells?: Record<string, string>;
  onOpenWell?: (well: string) => void;
}) {
  const Icon = KIND_ICON[item.kind] ?? CircleCheck;
  let body: ReactNode;
  if (item.kind === "text" || TEXT_ID.test(item.ref)) {
    const entry = quotes?.(item.ref);
    body =
      entry === undefined ? (
        <span className="text-muted">Reading the quoted text…</span>
      ) : entry === null ? (
        <span className="text-muted">
          Text <code className="font-mono text-xs">{item.ref}</code> is not in this session's quarantine.
        </span>
      ) : (
        <Quote entry={entry} />
      );
  } else if (item.kind === "cell") {
    const textId = cellText(item.ref, sheetCells);
    const entry = textId ? quotes?.(textId) : null;
    body = (
      <>
        <div className="text-muted">
          Cell <code className="font-mono text-xs text-fg">{item.ref}</code>
          {item.ref.startsWith("sent_back/") ? " of the table Prism sent back" : ""}
        </div>
        {entry ? (
          <div className="mt-1">
            <Quote entry={entry} />
          </div>
        ) : entry === undefined && textId ? (
          <span className="text-muted">Reading the cell…</span>
        ) : null}
      </>
    );
  } else if (item.kind === "well" || item.kind === "curve") {
    body = (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted">{item.kind === "curve" ? "Curve of well" : "Well"}</span>
        <code className="font-mono text-xs text-fg">{item.ref}</code>
        {onOpenWell ? (
          <Button size="sm" variant="secondary" icon={<Activity />} onClick={() => onOpenWell(item.ref)}>
            Open the curve
          </Button>
        ) : null}
      </div>
    );
  } else {
    body = (
      <span className="text-muted">
        {(KIND_WORD[item.kind] ?? item.kind).replace(/^./, (c) => c.toUpperCase())}{" "}
        <code className="font-mono text-xs text-fg">{item.ref}</code>
      </span>
    );
  }
  return (
    <li className="flex min-w-0 gap-2.5">
      <Icon className="mt-0.5 size-3.5 shrink-0 text-faint" aria-hidden />
      <div className="min-w-0 flex-1 text-[13px]">
        {body}
        {item.note ? <p className="mt-0.5 text-xs text-muted">{item.note}</p> : null}
      </div>
    </li>
  );
}

/** Every source behind a proposal; the first {@link EVIDENCE_SHOWN}, then "Show all". */
export function EvidenceList({
  evidence,
  quotes,
  sheetCells,
  onOpenWell,
}: {
  evidence: Evidence[];
  quotes?: QuoteLookup;
  sheetCells?: Record<string, string>;
  onOpenWell?: (well: string) => void;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? evidence : evidence.slice(0, EVIDENCE_SHOWN);
  return (
    <div>
      <ul className="flex flex-col gap-2.5">
        {shown.map((item, i) => (
          <EvidenceItem key={`${item.kind}:${item.ref}:${i}`} item={item} quotes={quotes} sheetCells={sheetCells} onOpenWell={onOpenWell} />
        ))}
      </ul>
      {evidence.length > EVIDENCE_SHOWN ? (
        <button type="button" className="mt-2 text-xs font-medium text-accent hover:underline" onClick={() => setAll((a) => !a)}>
          {all ? "Show fewer" : `Show all ${count(evidence.length)} sources`}
        </button>
      ) : null}
    </div>
  );
}

/** The Why row's one line: the single quoted text inline when there is one, else the counts. */
export function WhySummary({ evidence, quotes }: { evidence: Evidence[]; quotes?: QuoteLookup }) {
  const first = evidence[0];
  if (evidence.length === 1 && first && (first.kind === "text" || TEXT_ID.test(first.ref))) {
    const entry = quotes?.(first.ref);
    if (entry) {
      const text = visibleText(entry.value);
      return (
        <span className="inline-flex min-w-0 flex-wrap items-baseline gap-x-1.5">
          <q className="min-w-0 truncate rounded bg-sunken px-1 font-mono text-[12.5px] text-fg">
            {text.length > 80 ? `${text.slice(0, 80)}…` : text}
          </q>
          <span className="text-muted">from {originWords(entry.origin)}</span>
          {entry.flags.includes("instruction_like") ? (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-warn">
              <ShieldAlert className="size-3" aria-hidden /> reads like an instruction, never obeyed
            </span>
          ) : null}
        </span>
      );
    }
  }
  return <span className="text-muted">{evidenceSummary(evidence)}</span>;
}

// ---------------------------------------------------------------------------------------------
// Details (a check's numbers, a consequence)

const TABLE_ROWS = 8;
const TABLE_COLUMNS = 9;
const COLUMN_ORDER = [
  "run_id",
  "well",
  "sample",
  "target",
  "class",
  "status",
  "cq",
  "gap_cycles",
  "unknown_median_cq",
  "r2",
  "efficiency",
  "slope",
  "intercept",
  "n_wells",
  "n_wells_used",
  "copies",
  "n",
  "range",
  "tolerance",
];

/** A list of records (wells with a signal, replicate sets, fits) as a small table. */
function DetailTable({ rows, label, onOpenWell }: { rows: Dict[]; label: string; onOpenWell?: (well: string) => void }) {
  const [all, setAll] = useState(false);
  const columns: string[] = [];
  for (const r of rows.slice(0, 50)) {
    for (const [k, v] of Object.entries(r)) if (!columns.includes(k) && isScalar(v)) columns.push(k);
  }
  // Where a row is (plate, well, sample, target) first, then what was found, then the rest.
  const rank = (k: string) => {
    const i = COLUMN_ORDER.indexOf(k);
    return i >= 0 ? i : COLUMN_ORDER.length + columns.indexOf(k);
  };
  const cols = [...columns].sort((a, b) => rank(a) - rank(b)).slice(0, TABLE_COLUMNS);
  const wells = Boolean(onOpenWell) && cols.includes("run_id") && cols.includes("well");
  const shown = all ? rows : rows.slice(0, TABLE_ROWS);
  return (
    <div className="min-w-0">
      <div className="overflow-x-auto rounded-lg border border-line qp-scroll">
        <table className="w-full border-collapse text-xs" aria-label={label}>
          <thead className="bg-surface-2">
            <tr>
              {cols.map((c) => (
                <th key={c} scope="col" className="px-2 py-1.5 text-left font-medium whitespace-nowrap text-muted">
                  {detailLabel(c)}
                </th>
              ))}
              {wells ? (
                <th scope="col" className="px-2 py-1.5">
                  <span className="sr-only">Curve</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {cols.map((c) => {
                  const v = r[c];
                  const numeric = typeof v === "number";
                  const text =
                    c === "class" && typeof v === "string"
                      ? (SIGNAL_CLASS[v] ?? detailValue(v))
                      : c === "status" && (v === "consistent" || v === "contradicted" || v === "cannot_check")
                        ? CHECK[v].word.toLowerCase()
                        : detailValue(v);
                  return (
                    <td
                      key={c}
                      className={cn(
                        "px-2 py-1 whitespace-nowrap",
                        numeric ? "text-right font-mono tabular" : c === "run_id" || c === "well" ? "font-mono" : "",
                      )}
                    >
                      {text}
                    </td>
                  );
                })}
                {wells ? (
                  <td className="px-1 py-0.5 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Activity />}
                      onClick={() => onOpenWell?.(`${String(r.run_id)}/${String(r.well)}`)}
                      aria-label={`Open the curve of ${String(r.run_id)}/${String(r.well)}`}
                    >
                      Curve
                    </Button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > TABLE_ROWS ? (
        <button type="button" className="mt-1 text-xs font-medium text-accent hover:underline" onClick={() => setAll((a) => !a)}>
          {all ? "Show fewer" : `Show all ${count(rows.length)}`}
        </button>
      ) : null}
    </div>
  );
}

function Nested({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 text-xs font-medium text-muted hover:text-fg"
      >
        <ChevronRight aria-hidden className={cn("size-3.5 transition-transform duration-150", open && "rotate-90")} />
        {label}
      </button>
      {open ? (
        <div id={id} className="mt-1.5 border-l border-line pl-3">
          {children}
        </div>
      ) : null}
    </div>
  );
}

/**
 * A check's (or a consequence's) `details`, in words: numbers as label/value rows, each rule's
 * own result with its note, lists of wells or replicate sets as small tables (a well opens its
 * curve), anything nested folded away.
 */
export function DetailsView({
  details,
  onOpenWell,
  hide = [],
}: {
  details: Dict;
  onOpenWell?: (well: string) => void;
  /** Keys not to show (already shown elsewhere). */
  hide?: string[];
}) {
  const entries = Object.entries(details).filter(([k]) => !hide.includes(k));
  const scalars = entries.filter(([, v]) => isScalar(v) || (Array.isArray(v) && v.every(isScalar) && v.length > 0));
  const checks = entries.find(([k, v]) => k === "checks" && isDict(v))?.[1] as Dict | undefined;
  const tables = entries.filter(([, v]) => Array.isArray(v) && v.length > 0 && v.every(isDict)) as [string, Dict[]][];
  const nested = entries.filter(([k, v]) => k !== "checks" && isDict(v)) as [string, Dict][];
  const empties = entries.filter(([, v]) => Array.isArray(v) && v.length === 0);
  return (
    <div className="flex flex-col gap-3">
      {scalars.length || empties.length ? (
        <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
          {[...scalars, ...empties].map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{detailLabel(k)}</dt>
              <dd className={cn("min-w-0 break-words text-fg", typeof v === "number" && "font-mono tabular")}>
                {Array.isArray(v) && v.length === 0
                  ? "none"
                  : k.endsWith("_range") && Array.isArray(v) && v.length === 2
                    ? `${detailValue(v[0])} to ${detailValue(v[1])}`
                    : detailValue(v)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {checks ? (
        <ul className="flex flex-col gap-2">
          {Object.entries(checks).map(([rule, sub]) => {
            const s = isDict(sub) ? sub : {};
            const status = (["consistent", "contradicted", "cannot_check"] as const).find((x) => x === s.status);
            return (
              <li key={rule} className="rounded-lg border border-line px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <RuleChip rule={rule} />
                  {status ? <CheckTag status={status} /> : null}
                  {typeof s.note === "string" && s.note ? <span className="text-[13px] text-fg">{s.note}</span> : null}
                </div>
                {isDict(s.details) && Object.keys(s.details).length ? (
                  <div className="mt-1.5">
                    <Nested label="Its numbers">
                      <DetailsView details={s.details} onOpenWell={onOpenWell} />
                    </Nested>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {tables.map(([k, rows]) => (
        <div key={k} className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-muted">
            {detailLabel(k).replace(/^./, (c) => c.toUpperCase())} ({count(rows.length)})
          </p>
          <DetailTable rows={rows} label={detailLabel(k)} onOpenWell={onOpenWell} />
        </div>
      ))}
      {nested.map(([k, v]) => (
        <Nested key={k} label={detailLabel(k).replace(/^./, (c) => c.toUpperCase())}>
          <DetailsView details={v} onOpenWell={onOpenWell} />
        </Nested>
      ))}
    </div>
  );
}

/** A rule id (`D-NTC`) with what it can refute on hover. */
export function RuleChip({ rule }: { rule: string }) {
  const parts = rule.split("/");
  const words = parts
    .map((r) => RULE_WORDS[r])
    .filter(Boolean)
    .join(" ");
  const title = parts
    .map((r) => RULE_TITLE[r])
    .filter(Boolean)
    .join(" · ");
  const chip = (
    <span
      tabIndex={words ? 0 : undefined}
      className="inline-flex h-5 items-center gap-1 rounded border border-line bg-surface-2 px-1.5 text-[11px] text-muted"
    >
      {title ? <span className="font-medium text-fg">{title}</span> : null}
      <span className="font-mono">{rule}</span>
    </span>
  );
  return words ? <Tooltip content={<span className="block max-w-xs">{words}</span>}>{chip}</Tooltip> : chip;
}

// ---------------------------------------------------------------------------------------------
// Engine check

/** The Engine check row's summary: the status, the note and the rule ids. */
export function CheckSummary({ check }: { check: ProposalCheck }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <CheckTag status={check.status} />
      <span className="text-fg">{check.note || CHECK[check.status].meaning}</span>
      {check.rule_ids.map((r) => (
        <RuleChip key={r} rule={r} />
      ))}
    </span>
  );
}

/** The check's fold-out: what the status means, then its numbers. */
export function CheckDetails({ check, onOpenWell }: { check: ProposalCheck; onOpenWell?: (well: string) => void }) {
  const details = (check.details ?? {}) as Dict;
  const rules = check.rule_ids.filter((r) => RULE_WORDS[r]);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted">{CHECK[check.status].meaning}</p>
      {rules.length ? (
        <ul className="flex flex-col gap-1 text-xs text-muted">
          {rules.map((r) => (
            <li key={r}>
              <span className="font-mono text-fg">{r}</span> · {RULE_WORDS[r]}
            </li>
          ))}
        </ul>
      ) : null}
      {Object.keys(details).length ? <DetailsView details={details} onOpenWell={onOpenWell} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Consequence

export const MATTERS_TEXT = "This matters for at least one conclusion; decide on the evidence.";
export const NOT_MATTERS_TEXT = "Neither reading changes any conclusion.";
export const CANNOT_TELL_TEXT =
  "This cannot be answered yet: the rest of the design does not run. Settle the other proposals, then ask again.";
export const BLIND_TEXT = "Hidden until the design and the curves are confirmed (blind): no gene, direction or number.";
export const HIDDEN_TEXT = "Hidden: the design or the curves are not confirmed (again) yet, so no result is shown.";

/** The blind answer, as one line with an icon. */
export function MattersLine({ matters }: { matters: boolean | null | undefined }) {
  if (matters === true) {
    return (
      <span className="inline-flex items-start gap-1.5 font-medium text-warn">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        {MATTERS_TEXT}
      </span>
    );
  }
  if (matters === false) {
    return (
      <span className="inline-flex items-start gap-1.5 text-ok">
        <CircleCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        {NOT_MATTERS_TEXT}
      </span>
    );
  }
  if (matters === null) return <span className="text-muted">{CANNOT_TELL_TEXT}</span>;
  return (
    <span className="inline-flex items-start gap-1.5 text-muted">
      <EyeOff className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      {BLIND_TEXT}
    </span>
  );
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function units(v: unknown): string {
  return Array.isArray(v) ? v.map((x) => (typeof x === "number" ? count(x) : MISSING)).join(" and ") : detailValue(v);
}

function Before({ label, before, after }: { label: ReactNode; before: ReactNode; after: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-muted">{label}</dt>
      <dd className="flex flex-wrap items-center gap-1.5 font-mono text-fg tabular">
        <span>{before}</span>
        <span aria-label="becomes" className="text-faint">
          →
        </span>
        <span>{after}</span>
      </dd>
    </div>
  );
}

function changedLine(changed: number, nGenes: unknown, together?: { n: unknown; alone: number }): string {
  const of = typeof nGenes === "number" ? count(nGenes) : "?";
  if (!together) {
    return changed
      ? `Excluding it changes ${count(changed)} of ${of} conclusions.`
      : `Excluding it changes no conclusion (0 of ${of}).`;
  }
  const n = typeof together.n === "number" ? count(together.n) : "?";
  if (changed && !together.alone)
    return `On its own it changes no conclusion, but together with the other exclusions found in this round trip (${n} in all) ${count(changed)} of ${of} conclusions change.`;
  if (changed) return `Together with the other exclusions found in this round trip (${n} in all), ${count(changed)} of ${of} conclusions change.`;
  return `Together with the other exclusions found in this round trip (${n} in all), no conclusion changes (0 of ${of}).`;
}

/** What excluding one value does (a round-trip exclusion): fold, p, conclusion, units; and together. */
export function ExclusionConsequence({ c }: { c: Dict }) {
  const gene = String(c.gene ?? "");
  const changed = num(c.n_conclusions_changed) ?? 0;
  const genes = Array.isArray(c.changed_genes) ? c.changed_genes.map(String) : [];
  const w = isDict(c.with_all_pending) ? c.with_all_pending : null;
  const wChanged = w ? (num(w.n_conclusions_changed) ?? 0) : 0;
  const wGenes = w && Array.isArray(w.changed_genes) ? w.changed_genes.map(String) : [];
  return (
    <div className="flex flex-col gap-3">
      <p className={cn("text-[13px]", changed ? "font-medium text-warn" : "text-fg")}>{changedLine(changed, c.n_genes)}</p>
      <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
        <Before label={`Fold change of ${gene}`} before={fold(num(c.fc_before))} after={fold(num(c.fc_after))} />
        <Before label="p-value" before={pValue(num(c.p_before))} after={pValue(num(c.p_after))} />
        <Before
          label={`Conclusion for ${gene}`}
          before={<ConclusionTag conclusion={asConclusion(c.conclusion_before)} />}
          after={<ConclusionTag conclusion={asConclusion(c.conclusion_after)} />}
        />
        <Before label="Biological units per group" before={units(c.n_units_before)} after={units(c.n_units_after)} />
        {genes.length ? (
          <div className="contents">
            <dt className="text-muted">Genes whose conclusion changes</dt>
            <dd className="text-fg">{genes.join(", ")}</dd>
          </div>
        ) : null}
      </dl>
      {w ? (
        <div className="rounded-lg border border-line bg-surface-2 p-3">
          <p className={cn("text-[13px]", wChanged ? "font-medium text-warn" : "text-fg")}>
            {changedLine(wChanged, c.n_genes, { n: w.n_exclusions, alone: changed })}
          </p>
          <dl className="mt-2 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
            <Before label={`Fold change of ${gene}, all together`} before={fold(num(w.fc_before))} after={fold(num(w.fc_after))} />
            <Before
              label={`Conclusion for ${gene}, all together`}
              before={<ConclusionTag conclusion={asConclusion(w.conclusion_before)} />}
              after={<ConclusionTag conclusion={asConclusion(w.conclusion_after)} />}
            />
            {wGenes.length ? (
              <div className="contents">
                <dt className="text-muted">Genes whose conclusion changes, all together</dt>
                <dd className="text-fg">{wGenes.join(", ")}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      ) : null}
    </div>
  );
}

/** The one line of a round-trip exclusion's consequence (the card's summary). */
export function exclusionHeadline(c: Dict): ReactNode {
  const changed = num(c.n_conclusions_changed) ?? 0;
  const before = asConclusion(c.conclusion_before);
  const after = asConclusion(c.conclusion_after);
  return (
    <span className={cn(changed ? "font-medium text-warn" : "text-fg")}>
      {changedLine(changed, c.n_genes)}{" "}
      <span className="font-normal text-muted">
        {String(c.gene ?? "")}: {fold(num(c.fc_before))} → {fold(num(c.fc_after))}
        {before !== after ? ` (${CONCLUSION[before].word} → ${CONCLUSION[after].word})` : ""}
      </span>
    </span>
  );
}
