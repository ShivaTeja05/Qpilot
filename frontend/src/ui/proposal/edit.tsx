/**
 * Editing a proposal before accepting it: one field per payload field, chosen by the
 * proposal's kind (a role from a list, a group by name, a dilution series' quantities, a call
 * rule…). Edits may change the payload's fields, never add one (the proposal store refuses).
 */
import { ArrowLeftRight } from "lucide-react";
import { useId, type ReactNode } from "react";
import { PRESET_WORDS, ROLE_SHORT, ROLE_WORDS, describeProposal, ruleLabel, ruleWords, type Proposal } from "@/lib/vocab";
import { Button } from "../Button";
import { Field, Input, SegmentedControl, Select, Switch, Textarea } from "../controls";

export type Payload = Record<string, unknown>;

/** Choices the page knows about (suggestions only; any value can be typed). */
export interface EditOptions {
  /** Group names already used in this session (design.group, design.comparison). */
  groups?: string[];
  /** Biological units already used (design.bio_unit). */
  units?: string[];
  /** Amplification-call rule ids to offer (curve.call_rule). */
  rules?: string[];
}

const DEFAULT_RULES = ["linregpcr", "cq_le_40", "cq_le_38", "cq_le_35"];
const ROLES = Object.keys(ROLE_SHORT);

/** The edits to send: only the fields whose value differs from the proposal's payload. */
export function diffPayload(original: Payload, edited: Payload): Payload {
  const out: Payload = {};
  for (const key of Object.keys(original)) {
    if (JSON.stringify(original[key]) !== JSON.stringify(edited[key])) out[key] = edited[key];
  }
  return out;
}

function Suggestions({ id, values }: { id: string; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <datalist id={id}>
      {values.map((v) => (
        <option key={v} value={v} />
      ))}
    </datalist>
  );
}

function TextField({
  label,
  value,
  onChange,
  suggestions,
  mono,
  hint,
}: {
  label: string;
  value: unknown;
  onChange: (v: string) => void;
  suggestions?: string[];
  mono?: boolean;
  hint?: ReactNode;
}) {
  const id = useId();
  const list = `${id}-list`;
  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <Input
        id={id}
        value={typeof value === "string" ? value : String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
        list={suggestions?.length ? list : undefined}
        className={mono ? "font-mono" : undefined}
        autoComplete="off"
        spellCheck={false}
      />
      <Suggestions id={list} values={suggestions} />
    </Field>
  );
}

