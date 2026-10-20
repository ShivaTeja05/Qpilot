/**
 * The checked text, as written, with every claim's words underlined in its verdict's colour and a
 * marker (the verdict's shape) after each claim. Click a word or a marker, or Tab to a marker and
 * press Enter, to open that claim. Text only: the person's words are rendered as text.
 */
import { Fragment, useMemo, type CSSProperties } from "react";
import { Glyph } from "@/ui";
import { cn } from "@/lib/cn";
import type { ClaimView } from "./api";
import { CLAIM_VERDICT, markerAt, runs } from "./marks";

function tint(tone: string, percent: number): string {
  return `color-mix(in srgb, ${tone} ${percent}%, transparent)`;
}

export function Annotated({
  text,
  claims,
  selected,
  onSelect,
}: {
  text: string;
  claims: ClaimView[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const byId = useMemo(() => new Map(claims.map((c) => [c.id, c])), [claims]);
  const index = useMemo(() => new Map(claims.map((c, i) => [c.id, i + 1])), [claims]);
  const pieces = useMemo(() => {
    const all = runs(text, claims);
    const markers = new Map<number, ClaimView[]>();
    for (const c of claims) {
      const at = Math.min(markerAt(c), text.length);
      markers.set(at, [...(markers.get(at) ?? []), c]);
    }
    // cut the runs where a marker sits, so each marker follows the words it closes
    const out: { start: number; end: number; run: (typeof all)[number]; after: ClaimView[] }[] = [];
    for (const run of all) {
      let start = run.start;
      const cuts = [...markers.keys()]
        .filter((p) => p > run.start && p < run.end)
        .sort((a, b) => a - b);
      for (const cut of [...cuts, run.end]) {
        out.push({ start, end: cut, run, after: markers.get(cut) ?? [] });
        start = cut;
      }
    }
    return out;
  }, [text, claims]);

  return (
    <p className="text-[15px] leading-8 whitespace-pre-wrap text-fg break-words">
      {pieces.map((piece, i) => {
        const words = text.slice(piece.start, piece.end);
        const { run } = piece;
        const mine = selected != null && run.claims.includes(selected);
        const verdict = mine ? byId.get(selected!)!.verdict : run.verdict;
        const tone = verdict ? CLAIM_VERDICT[verdict].tone : null;
        const style: CSSProperties | undefined = tone
          ? {
              textDecorationLine: "underline",
              textDecorationColor: tone,
              textDecorationThickness: run.gene ? "3px" : "2px",
              textUnderlineOffset: "5px",
              backgroundColor: mine ? tint(tone, 16) : undefined,
            }
          : undefined;
        const first = run.claims[0];
        const label = run.claims
          .map((id) => byId.get(id))
          .filter((c): c is ClaimView => Boolean(c))
          .map((c) => `${CLAIM_VERDICT[c.verdict].label}: ${c.headline.plain}`)
          .join("\n");
        return (
          <Fragment key={i}>
            {first ? (
              <span
                style={style}
                title={label}
                className={cn("cursor-pointer rounded-[3px]", run.gene && "font-medium")}
                onClick={() => onSelect(mine ? selected! : first)}
              >
                {words}
              </span>
            ) : (
              words
            )}
            {piece.after.map((c) => {
              const meta = CLAIM_VERDICT[c.verdict];
              const on = c.id === selected;
              return (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={on}
                  aria-label={`Claim ${index.get(c.id)}${c.reading.gene ? ` about ${c.reading.gene}` : ""}: ${meta.label}`}
                  title={`${meta.label}: ${c.headline.plain}`}
                  onClick={() => onSelect(c.id)}
                  className={cn(
                    "mx-0.5 inline-flex h-5 min-w-5 -translate-y-px items-center justify-center rounded-md border align-middle transition-colors duration-150",
                    on
                      ? "border-line-strong bg-surface shadow-sm"
                      : "border-transparent hover:border-line",
                  )}
                >
                  <Glyph mark={meta} size={11} />
                </button>
              );
            })}
          </Fragment>
        );
      })}
    </p>
  );
}
