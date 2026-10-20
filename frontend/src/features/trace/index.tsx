import type { SectionProps } from "@/shell/sections";
import { SectionPending } from "@/shell/SectionPending";

/** The "trace" section (owner: agent trace, see docs/app.md §7). */
export default function Section(_: SectionProps) {
  return <SectionPending id="trace" />;
}
