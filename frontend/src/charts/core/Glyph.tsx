/**
 * The marks' shapes, drawn centred on (0, 0): inside a chart (`GlyphMark`) and inline next to words
 * in legends, tags and tables (`Glyph`). Filled marks carry a ring in the surface colour so they
 * stay legible where they overlap.
 */
import type { CSSProperties } from "react";
import type { Mark, Shape } from "./encodings";

interface ShapeProps {
  shape: Shape;
  tone: string;
  r: number;
  /** The surface ring (charts: yes; inline icons: no). */
  ring?: boolean;
}

function ShapeBody({ shape, tone, r, ring = true }: ShapeProps) {
  const halo = ring ? { stroke: "var(--surface)", strokeWidth: 2, paintOrder: "stroke" as const } : {};
  const sw = Math.max(1.6, r * 0.32);
  switch (shape) {
    case "circle":
      return <circle r={r} fill={tone} {...halo} />;
    case "half":
      return (
        <g>
          {ring && <circle r={r + 1} fill="var(--surface)" />}
          <circle r={r - sw / 2} fill="none" stroke={tone} strokeWidth={sw} />
          <path d={`M0 ${-r} A${r} ${r} 0 0 0 0 ${r} Z`} fill={tone} />
        </g>
      );
    case "diamond": {
      const d = r * 1.18;
      return <path d={`M0 ${-d} L${d} 0 L0 ${d} L${-d} 0 Z`} fill={tone} {...halo} />;
    }
    case "triangle":
    case "up": {
      const h = r * 1.15;
      return <path d={`M0 ${-h} L${h} ${h * 0.8} L${-h} ${h * 0.8} Z`} fill={tone} {...halo} />;
    }
    case "down": {
      const h = r * 1.15;
      return <path d={`M0 ${h} L${h} ${-h * 0.8} L${-h} ${-h * 0.8} Z`} fill={tone} {...halo} />;
    }
    case "square-alert": {
      const s = r * 0.92;
      return (
        <g>
          <rect x={-s} y={-s} width={2 * s} height={2 * s} rx={s * 0.3} fill={tone} {...halo} />
          <rect x={-s * 0.14} y={-s * 0.62} width={s * 0.28} height={s * 0.72} fill="var(--surface)" />
          <rect x={-s * 0.14} y={s * 0.3} width={s * 0.28} height={s * 0.28} fill="var(--surface)" />
        </g>
      );
    }
    case "ring":
      return (
        <g>
          {ring && <circle r={r - sw / 2} fill="none" stroke="var(--surface)" strokeWidth={sw + 3} />}
          <circle r={r - sw / 2} fill="var(--surface)" fillOpacity={ring ? 0.6 : 0} stroke={tone} strokeWidth={sw} />
        </g>
      );
    case "dash": {
      const w = r * 1.25;
      const h = Math.max(2.4, r * 0.62);
      return <rect x={-w} y={-h / 2} width={2 * w} height={h} rx={h / 2} fill={tone} {...halo} />;
    }
    case "cross": {
      const c = r * 0.78;
      const d = `M${-c} ${-c} L${c} ${c} M${c} ${-c} L${-c} ${c}`;
      return (
        <g strokeLinecap="round">
          {ring && <path d={d} stroke="var(--surface)" strokeWidth={sw + 3} />}
          <path d={d} stroke={tone} strokeWidth={sw + 0.4} />
        </g>
      );
    }
  }
}

/** A mark inside a chart's SVG, centred on (x, y). */
export function GlyphMark({
  mark,
  x,
  y,
  r = 5,
  ring = true,
  style,
}: {
  mark: Pick<Mark, "shape" | "tone">;
  x: number;
  y: number;
  r?: number;
  ring?: boolean;
  style?: CSSProperties;
}) {
  return (
    <g transform={`translate(${x},${y})`} style={style}>
      <ShapeBody shape={mark.shape} tone={mark.tone} r={r} ring={ring} />
    </g>
  );
}

/** The mark as an inline icon beside its word (decorative: the word carries the meaning). */
export function Glyph({
  mark,
  size = 12,
  className,
}: {
  mark: Pick<Mark, "shape" | "tone">;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="-8 -8 16 16"
      aria-hidden="true"
      className={className}
      style={{ flex: "none", overflow: "visible" }}
    >
      <ShapeBody shape={mark.shape} tone={mark.tone} r={6.5} ring={false} />
    </svg>
  );
}
