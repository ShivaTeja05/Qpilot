/**
 * The Spreadsheet Check routes (`qpilot/web/routers/sheets.py`): keep a sheet by content
 * (`POST /api/sheets`, multipart field `sheet`), then recompute it (`POST /api/sheets/{id}/check`).
 * Nothing is saved and the sheet is never edited; sheet labels never come back.
 */
import { api, postForm, unwrap, type Schemas } from "@/api/client";

export type SheetUploaded = Schemas["SheetUploaded"];
export type SheetCheckView = Schemas["SheetCheckView"];
export type SheetCheckBody = Schemas["SheetCheckBody"];
export type SheetColumnSet = Schemas["SheetColumnSet"];
export type SheetColumnView = Schemas["SheetColumnView"];
export type SheetColumnCheckView = Schemas["SheetColumnCheckView"];
export type SheetFindingView = Schemas["SheetFindingView"];
export type SheetHandOverView = Schemas["SheetHandOverView"];
export type SheetGeneView = Schemas["SheetGeneView"];
export type SheetRole = SheetColumnSet["role"];
export type FactText = Schemas["FactText"];

/** The largest sheet the server keeps (`MAX_SHEET_BYTES`). */
export const MAX_SHEET_BYTES = 5 * 1024 * 1024;
/** What the server keeps as a sheet (`views.INPUT_SUFFIXES["sheet"]`). */
export const SHEET_SUFFIXES = [".xlsx", ".csv"] as const;

/** Keep a sheet for checking (by content: the same file is kept once). */
export function uploadSheet(file: File): Promise<SheetUploaded> {
  const form = new FormData();
  form.append("sheet", file, file.name);
  return postForm<SheetUploaded>("/api/sheets", form);
}

/** Recompute a kept sheet (read-only: nothing is saved). */
export function checkSheet(sheetId: string, body: SheetCheckBody): Promise<SheetCheckView> {
  return unwrap(
    api.POST("/api/sheets/{sheet_id}/check", {
      params: { path: { sheet_id: sheetId } },
      body,
    }),
  );
}

/** What a person set: the columns they changed, the reference genes they named. */
export interface MappingChoice {
  /** Columns a person set, by letter (others keep the guess). */
  columns: Record<string, SheetColumnSet>;
  /** Reference genes a person named (null: the guess). */
  references: string[] | null;
}

/** The body of a check: the study to compare with, what a person set, and whether they confirm. */
export function checkBody(
  studyId: string | null,
  choice: MappingChoice,
  confirm: boolean,
): SheetCheckBody {
  const body: SheetCheckBody = { confirm };
  if (studyId) body.study_id = studyId;
  const columns = Object.values(choice.columns);
  if (columns.length) body.columns = columns;
  if (choice.references) body.references = choice.references;
  return body;
}
