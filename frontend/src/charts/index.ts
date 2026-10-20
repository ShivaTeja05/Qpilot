/**
 * qPilot's science charts (owner: insight). SVG, responsive (ResizeObserver), tokens only, hover and
 * keyboard tooltips, `role="img"` with a summary, and "View as table" on every one. Feed them from
 * the API with the adapters at the bottom; never with typed-in numbers.
 */

/** Gene scatter: x fold change (log2, in ×), y share of analyses with the same call; marks by `MapPoint.mark`; click → `onSelect(gene)`. */
export { RobustnessMap, type MapPoint, type RobustnessMapProps } from "./RobustnessMap";
/** Every reasonable analysis of one gene as a stacked dot on the fold axis, by call; planned = accent diamond. Props: `rows: AnalysisDot[]`, `line`. */
export { AnalysesStrip, type AnalysisDot, type AnalysesStripProps } from "./AnalysesStrip";
/** One choice at a time: a row per decision, a dot per option on the fold axis; planned diamond, shortcuts hollow, call-changers ringed. */
export {
  ChoiceDotPlot,
  type ChoiceOption,
  type ChoiceRow,
  type ChoiceDotPlotProps,
} from "./ChoiceDotPlot";
/** Samples by group as a beeswarm with group means and the fold between them; late/no-Cq/flagged marks; click → `onSelectSample(point)`. */
export { Beeswarm, type SampleGroup, type SamplePoint, type BeeswarmProps } from "./Beeswarm";
/** What-if: planned → chosen fold per gene, changed calls first (`dumbbellOrder`); click → `onSelect(gene)`. */
export { Dumbbell, dumbbellOrder, type DumbbellRow, type DumbbellProps } from "./Dumbbell";
/** Decisions × genes heatmap: shade = a magnitude you give (`delta`, `shadeLabel`), cross = it alone flips the call; click → gene. */
export { FlipMatrix, flipOrder, type FlipCell, type FlipMatrixProps } from "./FlipMatrix";
/** geNorm M per candidate (with the M cut-off line) and V per step (with the V cut-off line). */
export { GenormBars, genormRows, type GenormBarsProps } from "./GenormBars";
/** Audit verdict counts: a proportional bar plus a tile per verdict (glyph, count, word, rule); tiles filter. */
export { VerdictStrip, type VerdictCount, type VerdictStripProps } from "./VerdictStrip";
/** Horizontal bars with value at the tip and an optional reference line (calls changed alone, share of spread). */
export { HBars, HBars as SpreadBars, barPath, type BarRow, type HBarsProps } from "./HBars";

// shared pieces for screens that sit next to the charts
export { ChartFrame, Legend, LineSwatch, type LegendItem } from "./core/ChartFrame";
export { DataTable, type Column } from "./core/DataTable";
export { Glyph, GlyphMark } from "./core/Glyph";
export {
  CALLS,
  CALL_ORDER,
  LEVELS,
  LEVEL_ORDER,
  VERDICTS,
  VERDICT_ORDER,
  TIER_WORDS,
  callKey,
  isLevel,
  isVerdict,
  type CallKey,
  type LevelKey,
  type Mark,
  type Shape,
  type VerdictKey,
} from "./core/encodings";
export * from "./core/format";
export { foldTickLabel } from "./core/fold";

// API view → chart props
export * from "./adapters";
