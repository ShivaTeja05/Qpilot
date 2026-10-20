import type { SectionProps } from "@/shell/sections";
import { SectionPending } from "@/shell/SectionPending";

/** The "planner" section (owner: agent planner, see docs/app.md §7). */
export default function Section(_: SectionProps) {
  return <SectionPending id="planner" />;
}
