/**
 * Where to look (`GET …/where-to-look`): from one gene, one sample or one well (`PLATE:WELL`) to
 * the places a person should look, at the analysis in use. The engine's sentences first (every
 * number a cited fact), then each place: what it fails (in words), what each option there does
 * to the calls, and **Decide…** where an option changes a call. In a Studio session (its current
 * analysis) Decide… opens the place's options and a reason box: a set-aside leaves the wells out
 * of the analysis and the study is analysed again (`POST …/where-to-look/decide`, Run Gate's
 * path; see `SetAside.tsx`), and what a person set aside is listed with Put the wells back. For a
 * study analysed outside Studio, Decide… opens the place as a Decision Card on Results (`POST
 * …/where-to-look/open`; recorded, the numbers stay as analysed) and the panel says how to leave
 * the wells out (open the file in Studio). A view that is out of date (409 `stale`) is read
 * again and says so; a study whose wells are still being read (409 `loading`) follows the job.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CircleCheck,
  CircleMinus,
  MoveHorizontal,
  RefreshCw,
  Search,
} from "lucide-react";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation } from "wouter";
import { ApiError, type Schemas } from "@/api/client";
import { count } from "@/lib/format";
import { refreshWorkspace, reportWriteError } from "@/shell/writes";
import { sectionPath } from "@/shell/sections";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorPanel,
  Field,
  Input,
  JobCard,
  LoadingBlock,
  SegmentedControl,
  Select,
  toast,
} from "@/ui";
import {
  decidePlace,
  isNotFound,
  loadingJob,
  openPlace,
  useWhere,
  type PlaceOpened,
  type TraceDecided,
  type TraceScope,
  type WhereKind,
  type WhereOption,
  type WherePlace,
  type WhereRoot,
  type WhereView,
} from "./api";
import { FactText } from "./FactText";
import { DecidePanel, SetAsideList, decidedToast } from "./SetAside";
import { TraceWaiting } from "./Waiting";
import { WELL_INPUT, WHERE_ROLE, WHERE_TONE, cannotWords, checkedWords, placeWords } from "./words";

type Workspace = Pick<Schemas["WorkspaceView"], "key" | "kind">;

const TOP = 3;
const MAX_TOP = 20;
const DECIDED = new Set(["decided", "auto_decided"]);

const KINDS: { value: WhereKind; label: string }[] = [
  { value: "gene", label: "A gene" },
  { value: "sample", label: "A sample" },
  { value: "well", label: "A well" },
];

function capital(text: string): string {
  return text ? text[0]!.toUpperCase() + text.slice(1) : text;
}

function ConsequenceIcon({ consequence }: { consequence: string }) {
  if (consequence === "changes_call") return <AlertTriangle aria-hidden />;
  if (consequence === "beyond_ci") return <MoveHorizontal aria-hidden />;
  return <CircleMinus aria-hidden />;
}

/** The analysis traced is the analysis in use; say whether a person's decisions changed it. */
export function analysisLine(view: Pick<WhereView, "planned">): string {
  return view.planned
    ? "Traced at the analysis in use: the planned one (no Decision Card is decided otherwise)."
    : "Traced at the analysis in use: your decisions on the Decision Cards changed it from the planned one.";
}

// ---- the panel ----------------------------------------------------------------------------------

