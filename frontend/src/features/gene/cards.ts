/** Which Decision Cards touch one gene, and how (from qPilot's own robustness grid). */
import type { CardLike, GeneCardRef, GeneView } from "./api";
import { KIND_DIMENSION } from "./words";

/**
 * The cards whose choice moves this gene, those that can flip its call first, then by how far
 * they move its fold. Uses the server's list when it sends one; otherwise joins the study's cards
 * with the gene's robustness impact (each card kind changes one decision dimension).
 */
export function cardsForGene(gene: Pick<GeneView, "cards" | "impact" | "flips_by">, cards: readonly CardLike[] | undefined): GeneCardRef[] {
  if (gene.cards) return sortCards(gene.cards);
  if (!cards) return [];
  const flipsBy = new Set(gene.flips_by ?? []);
  const out: GeneCardRef[] = [];
  for (const card of cards) {
    const dim = KIND_DIMENSION[card.kind];
    const impact = dim ? gene.impact?.[dim] : undefined;
    const flips = impact?.flips ?? (dim ? flipsBy.has(dim) : false);
    if (!impact && !flips) continue;
    const optionLabel = (id: string | null | undefined) => card.options?.find((o) => o.id === id)?.label ?? null;
    out.push({
      id: card.id,
      kind: card.kind,
      title: card.title ?? null,
      status: card.status,
      decision: card.decision ?? null,
      decision_label: optionLabel(card.decision),
      recommended: card.recommended ?? null,
      recommended_label: optionLabel(card.recommended),
      rank: card.rank ?? null,
      decided_by: card.decided_by ?? null,
      flips,
      max_delta_log2fc: impact?.max_delta_log2fc ?? null,
    });
  }
  return sortCards(out);
}

function sortCards(cards: readonly GeneCardRef[]): GeneCardRef[] {
  return [...cards].sort(
    (a, b) =>
      Number(Boolean(b.flips)) - Number(Boolean(a.flips)) ||
      (b.max_delta_log2fc ?? 0) - (a.max_delta_log2fc ?? 0) ||
      (a.rank ?? 99) - (b.rank ?? 99),
  );
}

/** A card's status in words (qpilot/schemas.py DecisionCard.status). */
export function cardStatusWords(card: Pick<GeneCardRef, "status" | "decision_label" | "decision" | "decided_by">): string {
  const chosen = card.decision_label ?? card.decision;
  switch (card.status) {
    case "decided":
      return chosen ? `Decided: ${chosen}` : "Decided";
    case "auto_decided":
      return chosen ? `Decided automatically: ${chosen}` : "Decided automatically";
    case "pending_human":
      return "An agent's request waits for a person";
    default:
      return "Waiting for your decision";
  }
}

/** A card waiting for a person. */
export function isOpen(card: Pick<GeneCardRef, "status">): boolean {
  return card.status === "open" || card.status === "pending_human";
}
