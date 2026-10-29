/**
 * The Design editor's draft: the design items a person has set on the page but not recorded
 * yet, and the pure helpers around it (what a sample or target is with the draft applied,
 * selection by name pattern, a pasted sample → group list). Nothing here talks to the server;
 * recording goes through `POST …/design/check` (shown first) and `POST …/design/set`.
 */
import type { Schemas } from "@/api/client";

export type EditItem = Schemas["DesignEditItem"];
export type EditKind = EditItem["kind"];
export type EditorView = Schemas["DesignEditorView"];
export type EditorSample = Schemas["EditorSample"];
export type EditorTarget = Schemas["EditorTarget"];

/** Draft items by `kind␀subject`; the last change to an item wins. */
export type Draft = ReadonlyMap<string, EditItem>;
export const EMPTY_DRAFT: Draft = new Map();

const keyOf = (kind: string, subject: string) => `${kind}\u0000${subject}`;
export const SERIES_NAME = "Standards set on the page";

/**
 * A person's group and unit names, kept as written ("LPS + inhibitor", "IL-6/ctrl", "Day 3 (50 µM)"):
 * any letters, digits, spaces and signs, at most 64 characters, no space first or last, and no
 * tab, line break or invisible character (the server's rule, `qpilot/core/names.py`).
 */
export const NAME_RE = /^(?!\s)(?!.*\s$)[^\p{C}\u2028\u2029]{1,64}$/u;
export const NAME_WORDS =
  "any letters, digits, spaces and signs, at most 64 characters, without tabs, line breaks or invisible characters";

export function withItems(draft: Draft, items: EditItem[]): Draft {
  const next = new Map(draft);
  for (const item of items) {
    const k = keyOf(item.kind, item.subject);
    next.delete(k);
    next.set(k, item);
  }
  return next;
}

export function withoutItem(draft: Draft, item: Pick<EditItem, "kind" | "subject">): Draft {
  const next = new Map(draft);
  next.delete(keyOf(item.kind, item.subject));
  return next;
}

export const targetRoleItem = (target: string, role: "ref" | "toi" | "ignore"): EditItem => ({
  kind: "design.target_role",
  subject: target,
  payload: { role },
});

export const groupItems = (samples: string[], group: string | null): EditItem[] =>
  samples.map((s) => ({ kind: "design.group", subject: s, payload: { group } }));

export const unitItems = (samples: string[], unit: string | null): EditItem[] =>
  samples.map((s) => ({ kind: "design.bio_unit", subject: s, payload: { biological_unit: unit } }));

export const comparisonItem = (groupA: string, groupB: string): EditItem => ({
  kind: "design.comparison",
  subject: "comparison",
  payload: { group_a: groupA, group_b: groupB },
});

/** The draft's standard series of one experiment (its samples and quantities). */
function seriesOf(draft: Draft, experiment: string | null): EditItem | undefined {
  for (const item of draft.values())
    if (item.kind === "design.dilution_series" && item.payload?.experiment_id === experiment)
      return item;
  return undefined;
}

function seriesSamples(item: EditItem | undefined): Record<string, number> {
  const s = item?.payload?.samples;
  return s && typeof s === "object" ? { ...(s as Record<string, number>) } : {};
}

/**
 * Give samples a type. Standards join the draft's standard series of their experiment with
 * their quantity; any other type takes them out of it and is a `design.well_role` item.
 */
export function withSampleType(
  draft: Draft,
  samples: { sample: string; experiment: string | null }[],
  role: string,
  quantities: Record<string, number> = {},
): Draft {
  let next = new Map(draft);
  const byExperiment = new Map<string | null, string[]>();
  for (const s of samples)
    byExperiment.set(s.experiment, [...(byExperiment.get(s.experiment) ?? []), s.sample]);
  for (const [experiment, names] of byExperiment) {
    const series = seriesOf(next, experiment);
    const members = seriesSamples(series);
    for (const name of names) {
      next.delete(keyOf("design.well_role", name));
      if (role === "std") members[name] = quantities[name]!;
      else delete members[name];
    }
    if (series) next.delete(keyOf(series.kind, series.subject));
    if (Object.keys(members).length) {
      const subject =
        series?.subject ??
        (byExperiment.size > 1 && experiment ? `${SERIES_NAME} (${experiment})` : SERIES_NAME);
      next.set(keyOf("design.dilution_series", subject), {
        kind: "design.dilution_series",
        subject,
        payload: { experiment_id: experiment, samples: members },
      });
    }
    if (role !== "std")
      next = new Map(
        withItems(
          next,
          names.map((name) => ({ kind: "design.well_role", subject: name, payload: { role } })),
        ),
      );
  }
  return next;
}

