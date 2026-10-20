import type { SectionProps } from "@/shell/sections";
import { SectionPending } from "@/shell/SectionPending";

/** The "report" section (owner: agent report, see docs/app.md §7). */
export default function Section(_: SectionProps) {
  return <SectionPending id="report" />;
}
