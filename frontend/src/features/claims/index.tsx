/**
 * Claims: paste what your paper says; every claim is checked against this study's own record.
 *
 * The text is read by rules (gene, direction, fold, p, robustness words, normaliser, group sizes,
 * efficiency) and each claim gets a verdict from a fixed vocabulary, with the checks behind it:
 * the planned analysis, qPilot's choice grid and, when the study was audited, the audit. Every
 * number in a reason is a fact the server cites; a value from your text is quoted as yours. A
 * model, when one runs on this machine, may only propose readings the rules then check. The text
 * is not stored; this page keeps a draft in this tab only.
 */
import { Quote, ScanText, Sparkles, SquarePen } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useJob } from "@/api/jobs";
import { useHotkeys, MOD } from "@/lib/hooks";
import { useSystem } from "@/shell/data";
import { sectionPath, type SectionProps } from "@/shell/sections";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  JobCard,
  Kbd,
  PageHeader,
  Textarea,
  Tooltip,
} from "@/ui";
import type { Schemas } from "@/api/client";
import {
  MAX_TEXT,
  assistResult,
  useCheckClaims,
  useExamples,
  useReadWithModel,
  type Checked,
  type ClaimView,
  type Verdict,
} from "./api";
import { Annotated } from "./Annotated";
import { ClaimCard } from "./ClaimCard";
import { ClaimList, SummaryBar } from "./ClaimList";
import { ordered } from "./marks";

export default function ClaimsSection({ workspace }: SectionProps) {
  if (!workspace) return null;
  return <ClaimsPage workspace={workspace} />;
}

type Workspace = Schemas["WorkspaceView"];

function studyOf(w: Workspace): string | null {
  return w.study_id ?? (w.kind === "study" ? w.key : null);
}

/** A draft kept in this tab only (never sent anywhere until "Check claims"). */
function useDraft(studyId: string | null): [string, (t: string) => void] {
  const key = `qpilot.claims.draft.${studyId ?? "none"}`;
  const [text, setText] = useState(() => {
    try {
      return sessionStorage.getItem(key) ?? "";
    } catch {
      return "";
    }
  });
  const save = useCallback(
    (t: string) => {
      setText(t);
      try {
        sessionStorage.setItem(key, t);
      } catch {
        // private mode or storage blocked: the draft lives in memory only
      }
    },
    [key],
  );
  return [text, save];
}