/** What a sample is with the draft applied (and which fields the draft changes). */
export interface SampleNow {
  role: string;
  quantity: number | null;
  group: string | null;
  unit: string | null;
  changed: Set<"role" | "group" | "unit">;
}

export function sampleNow(
  s: EditorSample,
  member: { group?: string | null; unit?: string | null } | undefined,
  draft: Draft,
): SampleNow {
  const out: SampleNow = {
    role: s.role,
    quantity: s.quantity ?? null,
    group: member?.group ?? null,
    unit: member?.unit ?? null,
    changed: new Set(),
  };
  const role = draft.get(keyOf("design.well_role", s.sample));
  if (role) {
    out.role = String(role.payload?.role);
    out.quantity = null;
    out.changed.add("role");
  }
  for (const item of draft.values()) {
    if (item.kind !== "design.dilution_series") continue;
    const q = seriesSamples(item)[s.sample];
    if (q !== undefined) {
      out.role = "std";
      out.quantity = q;
      out.changed.add("role");
    }
  }
  const group = draft.get(keyOf("design.group", s.sample));
  if (group) {
    out.group = (group.payload?.group as string | null) ?? null;
    out.changed.add("group");
  }
  const unit = draft.get(keyOf("design.bio_unit", s.sample));
  if (unit) {
    out.unit = (unit.payload?.biological_unit as string | null) ?? null;
    out.changed.add("unit");
  }
  return out;
}

export function targetNow(
  t: EditorTarget,
  draft: Draft,
): { role: string | null; changed: boolean } {
  const item = draft.get(keyOf("design.target_role", t.target));
  return item
    ? { role: String(item.payload?.role), changed: true }
    : { role: t.role ?? null, changed: false };
}

export function comparisonNow(view: EditorView, draft: Draft): Record<string, string> | null {
  const item = draft.get(keyOf("design.comparison", "comparison"));
  if (item) return (item.payload ?? {}) as Record<string, string>;
  return view.comparison ?? null;
}

/** Groups in use with the draft applied: name -> study samples in it. */
export function groupsNow(view: EditorView, draft: Draft): Map<string, number> {
  const out = new Map<string, number>();
  const members = new Map(view.membership.map((m) => [m.sample, m]));
  for (const s of view.samples) {
    const now = sampleNow(s, members.get(s.sample), draft);
    if (now.group && now.role === "unkn") out.set(now.group, (out.get(now.group) ?? 0) + 1);
  }
  return new Map([...out].sort(([a], [b]) => a.localeCompare(b)));
}

// ---------------------------------------------------------------------------------------------
// Names: matching what a person types or pastes to the file's samples

/** Lowercase, letters and digits only ("Sample ID*" -> "sampleid"), as the sheet reader does. */
export const squash = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

/** A lookup from a typed or pasted name to the sample it means (or null). */
export function sampleMatcher(
  samples: Pick<EditorSample, "sample" | "text_id">[],
  original: (textId: string | null | undefined) => string | null,
) {
  const exact = new Map<string, string>();
  const loose = new Map<string, Set<string>>();
  for (const s of samples) {
    const names = [s.sample, original(s.text_id)].filter((n): n is string => Boolean(n));
    for (const n of names) {
      if (!exact.has(n.trim())) exact.set(n.trim(), s.sample);
      const k = squash(n);
      if (k) loose.set(k, new Set([...(loose.get(k) ?? []), s.sample]));
    }
  }
  return (text: string): string | null => {
    const t = text.trim();
    const hit = exact.get(t);
    if (hit) return hit;
    const found = loose.get(squash(t));
    return found && found.size === 1 ? [...found][0]! : null;
  };
}

