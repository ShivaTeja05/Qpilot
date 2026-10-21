/** The Design section's small pure helpers (which wells a proposal is about; the comparison). */
import type { Proposal } from "@/lib/vocab";
import type { PlateWell } from "./DesignPlate";

/** Does this proposal concern this well (its sample, its target, the well itself)? */
export function concerns(p: Proposal, w: Pick<PlateWell, "sample" | "target" | "key">): boolean {
  if (p.subject === w.sample || p.subject === w.target || p.subject === w.key) return true;
  if (p.kind === "design.dilution_series") {
    const samples = p.payload.samples;
    return Boolean(samples && typeof samples === "object" && w.sample in (samples as object));
  }
  return false;
}

/** Groups that a person accepted, and whether a comparison is still to be proposed. */
export function comparisonState(all: Proposal[]) {
  const settled = all.filter((p) => p.status === "accepted" || p.status === "edited");
  const groups = new Set(
    settled
      .filter((p) => p.kind === "design.group")
      .map((p) => String({ ...p.payload, ...(p.edits ?? {}) }.group)),
  );
  const has = all.some(
    (p) =>
      (p.kind === "design.comparison" || p.kind === "design.preset") &&
      p.status !== "rejected" &&
      p.status !== "superseded",
  );
  return { groups: [...groups], ready: groups.size === 2 && !has };
}
