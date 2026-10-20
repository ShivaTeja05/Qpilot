import type { SectionProps } from "@/shell/sections";
import { SectionPending } from "@/shell/SectionPending";

/** The "claims" section (owner: agent claims, see docs/app.md §7). */
export default function Section(_: SectionProps) {
  return <SectionPending id="claims" />;
}
