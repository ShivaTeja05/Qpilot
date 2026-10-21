/**
 * The Sheet check's state: the kept sheet, the latest check of it, the study it is compared
 * with, and what a person set (columns, reference genes). Every change re-checks: a changed
 * column or reference re-checks with `confirm: false` (the mapping is a guess again until a person
 * confirms it); **Confirm this mapping** sends the same choices with `confirm: true`. Only the
 * latest request's answer is shown; a failed check keeps the last answer on screen under its error.
 */
import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  checkBody,
  checkSheet,
  uploadSheet,
  type MappingChoice,
  type SheetCheckBody,
  type SheetCheckView,
  type SheetColumnView,
  type SheetRole,
  type SheetUploaded,
} from "./api";
import { roleHasGene } from "./words";

export type Step = "upload" | "check";

type Request =
  { step: "upload"; file: File } | { step: "check"; sheetId: string; body: SheetCheckBody };

const NO_CHOICE: MappingChoice = { columns: {}, references: null };

export interface SheetCheck {
  /** The kept sheet (once its upload is in). */
  sheet: SheetUploaded | null;
  /** The name of the file being uploaded. */
  uploading: string | null;
  /** The latest check (kept on screen when a later one fails). */
  view: SheetCheckView | null;
  /** The guessed columns, as the sheet's first check answered them (before any change). */
  guess: SheetColumnView[] | null;
  studyId: string | null;
  choice: MappingChoice;
  /** What is running now. */
  busy: Step | null;
  /** The latest request's failure, and which step failed. */
  error: { step: Step; error: unknown } | null;
  /** The role a column shows: the person's choice, else the latest check's. */
  roleOf: (column: string) => SheetRole | undefined;
  start: (file: File) => void;
  setStudy: (studyId: string | null) => void;
  setRole: (column: string, role: SheetRole) => void;
  setReferences: (references: string[] | null) => void;
  confirm: () => void;
  retry: () => void;
  reset: () => void;
}

export function useSheetCheck(): SheetCheck {
  const [sheet, setSheet] = useState<SheetUploaded | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [view, setView] = useState<SheetCheckView | null>(null);
  const [guess, setGuess] = useState<SheetColumnView[] | null>(null);
  const [studyId, setStudyId] = useState<string | null>(null);
  const [choice, setChoice] = useState<MappingChoice>(NO_CHOICE);
  const [error, setError] = useState<{ step: Step; error: unknown } | null>(null);
  const last = useRef<Request | null>(null);

  const upload = useMutation({ mutationFn: uploadSheet });
  const check = useMutation({
    mutationFn: ({ sheetId, body }: { sheetId: string; body: SheetCheckBody }) =>
      checkSheet(sheetId, body),
  });

  const runCheck = (sheetId: string, body: SheetCheckBody) => {
    // An answer to a check with nothing set is the guess itself.
    const untouched = !body.columns?.length && !body.references;
    last.current = { step: "check", sheetId, body };
    setError(null);
    check.mutate(
      { sheetId, body },
      {
        onSuccess: (answer) => {
          setView(answer);
          if (untouched) setGuess((g) => g ?? answer.mapping.columns);
        },
        onError: (e) => setError({ step: "check", error: e }),
      },
    );
  };

  const runUpload = (file: File, study: string | null) => {
    last.current = { step: "upload", file };
    setError(null);
    setUploading(file.name);
    upload.mutate(file, {
      onSuccess: (kept) => {
        setUploading(null);
        setSheet(kept);
        runCheck(kept.sheet_id, checkBody(study, NO_CHOICE, false));
      },
      onError: (e) => {
        setUploading(null);
        setError({ step: "upload", error: e });
      },
    });
  };

  const start = (file: File) => {
    check.reset(); // an answer about the previous sheet is no longer wanted
    setSheet(null);
    setView(null);
    setGuess(null);
    setChoice(NO_CHOICE);
    runUpload(file, studyId);
  };

  const recheck = (next: MappingChoice, confirm: boolean, study = studyId) => {
    setChoice(next);
    if (sheet) runCheck(sheet.sheet_id, checkBody(study, next, confirm));
  };

  const roleOf = (column: string): SheetRole | undefined =>
    choice.columns[column]?.role ?? view?.mapping.columns.find((c) => c.column === column)?.role;

  return {
    sheet,
    uploading,
    view,
    guess,
    studyId,
    choice,
    busy: upload.isPending ? "upload" : check.isPending ? "check" : null,
    error,
    roleOf,
    start,
    setStudy: (id) => {
      setStudyId(id);
      // A comparison does not change the mapping: a confirmed mapping stays confirmed.
      recheck(choice, Boolean(view?.mapping.confirmed), id);
    },
    setRole: (column, role) => {
      const guessed = guess?.find((c) => c.column === column);
      const shown = view?.mapping.columns.find((c) => c.column === column);
      const columns = { ...choice.columns };
      if (guessed && guessed.role === role) {
        delete columns[column]; // back to the guess
      } else {
        const gene = roleHasGene(role) ? (shown?.gene ?? guessed?.gene ?? null) : null;
        columns[column] = gene ? { column, role, gene } : { column, role };
      }
      recheck({ ...choice, columns }, false);
    },
    setReferences: (references) => recheck({ ...choice, references }, false),
    confirm: () => recheck(choice, true),
    retry: () => {
      const r = last.current;
      if (!r) return;
      if (r.step === "upload") runUpload(r.file, studyId);
      else runCheck(r.sheetId, r.body);
    },
    reset: () => {
      last.current = null;
      upload.reset();
      check.reset();
      setSheet(null);
      setUploading(null);
      setView(null);
      setGuess(null);
      setChoice(NO_CHOICE);
      setError(null);
    },
  };
}
