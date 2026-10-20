/** Example questions for the open study, from its results (gene names are the study's own). */
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { ApiError, type Schemas } from "@/api/client";
import { exampleQuestions, type Example, type ExampleInput, type GeneLine } from "./examples";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function conclusionOf(value: unknown): GeneLine["conclusion"] {
  return value === "up" || value === "down" ? value : "none";
}

function share(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The genes, their calls and how often each call holds, and the reference genes, from the results view. */
export function readResults(body: unknown): Pick<ExampleInput, "genes" | "references"> {
  const genes: GeneLine[] = [];
  const references: string[] = [];
  if (!isRecord(body)) return { genes, references };
  const list = Array.isArray(body.genes) ? body.genes : [];
  for (const g of list) {
    if (!isRecord(g)) continue;
    const name =
      typeof g.gene === "string" ? g.gene : typeof g.target === "string" ? g.target : null;
    if (!name) continue;
    const robustness = isRecord(g.robustness) ? g.robustness : {};
    genes.push({
      gene: name,
      conclusion: conclusionOf(g.conclusion),
      holds:
        share(g.holds) ??
        share(g.holds_fraction) ??
        share(robustness.holds) ??
        share(robustness.holds_fraction),
    });
  }
  const summary = isRecord(body.summary) ? body.summary : {};
  for (const source of [summary.reference_genes, summary.references, body.reference_genes]) {
    if (Array.isArray(source)) {
      for (const r of source) {
        const name =
          typeof r === "string" ? r : isRecord(r) && typeof r.gene === "string" ? r.gene : null;
        if (name && !references.includes(name)) references.push(name);
      }
    }
  }
  return { genes, references };
}

async function fetchResults(studyId: string): Promise<unknown> {
  const response = await fetch(`/api/studies/${encodeURIComponent(studyId)}/results`, {
    credentials: "same-origin",
  });
  if (!response.ok)
    throw new ApiError(
      response.status,
      `http_${response.status}`,
      "The results could not be read.",
    );
  return response.json();
}

/** Up to four questions worth asking; study-level questions while the results are loading. */
export function useExamples(workspace: Schemas["WorkspaceView"] | null): {
  examples: Example[];
  loading: boolean;
} {
  const studyId = workspace?.study_id ?? null;
  const visible = Boolean(workspace?.results_visible && studyId);
  const results = useQuery({
    queryKey: ["w", workspace?.key, "ask", "examples", studyId],
    enabled: visible,
    queryFn: () => fetchResults(studyId!),
    select: readResults,
    staleTime: 5 * 60_000,
  });
  const hasAudit = Boolean(workspace?.has_audit);
  const examples = useMemo(
    () =>
      exampleQuestions({
        genes: results.data?.genes ?? [],
        references: results.data?.references ?? [],
        hasAudit,
      }),
    [results.data, hasAudit],
  );
  return { examples, loading: visible && results.isPending };
}
