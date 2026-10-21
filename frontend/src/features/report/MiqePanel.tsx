/**
 * The MIQE 2.0 checklist: a ring of the items by status (a count, never a score), a filter by
 * status and words, and every item grouped by section with its evidence from the data.
 */
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import { Badge, EmptyState, Input, SegmentedControl } from "@/ui";
import type { Facts, MiqeItem, MiqeStatus, ReportView } from "./api";
import { Cited } from "./Cited";
import { MIQE, MIQE_ORDER } from "./words";

type Filter = MiqeStatus | "all";

export function MiqeRing({
  counts,
  size = 112,
}: {
  counts: Record<string, number>;
  size?: number;
}) {
  const total = MIQE_ORDER.reduce((n, s) => n + (counts[s] ?? 0), 0);
  const r = size / 2 - 9;
  const circ = 2 * Math.PI * r;
  let offset = 0;
  const label = MIQE_ORDER.map(
    (s) => `${count(counts[s] ?? 0)} ${MIQE[s].word.toLowerCase()}`,
  ).join(", ");
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`MIQE 2.0 items by status: ${label}.`}
      className="shrink-0"
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        strokeWidth={12}
        className="stroke-sunken"
      />
      {total
        ? MIQE_ORDER.map((s) => {
            const n = counts[s] ?? 0;
            if (!n) return null;
            const length = (n / total) * circ;
            const el = (
              <circle
                key={s}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                strokeWidth={12}
                className={MIQE[s].stroke}
                strokeDasharray={`${Math.max(length - 1.5, 0.5)} ${circ - Math.max(length - 1.5, 0.5)}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
              />
            );
            offset += length;
            return el;
          })
        : null}
      <text
        x="50%"
        y="47%"
        textAnchor="middle"
        className="fill-fg text-[20px] font-semibold tabular"
      >
        {count(counts.met ?? 0)}/{count(total)}
      </text>
      <text x="50%" y="63%" textAnchor="middle" className="fill-muted text-[11px]">
        met
      </text>
    </svg>
  );
}

export function MiqePanel({ miqe, facts }: { miqe: ReportView["miqe"]; facts: Facts }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return miqe.items.filter(
      (i) =>
        (filter === "all" || i.status === filter) &&
        (!q ||
          i.label.toLowerCase().includes(q) ||
          i.id.startsWith(q) ||
          (i.evidence?.plain.toLowerCase().includes(q) ?? false)),
    );
  }, [miqe.items, filter, query]);
  const sections = useMemo(() => {
    const out: { section: string; items: MiqeItem[] }[] = [];
    for (const item of shown) {
      const last = out[out.length - 1];
      if (last?.section === item.section) last.items.push(item);
      else out.push({ section: item.section, items: [item] });
    }
    return out;
  }, [shown]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-5 rounded-xl border border-line bg-surface p-4">
        <MiqeRing counts={miqe.counts} />
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <p className="text-[13.5px] leading-relaxed text-muted">
            <Cited text={miqe.headline} facts={facts} />
          </p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px]" aria-label="Items by status">
            {MIQE_ORDER.map((s) => (
              <li key={s} className="flex items-center gap-1.5 text-muted">
                <span className={cn("font-semibold", MIQE[s].text)} aria-hidden>
                  {MIQE[s].glyph}
                </span>
                {MIQE[s].word}{" "}
                <span className="tabular font-medium text-fg">{count(miqe.counts[s] ?? 0)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl<Filter>
          label="Show items"
          size="sm"
          value={filter}
          onValueChange={setFilter}
          options={[
            { value: "all", label: `All ${miqe.n_items}` },
            ...MIQE_ORDER.map((s) => ({
              value: s,
              label: `${MIQE[s].short} ${miqe.counts[s] ?? 0}`,
              disabled: !miqe.counts[s],
            })),
          ]}
        />
        <div className="relative min-w-[180px] flex-1 sm:max-w-[260px]">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint"
            aria-hidden
          />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find an item"
            aria-label="Find a MIQE item"
            className="h-7 pl-8 text-[13px]"
          />
        </div>
      </div>

      {sections.length === 0 ? (
        <EmptyState compact title="No item matches" headingLevel={3}>
          Clear the filter or the search to see every item.
        </EmptyState>
      ) : (
        sections.map(({ section, items }) => (
          <section key={section} aria-label={section}>
            <h3 className="mb-1.5 text-[12px] font-semibold tracking-wide text-muted uppercase">
              {section}
            </h3>
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
              {items.map((item) => (
                <Item key={item.id} item={item} facts={facts} />
              ))}
            </ul>
          </section>
        ))
      )}
      <p className="text-[12px] text-muted">
        Item list: {miqe.pack.citation} Items only a person can attest are never answered by qPilot.
      </p>
    </div>
  );
}

function Item({ item, facts }: { item: MiqeItem; facts: Facts }) {
  const s = MIQE[item.status];
  return (
    <li className="grid grid-cols-[2.75rem_minmax(0,1fr)] gap-x-2 px-4 py-3">
      <span className="pt-0.5 font-mono text-[12px] text-muted tabular">{item.id}</span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <p className="min-w-0 flex-1 basis-56 text-[13.5px] font-medium text-fg">{item.label}</p>
          <span className="flex flex-wrap gap-1.5">
            <Badge tone={s.tone}>
              <span aria-hidden>{s.glyph}</span> {s.word}
            </Badge>
            {item.attest ? <Badge tone="neutral">a person attests</Badge> : null}
          </span>
        </div>
        {item.evidence ? (
          <p className="mt-1 text-[13px] leading-relaxed text-muted">
            <Cited text={item.evidence} facts={facts} />
          </p>
        ) : null}
      </div>
    </li>
  );
}