export function WhereToLook({
  workspace,
  scope,
  genes,
  initial,
  level = 2,
}: {
  workspace: Workspace;
  scope: TraceScope;
  /** The study's compared genes, for the gene menu (empty while they load). */
  genes: readonly string[];
  /** What to trace straight away (a gene's trace page passes its gene). */
  initial?: WhereRoot;
  level?: 2 | 3;
}) {
  const ids = useId();
  const qc = useQueryClient();
  const [, navigate] = useLocation();
  const [kind, setKind] = useState<WhereKind>(initial?.kind ?? "gene");
  const [gene, setGene] = useState<string | undefined>(
    initial?.kind === "gene" ? initial.id : undefined,
  );
  const [sample, setSample] = useState(initial?.kind === "sample" ? initial.id : "");
  const [well, setWell] = useState(initial?.kind === "well" ? initial.id : "");
  const [wellError, setWellError] = useState<string | null>(null);
  const [root, setRoot] = useState<WhereRoot | null>(initial ?? null);
  const [top, setTop] = useState(TOP);
  /** Said once after a refused Decide…: the view was read again. */
  const [notice, setNotice] = useState<string | null>(null);
  /** The study's wells were being read when Decide… was pressed: its job. */
  const [openJob, setOpenJob] = useState<string | null>(null);
  const q = useWhere(scope, root, top);

  const trace = (next: WhereRoot) => {
    setRoot(next);
    setTop(TOP);
    setNotice(null);
  };
  const traceSample = (s: string) => {
    setKind("sample");
    setSample(s);
    trace({ kind: "sample", id: s });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (kind === "sample") {
      const s = sample.trim();
      if (s) trace({ kind: "sample", id: s });
    } else if (kind === "well") {
      const w = well.trim();
      if (!WELL_INPUT.test(w)) {
        setWellError("Write the plate's name, a colon, then the well: PLATE:WELL.");
        return;
      }
      setWellError(null);
      trace({ kind: "well", id: w });
    }
  };

  const goToCard = (cardId: string) => navigate(sectionPath(workspace, "results", "card", cardId));
  const open = useMutation({
    mutationFn: (p: { view: WhereView; place: WherePlace; root: WhereRoot }) =>
      openPlace(scope.studyId!, {
        kind: p.root.kind,
        id: p.root.id,
        rank: p.place.rank,
        expected_head: p.view.head,
        ...(p.view.comparison ? { comparison: p.view.comparison } : {}),
      }),
    onSuccess: async (done: PlaceOpened) => {
      setNotice(null);
      await refreshWorkspace(qc, scope.key);
      toast.success(done.opened ? "Opened as a Decision Card" : "Already a Decision Card", {
        description: done.message,
        action: { label: "Go to the card", onClick: () => goToCard(done.card_id) },
        duration: 10_000,
      });
    },
    onError: (error) => {
      const job = loadingJob(error);
      if (job) {
        setOpenJob(job.id);
        return;
      }
      if (error instanceof ApiError && error.stale) {
        setNotice(error.message);
        void refreshWorkspace(qc, scope.key);
        toast.info("Something was decided since this trace was shown", {
          description: "Here is the trace again; look at it before you decide.",
        });
        return;
      }
      reportWriteError(qc, error, scope.key);
    },
  });

  const decide = useMutation({
    mutationFn: (p: {
      view: WhereView;
      place: WherePlace;
      root: WhereRoot;
      option: string;
      reason: string;
    }) =>
      decidePlace(scope.studyId!, {
        kind: p.root.kind,
        id: p.root.id,
        rank: p.place.rank,
        option: p.option,
        reason: p.reason,
        expected_head: p.view.head,
        expected_inbox: p.view.inbox_head ?? null,
        ...(p.view.comparison ? { comparison: p.view.comparison } : {}),
      }),
    onSuccess: async (done: TraceDecided) => {
      setNotice(null);
      decidedToast(done);
      await refreshWorkspace(qc, scope.key);
    },
    onError: (error) => {
      const job = loadingJob(error);
      if (job) {
        setOpenJob(job.id);
        return;
      }
      if (error instanceof ApiError && error.stale) {
        setNotice(error.message);
        void refreshWorkspace(qc, scope.key);
        toast.info("Something was decided since this trace was shown", {
          description: "Here is the trace again; look at it before you decide.",
        });
        return;
      }
      reportWriteError(qc, error, scope.key);
    },
  });

  const view = q.data;
  return (
    <Card as="section" aria-labelledby={`${ids}-title`}>
      <CardHeader
        id={`${ids}-title`}
        level={level}
        title="Where to look"
        hint="From a gene's result, a sample or a well to the places worth a look, ranked by what each option there does to the calls. Reading it changes nothing."
      />
      <CardBody className="@container flex flex-col gap-4">
        <SetAsideList scope={scope} heading={level === 2 ? "h3" : "h4"} />
        <form onSubmit={submit} className="flex flex-col gap-3" aria-label="What to trace">
          <SegmentedControl
            label="What to trace"
            value={kind}
            onValueChange={(k) => {
              setKind(k);
              setWellError(null);
            }}
            options={KINDS}
            className="self-start"
          />
          <div className="flex flex-wrap items-end gap-2">
            {kind === "gene" ? (
              <Field label="Gene" className="w-full max-w-xs">
                <Select
                  value={gene ?? ""}
                  onValueChange={(g) => {
                    setGene(g);
                    trace({ kind: "gene", id: g });
                  }}
                  placeholder={genes.length ? "Choose a gene" : "Reading the study's genes…"}
                  disabled={!genes.length}
                  options={genes.map((g) => ({ value: g, label: g }))}
                />
              </Field>
            ) : kind === "sample" ? (
              <>
                <Field
                  label="Sample"
                  hint="The sample's name as the file names it."
                  className="w-full max-w-xs"
                >
                  <Input
                    value={sample}
                    onChange={(e) => setSample(e.target.value)}
                    maxLength={200}
                    autoComplete="off"
                    spellCheck={false}
                  />
                </Field>
                <Button type="submit" size="sm" icon={<Search />} disabled={!sample.trim()}>
                  Trace
                </Button>
              </>
            ) : (
              <>
                <Field
                  label="Well"
                  hint="The plate's name as the file names it, a colon, then the well (PLATE:WELL)."
                  error={wellError}
                  className="w-full max-w-sm"
                >
                  <Input
                    value={well}
                    onChange={(e) => {
                      setWell(e.target.value);
                      setWellError(null);
                    }}
                    maxLength={200}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="PLATE:WELL"
                  />
                </Field>
                <Button type="submit" size="sm" icon={<Search />} disabled={!well.trim()}>
                  Trace
                </Button>
              </>
            )}
          </div>
        </form>

        {notice ? (
          <p
            role="status"
            className="flex items-start gap-2 rounded-lg border border-info/30 bg-info-soft/50 p-3 text-[13px] text-fg"
          >
            <RefreshCw className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
            <span>{notice}</span>
          </p>
        ) : null}
        {openJob ? (
          <div role="status" className="flex flex-col gap-2">
            <p className="text-[13px] text-muted">
              Trace is reading the study&rsquo;s wells from its file first; nothing was opened yet.
            </p>
            <JobCard id={openJob} onDismiss={() => setOpenJob(null)}>
              {() => (
                <p className="text-[13px] text-fg">Done: press Decide&hellip; again to open it.</p>
              )}
            </JobCard>
          </div>
        ) : null}

        {!root ? (
          <p className="text-[13px] text-muted">
            Choose a gene, or type a sample or a well, to see the places to look at behind it.
          </p>
        ) : !view ? (
          q.error ? (
            isNotFound(q.error) ? (
              <ErrorPanel compact title="Nothing to trace by that name" error={q.error} />
            ) : (
              <TraceWaiting
                error={q.error}
                onRetry={() => void q.refetch()}
                what={`the ${root.kind} ${root.id}`}
              />
            )
          ) : (
            <LoadingBlock label="Tracing" lines={4} />
          )
        ) : (
          <WhereResult
            workspace={workspace}
            view={view}
            root={root}
            heading={level === 2 ? "h3" : "h4"}
            busy={q.isFetching}
            deciding={
              open.isPending
                ? (open.variables?.place.rank ?? null)
                : decide.isPending
                  ? (decide.variables?.place.rank ?? null)
                  : null
            }
            onDecide={(place) => open.mutate({ view, place, root })}
            onApply={(place, option, reason) =>
              decide.mutate({ view, place, root, option, reason })
            }
            onOpenCard={goToCard}
            onMore={(n) => setTop(n)}
            onSample={traceSample}
          />
        )}
      </CardBody>
    </Card>
  );
}

