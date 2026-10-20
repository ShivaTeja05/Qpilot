/**
 * Confirm the analysis choices (Studio's "choices" stage, sessions only): freezes the option in use
 * on every Decision Card. Shows exactly what it covers first; a person says "Yes, confirm".
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ListChecks } from "lucide-react";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { Button, Card, Dialog, ErrorPanel, toast } from "@/ui";

type ConfirmView = Schemas["ConfirmView"];

export function ChoicesConfirm({
  workspace,
  autoFocus,
}: {
  workspace: Schemas["WorkspaceView"];
  autoFocus?: boolean;
}) {
  const qc = useQueryClient();
  const sid = workspace.key;
  const stage = workspace.stages.find((s) => s.stage === "choices");
  const [view, setView] = useState<ConfirmView | null>(null);
  const prepare = useMutation({
    mutationFn: () => unwrap(api.POST("/api/sessions/{sid}/confirm/{stage}", { params: { path: { sid, stage: "choices" } } })),
    onSuccess: (v) => setView(v),
  });
  const accept = useMutation({
    mutationFn: (v: ConfirmView) =>
      unwrap(
        api.POST("/api/sessions/{sid}/confirm/{stage}/accept", {
          params: { path: { sid, stage: "choices" } },
          body: { proposal_id: v.proposal!.id, expected_head: v.head },
        }),
      ),
    onSuccess: () => {
      setView(null);
      toast.success("Analysis choices confirmed", { description: "The option in use on every card is now fixed for Prism and the record." });
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["w", sid] }),
  });

  if (workspace.kind !== "session" || !stage) return null;
  if (stage.confirmed) {
    return (
      <Card id="confirm-choices" className="flex items-start gap-3 p-4 text-[13px]">
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
        <div>
          <p className="font-medium text-fg">Analysis choices confirmed</p>
          <p className="text-muted">The option in use on every card is fixed. Prism and the Analysis Record use these choices.</p>
        </div>
      </Card>
    );
  }
  const blockers = stage.blockers ?? [];
  return (
    <Card id="confirm-choices" className="space-y-2 p-4 text-[13px]">
      <div className="flex items-start gap-3">
        <ListChecks className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0">
          <p className="font-medium text-fg">Confirm the analysis choices</p>
          <p className="text-muted">
            When every card is decided, confirm the choices: they are fixed for the Prism export and recorded with the analysis.
          </p>
          {blockers.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-muted">
              {blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <Button size="sm" variant="secondary" autoFocus={autoFocus} loading={prepare.isPending} onClick={() => prepare.mutate()}>
        Confirm the analysis choices…
      </Button>
      {prepare.error && <ErrorPanel error={prepare.error} compact />}
      <Dialog
        open={Boolean(view)}
        onOpenChange={(o) => !o && setView(null)}
        title="Confirm the analysis choices"
        description={view?.message}
        footer={
          <>
            <Button variant="ghost" onClick={() => setView(null)}>
              Not yet
            </Button>
            <Button disabled={!view?.ready || !view.proposal} loading={accept.isPending} onClick={() => view && accept.mutate(view)}>
              Yes, confirm
            </Button>
          </>
        }
      >
        {view && (
          <div className="space-y-3">
            {view.warnings.length > 0 && (
              <ul className="space-y-1 rounded-lg border border-warn/40 bg-warn-soft p-3 text-[13px] text-fg">
                {view.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            {view.covers.length > 0 ? (
              <>
                <p className="text-[13px] text-muted">This confirms exactly these:</p>
                <ul className="space-y-1 text-[13px]">
                  {view.covers.map((p) => (
                    <li key={p.id} className="rounded-md bg-sunken px-3 py-1.5 text-fg">
                      {view.descriptions[p.id] ?? p.subject}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-[13px] text-muted">Nothing else is covered by this step.</p>
            )}
            {accept.error && <ErrorPanel error={accept.error} compact />}
          </div>
        )}
      </Dialog>
    </Card>
  );
}
