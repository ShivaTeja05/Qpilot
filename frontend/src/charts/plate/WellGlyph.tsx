/** One well drawn as a plate well: a disc whose fill, shape and marks follow the layer. */
import { memo } from "react";
import {
  CALL_STYLE,
  DISAGREE_COLOR,
  NUMERIC,
  callKey,
  isNumericLayer,
  position,
  rampColor,
  rampInk,
  roleStyle,
  type Domain,
  type PlateLayer,
  type PlateWell,
} from "./layers";

const C = 12;
const R = 8.6;

/** The well's mark under a layer (an empty position when `well` is null). */
export const WellGlyph = memo(function WellGlyph({
  well,
  layer,
  domain,
  size,
}: {
  well: PlateWell | null;
  layer: PlateLayer;
  domain: Domain | null;
  /** Fixed pixel size (legends); fills its box when omitted. */
  size?: number;
}) {
  const box = size ? { width: size, height: size } : { width: "100%", height: "100%" };
  if (!well) {
    return (
      <svg viewBox="0 0 24 24" {...box} aria-hidden="true" focusable="false">
        <circle
          cx={C}
          cy={C}
          r={R - 1}
          fill="none"
          style={{ stroke: "var(--line)" }}
          strokeWidth={1}
        />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" {...box} aria-hidden="true" focusable="false">
      <Body well={well} layer={layer} domain={domain} />
      {well.disagree ? (
        <circle
          cx={C}
          cy={C}
          r={11}
          fill="none"
          style={{ stroke: DISAGREE_COLOR }}
          strokeWidth={2.2}
        />
      ) : null}
      {well.personCall ? <path d="M15.5 1.5 H22.5 V8.5 Z" style={{ fill: "var(--text)" }} /> : null}
      {well.flagged ? <path d="M1.5 22.5 V15.5 H8.5 Z" style={{ fill: "var(--danger)" }} /> : null}
    </svg>
  );
});

function Body({
  well,
  layer,
  domain,
}: {
  well: PlateWell;
  layer: PlateLayer;
  domain: Domain | null;
}) {
  if (layer === "role") {
    const s = roleStyle(well.role);
    return (
      <>
        <circle cx={C} cy={C} r={R} style={{ fill: s.color }} />
        {s.letter ? (
          <text
            x={C}
            y={C}
            dy="0.36em"
            textAnchor="middle"
            fontSize={s.letter.length > 1 ? 6.6 : 10}
            fontWeight={650}
            style={{ fill: "var(--surface)", fontFamily: "var(--font-sans)" }}
          >
            {s.letter}
          </text>
        ) : null}
      </>
    );
  }
  if (layer === "call") {
    const k = callKey(well.amplified);
    const color = CALL_STYLE[k].color;
    if (k === "amplified") return <circle cx={C} cy={C} r={R} style={{ fill: color }} />;
    if (k === "not_amplified") {
      return (
        <>
          <circle
            cx={C}
            cy={C}
            r={R - 0.9}
            fill="none"
            style={{ stroke: color }}
            strokeWidth={1.8}
          />
          <path
            d="M8.6 8.6 L15.4 15.4 M15.4 8.6 L8.6 15.4"
            style={{ stroke: color }}
            strokeWidth={1.8}
            strokeLinecap="round"
          />
        </>
      );
    }
    return (
      <>
        <circle
          cx={C}
          cy={C}
          r={R - 0.9}
          fill="none"
          style={{ stroke: "var(--line-strong)" }}
          strokeWidth={1.2}
        />
        <path d="M8.5 12 H15.5" style={{ stroke: color }} strokeWidth={1.8} strokeLinecap="round" />
      </>
    );
  }
  if (isNumericLayer(layer)) {
    const v = NUMERIC[layer].get(well);
    if (v == null || !Number.isFinite(v) || !domain) {
      return (
        <circle
          cx={C}
          cy={C}
          r={R - 0.9}
          fill="none"
          style={{ stroke: "var(--text-faint)" }}
          strokeWidth={1.2}
          strokeDasharray="2.2 2"
        />
      );
    }
    const t = position(domain, v);
    return (
      <>
        <circle cx={C} cy={C} r={R} style={{ fill: rampColor(t) }} />
        {/* a hairline keeps the palest wells visible on the surface */}
        <circle
          cx={C}
          cy={C}
          r={R}
          fill="none"
          style={{ stroke: rampInk(t) === "var(--text)" ? "var(--line-strong)" : "transparent" }}
          strokeWidth={0.6}
        />
      </>
    );
  }
  return null;
}
