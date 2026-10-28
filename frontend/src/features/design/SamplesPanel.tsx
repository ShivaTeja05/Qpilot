/**
 * The sample table of the Design editor: select samples (a click, Shift-click for a range,
 * ⌘/Ctrl-A, a name pattern, or wells on the plate map) and set their group, type and
 * biological unit in one go. Every change goes to the draft; nothing is recorded until the
 * person reviews it. Blind: the table shows names, wells and the design so far, never a number
 * about a well.
 */
import { CircleDot, Layers, ListChecks, Tag, Users } from "lucide-react";
import { useMemo, useRef, useState, type MouseEvent } from "react";
import { count } from "@/lib/format";
import { ROLE_SHORT, ROLE_WORDS } from "@/lib/vocab";
import { Button, Input, Select, Table, TBody, TD, TH, THead, TR } from "@/ui";
import { visibleText, type QuoteLookup } from "@/ui/proposal";
import { CopiesHelper } from "./CopiesHelper";
import {
  NAME_RE,
  NAME_WORDS,
  byPlateOrder,
  dilutionQuantities,
  groupItems,
  patternTest,
  sampleNow,
  unitItems,
  withItems,
  withSampleType,
  type Draft,
  type EditorSample,
  type EditorView,
} from "./draft";

const CONTROLS = new Set(["ntc", "nrt", "nac"]);
type Show = "all" | "study" | "other" | "ungrouped";
const SHOW: { value: Show; label: string }[] = [
  { value: "all", label: "Every sample" },
  { value: "study", label: "Study samples" },
  { value: "other", label: "Controls, standards…" },
  { value: "ungrouped", label: "Study samples in no group" },
];

/** What waiting proposals say about a sample (shown, and taken with one click). */
export interface Proposed {
  group?: string | null;
  unit?: string | null;
}

