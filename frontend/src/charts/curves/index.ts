/**
 * The curve viewer (owner: curves). Fluorescence by cycle for one or more wells on uPlot:
 * linear/log, the Cq marker and the baseline when known, neighbouring wells of the same sample
 * overlaid faint, light/dark, resizes, an accessible summary and "View as table".
 *
 *   <CurveViewer series={[{ id, label: "A1 · 1495", cycles, values, cq, role: "focus" }]}
 *                yLabel="Fluorescence (raw)" label="Well A1 of plate ODC1_20080226" />
 */
export { CurveViewer, type CurveViewerProps } from "./CurveViewer";
export { CurveTable } from "./CurveTable";
export { align, curvesSummary, type CurveScale, type CurveSeries } from "./data";
