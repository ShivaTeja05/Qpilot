import type { SectionProps } from "@/shell/sections";
import { SectionPending } from "@/shell/SectionPending";

/** The "history" section (owner: agent history, see docs/app.md §7). */
export default function Section(_: SectionProps) {
  return <SectionPending id="history" />;
}
