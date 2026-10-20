/**
 * The plate map (owner: curves). One plate, 96 or 384 wells, coloured by a layer (sample type,
 * amplification call, Cq, efficiency, R²), with a legend, shapes for calls, outlines where the
 * Curve Judge disagrees, a hover card, keyboard navigation, selection and a table view. Blind by
 * construction: a {@link PlateWell} has no group. Feed it from the API, never typed-in values.
 *
 *   <PlateMap wells={wells} layer="call" label="Plate ODC1_20080226"
 *             selected={sel} onSelectedChange={setSel} onActivate={openCurve} />
 */
export { PlateMap, type PlateMapProps } from "./PlateMap";
export { PlateLegend } from "./PlateLegend";
export { WellGlyph } from "./WellGlyph";
export {
  PLATE_LAYER_LABEL,
  layerOptions,
  numericDomain,
  plateSummary,
  roleStyle,
  wellSummary,
  type PlateLayer,
  type PlateWell,
} from "./layers";
export { compareWells, parseWell, plateShape, rowLetters, wellLabel, type PlateShape, type WellPosition } from "./geometry";
