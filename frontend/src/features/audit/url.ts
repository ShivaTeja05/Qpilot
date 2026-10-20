/**
 * The Audit section's place in the hash path: `…/audit` (Study), `…/audit/whatif`,
 * `…/audit/how`, `…/audit/verify`. The what-if lab's choices follow as one segment per changed
 * decision (`…/audit/whatif/late_cq=cq35/refs=HMBS`), so a set of choices is a link anyone can
 * open, and the page's `?token=…` is never touched. An attached results folder (`qpilot app
 * --audit DIR`) is shown under `…/audit/attached/<name>/…` with the same tabs.
 */
import type { Changes } from "./types";

export const TABS = ["study", "whatif", "how", "verify"] as const;
export type AuditTab = (typeof TABS)[number];

export interface AuditPlace {
  tab: AuditTab;
  changes: Changes;
  /** The attached folder shown instead of the study's own audit. */
  attached?: string;
}

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** The tab and the what-if choices from the path segments after `audit`. */
export function parsePlace(rest: string[]): AuditPlace {
  let segments = rest.map(decode);
  let attached: string | undefined;
  if (segments[0] === "attached" && segments[1]) {
    attached = segments[1];
    segments = segments.slice(2);
  }
  const [first, ...more] = segments;
  const tab = (TABS as readonly string[]).includes(first ?? "") ? (first as AuditTab) : "study";
  const changes: Changes = {};
  if (tab === "whatif") {
    for (const pair of more) {
      const at = pair.indexOf("=");
      if (at > 0 && at < pair.length - 1) changes[pair.slice(0, at)] = pair.slice(at + 1);
    }
  }
  return attached ? { tab, changes, attached } : { tab, changes };
}

/** The path segments after `audit` for a place (decisions in a stable order). */
export function placeSegments(
  { tab, changes, attached }: AuditPlace,
  order: readonly string[] = [],
): string[] {
  const prefix = attached ? ["attached", attached] : [];
  if (tab === "study") return prefix;
  if (tab !== "whatif") return [...prefix, tab];
  const rank = (d: string) => {
    const i = order.indexOf(d);
    return i < 0 ? order.length : i;
  };
  const ids = Object.keys(changes).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  return [...prefix, "whatif", ...ids.map((d) => `${d}=${changes[d]}`)];
}
