/**
 * Open a file: drop or choose the instrument's RDML file or its export (one file or a whole
 * export set: CFX, QuantStudio, LightCycler 480, a tidy table), add a sample sheet and one
 * sentence if you have them, then Open. The upload shows its progress, then the open job (the
 * files are read, an export is written as RDML, every name quarantined; nothing is analysed),
 * then the session's next step. What each file is, the server decides from its content; the
 * labels here are a first guess from the names.
 */
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FileSpreadsheet, FileText, FileUp, FlaskConical, Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  Button,
  ErrorPanel,
  Field,
  IconButton,
  JobCard,
  Kbd,
  ProgressBar,
  Textarea,
  toast,
} from "@/ui";
import { cn } from "@/lib/cn";
import { bytes, plural } from "@/lib/format";
import { MOD } from "@/lib/hooks";
import { useOpenFileRequest } from "@/shell/actions";
import { openFile } from "./upload";
import type { Intake } from "./useIntake";
import { openedKey, useGoToSession, useJobOutcome } from "./useOpenWorkspace";
import { EXPORT_SUFFIXES, MAX_SENTENCE, SHEET_SUFFIXES, guessFile } from "./workspace";

const KIND_ICON = {
  rdml: <FlaskConical />,
  export: <FileText />,
  table: <FileSpreadsheet />,
} as const;

/** The files an open job did not use (`OpenDone.unused`), if it names any. */
function unusedOf(result: unknown): string[] {
  const unused = (result as { unused?: unknown } | null | undefined)?.unused;
  return Array.isArray(unused) ? unused.filter((n): n is string => typeof n === "string") : [];
}

type Phase =
  | { kind: "choose" }
  | { kind: "uploading"; loaded: number; total: number; abort: () => void }
  | { kind: "opening"; jobId: string }
  | { kind: "failed"; error: unknown };

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
  // Open and Cancel give way to the progress: keep keyboard focus there, not on the page.
  const status = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (phase.kind === "uploading" || phase.kind === "failed") status.current?.focus();
  }, [phase.kind]);
  const sentenceId = useId();
  const busy = phase.kind === "uploading" || phase.kind === "opening";

  const job = useJobOutcome(phase.kind === "opening" ? phase.jobId : null, (j) => {
    const key = openedKey(j.result);
    if (key) {
      const unused = unusedOf(j.result);
      if (unused.length) {
        toast.info(`Not used: ${unused.join(", ")}`, {
          description: "qPilot did not read these files; the rest were opened.",
        });
      }
      intake.reset();
      void goTo(key).catch((error: unknown) => setPhase({ kind: "failed", error }));
    }
  });

  // ⌘O (the shell binds it everywhere, comes here, and asks): show the file picker.
  useOpenFileRequest(() => !busy && fileInput.current?.click());

  const plan = intake.plan;
  const start = () => {
    if (!plan || busy) return;
    const sent = plan.mode === "rdml" ? [plan.rdml] : plan.files;
    const total = [...sent, ...(plan.sheet ? [plan.sheet] : [])].reduce((n, f) => n + f.size, 0);
    const upload = openFile(
      plan.mode === "rdml"
        ? { rdml: plan.rdml, sheet: plan.sheet, sentence: intake.sentence }
        : { files: plan.files, sheet: plan.sheet, sentence: intake.sentence },
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
        accept={EXPORT_SUFFIXES.join(",")}
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
          intake.setSheet(e.target.files?.[0] ?? null);
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
  if (!intake.files.length && phase.kind === "choose") {
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
            {dragging ? "Drop them to open" : "Open your instrument's files"}
          </h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
            Drop an RDML file or what your instrument exported here, or choose them: Bio-Rad CFX
            (every sheet of a run), QuantStudio, StepOne or 7500, LightCycler 480, or a tidy table.
            Add a sample sheet ({SHEET_SUFFIXES.join(" or ")}) with them if you have one.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button variant="primary" size="lg" icon={<FileUp />} onClick={choose}>
            Choose files…
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
        <p className="max-w-sm text-xs text-muted">
          Opening reads the files and quarantines every name in them; an export is written as an
          RDML file first. Nothing is analysed yet, and the files stay on this computer.
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
            ? intake.files.length > 1
              ? "Opening your files"
              : "Opening your file"
            : intake.files.length > 1
              ? `Open these ${intake.files.length} files`
              : "Open this file"}
        </h2>
        <p className="mt-0.5 text-[13px] text-muted">
          A sample sheet and one sentence help the AI propose the design. Both are optional.
        </p>
      </div>

      <div
        className={cn(
          "flex flex-col gap-2",
          intake.files.length > 4 &&
            "qp-scroll max-h-72 overflow-y-auto rounded-lg pr-1 outline-none focus-visible:outline-2 focus-visible:outline-offset-2",
        )}
        {...(intake.files.length > 4
          ? { tabIndex: 0, role: "region", "aria-label": "Files to open" }
          : {})}
      >
        {intake.files.map((file) => {
          const guess = guessFile(file.name);
          return (
            <FileRow
              key={`${file.name}-${file.size}`}
              file={file}
              kind={guess.label}
              icon={KIND_ICON[guess.kind]}
              onRemove={() => intake.remove(file)}
              disabled={busy}
            />
          );
        })}
      </div>
      {intake.files.length > 1 || plan?.mode === "files" ? (
        <p className="text-xs text-muted">
          qPilot reads each file&rsquo;s content to decide what it is (the labels above are a guess
          from the names): one export or one RDML file, and a sample sheet if one is among them.
          {intake.files.length > 1
            ? ` ${plural(intake.files.length, "file")} are sent together.`
            : ""}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" icon={<Plus />} onClick={choose} disabled={busy}>
          Add more files…
        </Button>
        {intake.sheet ? null : (
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus />}
            onClick={() => sheetInput.current?.click()}
            disabled={busy}
          >
            Add a sample sheet ({SHEET_SUFFIXES.join(" or ")})
          </Button>
        )}
      </div>
      {intake.sheet ? (
        <FileRow
          file={intake.sheet}
          kind="Sample sheet"
          icon={<FileSpreadsheet />}
          onRemove={() => intake.setSheet(null)}
          disabled={busy}
        />
      ) : null}
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

      <div
        ref={status}
        tabIndex={-1}
        className="mt-auto flex flex-col gap-3 rounded-xl outline-none focus-visible:outline-2 focus-visible:outline-offset-4"
      >
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
          <ErrorPanel
            compact
            error={phase.error}
            title={
              intake.files.length > 1
                ? "These files could not be opened"
                : "This file could not be opened"
            }
          />
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
              disabled={!plan}
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
