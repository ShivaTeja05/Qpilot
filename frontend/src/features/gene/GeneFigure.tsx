/**
 * The Gene section's "Figure" panel: this gene's figure for a lab meeting or a paper, drawn by
 * the server from the engine's numbers (`GET /api/studies/{id}/report/figure/info` and
 * `…/report/figure?format=svg|png|csv`, exports' `qpilot/report/figures.py`).
 *
 * Each dot is one biological unit (never a technical replicate), the bar the group mean with its
 * 95 % confidence interval, and the engine's call above the groups; the caption is built from the
 * engine's facts. The figure follows the options chosen on the Decision Cards ("As decided");
 * when those are not the recommended ones, a switch shows the recommended analysis instead. The
 * preview is the SVG itself; the downloads are the editable SVG, a 300-dpi PNG and the data behind
 * the figure (CSV).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { api, ApiError, unwrap, type Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { fold, pValue } from "@/lib/format";
import {
  Button,
  ConclusionTag,
  CopyButton,
  ErrorPanel,
  SegmentedControl,
  Select,
  Skeleton,
} from "@/ui";
import { Panel } from "./Panel";

export type FigureInfo = Schemas["FigureInfo"];
export type FigureBasis = FigureInfo["basis"];

const BASIS_LABEL: Record<FigureBasis, string> = {
  as_decided: "As decided",
  recommended: "Recommended",
};

/** `GET /api/studies/{id}/report/figure/info` for one gene (key under `["w", key]`: live events refresh it). */
export function useGeneFigure(
  workspaceKey: string,
  studyId: string | null,
  gene: string,
  basis: FigureBasis,
  comparison: string | null,
) {
  return useQuery({
    queryKey: ["w", workspaceKey, studyId, "figure", gene, basis, comparison],
    enabled: Boolean(studyId && gene),
    placeholderData: keepPreviousData, // switching the analysis keeps the figure until the next
    // The server reads the file once after it starts (503 `warming`): ask again until it is done.
    retry: (n, error) => (error instanceof ApiError ? error.code === "warming" && n < 40 : n < 2),
    retryDelay: (n) => Math.min(1000 * 2 ** n, 3000),
    queryFn: () =>
      unwrap(
        api.GET("/api/studies/{study_id}/report/figure/info", {
          params: {
            path: { study_id: studyId! },
            query: { gene, basis, ...(comparison ? { comparison } : {}) },
          },
        }),
      ),
  });
}

/** A file link that saves the file (the server names it). */
export function fileHref(url: string, head: string, download: boolean): string {
  return `${url}&v=${encodeURIComponent(head.slice(0, 12))}${download ? "&download=true" : ""}`;
}

/** The figure's alternative text: what it shows, in numbers. */
export function figureAlt(info: FigureInfo): string {
  const groups = info.groups.map((g) => `${g.name} (n = ${g.n})`).join(" and ");
  const call =
    info.call === null
      ? "not compared"
      : `${info.call === "none" ? "no call" : info.call}, ${fold(info.fold_change)}, ${info.p_adjusted != null ? `corrected p ${pValue(info.p_adjusted)}` : `p ${pValue(info.p)}`}`;
  return `${info.gene}: log2 relative quantity of each biological unit in ${groups}, with each group's mean and 95 % confidence interval; ${call}.`;
}

