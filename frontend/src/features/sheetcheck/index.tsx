/**
 * Sheet check (`#/sheetcheck`): recompute a lab's own ΔΔCq spreadsheet from its Cq values and
 * find the first step that differs (`POST /api/sheets`, `POST /api/sheets/{id}/check`; the
 * method card is `methods/sheetcheck.md`). Drop or choose a sheet; optionally compare it with an
 * analysed study for hand-overs. The column mapping is a guess until a person confirms it, and
 * the page says so first. Nothing is saved and the sheet is never edited; sheet labels never come
 * back from the server, so the page shows columns by letter and rows by number.
 */
import { useRef, useState, type DragEvent } from "react";
import { ApiError } from "@/api/client";
import { useWorkspaces } from "@/shell/data";
import type { SectionProps } from "@/shell/sections";
import { Card, CardBody, CardHeader, PageHeader } from "@/ui";
import { ColumnsChecked, FirstPlace, Overview } from "./Findings";
import { Genes, HandOvers, Notes } from "./HandOvers";
import { MappingBanner, MappingCard, References } from "./Mapping";
import { comparableStudies, Source } from "./Source";
import { useSheetCheck } from "./useSheetCheck";
import { SLIP_WORDS } from "./words";

/**
 * A first check that failed because no reference gene was recognised (the engine says "name the
 * references in the mapping"): the page offers the references field on its own.
 */
function asksForReferences(error: { step: string; error: unknown } | null): boolean {
  return (
    error?.step === "check" &&
    error.error instanceof ApiError &&
    error.error.code === "bad_sheet" &&
    /reference/i.test(error.error.message)
  );
}

function hasFiles(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes("Files");
}

/** What the check does and which sheets it reads (before a sheet is chosen). */
function About() {
  const slips = Object.entries(SLIP_WORDS).filter(([id]) => id !== "livak_per_unit");
  return (
    <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
      <Card as="section" aria-labelledby="sheetcheck-what">
        <CardHeader id="sheetcheck-what" title="What the check does" />
        <CardBody>
          <ol className="flex list-decimal flex-col gap-2 pl-5 text-[13px] text-fg marker:text-muted">
            <li>
              Reads your sheet&rsquo;s Cq values and guesses what each column holds. You look at the
              guess, change any column it got wrong, and confirm it.
            </li>
            <li>
              Recomputes every ΔCq, ΔΔCq, fold change, group mean, SD, SEM and p-value from those Cq
              values, with the textbook Livak path (perfect doubling per cycle, per biological unit,
              geometric means).
            </li>
            <li>
              Names the first column and row that differ, and the known slip that reproduces it:
              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5 text-muted">
                {slips.map(([id, words]) => (
                  <li key={id}>{words}</li>
                ))}
              </ul>
            </li>
            <li>
              Compared with an analysed study, it hands over the genes whose arithmetic is right but
              whose fold change differs from qPilot&rsquo;s: a difference of method, not a slip.
            </li>
          </ol>
        </CardBody>
      </Card>
      <Card as="section" aria-labelledby="sheetcheck-reads">
        <CardHeader id="sheetcheck-reads" title="Which sheets it reads" />
        <CardBody>
          <ul className="flex list-disc flex-col gap-2 pl-5 text-[13px] text-fg marker:text-muted">
            <li>
              Excel workbooks (.xlsx): the values the spreadsheet program saved. Formulas are not
              evaluated, so save the workbook in a spreadsheet program (or export a CSV) first.
            </li>
            <li>CSV files (.csv), including those with comma decimals.</li>
            <li>
              Wide sheets, with one Cq column per gene, and long sheets, with a gene column and a
              row per gene and sample.
            </li>
            <li>
              Sample and group names stay in your sheet: the check names columns by letter, rows by
              number and groups by their order.
            </li>
            <li>The sheet is read, never edited; nothing from the check is saved.</li>
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}

export default function Section(_: SectionProps) {
  const state = useSheetCheck();
  const workspaces = useWorkspaces();
  const studies = comparableStudies(workspaces.data);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const depth = useRef(0);
  const mappingHeading = useRef<HTMLHeadingElement>(null);
  const view = state.view;

  const take = (files: File[]) => {
    const [file, ...extra] = files;
    if (!file) return;
    setNotice(
      extra.length ? `Only ${file.name} is checked; drop or choose one sheet at a time.` : null,
    );
    state.start(file);
  };

  const drag = {
    onDragEnter: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    onDragOver: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    onDrop: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setDragging(false);
      if (state.busy !== "upload") take(Array.from(e.dataTransfer.files));
    },
  };

  const review = () => {
    const h = mappingHeading.current;
    if (!h) return;
    h.scrollIntoView?.({ block: "start", behavior: "smooth" });
    h.focus({ preventScroll: true });
  };

  return (
    <div className="mx-auto min-h-full w-full max-w-[1400px] pb-6" {...drag}>
      <PageHeader
        eyebrow="Lab"
        title="Sheet check"
        hint="Recompute your own ΔΔCq spreadsheet from its Cq values; find the first step that differs."
      />
      <div className="flex flex-col gap-6">
        <Source
          state={state}
          studies={studies}
          studiesLoading={workspaces.isPending}
          dragging={dragging}
          onFiles={take}
        >
          {notice ? (
            <p role="status" className="text-[13px] text-muted">
              {notice}
            </p>
          ) : null}
        </Source>

        <p className="sr-only" aria-live="polite">
          {view && !state.busy ? `Checked. Column mapping: ${view.mapping.status}.` : ""}
        </p>
        {view ? (
          <>
            <MappingBanner view={view} onReview={review} />
            <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_480px] [&>*]:min-w-0">
              <div className="flex flex-col gap-6">
                <Overview view={view} />
                <FirstPlace view={view} />
                <HandOvers view={view} study={studies.find((w) => w.study_id === view.study_id)} />
                <Genes view={view} />
                <Notes view={view} />
                <ColumnsChecked view={view} />
              </div>
              <MappingCard state={state} view={view} headingRef={mappingHeading} />
            </div>
          </>
        ) : (
          <>
            {state.sheet && asksForReferences(state.error) ? (
              <Card as="section" aria-labelledby="sheetcheck-refs" className="max-w-xl">
                <CardHeader
                  id="sheetcheck-refs"
                  title="Name the reference genes"
                  hint="If the check could not tell which genes are the references, name them and it checks again."
                />
                <CardBody>
                  <References key={state.sheet.sheet_id} state={state} current={[]} />
                </CardBody>
              </Card>
            ) : null}
            <About />
          </>
        )}
      </div>
    </div>
  );
}
