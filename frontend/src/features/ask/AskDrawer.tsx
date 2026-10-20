import { useQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, FolderOpen, Loader2, MessageCircleQuestion, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { useReducedMotion } from "@/lib/hooks";
import { Button, EmptyState, SegmentedControl, Skeleton } from "@/ui";
import type { AnswerLinks } from "./Answer";
import { startAsk, type AskSource } from "./askApi";
import { Composer } from "./Composer";
import { addTurn, clearTurns, recallList, updateTurn, useTurns, type Turn } from "./history";
import { ModelLine } from "./ModelLine";
import { ModelSaw } from "./ModelSaw";
import { TurnView } from "./TurnView";
import { useExamples } from "./useExamples";

export interface AskDrawerProps {
  workspace: Schemas["WorkspaceView"] | null;
  open: boolean;
  onClose: () => void;
}

const SOURCES: { value: AskSource; label: string }[] = [
  { value: "auto", label: "qPilot picks" },
  { value: "study", label: "Study" },
  { value: "audit", label: "Audit" },
];

/**
 * The Ask drawer's content. The shell renders it inside its drawer frame (⌘J); it fills the
 * frame's height: the model line, the conversation (scrolls), and the question box.
 */
export default function AskDrawer({ workspace, open }: AskDrawerProps) {
  const system = useQuery({ queryKey: ["system"], queryFn: () => unwrap(api.GET("/api/system")) });
  const model = system.data?.model;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-4 py-2.5">
        {model ? <ModelLine model={model} /> : <Skeleton className="h-4 w-3/4" />}
      </div>
      {!workspace ? (
        <Closed>
          <EmptyState
            icon={<FolderOpen />}
            title="Open a study to ask about it"
            action={
              <Button asChild size="sm">
                <a href="#/">Open a study</a>
              </Button>
            }
          >
            Ask answers questions about the open study (a gene, an analysis choice, the study
            itself) with qPilot's own tools, and shows the facts behind every number.
          </EmptyState>
        </Closed>
      ) : !workspace.results_visible || !workspace.study_id ? (
        <Closed>
          <BlindNotice workspace={workspace} />
        </Closed>
      ) : (
        <Conversation
          workspace={workspace}
          studyId={workspace.study_id}
          open={open}
          model={model}
        />
      )}
    </div>
  );
}

function Closed({ children }: { children: ReactNode }) {
  return <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">{children}</div>;
}

/** Why Ask is closed on a blind (or not yet analysed) Studio session, and where to go. */
function BlindNotice({ workspace }: { workspace: Schemas["WorkspaceView"] }) {
  const base = `#/${workspace.kind === "session" ? "s" : "r"}/${workspace.key}`;
  const stage = (name: "design" | "curves") => workspace.stages.find((s) => s.stage === name);
  const design = stage("design");
  const curves = stage("curves");
  const next =
    design && !design.confirmed ? "design" : curves && !curves.confirmed ? "curves" : null;
  if (!next) {
    return (
      <EmptyState icon={<Loader2 className="animate-spin" />} title="The results are not ready yet">
        qPilot is analysing the confirmed design. Ask opens as soon as the results are ready.
      </EmptyState>
    );
  }
  return (
    <EmptyState
      icon={<EyeOff />}
      title="Ask waits until the study is unblinded"
      action={
        <Button asChild size="sm" variant="primary">
          <a href={`${base}/${next}`}>
            {next === "design" ? "Confirm the design" : "Confirm the curves"}
          </a>
        </Button>
      }
    >
      Until the design and the curves are both confirmed, qPilot keeps every group difference out of
      sight, and an answer could reveal one.{" "}
      {next === "design" ? "The design is" : "The curves are"} not confirmed yet.
    </EmptyState>
  );
}