export function GeneFigure({
  workspace,
  studyId,
  gene,
  comparison: shown,
}: {
  workspace: Pick<Schemas["WorkspaceView"], "key">;
  studyId: string | null;
  gene: string;
  /** The comparison the page shows (its id; the figure follows it), when the page picks one. */
  comparison?: string | null;
}) {
  const [basis, setBasis] = useState<FigureBasis>("as_decided");
  const [own, setComparison] = useState<string | null>(null);
  const controlled = shown !== undefined;
  const comparison = controlled ? shown : own;
  const q = useGeneFigure(workspace.key, studyId, gene, basis, comparison);
  if (!studyId) return null;
  const info = q.data;
  return (
    <Panel
      id="gene-figure"
      title="Figure"
      hint="For a lab meeting or a paper: each dot is one biological unit, the bar its group's mean with the 95 % confidence interval."
    >
      {q.error ? (
        <ErrorPanel
          compact
          title="No figure for this gene"
          error={q.error}
          onRetry={() => void q.refetch()}
        />
      ) : !info ? (
        <div role="status" aria-label={`Drawing ${gene}'s figure`}>
          <Skeleton className="aspect-[260/300] w-full rounded-lg" />
        </div>
      ) : (
        <FigureBody
          info={info}
          busy={q.isFetching}
          onBasis={setBasis}
          onComparison={controlled ? undefined : (c) => setComparison(c)}
        />
      )}
    </Panel>
  );
}

export function FigureBody({
  info,
  busy = false,
  onBasis,
  onComparison,
}: {
  info: FigureInfo;
  busy?: boolean;
  onBasis: (b: FigureBasis) => void;
  /** Pick the comparison here (none: the page's own picker chooses it). */
  onComparison?: (c: string) => void;
}) {
  const head = info.chain_head;
  const pickHere = Boolean(onComparison) && info.comparisons.length > 1;
  return (
    <div className={cn("flex flex-col gap-3", busy && "opacity-70")} aria-busy={busy}>
      {info.bases.length > 1 || pickHere ? (
        <div className="flex flex-wrap items-center gap-2">
          {info.bases.length > 1 ? (
            <SegmentedControl
              size="sm"
              label="Which analysis the figure shows"
              value={info.basis}
              onValueChange={(v) => onBasis(v)}
              options={info.bases.map((b) => ({
                value: b,
                label: BASIS_LABEL[b],
                title:
                  b === "as_decided"
                    ? "The options chosen on the Decision Cards"
                    : "Every Decision Card at its recommended option",
              }))}
            />
          ) : null}
          {pickHere && onComparison ? (
            <Select
              size="sm"
              label="Comparison"
              value={info.comparison}
              onValueChange={onComparison}
              options={info.comparisons.map((c) => ({ value: c, label: c }))}
            />
          ) : null}
        </div>
      ) : null}
      <figure className="flex flex-col gap-2">
        <img
          src={fileHref(info.files.svg, head, false)}
          alt={figureAlt(info)}
          className="w-full max-w-[420px] rounded-lg border border-line bg-white"
          width={260}
          height={300}
        />
        <figcaption className="text-[12.5px] leading-relaxed text-muted">
          <span className="mb-1 flex flex-wrap items-center gap-2 text-fg">
            <span className="font-medium">{info.basis_label}</span>
            {info.call ? <ConclusionTag conclusion={info.call} compact /> : null}
            {info.call ? (
              <span className="font-mono text-[12px] tabular">
                {fold(info.fold_change)} ·{" "}
                {info.p_adjusted != null
                  ? `corrected p ${pValue(info.p_adjusted)}`
                  : `p ${pValue(info.p)}`}
              </span>
            ) : (
              <span>not compared</span>
            )}
          </span>
          {info.caption}
        </figcaption>
      </figure>
      <div className="flex flex-wrap gap-1.5">
        <CopyButton text={info.caption} label="Copy caption" showLabel />
        <FileButton href={fileHref(info.files.svg, head, true)} label="SVG" hint="editable" />
        <FileButton href={fileHref(info.files.png, head, true)} label="PNG" hint="300 dpi" />
        <FileButton href={fileHref(info.files.csv, head, true)} label="Data" hint="CSV" />
      </div>
    </div>
  );
}

function FileButton({ href, label, hint }: { href: string; label: string; hint: string }) {
  return (
    <Button asChild size="sm" variant="secondary">
      <a href={href} download aria-label={`Download the figure as ${label} (${hint})`}>
        <Download aria-hidden />
        {label}
        <span className="font-normal text-muted">{hint}</span>
      </a>
    </Button>
  );
}
