/**
 * Open a file: drop or choose the instrument's RDML export, add a sample sheet and one sentence
 * if you have them, then Open. The upload shows its progress, then the open job (the file is
 * read and every name quarantined; nothing is analysed), then the session's next step.
 */
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FileSpreadsheet, FileUp, FlaskConical, Plus, X } from "lucide-react";
import { useId, useRef, useState, type ReactNode } from "react";
import { Button, ErrorPanel, Field, IconButton, JobCard, Kbd, ProgressBar, Textarea } from "@/ui";
import { cn } from "@/lib/cn";
import { bytes } from "@/lib/format";
import { MOD, useHotkeys } from "@/lib/hooks";
import { openFile } from "./upload";
import { openedKey, useGoToSession, useJobOutcome } from "./useOpenWorkspace";
import { MAX_SENTENCE, RDML_SUFFIXES, SHEET_SUFFIXES, sortFiles } from "./workspace";

type Phase =
  | { kind: "choose" }
  | { kind: "uploading"; loaded: number; total: number; abort: () => void }
  | { kind: "opening"; jobId: string }
  | { kind: "failed"; error: unknown };

/** The files chosen so far, shared with the page so a drop anywhere on it lands here. */
export interface Intake {
  rdml: File | null;
  sheet: File | null;
  sentence: string;
  /** What the last drop or choice could not use, in words. */
  notice: string | null;
  setSentence: (s: string) => void;
  add: (files: readonly File[]) => void;
  removeRdml: () => void;
  removeSheet: () => void;
  reset: () => void;
}

/** The intake's state (lifted to the page so the whole page is a drop target). */
export function useIntake(): Intake {
  const [rdml, setRdml] = useState<File | null>(null);
  const [sheet, setSheet] = useState<File | null>(null);
  const [sentence, setSentence] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  return {
    rdml,
    sheet,
    sentence,
    notice,
    setSentence,
    add: (files) => {
      const sorted = sortFiles(files);
      if (sorted.rdml) setRdml(sorted.rdml);
      if (sorted.sheet) setSheet(sorted.sheet);
      if (sorted.ignored.length) {
        const names = sorted.ignored.map((f) => f.name).join(", ");
        setNotice(
          `Not used: ${names}. qPilot opens an RDML file (${RDML_SUFFIXES.join(" or ")}) and an optional sample sheet (${SHEET_SUFFIXES.join(" or ")}).`,
        );
      } else setNotice(null);
    },
    removeRdml: () => setRdml(null),
    removeSheet: () => setSheet(null),
    reset: () => {
      setRdml(null);
      setSheet(null);
      setSentence("");
      setNotice(null);
    },
  };
}

function FileRow({
  file,
  kind,
  icon,
  onRemove,
  disabled,
}: {
  file: File;
  kind: string;
  icon: ReactNode;
  onRemove: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line bg-surface-2 py-2 pr-1.5 pl-3">
      <span
        className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent-strong [&_svg]:size-4"
        aria-hidden
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[13px] text-fg" title={file.name}>
          {file.name}
        </p>
        <p className="text-xs text-muted">
          {kind} · <span className="tabular">{bytes(file.size)}</span>
        </p>
      </div>
      <IconButton label={`Remove ${file.name}`} size="sm" onClick={onRemove} disabled={disabled}>
        <X />
      </IconButton>
    </div>
  );
}

