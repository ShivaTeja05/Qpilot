import { SECTION, type SectionId } from "./sections";

/** Development only: a section whose screen is not built yet. Must not ship. */
export function SectionPending({ id }: { id: SectionId }) {
  const s = SECTION[id];
  return (
    <div className="mx-auto max-w-3xl p-10">
      <h1 className="text-2xl font-semibold tracking-tight">{s.label}</h1>
      <p className="mt-2 text-muted">{s.hint}</p>
      <p className="mt-6 rounded-lg border border-dashed border-line-strong p-4 text-sm text-muted">
        This section is being built.
      </p>
    </div>
  );
}