export function SamplesPanel({
  view,
  draft,
  quotes,
  selected,
  onSelect,
  onDraft,
  proposed,
  disabled,
}: {
  view: EditorView;
  draft: Draft;
  quotes: QuoteLookup;
  selected: ReadonlySet<string>;
  onSelect: (next: Set<string>) => void;
  onDraft: (next: Draft) => void;
  proposed: ReadonlyMap<string, Proposed>;
  disabled?: boolean;
}) {
  const [show, setShow] = useState<Show>("all");
  const [pattern, setPattern] = useState("");
  const [group, setGroup] = useState("");
  const [unit, setUnit] = useState("");
  const [type, setType] = useState("unkn");
  const [top, setTop] = useState("");
  const [step, setStep] = useState("10");
  const anchor = useRef<number | null>(null);

  const members = useMemo(() => new Map(view.membership.map((m) => [m.sample, m])), [view]);
  const rows = useMemo(
    () =>
      [...view.samples].sort(byPlateOrder).map((s) => ({
        s,
        now: sampleNow(s, members.get(s.sample), draft),
        name: nameOf(s, quotes),
      })),
    [view, members, draft, quotes],
  );
  const shown = rows.filter(({ now }) =>
    show === "all"
      ? true
      : show === "study"
        ? now.role === "unkn"
        : show === "other"
          ? now.role !== "unkn"
          : now.role === "unkn" && !now.group,
  );
  const chosen = rows.filter((r) => selected.has(r.s.sample));
  const nWells = chosen.reduce((n, r) => n + r.s.n_wells, 0);
  const locked = chosen.filter((r) => r.s.locked || CONTROLS.has(r.now.role));
  const free = chosen.filter((r) => !(r.s.locked || CONTROLS.has(r.now.role)));
  const groups = [...new Set(rows.map((r) => r.now.group).filter(Boolean) as string[])].sort();
  const units = [...new Set(rows.map((r) => r.now.unit).filter(Boolean) as string[])].sort();
  const test = patternTest(pattern);
  const withProposal = rows.filter((r) => proposed.has(r.s.sample));

  const toggle = (index: number, e: MouseEvent | null) => {
    const row = shown[index];
    if (!row) return;
    const next = new Set(selected);
    if (e?.shiftKey && anchor.current !== null) {
      const [a, b] = [anchor.current, index].sort((x, y) => x - y);
      for (const r of shown.slice(a, b! + 1)) next.add(r.s.sample);
    } else if (next.has(row.s.sample)) next.delete(row.s.sample);
    else next.add(row.s.sample);
    anchor.current = index;
    onSelect(next);
  };
  const selectWhere = (keep: (r: (typeof rows)[number]) => boolean, add = false) =>
    onSelect(new Set([...(add ? selected : []), ...rows.filter(keep).map((r) => r.s.sample)]));

  const groupOk = NAME_RE.test(group.trim());
  const unitOk = NAME_RE.test(unit.trim());
  const topNumber = Number(top);
  const stepNumber = Number(step);
  const stdOk = type !== "std" || (topNumber > 0 && stepNumber >= 1);
  const ordered = [...free].sort((a, b) => byPlateOrder(a.s, b.s));
  const quantities =
    type === "std" && stdOk
      ? dilutionQuantities(
          ordered.map((r) => r.s.sample),
          topNumber,
          stepNumber,
        )
      : {};

  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-prose text-[13px] text-muted">
        Select samples here or on the plate map (click a well, Shift-click for a rectangle,
        ⌘/Ctrl-click to add, a row letter or column number for the whole row or column), then set
        their group, type or biological unit. Wells of one sample are its technical replicates;
        samples of one biological unit (one animal, one donor) are averaged and count once.
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="flex min-w-[14rem] flex-1 flex-col gap-1">
          <label htmlFor="sample-pattern" className="text-[13px] font-medium text-fg">
            Select by name
          </label>
          <Input
            id="sample-pattern"
            value={pattern}
            placeholder="e.g. KO*, *_d7, or part of a name"
            onChange={(e) => setPattern(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && test) {
                e.preventDefault();
                selectWhere((r) => test(r.name) || test(r.s.sample), e.shiftKey);
              }
            }}
          />
        </div>
        <Button
          size="sm"
          variant="secondary"
          disabled={!test}
          onClick={() => test && selectWhere((r) => test(r.name) || test(r.s.sample))}
        >
          Select matching
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!test}
          onClick={() => test && selectWhere((r) => test(r.name) || test(r.s.sample), true)}
        >
          Add matching
        </Button>
        <Button size="sm" variant="ghost" onClick={() => selectWhere((r) => r.now.role === "unkn")}>
          All study samples
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!selected.size}
          onClick={() => onSelect(new Set())}
        >
          Clear
        </Button>
      </div>

      <div
        className="flex flex-col gap-3 rounded-xl border border-line bg-surface-2 p-3"
        aria-label="Set the selected samples"
        role="group"
      >
        <p className="text-[13px] text-fg" aria-live="polite">
          {chosen.length ? (
            <>
              <span className="font-semibold">{count(chosen.length)}</span> sample
              {chosen.length === 1 ? "" : "s"} selected ({count(nWells)} well
              {nWells === 1 ? "" : "s"})
              {locked.length ? (
                <span className="text-muted">
                  {" "}
                  · {count(locked.length)} {locked.length === 1 ? "is a control" : "are controls"}:
                  they keep their type and join no group
                </span>
              ) : null}
            </>
          ) : (
            <span className="text-muted">Select samples to set their group, type or unit.</span>
          )}
        </p>
        <div className="grid gap-3 lg:grid-cols-3">
          <fieldset className="flex flex-col gap-1.5" disabled={disabled || !free.length}>
            <legend className="mb-1 flex items-center gap-1.5 text-[13px] font-medium text-fg">
              <Users className="size-3.5 text-muted" aria-hidden /> Group
            </legend>
            <Input
              aria-label="Group name"
              list="design-groups"
              value={group}
              placeholder={groups[0] ? `e.g. ${groups[0]}` : "e.g. control, treated"}
              onChange={(e) => setGroup(e.target.value)}
              aria-invalid={Boolean(group.trim()) && !groupOk}
            />
            <datalist id="design-groups">
              {groups.map((g) => (
                <option key={g} value={g} />
              ))}
            </datalist>
            {group.trim() && !groupOk ? (
              <p className="text-xs text-danger">A group name uses {NAME_WORDS}.</p>
            ) : null}
            <div className="flex flex-wrap gap-1.5">
              <Button
                size="sm"
                variant="primary"
                disabled={!groupOk}
                onClick={() =>
                  onDraft(
                    withItems(
                      draft,
                      groupItems(
                        free.map((r) => r.s.sample),
                        group.trim(),
                      ),
                    ),
                  )
                }
              >
                Put in group
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  onDraft(
                    withItems(
                      draft,
                      groupItems(
                        free.map((r) => r.s.sample),
                        null,
                      ),
                    ),
                  )
                }
              >
                No group
              </Button>
            </div>
          </fieldset>

          <fieldset className="flex flex-col gap-1.5" disabled={disabled || !free.length}>
            <legend className="mb-1 flex items-center gap-1.5 text-[13px] font-medium text-fg">
              <Tag className="size-3.5 text-muted" aria-hidden /> Sample type
            </legend>
            <Select
              label="Sample type"
              value={type}
              onValueChange={setType}
              options={view.sample_types.map((o) => ({
                value: o.value,
                label: o.label,
                hint: o.hint,
              }))}
              size="sm"
            />
            {type === "std" ? (
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                <label htmlFor="std-top">Highest quantity</label>
                <Input
                  id="std-top"
                  inputMode="decimal"
                  className="h-7 w-24 text-[13px]"
                  value={top}
                  placeholder="e.g. 1e6"
                  onChange={(e) => setTop(e.target.value)}
                />
                <label htmlFor="std-step">each next ÷</label>
                <Input
                  id="std-step"
                  inputMode="decimal"
                  className="h-7 w-16 text-[13px]"
                  value={step}
                  onChange={(e) => setStep(e.target.value)}
                />
                <span className="basis-full">
                  In plate order (copies, or a relative dilution such as 1 for the most
                  concentrated).
                  {ordered.length && stdOk
                    ? ` ${ordered
                        .slice(0, 4)
                        .map((r) => `${r.name}: ${quantities[r.s.sample]?.toPrecision(3)}`)
                        .join(", ")}${ordered.length > 4 ? " …" : ""}`
                    : ""}
                </span>
                <CopiesHelper onUse={(copies) => setTop(String(copies))} />
              </div>
            ) : null}
            <div className="flex flex-wrap gap-1.5">
              <Button
                size="sm"
                variant="primary"
                disabled={!stdOk}
                onClick={() =>
                  onDraft(
                    withSampleType(
                      draft,
                      free.map((r) => ({
                        sample: r.s.sample,
                        experiment: r.s.experiments[0] ?? view.experiments[0] ?? null,
                      })),
                      type,
                      quantities,
                    ),
                  )
                }
              >
                Set type
              </Button>
            </div>
          </fieldset>

          <fieldset className="flex flex-col gap-1.5" disabled={disabled || !free.length}>
            <legend className="mb-1 flex items-center gap-1.5 text-[13px] font-medium text-fg">
              <Layers className="size-3.5 text-muted" aria-hidden /> Biological unit
            </legend>
            <Input
              aria-label="Biological unit name"
              list="design-units"
              value={unit}
              placeholder="e.g. mouse 3, donor B"
              onChange={(e) => setUnit(e.target.value)}
              aria-invalid={Boolean(unit.trim()) && !unitOk}
            />
            <datalist id="design-units">
              {units.map((u) => (
                <option key={u} value={u} />
              ))}
            </datalist>
            {unit.trim() && !unitOk ? (
              <p className="text-xs text-danger">A unit name uses {NAME_WORDS}.</p>
            ) : null}
            <div className="flex flex-wrap gap-1.5">
              <Button
                size="sm"
                variant="primary"
                disabled={!unitOk}
                onClick={() =>
                  onDraft(
                    withItems(
                      draft,
                      unitItems(
                        free.map((r) => r.s.sample),
                        unit.trim(),
                      ),
                    ),
                  )
                }
              >
                One biological unit
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  onDraft(
                    withItems(
                      draft,
                      unitItems(
                        free.map((r) => r.s.sample),
                        null,
                      ),
                    ),
                  )
                }
              >
                Each its own unit
              </Button>
            </div>
          </fieldset>
        </div>
        {withProposal.length ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-2.5 text-[13px] text-muted">
            <ListChecks className="size-4 text-info" aria-hidden />
            <span>
              {count(withProposal.length)} sample{withProposal.length === 1 ? " has" : "s have"} a
              group or unit proposed (from your sample sheet, or a model). Take what is proposed,
              then review it like any other change.
            </span>
            <Button
              size="sm"
              variant="secondary"
              className="ml-auto"
              onClick={() => {
                const items = [];
                const pick = selected.size
                  ? withProposal.filter((r) => selected.has(r.s.sample))
                  : withProposal;
                for (const r of pick) {
                  const p = proposed.get(r.s.sample)!;
                  if (p.group !== undefined) items.push(...groupItems([r.s.sample], p.group));
                  if (p.unit !== undefined) items.push(...unitItems([r.s.sample], p.unit));
                }
                onDraft(withItems(draft, items));
              }}
            >
              {selected.size ? "Take what is proposed for the selected" : "Take what is proposed"}
            </Button>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select
          label="Show"
          value={show}
          onValueChange={setShow}
          options={SHOW.map((o) => ({ value: o.value, label: o.label }))}
          size="sm"
          className="w-56"
        />
        <span className="text-xs text-muted">
          {count(shown.length)} of {count(rows.length)} samples · Shift-click selects a range ·
          ⌘/Ctrl-A selects every one shown
        </span>
      </div>
      <div
        className="max-h-[28rem] overflow-auto rounded-lg border border-line qp-scroll"
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
            e.preventDefault();
            onSelect(new Set([...selected, ...shown.map((r) => r.s.sample)]));
          }
        }}
      >
        <Table caption="Samples, their wells and the design so far">
          <THead>
            <TR>
              <TH className="w-8">
                <input
                  type="checkbox"
                  aria-label="Select every sample shown"
                  checked={shown.length > 0 && shown.every((r) => selected.has(r.s.sample))}
                  onChange={(e) =>
                    onSelect(
                      e.target.checked
                        ? new Set([...selected, ...shown.map((r) => r.s.sample)])
                        : new Set(
                            [...selected].filter((s) => !shown.some((r) => r.s.sample === s)),
                          ),
                    )
                  }
                  className="size-4 accent-[var(--accent)]"
                />
              </TH>
              <TH>Sample</TH>
              <TH>Wells</TH>
              <TH>Type</TH>
              <TH>Group</TH>
              <TH>Biological unit</TH>
            </TR>
          </THead>
          <TBody>
            {shown.map((r, index) => {
              const on = selected.has(r.s.sample);
              const p = proposed.get(r.s.sample);
              return (
                <TR key={r.s.sample} className={on ? "bg-accent-soft/40" : undefined}>
                  <TD>
                    <input
                      type="checkbox"
                      aria-label={`Select sample ${r.name}`}
                      checked={on}
                      onClick={(e) => {
                        e.preventDefault();
                        toggle(index, e);
                      }}
                      onChange={() => undefined}
                      className="size-4 accent-[var(--accent)]"
                    />
                  </TD>
                  <TD className="max-w-[14rem]">
                    <button
                      type="button"
                      className="block max-w-full truncate text-left font-mono text-[12.5px] text-fg hover:underline"
                      title={r.name === r.s.sample ? r.name : `${r.name} (${r.s.sample})`}
                      onClick={(e) => toggle(index, e)}
                    >
                      {r.name}
                    </button>
                  </TD>
                  <TD
                    className="max-w-[10rem] truncate font-mono text-xs text-muted"
                    title={wellsText(r.s)}
                  >
                    {wellsText(r.s)}
                  </TD>
                  <TD>
                    <span title={ROLE_WORDS[r.now.role] ?? r.now.role}>
                      {ROLE_SHORT[r.now.role] ?? r.now.role}
                      {r.now.role === "std" && r.now.quantity != null ? (
                        <span className="ml-1 font-mono text-xs text-muted">
                          {r.now.quantity.toPrecision(3)}
                        </span>
                      ) : null}
                    </span>
                    {r.now.changed.has("role") ? <Changed /> : null}
                  </TD>
                  <TD>
                    {r.now.group ?? <span className="text-faint">—</span>}
                    {r.now.changed.has("group") ? <Changed /> : null}
                    {!r.now.changed.has("group") &&
                    p?.group !== undefined &&
                    p.group !== r.now.group ? (
                      <span className="ml-1 text-xs text-info">proposed: {p.group ?? "none"}</span>
                    ) : null}
                  </TD>
                  <TD>
                    {r.now.unit ?? <span className="text-faint">its own</span>}
                    {r.now.changed.has("unit") ? <Changed /> : null}
                    {!r.now.changed.has("unit") &&
                    p?.unit !== undefined &&
                    p.unit !== r.now.unit ? (
                      <span className="ml-1 text-xs text-info">proposed: {p.unit ?? "own"}</span>
                    ) : null}
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </div>
    </div>
  );
}

function Changed() {
  return (
    <span className="ml-1.5 inline-flex align-middle" title="Not recorded yet">
      <CircleDot className="size-3 text-accent" aria-label="not recorded yet" />
    </span>
  );
}

function nameOf(s: EditorSample, quotes: QuoteLookup): string {
  const q = s.text_id ? quotes(s.text_id) : null;
  return q ? visibleText(q.value).slice(0, 80) : s.sample;
}

function wellsText(s: EditorSample): string {
  const runs = new Set(s.wells.map((w) => w.split("/")[0]));
  const labels = s.wells.map((w) => (runs.size > 1 ? w : (w.split("/").pop() ?? w)));
  return labels.slice(0, 8).join(" ") + (labels.length > 8 ? ` +${labels.length - 8}` : "");
}
