/**
 * The sample sheet, from the Design page: download a template pre-filled with this plate's
 * sample and target names, fill it in Excel, attach it here (no need to open the files again).
 * The rules then propose from it; nothing is decided until you accept.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, Upload } from "lucide-react";
import { useRef, useState } from "react";
import type { JobView } from "@/api/client";
import { refreshWorkspace, reportWriteError } from "@/shell/writes";
import { Button, JobCard, toast } from "@/ui";
import type { EditorView } from "./draft";
import { attachSheet } from "./editorApi";
import { ProposeReportView } from "./ProposeDesign";

const COLUMNS: [string, string][] = [
  ["Sample", "the sample's name as in the file (the template lists them)"],
  ["Group", "control, treated, KO… (the groups you compare)"],
  ["Biological unit", "the animal, donor or culture a sample comes from (optional)"],
  ["Sample type", "Unknown, Standard, NTC, NRT, Positive control (optional)"],
  ["Quantity", "a standard's copies or relative dilution (standards only)"],
  ["Target · Target role", "Reference (housekeeping), Target (gene of interest) or Ignore"],
];

export function SheetPanel({ sid, view }: { sid: string; view: EditorView }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobView | null>(null);
  const attach = async (file: File) => {
    setBusy(true);
    try {
      const done = await attachSheet(sid, file);
      setJob(done.job);
      toast.success(done.message);
      void refreshWorkspace(qc, sid);
    } catch (err) {
      reportWriteError(qc, err, sid);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-prose text-[13px] text-muted">
        A model is optional: everything it could propose, you can set on this page. If you keep your
        plate layout in a spreadsheet, a sample sheet does it in one go: download the template (it
        lists this plate's samples and targets), fill it in Excel, attach it.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild variant="secondary" icon={<Download />}>
          <a href={view.template_url} download>
            Download the template (CSV)
          </a>
        </Button>
        <input
          ref={input}
          type="file"
          accept=".csv,.tsv,.xlsx,.xlsm"
          className="sr-only"
          id={`attach-sheet-${sid}`}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void attach(file);
          }}
        />
        <Button
          variant="primary"
          icon={<Upload />}
          loading={busy}
          onClick={() => input.current?.click()}
        >
          {view.has_sheet ? "Attach another sample sheet…" : "Attach a sample sheet…"}
        </Button>
        {view.sheet_name ? (
          <span className="inline-flex items-center gap-1.5 text-[13px] text-muted">
            <FileSpreadsheet className="size-4" aria-hidden /> Attached:{" "}
            <span className="font-medium text-fg">{view.sheet_name}</span>
          </span>
        ) : null}
      </div>
      {job ? (
        <JobCard id={job.id} onDismiss={() => setJob(null)}>
          {(result) => <ProposeReportView result={result} />}
        </JobCard>
      ) : null}
      <div>
        <h3 className="text-[13px] font-semibold text-fg">The columns qPilot reads</h3>
        <dl className="mt-1.5 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
          {COLUMNS.map(([name, what]) => (
            <div key={name} className="contents">
              <dt className="font-medium text-fg">{name}</dt>
              <dd className="text-muted">{what}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-xs text-muted">
          Other spellings work too: Condition or Treatment for the group; Animal, Mouse, Donor or
          Patient for the unit; Gene Type, Reference, Housekeeping or Endogenous control for the
          target role. Every cell is read as text, never run.
        </p>
      </div>
    </div>
  );
}
