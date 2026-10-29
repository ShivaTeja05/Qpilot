/**
 * What the study is for: compare groups (the default) or quantify samples from a standard curve
 * (a viral load, wastewater, copies of a construct, a library). A person's design item
 * (`design.purpose`), recorded like every other change on this page. Quantify samples needs no
 * comparison and no reference gene; it needs standards with a quantity instead.
 */
import { FlaskConical } from "lucide-react";
import { count } from "@/lib/format";
import { SegmentedControl } from "@/ui";
import { type Draft, type EditItem, type EditorView } from "./draft";

export type Purpose = "compare" | "quantify";
const KEY = "design.purpose\u0000purpose";

export const purposeItem = (purpose: Purpose): EditItem => ({
  kind: "design.purpose",
  subject: "purpose",
  payload: { purpose },
});

/** The purpose with the draft applied. */
export function purposeNow(view: EditorView | undefined, draft: Draft): Purpose {
  const drafted = draft.get(KEY)?.payload?.purpose;
  if (drafted === "quantify" || drafted === "compare") return drafted;
  return view?.purpose === "quantify" ? "quantify" : "compare";
}

export function PurposePanel({
  view,
  draft,
  onDraft,
}: {
  view: EditorView;
  draft: Draft;
  onDraft: (next: Draft) => void;
}) {
  const now = purposeNow(view, draft);
  const options = view.purposes.length
    ? view.purposes
    : [
        { value: "compare", label: "Compare groups", hint: "" },
        { value: "quantify", label: "Quantify samples", hint: "" },
      ];
  const hint = options.find((o) => o.value === now)?.hint;
  const set = (value: Purpose) => {
    const next = new Map(draft);
    next.delete(KEY);
    if (value !== (view.purpose === "quantify" ? "quantify" : "compare"))
      next.set(KEY, purposeItem(value));
    onDraft(next);
  };
  const withQuantity = view.n_standards_with_quantity ?? 0;
  return (
    <section
      aria-labelledby="design-purpose"
      className="flex flex-col gap-2 rounded-lg border border-line bg-surface-2 px-3 py-3"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h3 id="design-purpose" className="text-[13px] font-semibold text-fg">
          What is this study for?
        </h3>
        <SegmentedControl<Purpose>
          label="What this study is for"
          size="sm"
          value={now}
          onValueChange={set}
          options={options.map((o) => ({
            value: o.value as Purpose,
            label: o.label,
            title: o.hint,
          }))}
        />
      </div>
      {hint ? <p className="text-[12.5px] text-muted">{hint}.</p> : null}
      {now === "quantify" ? (
        <p className="flex gap-2 text-[12.5px] text-fg" role="status">
          <FlaskConical className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
          <span>
            No comparison and no reference gene are needed (groups, if you set them, only sort the
            samples). Each sample&apos;s quantity is read from the standard curve:{" "}
            {view.n_standards ? (
              <>
                {count(view.n_standards)} standard sample{view.n_standards === 1 ? "" : "s"} on the
                plate, {count(withQuantity)} with a quantity
                {withQuantity < view.n_standards
                  ? "; give the others theirs on Samples (the highest quantity and the dilution step)"
                  : ""}
                .
              </>
            ) : (
              <>no standard yet: mark the dilution series on Samples (type Standard).</>
            )}
          </span>
        </p>
      ) : null}
    </section>
  );
}
