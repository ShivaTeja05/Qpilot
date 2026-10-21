/**
 * The sheet to check and what to compare it with: a drop zone (or the kept sheet's row), the
 * study select (analysed studies whose results show), the step running now, and an error in the
 * server's own words. The page around it is the drop target.
 */
import { FileSpreadsheet, FileUp, RefreshCw } from "lucide-react";
import { useId, useRef, type ReactNode } from "react";
import { Button, Card, ErrorPanel, Field, ProgressBar, Select } from "@/ui";
import { cn } from "@/lib/cn";
import { NNBSP, bytes, count, plural } from "@/lib/format";
import type { WorkspaceSummary } from "@/shell/data";
import { MAX_SHEET_BYTES, SHEET_SUFFIXES } from "./api";
import type { SheetCheck } from "./useSheetCheck";

const NO_STUDY = "none";
/** The upload limit as the server says it ("20 MB": binary megabytes). */
const MAX_WORDS = `${count(MAX_SHEET_BYTES / (1024 * 1024))}${NNBSP}MB`;

/** Analysed studies whose results show (one entry per study id). */
export function comparableStudies(list: readonly WorkspaceSummary[] | undefined) {
  const seen = new Set<string>();
  const out: WorkspaceSummary[] = [];
  for (const w of list ?? []) {
    if (!w.results_visible || !w.study_id || seen.has(w.study_id)) continue;
    seen.add(w.study_id);
    out.push(w);
  }
  return out;
}

function StudySelect({
  state,
  studies,
  loading,
}: {
  state: SheetCheck;
  studies: WorkspaceSummary[];
  loading: boolean;
}) {
  const options = [
    { value: NO_STUDY, label: "No study: check the sheet's own arithmetic" },
    ...studies.map((w) => ({
      value: w.study_id!,
      label: w.title,
      hint: w.kind === "session" ? "Studio session" : "Analysed outside Studio",
    })),
  ];
  return (
    <Field
      label="Compare with a study"
      optional
      hint={
        studies.length || loading
          ? "A gene whose arithmetic reproduces but whose fold change differs from qPilot's analysis of that study is handed over: a difference of method, not a slip."
          : "No analysed study to compare with yet. Open one first; until then the sheet's own arithmetic is checked."
      }
    >
      <Select
        value={state.studyId ?? NO_STUDY}
        onValueChange={(v) => state.setStudy(v === NO_STUDY ? null : v)}
        options={options}
        disabled={!studies.length || state.busy === "upload"}
        className="max-w-md"
      />
    </Field>
  );
}

export function Source({
  state,
  studies,
  studiesLoading,
  dragging,
  onFiles,
  children,
}: {
  state: SheetCheck;
  studies: WorkspaceSummary[];
  studiesLoading: boolean;
  dragging: boolean;
  onFiles: (files: File[]) => void;
  /** Shown under the source (the notice about extra dropped files). */
  children?: ReactNode;
}) {
  const input = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const choose = () => input.current?.click();
  const { sheet, view, busy, error } = state;
  const name = sheet?.name ?? state.uploading;

  return (
    <Card
      as="section"
      aria-labelledby={titleId}
      className={cn(
        "transition-[border-color,background-color] duration-150 ease-out",
        dragging && "border-2 border-dashed border-accent bg-accent-soft/40",
      )}
    >
      <input
        ref={input}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        accept={SHEET_SUFFIXES.join(",")}
        onChange={(e) => {
          onFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <h2 id={titleId} className="sr-only">
        The sheet to check
      </h2>

      {name ? (
        <div className="flex flex-wrap items-center gap-3 px-4 pt-4 pb-3">
          <span
            className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-strong [&_svg]:size-4"
            aria-hidden
          >
            <FileSpreadsheet />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-[13px] text-fg" title={name}>
              {name}
            </p>
            <p className="text-xs text-muted">
              {sheet ? <span className="tabular">{bytes(sheet.bytes)}</span> : "Uploading"}
              {view ? (
                <>
                  {" · "}
                  {view.file_kind === "xlsx" ? "Excel workbook" : "CSV file"}
                  {" · "}
                  <span className="tabular">{plural(view.n_rows, "row")}</span> read
                </>
              ) : null}
            </p>
          </div>
          <Button icon={<FileUp />} onClick={choose} disabled={busy === "upload"}>
            Check another sheet
          </Button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
          <span
            className={cn(
              "flex size-12 items-center justify-center rounded-2xl border border-accent/25 bg-accent-soft text-accent-strong transition-transform duration-200 ease-out [&_svg]:size-5",
              dragging && "motion-safe:scale-110",
            )}
            aria-hidden
          >
            <FileUp />
          </span>
          <div className="max-w-md">
            <p className="text-[15px] font-semibold text-fg">Drop your analysis sheet here</p>
            <p className="mt-1 text-[13px] text-muted">
              An Excel workbook (.xlsx) or a CSV file, up to {MAX_WORDS}. It is read, never edited,
              and nothing is saved.
            </p>
          </div>
          <Button variant="primary" icon={<FileUp />} onClick={choose}>
            Choose a sheet
          </Button>
        </div>
      )}

      <div className="flex flex-col gap-3 border-t border-line px-4 py-3">
        <StudySelect state={state} studies={studies} loading={studiesLoading} />
        {busy ? (
          <div role="status" className="flex flex-col gap-1.5">
            <p className="text-[13px] text-muted">
              {busy === "upload"
                ? "Uploading the sheet…"
                : "Recomputing the sheet from its own Cq values…"}
            </p>
            <ProgressBar value={null} label={busy === "upload" ? "Uploading" : "Checking"} />
          </div>
        ) : null}
        {error ? (
          <ErrorPanel
            compact
            error={error.error}
            title={
              error.step === "upload" ? "The sheet was not uploaded" : "The sheet was not checked"
            }
          >
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" icon={<RefreshCw />} onClick={state.retry}>
                Try again
              </Button>
              <Button size="sm" variant="ghost" icon={<FileUp />} onClick={choose}>
                Choose another sheet
              </Button>
            </div>
            {view ? (
              <p className="mt-2 text-xs text-muted">
                Below is the last check that answered; change a column back, or name the references,
                and it checks again.
              </p>
            ) : null}
          </ErrorPanel>
        ) : null}
        {children}
      </div>
    </Card>
  );
}