// ---- one answer (pure: data in, events out) ----------------------------------------------------

export function WhereResult({
  workspace,
  view,
  root,
  heading: H = "h3",
  busy,
  deciding,
  onDecide,
  onApply,
  onOpenCard,
  onMore,
  onSample,
}: {
  workspace: Workspace;
  view: WhereView;
  root: WhereRoot;
  /** The level of its own headings (one below the panel's title). */
  heading?: "h3" | "h4";
  busy?: boolean;
  /** The rank whose Decide… is being sent. */
  deciding: number | null;
  /** Outside Studio: open the place as a Decision Card. */
  onDecide: (place: WherePlace) => void;
  /** In a Studio session: apply the person's option at the place, with the reason. */
  onApply?: (place: WherePlace, option: string, reason: string) => void;
  onOpenCard: (cardId: string) => void;
  onMore: (top: number) => void;
  onSample: (sample: string) => void;
}) {
  const ids = useId();
  const checked = checkedWords(view.checked_nothing_found);
  const cannot = cannotWords(view.cannot_show);
  const decidable = view.places.some((p) => p.can_decide && (view.can_apply || !p.card_status));
  const total = view.places.length + view.n_more;
  const H4 = H === "h3" ? "h4" : "h5";
  return (
    <div className="flex flex-col gap-4" aria-busy={busy}>
      <p className="text-[12px] text-muted">{analysisLine(view)}</p>
      {view.comparison_note ? (
        <p className="text-[12px] text-muted" data-testid="where-comparison">
          {view.comparison_note}
        </p>
      ) : null}
      <div className="grid min-w-0 gap-4 @5xl:grid-cols-2 [&>*]:min-w-0">
        <section aria-labelledby={`${ids}-words`}>
          <H id={`${ids}-words`} className="mb-1.5 text-xs font-medium text-muted">
            In words
          </H>
          <div className="flex flex-col gap-1 rounded-lg bg-sunken/60 p-3 text-[13px] leading-relaxed text-fg">
            {view.text.map((t, i) => (
              <p key={i}>
                <FactText text={t} />
              </p>
            ))}
          </div>
        </section>
        <section aria-labelledby={`${ids}-places`}>
          <H id={`${ids}-places`} className="mb-1.5 text-xs font-medium text-muted">
            {view.places.length === 1
              ? "The place to look"
              : view.places.length
                ? `The ${count(view.places.length)} places, most consequential first`
                : "No place to look at"}
          </H>
          {view.places.length ? (
            <ol className="flex flex-col gap-3" aria-label="Places to look">
              {view.places.map((p) => (
                <PlaceRow
                  key={`${p.rank}:${p.card_id}`}
                  workspace={workspace}
                  place={p}
                  root={root}
                  canApply={view.can_apply}
                  deciding={deciding}
                  onDecide={onDecide}
                  onApply={onApply}
                  onOpenCard={onOpenCard}
                />
              ))}
            </ol>
          ) : (
            <p className="text-[13px] text-muted">
              {view.answer === "absent"
                ? "It is in no comparison, so nothing behind it moves a call; why is said below."
                : `No well or sample behind this ${root.kind} is unusual.`}
            </p>
          )}
          {view.n_more > 0 ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-muted">
              <span>
                {count(view.n_more)} more {view.n_more === 1 ? "place" : "places"} found, not shown.
              </span>
              {view.places.length < MAX_TOP ? (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => onMore(Math.min(MAX_TOP, total))}
                >
                  {total <= MAX_TOP
                    ? `Show all ${count(total)}`
                    : `Show the first ${count(MAX_TOP)}`}
                </Button>
              ) : null}
            </div>
          ) : null}
          {decidable ? <p className="mt-3 text-[12px] text-muted">{view.decide_note}</p> : null}
          {decidable && !view.can_apply && view.apply_note ? (
            <p className="mt-1 text-[12px] text-muted">{view.apply_note}</p>
          ) : null}
        </section>
      </div>

      {checked.length || cannot.length ? (
        <div className="grid gap-4 border-t border-line pt-3 md:grid-cols-2">
          {checked.length ? (
            <div>
              <H4 className="mb-1.5 text-xs font-medium text-muted">Checked, nothing found</H4>
              <ul className="flex list-disc flex-col gap-1 pl-4 text-[13px] text-fg">
                {checked.map((t) => (
                  <li key={t}>{capital(t)}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {cannot.length ? (
            <div>
              <H4 className="mb-1.5 text-xs font-medium text-muted">The data cannot show</H4>
              <ul className="flex list-disc flex-col gap-1 pl-4 text-[13px] text-fg">
                {cannot.map((t) => (
                  <li key={t}>{capital(t)}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {view.n_absent > 0 ? (
        <div className="border-t border-line pt-3">
          <H4 className="mb-1.5 text-xs font-medium text-muted">
            {view.n_absent === 1
              ? "1 sample is in no comparison"
              : `${count(view.n_absent)} samples are in no comparison`}
          </H4>
          <ul className="flex flex-col gap-1 text-[13px] text-fg">
            {view.absent.map((a) => (
              <li key={a.sample}>
                {root.kind === "sample" && root.id === a.sample ? (
                  <span className="font-medium">Sample {a.sample}</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => onSample(a.sample)}
                    className="rounded-sm font-medium text-accent underline-offset-4 hover:underline"
                  >
                    Sample {a.sample}
                  </button>
                )}
                : {a.why}.
              </li>
            ))}
          </ul>
          {view.n_absent > view.absent.length ? (
            <p className="mt-1 text-[12px] text-muted">
              and {count(view.n_absent - view.absent.length)} more; trace a sample to see its own.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PlaceRow({
  workspace,
  place,
  root,
  canApply,
  deciding,
  onDecide,
  onApply,
  onOpenCard,
}: {
  workspace: Workspace;
  place: WherePlace;
  root: WhereRoot;
  canApply: boolean;
  deciding: number | null;
  onDecide: (place: WherePlace) => void;
  onApply?: (place: WherePlace, option: string, reason: string) => void;
  onOpenCard: (cardId: string) => void;
}) {
  const where = placeWords(place);
  const tone = WHERE_TONE[place.consequence] ?? "neutral";
  const [choosing, setChoosing] = useState(false);
  let action: ReactNode;
  if (canApply && place.can_decide && onApply) {
    action = choosing ? null : (
      <Button
        size="sm"
        disabled={deciding != null}
        onClick={() => setChoosing(true)}
        aria-expanded={choosing}
      >
        Decide&hellip;<span className="sr-only"> {where}</span>
      </Button>
    );
  } else if (place.card_status && DECIDED.has(place.card_status)) {
    action = (
      <>
        <Badge tone="ok" icon={<CircleCheck aria-hidden />}>
          Decided
        </Badge>
        <Button
          size="sm"
          variant="ghost"
          icon={<ArrowUpRight />}
          onClick={() => onOpenCard(place.card_id)}
        >
          See it on Results
        </Button>
      </>
    );
  } else if (place.card_status) {
    action = (
      <Button
        size="sm"
        variant="secondary"
        icon={<ArrowUpRight />}
        onClick={() => onOpenCard(place.card_id)}
      >
        Open on Results<span className="sr-only">: {where}</span>
      </Button>
    );
  } else if (place.can_decide) {
    action = (
      <Button
        size="sm"
        loading={deciding === place.rank}
        disabled={deciding != null}
        onClick={() => onDecide(place)}
      >
        Decide&hellip;<span className="sr-only"> {where}</span>
      </Button>
    );
  } else {
    action = (
      <p className="text-[12px] text-muted">
        Nothing to decide from here: no option at this place changes{" "}
        {root.kind === "gene" ? `${root.id}'s call` : "a call"}.
      </p>
    );
  }
  return (
    <li className="rounded-lg border border-line bg-surface p-3">
      <div className="flex items-start gap-2">
        <span className="tabular grid size-6 shrink-0 place-items-center rounded-full bg-surface-2 text-xs font-semibold text-fg">
          {place.rank}
        </span>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 pt-0.5">
          <span className="min-w-0 text-[13px] font-medium break-words text-fg">{where}</span>
          <Badge
            tone={tone === "danger" ? "danger" : tone === "warn" ? "warn" : "neutral"}
            icon={<ConsequenceIcon consequence={place.consequence} />}
          >
            {capital(place.consequence_word)}
          </Badge>
        </div>
      </div>
      <p className="mt-1 text-[12px] text-muted">
        {WHERE_ROLE[place.role] ?? capital(place.role.replace(/_/g, " "))}
        {place.target ? ` · ${place.target}` : ""}
      </p>
      {place.checks.length ? (
        <ul className="mt-2 flex flex-col gap-1.5 text-[13px]">
          {place.checks.map((c) => (
            <li key={c.code}>
              <span className="text-fg">Looks like {c.looks_like}.</span>{" "}
              <span className="text-muted">
                Consistent with {c.consistent_with}. What to check: {c.what_to_check}.
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[13px] text-muted">
          No check fails here; it is listed for what its options do to the calls.
        </p>
      )}
      <div className="mt-2 border-t border-line pt-2">
        <p className="text-[12px] font-medium text-muted">What each option does</p>
        <ul className="mt-1 flex flex-col gap-1 text-[12px]">
          {place.options.map((o) => (
            <OptionRow key={o.id} workspace={workspace} option={o} />
          ))}
        </ul>
      </div>
      {action ? <div className="mt-3 flex flex-wrap items-center gap-2">{action}</div> : null}
      {choosing && onApply ? (
        <DecidePanel
          place={place}
          busy={deciding === place.rank}
          onDecide={(option, reason) => onApply(place, option, reason)}
          onCancel={() => setChoosing(false)}
        />
      ) : null}
    </li>
  );
}

function OptionRow({ workspace, option }: { workspace: Workspace; option: WhereOption }) {
  const tone = WHERE_TONE[option.consequence] ?? "neutral";
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span className="text-fg">{option.label}:</span>
      <span
        className={
          tone === "danger"
            ? "inline-flex items-center gap-1 font-medium text-danger [&_svg]:size-3"
            : tone === "warn"
              ? "inline-flex items-center gap-1 font-medium text-warn [&_svg]:size-3"
              : "inline-flex items-center gap-1 text-muted [&_svg]:size-3"
        }
      >
        <ConsequenceIcon consequence={option.consequence} />
        {option.consequence_word}
      </span>
      {option.changed_calls.length ? (
        <span className="text-muted">
          · {option.changed_calls.length === 1 ? "the call that changes" : "calls that change"}:{" "}
          {option.changed_calls.map((g, i) => (
            <span key={g}>
              {i ? ", " : ""}
              <Link
                href={sectionPath(workspace, "trace", g)}
                className="font-medium text-accent underline-offset-4 hover:underline"
              >
                {g}
              </Link>
            </span>
          ))}
        </span>
      ) : null}
    </li>
  );
}