/**
 * Which names match a pattern: `*` and `?` are wildcards; without one the pattern matches
 * anywhere in the name; `/…/` is a regular expression. Case is ignored.
 */
export function patternTest(pattern: string): ((name: string) => boolean) | null {
  const p = pattern.trim();
  if (!p) return null;
  if (p.length > 2 && p.startsWith("/") && p.endsWith("/")) {
    try {
      const re = new RegExp(p.slice(1, -1), "i");
      return (name) => re.test(name);
    } catch {
      return null;
    }
  }
  if (/[*?]/.test(p)) {
    const body = p
      .split("")
      .map((ch) => (ch === "*" ? ".*" : ch === "?" ? "." : ch.replace(/[.+^${}()|[\]\\]/g, "\\$&")))
      .join("");
    const re = new RegExp(`^${body}$`, "i");
    return (name) => re.test(name);
  }
  const lower = p.toLowerCase();
  return (name) => name.toLowerCase().includes(lower);
}

// ---------------------------------------------------------------------------------------------
// A pasted sample -> group list (two columns from Excel; an optional third: the unit)

export interface PastedRow {
  line: number;
  text: string;
  sample: string | null;
  group: string | null;
  unit: string | null;
  problem: string | null;
}

const HEADER_WORDS = /^(sample|samples|sample ?name|sample ?id|name|tube|well)$/i;

export function parsePasted(text: string, match: (name: string) => string | null): PastedRow[] {
  const lines = text.split(/\r?\n/);
  const rows: PastedRow[] = [];
  const seen = new Map<string, number>();
  lines.forEach((raw, index) => {
    if (!raw.trim()) return;
    const cells = (raw.includes("\t") ? raw.split("\t") : raw.split(/[,;]/)).map((c) =>
      c.trim().replace(/^"(.*)"$/, "$1"),
    );
    const [name = "", group = "", unit = ""] = cells;
    if (index === 0 && HEADER_WORDS.test(name) && !match(name)) return; // a header row
    const sample = name ? match(name) : null;
    let problem: string | null = null;
    if (!name) problem = "no sample name in the first column";
    else if (!sample) problem = "no sample in this file has this name";
    else if (group && !NAME_RE.test(group)) problem = `a group name may use ${NAME_WORDS}`;
    else if (unit && !NAME_RE.test(unit)) problem = `a unit name may use ${NAME_WORDS}`;
    else if (!group && !unit) problem = "no group in the second column";
    if (sample && !problem) {
      const before = seen.get(sample);
      if (before !== undefined) problem = `this sample is already on line ${before}`;
      else seen.set(sample, index + 1);
    }
    rows.push({
      line: index + 1,
      text: raw.slice(0, 200),
      sample,
      group: group || null,
      unit: unit || null,
      problem,
    });
  });
  return rows;
}

/** The draft items of the usable pasted rows. */
export function pastedItems(rows: PastedRow[]): EditItem[] {
  const out: EditItem[] = [];
  for (const r of rows) {
    if (r.problem || !r.sample) continue;
    if (r.group) out.push(...groupItems([r.sample], r.group));
    if (r.unit) out.push(...unitItems([r.sample], r.unit));
  }
  return out;
}

/** A dilution series' quantities in plate order: the first `top`, each next one `/ step`. */
export function dilutionQuantities(samples: string[], top: number, step: number) {
  const out: Record<string, number> = {};
  samples.forEach((s, i) => {
    out[s] = Number((top / step ** i).toPrecision(6));
  });
  return out;
}

/** "B3" -> [row, column] (1-based), for plate order. */
export function wellOrder(key: string): [number, number] {
  const well = key.split("/").pop() ?? "";
  const m = /^([A-Z]+)(\d+)$/.exec(well);
  if (!m) return [Number.MAX_SAFE_INTEGER, 0];
  let row = 0;
  for (const ch of m[1]!) row = row * 26 + (ch.charCodeAt(0) - 64);
  return [row, Number(m[2])];
}

export function byPlateOrder(a: EditorSample, b: EditorSample): number {
  const [ra, ca] = wellOrder(a.wells[0] ?? "");
  const [rb, cb] = wellOrder(b.wells[0] ?? "");
  return ra - rb || ca - cb || a.sample.localeCompare(b.sample);
}
