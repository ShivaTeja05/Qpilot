/**
 * Run files (G-INSTR): per plate, which run file the rule read. The study's own file (RDML)
 * names the instrument and the run date at most; a study opened from an instrument export reads
 * each plate's run file in the export when it has one (a QuantStudio results export, CFX run
 * information); a person links the run file the instrument wrote (an .eds, a QuantStudio results
 * export or CFX run information) to a plate, and G-INSTR checks whether that run completed, its
 * pauses and its calibrations. Linking changes no number: the gate is read again with it, and the
 * link is kept for every analysis of the file. Serial numbers never come back from the server.
 */
import { FileUp, Link2Off } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { dateTime } from "@/lib/format";
import { Button, Card, CardBody, CardHeader, ErrorPanel, Select, toast } from "@/ui";
import {
  useLinkRunFile,
  useUnlinkRunFile,
  type GateScope,
  type GateView,
  type RunFile,
} from "./api";
import { VerdictChip } from "./Pieces";
import { plateLabel, runFilesSentence, runSourceText } from "./words";

const ACCEPT = ".eds,.csv,.txt";

function errorToast(e: unknown, fallback: string) {
  toast.error(e instanceof ApiError || e instanceof Error ? e.message : fallback);
}

function LinkedRow({
  run,
  scope,
  onOpen,
}: {
  run: RunFile;
  scope: GateScope;
  onOpen: (evaluation: string) => void;
}) {
  const unlink = useUnlinkRunFile(scope);
  return (
    <li className="flex flex-col gap-1.5 border-b border-line px-4 py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <VerdictChip verdict={run.verdict} />
        <span className="text-[13px] font-medium text-fg">Plate {plateLabel(run.plate)}</span>
      </div>
      <p className="text-[13px] text-fg">
        {runSourceText(run)}
        {run.linked_at ? <span className="text-muted"> on {dateTime(run.linked_at)}</span> : null}
      </p>
      <div className="flex flex-wrap gap-2">
        {run.evaluation && (
          <Button size="sm" variant="ghost" onClick={() => onOpen(run.evaluation!)}>
            Show the check
          </Button>
        )}
        <Button
          size="sm"
          variant="secondary"
          icon={<Link2Off />}
          loading={unlink.isPending}
          aria-label={`Unlink the run file of plate ${plateLabel(run.plate)}`}
          onClick={() =>
            unlink.mutate(run.plate, {
              onSuccess: (done) =>
                toast.success("Run file unlinked", { description: done.message }),
              onError: (e) => errorToast(e, "The run file could not be unlinked."),
            })
          }
        >
          Unlink
        </Button>
      </div>
    </li>
  );
}

export function RunFiles({
  view,
  scope,
  plate,
  onPlate,
  focus,
  onOpen,
  checking = false,
}: {
  view: GateView;
  scope: GateScope;
  /** The plate the next run file is linked to. */
  plate: string;
  onPlate: (plate: string) => void;
  /** Bring the card into view and focus its file button (asked for from a rule check). */
  focus: number;
  onOpen: (evaluation: string) => void;
  /** The gate is being read again (after a link). */
  checking?: boolean;
}) {
  const link = useLinkRunFile(scope);
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const [over, setOver] = useState(false);
  useEffect(() => {
    if (!focus) return;
    card.current?.scrollIntoView?.({ block: "center" });
    button.current?.focus({ preventScroll: true });
  }, [focus]);
  if (view.runs.length === 0) return null;
  const linked = view.runs.filter((r) => r.source === "linked");
  const options = view.runs.map((r) => ({
    value: r.plate,
    label: `${plateLabel(r.plate)}${r.source === "linked" ? " (linked)" : r.source === "export" ? " (from the export)" : ""}`,
  }));
  const choose = (files: FileList | null) => {
    const file = files?.[0];
    if (!file || !plate) return;
    link.mutate(
      { plate, file },
      {
        onSuccess: (done) =>
          toast.success(`Run file linked to plate ${plateLabel(done.plate)}`, {
            description: done.message,
          }),
      },
    );
  };
  return (
    <div ref={card}>
      <Card as="section" aria-labelledby="gate-runs-title">
        <CardHeader id="gate-runs-title" title="Run files" hint={view.run_note} />
        <CardBody className="flex flex-col gap-3">
          <p className="text-[13px] text-fg">{runFilesSentence(view.runs)}</p>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              choose(e.dataTransfer.files);
            }}
            className={cn(
              "flex flex-col gap-2 rounded-lg border border-dashed px-3 py-3 text-[13px] transition-colors",
              over ? "border-accent bg-accent-soft/40" : "border-line-strong",
            )}
          >
            <Select
              size="sm"
              label="Plate to link a run file to"
              value={plate}
              onValueChange={onPlate}
              options={options}
              className="w-full"
            />
            <p className="text-muted">
              Drop the plate&rsquo;s run file here (an .eds file, a QuantStudio results export or
              CFX run information), or
            </p>
            <Button
              ref={button}
              size="sm"
              icon={<FileUp />}
              loading={link.isPending}
              disabled={!plate}
              onClick={() => input.current?.click()}
              className="h-auto min-h-7 max-w-full self-start py-1 text-left whitespace-normal"
            >
              Choose the run file for plate {plateLabel(plate)}
            </Button>
            <label htmlFor={inputId} className="sr-only">
              Run file for plate {plateLabel(plate)}
            </label>
            <input
              id={inputId}
              ref={input}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              tabIndex={-1}
              onChange={(e) => {
                choose(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
          {link.error ? (
            <ErrorPanel error={link.error} title="This run file was not linked" compact />
          ) : null}
          {checking ? (
            <p className="text-[13px] text-muted" role="status">
              Checking the controls again with the run files as they are now…
            </p>
          ) : null}
        </CardBody>
        {linked.length > 0 && (
          <ul className="border-t border-line" aria-label="Linked run files">
            {linked.map((r) => (
              <LinkedRow key={r.plate} run={r} scope={scope} onOpen={onOpen} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
