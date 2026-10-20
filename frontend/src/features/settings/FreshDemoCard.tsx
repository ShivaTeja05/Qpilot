/**
 * Start a fresh demo: `POST /api/demo/fresh` moves the demo's session, studies and audit aside
 * (kept, never deleted), after a dialog that says exactly what moves. Then the demo can be
 * opened again from a clean start, here or on Open.
 */
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, RotateCcw } from "lucide-react";
import { useState } from "react";
import { api, unwrap, type JobView, type Schemas } from "@/api/client";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CopyButton,
  Dialog,
  ErrorPanel,
  JobCard,
  toast,
} from "@/ui";
import { plural } from "@/lib/format";
import type { WorkspaceSummary } from "@/shell/data";
import { openedKey, useGoToSession, useJobOutcome } from "@/features/home/useOpenWorkspace";
import { countsLine } from "@/features/home/workspace";

type Fresh = Schemas["FreshDemo"];

/** What the dialog says will move: the demo session as the list shows it. */
function WhatMoves({ demo }: { demo: WorkspaceSummary | undefined }) {
  if (!demo) {
    return (
      <p className="text-muted">
        There is no demo session in the list right now; any earlier demo studies or audits are still
        moved aside.
      </p>
    );
  }
  const parts = [
    countsLine(demo) && `In the file: ${countsLine(demo)}`,
    demo.decisions ? `${plural(demo.decisions, "decision")} recorded` : "no decisions yet",
    demo.has_audit ? "its robustness audit" : null,
  ].filter(Boolean);
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-3">
      <p className="font-medium text-fg">{demo.title}</p>
      <p className="mt-0.5 text-[13px] text-muted">{parts.join(" · ")}</p>
    </div>
  );
}

export function FreshDemoCard({ demo }: { demo: WorkspaceSummary | undefined }) {
  const qc = useQueryClient();
  const goTo = useGoToSession();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<Fresh | null>(null);
  const [openJob, setOpenJob] = useState<string | null>(null);
  const [openError, setOpenError] = useState<unknown>(null);

  useJobOutcome(openJob, (job) => {
    const key = openedKey(job.result);
    if (key) void goTo(key).catch(setOpenError);
  });

  const fresh = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await unwrap(api.POST("/api/demo/fresh"));
      setDone(result);
      setOpen(false);
      await qc.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success(result.moved.length ? "The demo starts fresh" : "Nothing to move aside", {
        description: result.message,
      });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const openDemo = async () => {
    setOpenError(null);
    try {
      const { job } = await unwrap(api.POST("/api/workspaces/demo"));
      qc.setQueryData<JobView>(["job", job.id], job);
      setOpenJob(job.id);
    } catch (e) {
      setOpenError(e);
    }
  };

  return (
    <Card as="section" aria-labelledby="settings-fresh">
      <CardHeader
        id="settings-fresh"
        title="Start a fresh demo"
        hint="Moves the demo's earlier work aside (kept, never deleted) so you can walk it again from the start. Your own studies are not touched."
        actions={
          <Button
            icon={<RotateCcw />}
            onClick={() => {
              setError(null);
              setOpen(true);
            }}
          >
            Start a fresh demo…
          </Button>
        }
      />
      {done || openJob || openError ? (
        <CardBody className="flex flex-col gap-3">
          {done ? (
            <div role="status" className="flex flex-col gap-2 text-[13px]">
              <p className="text-fg">{done.message}</p>
              {done.archive ? (
                <CopyButton
                  text={done.archive}
                  label="Copy the folder path"
                  showLabel
                  className="self-start"
                />
              ) : null}
            </div>
          ) : null}
          {openJob ? <JobCard id={openJob} /> : null}
          {openError ? (
            <ErrorPanel compact error={openError} title="The demo could not be opened" />
          ) : null}
          {done && !openJob ? (
            <Button
              variant="primary"
              icon={<ArrowRight />}
              onClick={() => void openDemo()}
              className="self-start"
            >
              Open the demo study
            </Button>
          ) : null}
        </CardBody>
      ) : null}

      <Dialog
        open={open}
        onOpenChange={(o) => !busy && setOpen(o)}
        title="Start a fresh demo?"
        description="The demo's Studio session, its analysed studies and its audit move to a folder next to your studies. Nothing is deleted, and your own studies stay where they are."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} onClick={() => void fresh()}>
              Move it aside
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <WhatMoves demo={demo} />
          {error ? (
            <ErrorPanel compact error={error} title="The demo could not be moved aside" />
          ) : null}
        </div>
      </Dialog>
    </Card>
  );
}
