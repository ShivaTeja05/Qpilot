/**
 * Melt curves (owner: melt). −dF/dT by temperature with each well's peaks and the assay's
 * expected melting temperature (rule G-MELT), from `/api/{sessions,studies}/…/melt`.
 *
 *   <MeltPanel sid={sid} run={run} wells={["A1"]} onPickWells={…} />   // the Curves stage
 *   const q = useMelt({ kind: "study", studyId }, plate, wells); <MeltCurves view={q.data} … />
 */
export { MAX_MELT_WELLS, useMelt, type MeltSource, type MeltView, type MeltWell } from "./api";
export { MeltChart, alignMelt, meltSummary, type MeltBand, type MeltSeries } from "./MeltChart";
export { CallChip, MeltCurves, MeltPanel, MeltWellsTable, bandOf, meltSeries } from "./MeltPanel";
export { STATUS_TONE, STATUS_WORD, assaySentence, celsius, delta } from "./words";
