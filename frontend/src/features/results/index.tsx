import type { SectionProps } from "@/shell/sections";
import { SectionPending } from "@/shell/SectionPending";

/** The "results" section (owner: see docs/app.md, "Who builds what"). */
export default function Section(_: SectionProps) {
  return <SectionPending id="results" />;
}