function ClaimsPage({ workspace }: { workspace: Workspace }) {
  const studyId = studyOf(workspace);
  const [text, setText] = useDraft(studyId);
  const [checked, setChecked] = useState<Checked | null>(null);
  const [mode, setMode] = useState<"write" | "read">("write");
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<Verdict | null>(null);
  const [order, setOrder] = useState<"text" | "severity">("text");
  const [jobId, setJobId] = useState<string | null>(null);
  const [source, setSource] = useState<"rules" | "model">("rules");
  const box = useRef<HTMLTextAreaElement>(null);
  const card = useRef<HTMLDivElement>(null);

  const check = useCheckClaims(studyId);
  const read = useReadWithModel(studyId);
  const examples = useExamples(workspace.key, studyId);
  const system = useSystem();
  const model = system.data?.model;
  const job = useJob(jobId);

  const run = useCallback(
    (t: string) => {
      if (!t.trim() || t.length > MAX_TEXT) return;
      check.mutate(t, {
        onSuccess: (result) => {
          setSource("rules");
          setChecked(result);
          setMode("read");
          setFilter(null);
          setSelected(null);
        },
      });
    },
    [check],
  );

  const runWithModel = (t: string) => {
    if (!t.trim() || t.length > MAX_TEXT) return;
    setSource("model");
    setMode("read");
    setFilter(null);
    setSelected(null);
    read.mutate(t, { onSuccess: (r) => setJobId(r.jobId) });
  };

  // The model's job, once done, gives the report shown (the rules checked every reading in it).
  const assisted = useMemo(() => {
    const view = job.data;
    return view?.status === "done" ? assistResult(view.result) : null;
  }, [job.data]);
  const modelText = read.data?.text;
  const shown: Checked | null = useMemo(
    () =>
      source === "model"
        ? assisted && modelText != null
          ? { text: modelText, report: assisted.report }
          : null
        : checked,
    [source, assisted, modelText, checked],
  );
  const assistNote =
    source === "model" && assisted?.proposed
      ? `The model proposed ${assisted.proposed} reading${assisted.proposed === 1 ? "" : "s"}; ` +
        `${assisted.accepted} passed the rules' check.`
      : null;

  const stale = shown != null && shown.text !== text;
  const claims = useMemo(() => shown?.report.claims ?? [], [shown]);
  const listed = useMemo(
    () => ordered(claims, order).filter((c) => !filter || c.verdict === filter),
    [claims, order, filter],
  );
  const current = claims.find((c) => c.id === selected) ?? ordered(claims, "severity")[0] ?? null;
  const position = current ? listed.findIndex((c) => c.id === current.id) + 1 : 0;

  const move = useCallback(
    (step: 1 | -1) => {
      if (!listed.length) return;
      const i = listed.findIndex((c) => c.id === current?.id);
      const next = listed[Math.min(listed.length - 1, Math.max(0, (i < 0 ? -1 : i) + step))];
      if (next) setSelected(next.id);
    },
    [listed, current],
  );
  useHotkeys({ j: () => move(1), k: () => move(-1) }, mode === "read" && claims.length > 0);

  const select = (id: string) => {
    setSelected(id);
    if (window.matchMedia?.("(max-width: 1279px)").matches) {
      card.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  };

  const tryExample = () => {
    const paragraph = examples.data?.paragraph;
    if (!paragraph) return;
    setText(paragraph);
    run(paragraph);
  };

  const replaceSentence = (claim: ClaimView) => {
    if (!shown || !claim.suggestion) return;
    const { start, end } = claim.sentence;
    const next = shown.text.slice(0, start) + claim.suggestion.plain + shown.text.slice(end);
    setText(next);
    run(next);
  };

  const exampleWhat = (claim: ClaimView): string | null => {
    if (!shown || !examples.data) return null;
    const sentence = shown.text.slice(claim.sentence.start, claim.sentence.end);
    return examples.data.examples.find((e) => e.text === sentence)?.what ?? null;
  };

  const linksOf = (claim: ClaimView) => {
    const gene = claim.gene ? sectionPath(workspace, "gene", claim.gene) : undefined;
    const card = claim.choices.find((c) => c.card_id)?.card_id;
    const choices = claim.choices.length
      ? card
        ? sectionPath(workspace, "results", "card", card)
        : sectionPath(workspace, "results")
      : undefined;
    const audit = claim.audit_verdict ? sectionPath(workspace, "audit") : undefined;
    return { gene, choices, audit };
  };

  const sentenceClaims = (claim: ClaimView) =>
    claims.filter((c) => c.sentence.start === claim.sentence.start).length;

  if (!studyId) {
    return (
      <EmptyState icon={<Quote />} title="No results to check claims against yet" headingLevel={1}>
        Confirm the design and the curves first; claims are checked against the study's results.
      </EmptyState>
    );
  }

  const tooLong = text.length > MAX_TEXT;
  const modelOk = Boolean(model?.available);
  const modelLocal = Boolean(model?.local);
  const busy = check.isPending || read.isPending || jobId != null;

  return (
    <div className="mx-auto w-full max-w-[1400px]">
      <PageHeader
        title="Claims"
        hint="Paste what your paper says. Every claim is read, then checked against this study's own record: the planned analysis, every choice qPilot checks and, if run, the audit."
        actions={
          <Button
            variant="secondary"
            icon={<Sparkles />}
            onClick={tryExample}
            disabled={!examples.data?.examples.length || busy}
            loading={examples.isLoading}
          >
            Try an example from this study
          </Button>
        }
      />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader
              title={mode === "read" && shown ? "Your text, checked" : "Your text"}
              hint={
                mode === "read" && shown
                  ? "Underlined words are what each claim was read from; the mark after a claim is its verdict. Click either to open it."
                  : "A results paragraph, a figure legend or an abstract. It is checked on this machine and not stored."
              }
              actions={
                mode === "read" && shown ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<SquarePen />}
                    onClick={() => {
                      setMode("write");
                      requestAnimationFrame(() => box.current?.focus());
                    }}
                  >
                    Edit the text
                  </Button>
                ) : null
              }
            />
            <CardBody>
              {mode === "read" && shown ? (
                <>
                  {stale ? (
                    <p className="mb-3 rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
                      The text changed since it was checked.{" "}
                      <button
                        type="button"
                        className="font-medium underline"
                        onClick={() => run(text)}
                      >
                        Check it again
                      </button>
                    </p>
                  ) : null}
                  <Annotated
                    text={shown.text}
                    claims={claims}
                    selected={current?.id ?? null}
                    onSelect={select}
                  />
                </>
              ) : (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(text);
                  }}
                >
                  <label htmlFor="claims-text" className="sr-only">
                    The text to check
                  </label>
                  <Textarea
                    id="claims-text"
                    ref={box}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                        e.preventDefault();
                        run(text);
                      }
                    }}
                    maxLength={MAX_TEXT}
                    showCount
                    rows={9}
                    spellCheck
                    placeholder="e.g. a sentence naming one of this study's genes, how it changed between the groups, and the numbers you report."
                    className="text-[15px]"
                  />
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      type="submit"
                      variant="primary"
                      icon={<ScanText />}
                      loading={check.isPending}
                      disabled={!text.trim() || tooLong || busy}
                    >
                      Check claims
                    </Button>
                    <Kbd>{MOD}</Kbd>
                    <Kbd>↵</Kbd>
                    {modelOk ? (
                      <Tooltip
                        content={
                          modelLocal
                            ? "The model only proposes readings of sentences the rules could not read; the rules check every value it proposes. It never gives a verdict."
                            : "The configured model is remote: your unpublished text would leave this machine, so it is not sent."
                        }
                      >
                        <span>
                          <Button
                            type="button"
                            variant="ghost"
                            icon={<Sparkles />}
                            disabled={!modelLocal || !text.trim() || tooLong || busy}
                            loading={read.isPending}
                            onClick={() => runWithModel(text)}
                          >
                            Check, with the model reading too
                          </Button>
                        </span>
                      </Tooltip>
                    ) : null}
                    {shown && !stale ? (
                      <Button type="button" variant="link" onClick={() => setMode("read")}>
                        Back to the checked text
                      </Button>
                    ) : null}
                  </div>
                </form>
              )}
              {check.error ? (
                <ErrorPanel
                  className="mt-3"
                  error={check.error}
                  compact
                  onRetry={() => run(text)}
                />
              ) : null}
              {read.error ? <ErrorPanel className="mt-3" error={read.error} compact /> : null}
              {jobId ? <JobCard className="mt-3" id={jobId} /> : null}
            </CardBody>
          </Card>

          {shown ? (
            <section aria-label="What was found" className="space-y-4">
              <SummaryBar report={shown.report} filter={filter} onFilter={setFilter} />
              {shown.report.model_note || assistNote || shown.report.notes.length ? (
                <ul className="space-y-1 text-[13px] text-muted">
                  {[shown.report.model_note, assistNote, ...shown.report.notes]
                    .filter(Boolean)
                    .map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                </ul>
              ) : null}
              {claims.length ? (
                <ClaimList
                  claims={listed}
                  selected={current?.id ?? null}
                  order={order}
                  onOrder={setOrder}
                  onSelect={select}
                />
              ) : (
                <EmptyState icon={<Quote />} title="No checkable claim in this text" compact>
                  A claim names a gene of this study and says how it changed between{" "}
                  {shown.report.groups.join(" and ")}: a direction, a fold change or a p-value.
                </EmptyState>
              )}
              <Legend report={shown.report} />
            </section>
          ) : (
            <Explainer examples={examples.data?.examples ?? []} />
          )}
        </div>

        <aside
          ref={card}
          aria-label="The selected claim"
          className="min-w-0 xl:sticky xl:top-4 xl:self-start"
        >
          {shown && current ? (
            <ClaimCard
              text={shown.text}
              claim={current}
              position={position || 1}
              total={listed.length || claims.length}
              example={exampleWhat(current)}
              links={linksOf(current)}
              canReplace={!stale && sentenceClaims(current) === 1 && current.kind === "gene"}
              onReplace={() => replaceSentence(current)}
              onMove={move}
            />
          ) : shown && claims.length ? (
            <EmptyState icon={<Quote />} title="Open a claim" compact>
              Click an underlined word, or Tab to a mark and press Enter.
            </EmptyState>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function Legend({ report }: { report: Schemas["ClaimsReport"] }) {
  return (
    <details className="rounded-xl border border-line bg-surface px-4 py-3 text-[13px]">
      <summary className="cursor-pointer font-medium text-fg">What the verdicts mean</summary>
      <dl className="mt-2 space-y-1.5 text-muted">
        {Object.entries(report.verdicts).map(([v, label]) => (
          <div key={v}>
            <dt className="inline font-medium text-fg">{label}: </dt>
            <dd className="inline">{report.verdict_rules[v]}</dd>
          </div>
        ))}
        <div>
          <dt className="inline font-medium text-fg">The call rule: </dt>
          <dd className="inline">{report.rule}.</dd>
        </div>
      </dl>
    </details>
  );
}

/** Before a check: what is read and checked, and the server's examples for this study. */
function Explainer({ examples }: { examples: Schemas["ClaimExample"][] }) {
  return (
    <Card>
      <CardHeader
        level={2}
        title="What is checked"
        hint="Each claim is read by rules first; nothing is judged by a model."
      />
      <CardBody className="grid gap-4 text-[13px] text-muted md:grid-cols-2">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="text-fg">Genes</span> by name, assay name or HGNC alias (survivin is
            BIRC5).
          </li>
          <li>
            <span className="text-fg">Direction</span>: up, down or unchanged, between the study's
            two groups (either way round).
          </li>
          <li>
            <span className="text-fg">Fold changes</span> (3.6-fold, 3.6×, a 72 % decrease, log2
            FC), <span className="text-fg">p-values</span> and words like significantly.
          </li>
          <li>
            <span className="text-fg">Robustness words</span> such as robustly, the{" "}
            <span className="text-fg">normaliser</span>, <span className="text-fg">n</span> and{" "}
            <span className="text-fg">efficiency</span> ranges.
          </li>
        </ul>
        {examples.length ? (
          <div>
            <p className="mb-1 font-medium text-fg">Examples written from this study</p>
            <ul className="space-y-1.5">
              {examples.map((e, i) => (
                <li key={i}>
                  <q className="text-fg">{e.text}</q> <span className="text-faint">{e.what}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