function SeriesEditor({ value, onChange }: { value: Payload; onChange: (v: Payload) => void }) {
  const samples = (value.samples && typeof value.samples === "object" ? value.samples : {}) as Record<string, unknown>;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px] text-muted">
        Quantity of each sample of the series (copies, or a relative dilution) in experiment{" "}
        <code className="font-mono text-xs text-fg">{String(value.experiment_id ?? "?")}</code>.
      </p>
      <div className="max-h-64 overflow-y-auto rounded-lg border border-line qp-scroll">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 bg-surface-2">
            <tr>
              <th scope="col" className="px-3 py-1.5 text-left text-xs font-medium text-muted">
                Sample
              </th>
              <th scope="col" className="px-3 py-1.5 text-right text-xs font-medium text-muted">
                Quantity
              </th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(samples).map(([name, q]) => (
              <tr key={name} className="border-t border-line">
                <td className="px-3 py-1 font-mono text-xs">{name}</td>
                <td className="px-2 py-1 text-right">
                  <Input
                    type="number"
                    step="any"
                    min={0}
                    aria-label={`Quantity of ${name}`}
                    className="ml-auto h-7 w-32 text-right font-mono tabular"
                    value={typeof q === "number" || typeof q === "string" ? String(q) : ""}
                    onChange={(e) => {
                      const n = e.target.value === "" ? "" : Number(e.target.value);
                      onChange({ ...value, samples: { ...samples, [name]: n } });
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GenericEditor({ value, onChange }: { value: Payload; onChange: (v: Payload) => void }) {
  const kept: string[] = [];
  const fields = Object.entries(value).map(([key, v]) => {
    const label = key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
    if (typeof v === "string") {
      return v.length > 80 ? (
        <Field key={key} label={label}>
          <Textarea value={v} onChange={(e) => onChange({ ...value, [key]: e.target.value })} rows={4} aria-label={label} />
        </Field>
      ) : (
        <TextField key={key} label={label} value={v} onChange={(s) => onChange({ ...value, [key]: s })} />
      );
    }
    if (typeof v === "number") {
      return (
        <TextField
          key={key}
          label={label}
          value={String(v)}
          mono
          onChange={(s) => onChange({ ...value, [key]: s === "" ? "" : Number(s) })}
        />
      );
    }
    if (typeof v === "boolean") {
      return <Switch key={key} label={label} checked={v} onCheckedChange={(c) => onChange({ ...value, [key]: c })} />;
    }
    if (Array.isArray(v) && v.every((x) => typeof x === "string")) {
      return (
        <TextField
          key={key}
          label={`${label} (separated by commas)`}
          value={v.join(", ")}
          onChange={(s) =>
            onChange({
              ...value,
              [key]: s
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean),
            })
          }
        />
      );
    }
    kept.push(label.toLowerCase());
    return null;
  });
  return (
    <div className="flex flex-col gap-3">
      {fields}
      {kept.length ? <p className="text-xs text-muted">Kept as proposed: {kept.join(", ")}.</p> : null}
    </div>
  );
}

/** The fields of one kind of proposal, editing `value` (the payload with the edits so far). */
export function PayloadEditor({
  proposal,
  value,
  onChange,
  options,
}: {
  proposal: Pick<Proposal, "kind" | "subject" | "payload" | "alternatives">;
  value: Payload;
  onChange: (next: Payload) => void;
  options?: EditOptions;
}) {
  const set = (key: string, v: unknown) => onChange({ ...value, [key]: v });
  const s = proposal.subject;
  switch (proposal.kind) {
    case "design.well_role":
      return (
        <Field label={`Role of sample ${s}`}>
          <Select
            label={`Role of sample ${s}`}
            value={String(value.role ?? "")}
            onValueChange={(v) => set("role", v)}
            options={ROLES.map((r) => ({ value: r, label: ROLE_SHORT[r] ?? r, hint: ROLE_WORDS[r] }))}
          />
        </Field>
      );
    case "design.group":
      return <TextField label={`Group of sample ${s}`} value={value.group} onChange={(v) => set("group", v)} suggestions={options?.groups} />;
    case "design.bio_unit":
      return (
        <TextField
          label={`Biological unit of sample ${s}`}
          value={value.biological_unit}
          onChange={(v) => set("biological_unit", v)}
          suggestions={options?.units}
          hint="Samples of one unit are technical replicates of it; the unit is what counts as n."
        />
      );
    case "design.target_role":
      return (
        <Field label={`Role of target ${s}`}>
          <SegmentedControl
            label={`Role of target ${s}`}
            value={String(value.role ?? "toi")}
            onValueChange={(v) => set("role", v)}
            options={[
              { value: "ref", label: "Reference gene" },
              { value: "toi", label: "Gene of interest" },
            ]}
          />
        </Field>
      );
    case "design.gene_symbol":
      return (
        <TextField
          label={`HGNC symbol of target ${s}`}
          value={value.symbol}
          mono
          onChange={(v) => set("symbol", v.trim())}
          hint="The engine checks it against the HGNC table (approved symbols only)."
        />
      );
    case "design.comparison":
      return (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-end gap-2">
            <TextField label="Group (numerator)" value={value.group_a} onChange={(v) => set("group_a", v)} suggestions={options?.groups} />
            <Button
              variant="ghost"
              size="md"
              aria-label="Swap the two groups"
              className="mb-0 px-2"
              onClick={() => onChange({ ...value, group_a: value.group_b, group_b: value.group_a })}
            >
              <ArrowLeftRight className="size-4" aria-hidden />
            </Button>
            <TextField label="Reference group" value={value.group_b} onChange={(v) => set("group_b", v)} suggestions={options?.groups} />
          </div>
          <p className="text-xs text-muted">Fold change = the first group relative to the reference group.</p>
        </div>
      );
    case "design.dilution_series":
      return <SeriesEditor value={value} onChange={onChange} />;
    case "design.preset": {
      const presets = [...new Set([String(value.preset ?? ""), ...Object.keys(PRESET_WORDS)])].filter(Boolean);
      return (
        <Field label="Built-in design">
          <Select
            label="Built-in design"
            value={String(value.preset ?? "")}
            onValueChange={(v) => set("preset", v)}
            options={presets.map((p) => ({ value: p, label: p, hint: PRESET_WORDS[p] }))}
          />
        </Field>
      );
    }
    case "curve.call_rule": {
      const rules = [
        ...new Set([
          String(value.rule ?? ""),
          String(proposal.payload.rule ?? ""),
          ...proposal.alternatives.map((a) => String(a.rule ?? "")),
          ...(options?.rules ?? DEFAULT_RULES),
        ]),
      ].filter(Boolean);
      return (
        <Field label="Count a well as amplified by">
          <Select
            label="Count a well as amplified by"
            value={String(value.rule ?? "")}
            onValueChange={(v) => set("rule", v)}
            options={rules.map((r) => ({ value: r, label: ruleLabel(r), hint: ruleWords(r) }))}
          />
        </Field>
      );
    }
    case "curve.well_call":
      return (
        <Field label={`Well ${s}`}>
          <SegmentedControl
            label={`Call of well ${s}`}
            value={value.amplified === true ? "yes" : "no"}
            onValueChange={(v) => set("amplified", v === "yes")}
            options={[
              { value: "yes", label: "Amplified" },
              { value: "no", label: "Not amplified" },
            ]}
          />
        </Field>
      );
    case "prism.exclusion_reason":
      return (
        <Field label="What to do with this value">
          <SegmentedControl
            label="What to do with this value"
            value={String(value.action ?? "exclude")}
            onValueChange={(v) => set("action", v)}
            options={[
              { value: "exclude", label: "Exclude it" },
              { value: "restore", label: "Keep it (restore)" },
            ]}
          />
        </Field>
      );
    case "prism.value_edit":
      return (
        <Field label="What to do with the changed value">
          <SegmentedControl
            label="What to do with the changed value"
            value={String(value.action ?? "restore")}
            onValueChange={(v) => set("action", v)}
            options={[
              { value: "restore", label: "Restore qPilot's value" },
              { value: "keep", label: "Keep the edit" },
            ]}
          />
        </Field>
      );
    default:
      return <GenericEditor value={value} onChange={onChange} />;
  }
}

/** Buttons that load another reading the proposer considered into the fields. */
export function AlternativeStarts({
  proposal,
  onPick,
}: {
  proposal: Pick<Proposal, "kind" | "subject" | "payload" | "alternatives">;
  onPick: (payload: Payload) => void;
}) {
  if (!proposal.alternatives.length) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs font-medium text-muted">Start from a reading the proposer considered</p>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="secondary" onClick={() => onPick({ ...(proposal.payload as Payload) })}>
          As proposed
        </Button>
        {proposal.alternatives.slice(0, 6).map((alt, i) => {
          const merged = { ...(proposal.payload as Payload), ...alt };
          return (
            <Button key={i} size="sm" variant="secondary" className="max-w-full" onClick={() => onPick(merged)} title={describeProposal(proposal, merged)}>
              <span className="truncate">{shortReading(proposal, merged)}</span>
            </Button>
          );
        })}
      </div>
    </div>
  );
}

/** A reading in a few words, for a button. */
function shortReading(p: Pick<Proposal, "kind">, d: Payload): string {
  switch (p.kind) {
    case "design.well_role":
      return ROLE_SHORT[String(d.role)] ?? String(d.role);
    case "design.target_role":
      return d.role === "ref" ? "Reference gene" : "Gene of interest";
    case "curve.call_rule":
      return ruleLabel(d.rule);
    case "curve.well_call":
      return d.amplified ? "Amplified" : "Not amplified";
    case "design.comparison":
      return `${String(d.group_a)} vs ${String(d.group_b)}`;
    case "design.group":
      return String(d.group);
    case "design.gene_symbol":
      return String(d.symbol);
    case "design.dilution_series": {
      const q = Object.values((d.samples ?? {}) as Record<string, unknown>)
        .map(Number)
        .filter(Number.isFinite);
      return q.length ? `Quantities ${Math.min(...q)} to ${Math.max(...q)}` : "Other quantities";
    }
    default:
      return "Other reading";
  }
}
