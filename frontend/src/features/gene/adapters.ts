/**
 * From api's GeneView to the charts' props and the section's lists: qPilot's own grid (every
 * analysis), one decision at a time, and the Decision Cards that move this gene. Raw numbers in,
 * nothing typed in.
 */
import { fmtFoldWords, type AnalysisDot, type ChoiceRow } from "@/charts";
import { CONCLUSION, asConclusion } from "@/lib/vocab";
import type { GeneCardRef, GeneView } from "./api";
import { DIMENSION } from "./words";

/** A grid option no card names, in words (qpilot/web/results_views.py option_label). */
export function optionWords(dimension: string, value: string): string {
  if (dimension === "refs") return value.split("|").join(" + ");
  if (dimension === "cut") {
    const f = Number(value);
    return Number.isFinite(f) ? `top ${Math.round(f * 100)} %` : value;
  }
  return value;
}

/** Each dimension's option labels by index (the cards' words where a card names the option). */
function optionLabels(view: Pick<GeneView, "grid" | "effects">): (dim: string, idx: number) => string {
  const byDim = new Map(view.effects.map((r) => [r.dimension, r]));
  return (dim, idx) => {
    const label = byDim.get(dim)?.options[idx]?.label ?? optionWords(dim, view.grid?.options[dim]?.[idx] ?? String(idx));
    const short = DIMENSION[dim]?.short;
    return short ? `${short}: ${label}` : label;
  };
}

const callWords = (call: string) => CONCLUSION[asConclusion(call)].long;

/** Every analysis in qPilot's grid for this gene, one dot each; the planned one marked. */
export function gridDots(view: Pick<GeneView, "grid" | "effects" | "row">): AnalysisDot[] {
  const g = view.grid;
  if (!g) return [];
  const label = optionLabels(view);
  const planned = asConclusion(view.row.conclusion);
  return g.cells.map((cell, k) => {
    const choices = cell.flatMap((idx, d) => (idx === g.planned[d] ? [] : [label(g.dimensions[d] ?? String(d), idx)]));
    const log2 = g.log2fc[k] ?? 0;
    const call = asConclusion(g.conclusion[k]);
    return {
      log2,
      call,
      same: call === planned,
      planned: choices.length === 0,
      choices,
      foldText: fmtFoldWords(log2),
      callText: callWords(call),
    };
  });
}

/** One decision at a time from qPilot's grid: each option with the others as planned. */
export function effectChoiceRows(view: Pick<GeneView, "effects" | "cards">): ChoiceRow[] {
  const cards = new Map(view.cards.map((c) => [c.card.id, c]));
  return view.effects
    .filter((r) => r.options.length > 0)
    .map((r) => {
      const card = r.card_id ? cards.get(r.card_id) : undefined;
      return {
        id: r.dimension,
        name: r.title,
        options: r.options.map((o) => {
          const shortcut = card?.options.find((c) => c.id === o.card_option)?.not_recommended;
          const log2 = o.log2fc[0] ?? 0;
          return {
            label: o.label,
            tier: shortcut ? "common_practice" : o.planned ? "prespecified" : "defensible",
            log2,
            call: asConclusion(o.conclusion[0]),
            changesCall: Boolean(o.flips[0]),
            planned: o.planned,
            foldText: fmtFoldWords(log2),
            callText: callWords(o.conclusion[0] ?? "none"),
          };
        }),
      };
    });
}

/**
 * The Decision Cards that move this gene: each card's decision row (can it flip the call alone,
 * how far it moves the fold), plus any card the server lists for it without a row. Cards that
 * can flip the call come first, then by how far they move it.
 */
export function geneCardRefs(view: Pick<GeneView, "gene" | "effects" | "cards">): GeneCardRef[] {
  const cards = new Map(view.cards.map((c) => [c.card.id, c]));
  const refs: GeneCardRef[] = [];
  for (const r of view.effects) {
    if (!r.card_id) continue;
    const card = cards.get(r.card_id);
    refs.push({
      id: r.card_id,
      title: card?.title ?? r.title,
      status: r.status ?? card?.card.status ?? "open",
      statusLine: card?.status_line ?? null,
      flips: Boolean(r.flips[0]),
      maxDeltaLog2: r.max_delta_log2fc[0] ?? null,
      chosenLabel: r.options.find((o) => o.chosen)?.label ?? card?.options.find((o) => o.chosen)?.label ?? null,
    });
  }
  for (const card of view.cards) {
    if (refs.some((r) => r.id === card.card.id)) continue;
    refs.push({
      id: card.card.id,
      title: card.title,
      status: card.card.status,
      statusLine: card.status_line,
      flips: card.options.some((o) => o.effects?.some((e) => e.gene === view.gene && e.changes_call)),
      maxDeltaLog2: null,
      chosenLabel: card.options.find((o) => o.chosen)?.label ?? null,
    });
  }
  return refs.sort(
    (a, b) => Number(b.flips) - Number(a.flips) || Math.abs(b.maxDeltaLog2 ?? 0) - Math.abs(a.maxDeltaLog2 ?? 0),
  );
}

/** A card's status in words: the server's line, else from its status. */
export function cardStatusWords(card: Pick<GeneCardRef, "status" | "statusLine" | "chosenLabel">): string {
  if (card.statusLine) return card.statusLine;
  switch (card.status) {
    case "decided":
      return card.chosenLabel ? `Decided: ${card.chosenLabel}` : "Decided";
    case "auto_decided":
      return card.chosenLabel ? `Decided automatically: ${card.chosenLabel}` : "Decided automatically";
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