function Conversation({
  workspace,
  studyId,
  open,
  model,
}: {
  workspace: Schemas["WorkspaceView"];
  studyId: string;
  open: boolean;
  model: Schemas["ModelStatus"] | undefined;
}) {
  const qc = useQueryClient();
  const turns = useTurns(studyId);
  const recall = useMemo(() => recallList(turns), [turns]);
  const { examples, loading } = useExamples(workspace);
  const [source, setSource] = useState<AskSource>("auto");
  const box = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const sending = turns.some((t) => t.state === "sending");
  const answered = turns.filter((t) => t.state === "done").length;

  const base = `#/${workspace.kind === "session" ? "s" : "r"}/${workspace.key}`;
  const links: AnswerLinks = useMemo(
    () => ({ gene: (g) => `${base}/gene/${encodeURIComponent(g)}`, results: `${base}/results` }),
    [base],
  );

  const run = useCallback(
    async (turn: Turn) => {
      try {
        const job = await startAsk(studyId, turn.question, source);
        updateTurn(studyId, turn.id, { state: "running", jobId: job.id, error: null });
      } catch (error) {
        updateTurn(studyId, turn.id, { state: "failed", error });
      }
    },
    [studyId, source],
  );

  const ask = useCallback(
    (question: string) => {
      if (sending) return false;
      void run(addTurn(studyId, question));
      return true;
    },
    [run, sending, studyId],
  );

  const retry = useCallback(
    (turn: Turn) => {
      updateTurn(studyId, turn.id, { state: "sending", error: null, jobId: null, answer: null });
      void run(turn);
    },
    [run, studyId],
  );

  // An answer that wrote to the decision chain (a change request) changes what other sections show.
  const lastWrite = turns.findLast(
    (t) => t.answer && t.answer.headAfter && t.answer.headAfter !== t.answer.headBefore,
  );
  useEffect(() => {
    if (lastWrite) void qc.invalidateQueries({ queryKey: ["w", workspace.key] });
  }, [lastWrite?.id, qc, workspace.key]); // eslint-disable-line react-hooks/exhaustive-deps -- once per writing answer

  // Focus the box when the drawer opens.
  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => box.current?.focus(), 60);
    return () => window.clearTimeout(id);
  }, [open]);

  // Keep the newest exchange in view.
  const last = turns[turns.length - 1];
  useEffect(() => {
    const el = log.current;
    if (!el || !last) return;
    el.scrollTo({ top: el.scrollHeight, behavior: reduced ? "auto" : "smooth" });
  }, [last?.id, last?.state, reduced]); // eslint-disable-line react-hooks/exhaustive-deps -- scroll on a new turn or state

  return (
    <>
      <div
        ref={log}
        role="log"
        aria-label="Questions and answers"
        aria-live="polite"
        className="qp-scroll flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 py-4"
      >
        {turns.length === 0 ? (
          <Intro examples={examples} loading={loading} onPick={(q) => ask(q)} disabled={sending} />
        ) : (
          <>
            <div className="flex justify-end">
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 />}
                onClick={() => clearTurns(studyId)}
              >
                Clear the conversation
              </Button>
            </div>
            {turns.map((t) => (
              <TurnView key={t.id} studyId={studyId} turn={t} links={links} onRetry={retry} />
            ))}
          </>
        )}
        <div className="mt-auto pt-2">
          <ModelSaw workspaceKey={workspace.key} model={model} asked={answered} />
        </div>
      </div>
      <div className="flex flex-col gap-2 border-t border-line bg-surface px-4 py-3">
        {workspace.has_audit ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted" aria-hidden>
              Answer from
            </span>
            <SegmentedControl
              size="sm"
              label="Answer from"
              value={source}
              onValueChange={setSource}
              options={SOURCES}
            />
          </div>
        ) : null}
        <Composer
          ref={box}
          onSend={ask}
          recall={recall}
          disabled={sending}
          disabledReason="Sending your question…"
        />
      </div>
    </>
  );
}

function Intro({
  examples,
  loading,
  onPick,
  disabled,
}: {
  examples: string[];
  loading: boolean;
  onPick: (q: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div
          className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-strong"
          aria-hidden
        >
          <MessageCircleQuestion className="size-4.5" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-fg">Ask about this study</h3>
          <p className="mt-1 text-[13px] leading-relaxed text-muted">
            qPilot answers with its own tools on this study. The words come from a template or a
            checked model; every number comes from a fact listed under the answer. A change you ask
            for goes to its Decision Card for a person to decide.
          </p>
        </div>
      </div>
      <div>
        <p className="mb-2 text-xs font-medium text-muted">Try one of these</p>
        {loading ? (
          <div className="flex flex-col gap-2" aria-hidden>
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-5/6" />
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {examples.map((q) => (
              <li key={q}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onPick(q)}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-left text-[13px] text-fg transition-colors hover:border-accent/40 hover:bg-accent-soft/40 disabled:opacity-55"
                >
                  {q}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