export function OpenFile({ intake, dragging }: { intake: Intake; dragging: boolean }) {
  const qc = useQueryClient();
  const goTo = useGoToSession();
  const [phase, setPhase] = useState<Phase>({ kind: "choose" });
  const fileInput = useRef<HTMLInputElement>(null);
  const sheetInput = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const sentenceId = useId();
  const busy = phase.kind === "uploading" || phase.kind === "opening";

  const job = useJobOutcome(phase.kind === "opening" ? phase.jobId : null, (j) => {
    const key = openedKey(j.result);
    if (key) {
      intake.reset();
      void goTo(key).catch((error: unknown) => setPhase({ kind: "failed", error }));
    }
  });

  useHotkeys({ "mod+o": () => !busy && fileInput.current?.click() });

  const start = () => {
    if (!intake.rdml || busy) return;
    const total = intake.rdml.size + (intake.sheet?.size ?? 0);
    const upload = openFile(
      { rdml: intake.rdml, sheet: intake.sheet, sentence: intake.sentence },
      (p) =>
        setPhase((cur) =>
          cur.kind === "uploading" ? { ...cur, loaded: p.loaded, total: p.total } : cur,
        ),
    );
    setPhase({ kind: "uploading", loaded: 0, total, abort: upload.abort });
    upload.done.then(
      ({ job: started }) => {
        qc.setQueryData(["job", started.id], started);
        setPhase({ kind: "opening", jobId: started.id });
      },
      (error: unknown) => setPhase({ kind: "failed", error }),
    );
  };

  const choose = () => fileInput.current?.click();
  const inputs = (
    <>
      <input
        ref={fileInput}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        multiple
        accept={[...RDML_SUFFIXES, ...SHEET_SUFFIXES].join(",")}
        onChange={(e) => {
          intake.add(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <input
        ref={sheetInput}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        accept={SHEET_SUFFIXES.join(",")}
        onChange={(e) => {
          intake.add(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
    </>
  );

  const shell = (children: ReactNode, empty = false) => (
    <section
      aria-labelledby={titleId}
      className={cn(
        "relative flex h-full flex-col rounded-2xl border bg-surface transition-[border-color,box-shadow,background-color] duration-150 ease-out",
        empty ? "border-2 border-dashed border-line-strong" : "border-line",
        dragging && !busy && "border-2 border-dashed border-accent bg-accent-soft/40 shadow-md",
      )}
    >
      {inputs}
      {children}
    </section>
  );

  // Nothing chosen yet: the drop zone.
  if (!intake.rdml && phase.kind === "choose") {
    return shell(
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-10 text-center sm:py-12">
        <div
          className={cn(
            "flex size-14 items-center justify-center rounded-2xl border border-accent/25 bg-accent-soft text-accent-strong transition-transform duration-200 ease-out [&_svg]:size-6",
            dragging && "scale-110",
          )}
          aria-hidden
        >
          <FileUp />
        </div>
        <div className="max-w-sm">
          <h2 id={titleId} className="text-lg font-semibold tracking-tight text-fg">
            {dragging ? "Drop it to open" : "Open your RDML file"}
          </h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
            Drop the instrument&rsquo;s RDML export here, or choose it. Add a sample sheet (
            {SHEET_SUFFIXES.join(" or ")}) with it if you have one.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button variant="primary" size="lg" icon={<FileUp />} onClick={choose}>
            Choose a file…
          </Button>
          <span className="hidden items-center gap-1 text-xs text-faint sm:inline-flex" aria-hidden>
            <Kbd>{MOD}</Kbd>
            <Kbd>O</Kbd>
          </span>
        </div>
        {intake.notice ? (
          <p className="max-w-sm text-xs text-warn" role="status">
            {intake.notice}
          </p>
        ) : null}
        <p className="max-w-sm text-xs text-faint">
          Opening reads the file and quarantines every name in it; nothing is analysed yet. The file
          stays on this computer.
        </p>
      </div>,
      true,
    );
  }

  return shell(
    <div className="flex flex-1 flex-col gap-4 p-5 sm:p-6">
      <div>
        <h2 id={titleId} className="text-lg font-semibold tracking-tight text-fg">
          {phase.kind === "opening" && job?.status !== "failed"
            ? "Opening your file"
            : "Open this file"}
        </h2>
        <p className="mt-0.5 text-[13px] text-muted">
          A sample sheet and one sentence help the AI propose the design. Both are optional.
        </p>
      </div>

      {intake.rdml ? (
        <FileRow
          file={intake.rdml}
          kind="RDML file"
          icon={<FlaskConical />}
          onRemove={intake.removeRdml}
          disabled={busy}
        />
      ) : (
        <Button
          variant="secondary"
          icon={<FileUp />}
          onClick={choose}
          disabled={busy}
          className="self-start"
        >
          Choose the RDML file…
        </Button>
      )}
      {intake.sheet ? (
        <FileRow
          file={intake.sheet}
          kind="Sample sheet"
          icon={<FileSpreadsheet />}
          onRemove={intake.removeSheet}
          disabled={busy}
        />
      ) : (
        <Button
          variant="ghost"
          size="sm"
          icon={<Plus />}
          onClick={() => sheetInput.current?.click()}
          disabled={busy}
          className="self-start"
        >
          Add a sample sheet ({SHEET_SUFFIXES.join(" or ")})
        </Button>
      )}
      {intake.notice ? (
        <p className="text-xs text-warn" role="status">
          {intake.notice}
        </p>
      ) : null}

      <Field
        label="One sentence about the experiment"
        optional
        htmlFor={sentenceId}
        hint="What was compared and how the samples are named. The AI reads it when it proposes the design; it is never obeyed as an instruction."
      >
        <Textarea
          id={sentenceId}
          rows={2}
          maxLength={MAX_SENTENCE}
          showCount
          value={intake.sentence}
          disabled={busy}
          onChange={(e) => intake.setSentence(e.target.value)}
          placeholder="What was compared, in your own words"
        />
      </Field>

      <div className="mt-auto flex flex-col gap-3">
        {phase.kind === "uploading" ? (
          <div className="rounded-xl border border-line bg-surface-2 p-3" aria-live="polite">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <p className="font-medium text-fg">Sending the file to qPilot on this computer</p>
              <p className="text-xs text-muted tabular">
                {phase.total ? `${bytes(phase.loaded)} of ${bytes(phase.total)}` : null}
              </p>
            </div>
            <ProgressBar
              className="mt-2"
              label="Upload"
              value={phase.total ? phase.loaded / phase.total : null}
            />
            <Button variant="link" size="sm" className="mt-2 text-xs" onClick={phase.abort}>
              Cancel
            </Button>
          </div>
        ) : null}
        {phase.kind === "opening" ? (
          <JobCard id={phase.jobId}>
            {() => <p className="text-[13px] text-muted">Going to the session…</p>}
          </JobCard>
        ) : null}
        {phase.kind === "failed" ? (
          <ErrorPanel compact error={phase.error} title="This file could not be opened" />
        ) : null}
        {job?.status === "failed" ? (
          <Button
            variant="secondary"
            onClick={() => setPhase({ kind: "choose" })}
            className="self-start"
          >
            Try again
          </Button>
        ) : null}

        {phase.kind === "choose" || phase.kind === "failed" ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              size="lg"
              icon={<ArrowRight />}
              onClick={start}
              disabled={!intake.rdml}
            >
              Open
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                intake.reset();
                setPhase({ kind: "choose" });
              }}
            >
              Cancel
            </Button>
          </div>
        ) : null}
      </div>
    </div>,
  );
}
