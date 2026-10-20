/**
 * Which audit the section shows: the study's own, or a results folder attached when the server
 * started (`qpilot app --audit DIR`), such as the Decision Simulator's benchmark run. Shown only
 * when something is attached.
 */
import { count } from "@/lib/format";
import { Select, type SelectOption } from "@/ui";
import type { AttachedAudit } from "./types";

const OWN = "__own__";

export function AuditSources({
  sources,
  studyId,
  value,
  onChange,
}: {
  sources: AttachedAudit[];
  studyId: string;
  /** The attached folder shown (none: the study's own audit). */
  value: string | undefined;
  onChange: (name: string | undefined) => void;
}) {
  if (!sources.length) return null;
  const options: SelectOption[] = [
    { value: OWN, label: "This study's audit" },
    ...sources.map((a) => ({
      value: a.name,
      label: `Attached: ${a.name}`,
      hint: !a.available
        ? (a.reason ?? "Cannot be shown")
        : a.qpilot_audit && a.study_id === studyId
          ? `An audit of this study (${a.source})`
          : a.qpilot_audit
            ? `An audit of another study (${a.source})`
            : `A Decision Simulator run of ${a.source}${a.analyses ? `, ${count(a.analyses)} analyses` : ""}`,
    })),
  ];
  return (
    <Select
      size="sm"
      label="Audit shown"
      className="min-w-[220px]"
      value={value ?? OWN}
      options={options}
      onValueChange={(v) => onChange(v === OWN ? undefined : v)}
    />
  );
}
