/** Example questions for the open study, from its results (gene names are the study's own). */
import { useMemo } from "react";
import type { Schemas } from "@/api/client";
import { useResults } from "@/features/results/api";
import { exampleQuestions, type Example, type ExampleInput, type GeneLine } from "./examples";

/** The fields of the results view the examples read (`GET /api/studies/{id}/results`). */
export interface ResultsForExamples {
  genes: { gene: string; conclusion: GeneLine["conclusion"]; holds?: number | null }[];
  references: { used: string[] };
}

/** The genes, their calls and how often each call holds, and the reference genes in use. */
export function readResults(
  view: ResultsForExamples | undefined,
): Pick<ExampleInput, "genes" | "references"> {
  return {
    genes: (view?.genes ?? []).map((g) => ({
      gene: g.gene,
      conclusion: g.conclusion,
      holds: g.holds ?? null,
    })),
    references: view?.references.used ?? [],
  };
}

/**
 * Up to four questions worth asking. Reads the same query as the Results section, so opening
 * Ask costs no extra request; study-level questions show while it loads or if it fails.
 */
export function useExamples(workspace: Schemas["WorkspaceView"] | null): {
  examples: Example[];
  loading: boolean;
} {
  const studyId = workspace?.results_visible ? (workspace.study_id ?? null) : null;
  const results = useResults(workspace?.key ?? "", studyId);
  const hasAudit = Boolean(workspace?.has_audit);
  const examples = useMemo(
    () => exampleQuestions({ ...readResults(results.data), hasAudit }),
    [results.data, hasAudit],
  );
  return { examples, loading: Boolean(studyId) && results.isPending };
}
