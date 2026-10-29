/**
 * The reference genes under two rankings (docs/app.md §4 Results): geNorm M next to NormFinder's
 * stability value, both best pairs, and whether they agree, in plain words. Read from
 * `GET /api/studies/{id}/references` (qpilot/web/routers/references.py), the engine's numbers.
 * It never changes which reference genes are used: that stays a person's choice on the
 * reference-gene card.
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { cn } from "@/lib/cn";
import { count, fixed } from "@/lib/format";
import { Badge, ErrorPanel, Skeleton, Table, TBody, TD, TH, THead, TR, type Tone } from "@/ui";

const getReferences = (study_id: string) =>
  unwrap(api.GET("/api/studies/{study_id}/references", { params: { path: { study_id } } }));

export type ReferencesView = Awaited<ReturnType<typeof getReferences>>;

export function useReferences(key: string, studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["w", key, "references", studyId],
    enabled: Boolean(studyId),
    queryFn: () => getReferences(studyId as string),
    staleTime: Infinity, // a study's numbers never change
    retry: false,
  });
}

/** The verdict as a badge: the words carry the detail. */
export const VERDICT: Record<ReferencesView["verdict"], { word: string; tone: Tone }> = {
  agree: { word: "Same best pair", tone: "ok" },
  share_one: { word: "Best pairs share one gene", tone: "warn" },
  disagree: { word: "Different best pairs", tone: "warn" },
  not_available: { word: "NormFinder not available", tone: "neutral" },
};

function rank(value: number | null | undefined): string {
  return value == null ? "—" : `${value}`;
}

/** geNorm M and NormFinder's stability side by side, with the plain recommendation. */
export function ReferenceComparisonView({ view }: { view: ReferencesView }) {
  const verdict = VERDICT[view.verdict];
  const groups = Object.entries(view.groups ?? {});
  const tied = view.genorm_pair?.genes ?? [];
  return (
    <div className="space-y-3 text-[13px]" data-testid="reference-comparison">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">geNorm and NormFinder side by side</h3>
        <Badge tone={verdict.tone}>{verdict.word}</Badge>
      </div>
      <p className="text-fg">{view.words}</p>
      {view.rows.length ? (
        <div
          className="overflow-x-auto rounded-lg border border-line"
          tabIndex={0}
          role="region"
          aria-label="geNorm and NormFinder, gene by gene"
        >
          <Table caption="Each candidate reference gene under geNorm and NormFinder (lower is steadier)">
            <THead>
              <TR>
                <TH>Gene</TH>
                <TH numeric>geNorm M</TH>
                <TH numeric>geNorm rank</TH>
                <TH numeric>NormFinder</TH>
                <TH numeric>NormFinder rank</TH>
                <TH>In use</TH>
              </TR>
            </THead>
            <TBody>
              {view.rows.map((r) => (
                <TR key={r.gene}>
                  <TD className="font-medium">{r.gene}</TD>
                  <TD numeric>{r.genorm_m == null ? "—" : fixed(r.genorm_m, 2)}</TD>
                  <TD numeric>
                    {rank(r.genorm_rank)}
                    {tied.includes(r.gene) ? (
                      <span className="text-muted"> (best pair)</span>
                    ) : null}
                  </TD>
                  <TD numeric>{r.normfinder == null ? "—" : fixed(r.normfinder, 3)}</TD>
                  <TD numeric>{rank(r.normfinder_rank)}</TD>
                  <TD className={cn(r.used ? "text-fg" : "text-muted")}>{r.used ? "Yes" : "No"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      ) : null}
      <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
        {view.genorm_pair ? (
          <>
            <dt className="text-muted">geNorm&apos;s best pair</dt>
            <dd className="text-fg">
              {view.genorm_pair.genes.join(" and ")}
              <span className="text-muted"> (geNorm cannot order its last two genes)</span>
            </dd>
          </>
        ) : null}
        {view.normfinder_pair ? (
          <>
            <dt className="text-muted">NormFinder&apos;s best pair</dt>
            <dd className="text-fg">
              {view.normfinder_pair.genes.join(" and ")}
              {view.normfinder_pair.value != null ? (
                <span className="text-muted">
                  {" "}
                  (stability value {fixed(view.normfinder_pair.value, 3)})
                </span>
              ) : null}
            </dd>
          </>
        ) : null}
        {view.normfinder_pair ? (
          <>
            <dt className="text-muted">Groups NormFinder used</dt>
            <dd className="text-fg">
              {view.grouped
                ? groups.map(([g, n]) => `${g} (${count(n)})`).join(", ")
                : "none: every unit as one group, so only the variation within it counts"}
            </dd>
          </>
        ) : null}
      </dl>
      <p className="text-xs text-muted">
        geNorm M is the mean spread of a gene&apos;s ratio to every other candidate across all
        samples. NormFinder&apos;s stability value is the error a gene would bring into the
        normalisation, from its spread within each group and its shift between the groups. Lower is
        steadier in both.
      </p>
      {view.n_left_out ? (
        <p className="text-xs text-muted">
          NormFinder left out {count(view.n_left_out)} {view.n_left_out === 1 ? "unit" : "units"}:{" "}
          {Object.entries(view.left_out_reasons ?? {})
            .map(([why, n]) => `${why} (${count(n)})`)
            .join("; ")}
          .
        </p>
      ) : null}
      {(view.warnings ?? []).map((w) => (
        <p key={w} className="text-xs text-muted">
          {w.charAt(0).toUpperCase() + w.slice(1)}.
        </p>
      ))}
      <p className="text-xs font-medium text-fg">{view.choice_note}</p>
    </div>
  );
}

export function ReferenceComparison({
  workspaceKey,
  studyId,
}: {
  workspaceKey: string;
  studyId: string;
}) {
  const q = useReferences(workspaceKey, studyId);
  if (q.error) return <ErrorPanel error={q.error} title="NormFinder could not be shown" compact />;
  if (!q.data) return <Skeleton className="h-40 w-full rounded-lg" />;
  return <ReferenceComparisonView view={q.data} />;
}
