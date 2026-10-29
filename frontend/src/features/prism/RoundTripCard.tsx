/**
 * Step 4: the round trip. After editing in Prism, the scientist saves the project (.pzfx); qPilot
 * reads it — uploaded, or from the folder it was saved in (the bundle folder when Prism runs on
 * this computer) — checks the bundle's checksums, and turns every change into a question with
 * its consequence: an excluded value asks why, a deleted one too, a changed one offers qPilot's
 * value back. Nothing is accepted silently. (The older sent_back/ CSV folder still works.)
 */
import { FileUp, FolderInput, Inbox as InboxIcon } from "lucide-react";
import { useQueries } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";
import { api, unwrap } from "@/api/client";
import { StageInbox } from "@/ui/proposal";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorPanel,
  Field,
  Input,
  JobCard,
  LoadingBlock,
  Select,
} from "@/ui";
import { count, dateTime, plural, shortHash } from "@/lib/format";
import {
  activeJob,
  usePrismBundles,
  useStartRoundTrip,
  useStartRoundTripUpload,
  type PrismBundleView,
  type PrismRoundTrip,
  type Proposal,
  type ProposalList,
  type Workspace,
} from "./api";
import { DIFF_KIND_WORDS } from "./words";

export function RoundTripCard({
  workspace,
  inbox,
}: {
  workspace: Workspace;
  inbox: { data?: ProposalList; isPending: boolean; error: unknown; refetch: () => unknown };
}) {
  const bundles = usePrismBundles(workspace.key);
  const start = useStartRoundTrip(workspace.key);
  const upload = useStartRoundTripUpload(workspace.key);
  const [file, setFile] = useState<File | null>(null);
  const fileId = useId();
  const [jobId, setJobId] = useState<string | null>(null);
  const running = activeJob(workspace, "prism.roundtrip");
  const shownJob = jobId ?? running?.id ?? null;

  // newest first; only bundles this launch wrote can be read back from the page
  const list = useMemo(
    () =>
      (bundles.data ?? []).filter((b): b is PrismBundleView & { id: string } =>
        Boolean(b.id && b.round_trip),
      ),
    [bundles.data],
  );
  const older = (bundles.data?.length ?? 0) - list.length;
  const [bundleId, setBundleId] = useState<string | undefined>(undefined);
  const bundle = list.find((b) => b.id === bundleId) ?? list[0];
  // The folder Prism sends this bundle's tables back to is suggested until the person types one.
  const [typed, setTyped] = useState<string | null>(null);
  const folder = typed ?? bundle?.sent_back_folder ?? "";
  const folderId = useId();
  const bundleSelectId = useId();

  const proposals = inbox.data?.proposals ?? [];
  const waiting = proposals.filter((p) => p.status === "proposed");
  const decided = proposals.filter((p) => p.status !== "proposed");
  const stale = useStaleConsequences(workspace.key, waiting);

  return (
    <Card
      as="section"
      aria-labelledby="prism-roundtrip-title"
      id="prism-step-roundtrip"
      tabIndex={-1}
      className="scroll-mt-4 outline-none"
    >
      <CardHeader
        id="prism-roundtrip-title"
        title="Round trip: what changed in Prism"
        hint="Every value excluded, deleted or changed in Prism comes back as a question, with what accepting it would change."
      />
      <CardBody className="flex flex-col gap-5">
        {bundles.isPending ? (
          <LoadingBlock label="Reading the bundles" lines={2} />
        ) : bundles.error ? (
          <ErrorPanel
            error={bundles.error}
            title="The bundles could not be listed"
            onRetry={() => void bundles.refetch()}
            compact
          />
        ) : !list.length ? (
          <EmptyState
            icon={<FolderInput />}
            title={
              older
                ? "No bundle from this launch to read back"
                : "Nothing has been sent to Prism yet"
            }
            compact
          >
            {older ? (
              <>
                {plural(older, "bundle was", "bundles were")} sent from this session before qPilot
                was last started (or from another page); the page reads back only bundles it wrote
                itself. Send again, or compare in a terminal with{" "}
                <span className="font-mono">qpilot prism diff</span>.
              </>
            ) : (
              <>
                Send to Prism first. After editing in Prism, save the project there and come back
                here.
              </>
            )}
          </EmptyState>
        ) : (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-[13px] text-fg marker:text-muted">
              <li>
                In Prism, leave values out with Edit &gt; Exclude, or change them, then save the
                project: File &gt; Save (keep the Prism XML format, .pzfx, if Prism asks).
              </li>
              <li>
                Choose the saved project here, or give the folder it is in: when Prism runs on this
                computer that is the bundle folder, already filled in.
              </li>
              <li>
                Each exclusion, deletion or change comes back below as a question, with what it does
                to the conclusions.
              </li>
            </ol>
            <div className="flex flex-col gap-4">
              <Field label="Bundle sent from this session" htmlFor={bundleSelectId}>
                <Select
                  id={bundleSelectId}
                  value={bundle?.id}
                  onValueChange={(v) => {
                    setBundleId(v);
                    setTyped(null);
                  }}
                  options={list.map((b) => ({
                    value: b.id,
                    label: bundleLabel(b),
                    hint: shortHash(b.bundle_sha256, 12),
                  }))}
                />
              </Field>
              {bundle && !bundle.current ? (
                <p className="text-[12.5px] text-warn">
                  This bundle was sent for an earlier analysis (a choice or an accepted exclusion
                  has changed it since). What it brings back is compared with that analysis; send
                  again to edit projects of the current one.
                </p>
              ) : null}
              <form
                className="flex flex-col gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!bundle || !file) return;
                  upload.mutate(
                    { bundle: bundle.id, file },
                    { onSuccess: ({ job }) => setJobId(job.id) },
                  );
                }}
              >
                <Field
                  label="The project Prism saved (.pzfx)"
                  htmlFor={fileId}
                  hint="From any computer: the file is read here and kept with the bundle."
                >
                  <input
                    id={fileId}
                    type="file"
                    accept=".pzfx"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="block w-full text-[13px] text-fg file:mr-3 file:rounded-md file:border file:border-line file:bg-surface-2 file:px-2.5 file:py-1 file:text-[12.5px] file:text-fg hover:file:border-line-strong"
                  />
                </Field>
                <div>
                  <Button
                    type="submit"
                    variant="primary"
                    icon={<FileUp />}
                    loading={upload.isPending}
                    disabled={!bundle || !file || Boolean(running)}
                  >
                    Read the saved project
                  </Button>
                </div>
              </form>
              <form
                className="flex flex-col gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!bundle || !folder.trim()) return;
                  start.mutate(
                    { bundle: bundle.id, folder: folder.trim() },
                    { onSuccess: ({ job }) => setJobId(job.id) },
                  );
                }}
              >
                <Field
                  label="Or the folder (or file) it was saved in"
                  htmlFor={folderId}
                  hint="On this computer, inside your home folder or qPilot's export folder; links and the study store are refused. The send_back folder of the Prism scripts works too."
                >
                  <Input
                    id={folderId}
                    value={folder}
                    onChange={(e) => setTyped(e.target.value)}
                    placeholder="~/Documents/qpilot-prism"
                    spellCheck={false}
                    autoComplete="off"
                    className="font-mono"
                  />
                </Field>
                <div>
                  <Button
                    type="submit"
                    variant="secondary"
                    icon={<FolderInput />}
                    loading={start.isPending}
                    disabled={!bundle || !folder.trim() || Boolean(running)}
                  >
                    Read what came back
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}

        {start.error || upload.error ? (
          <ErrorPanel
            error={start.error ?? upload.error}
            title="Could not read what came back from Prism"
            compact
          />
        ) : null}
        {shownJob ? (
          <JobCard id={shownJob} onDismiss={() => setJobId(null)}>
            {(result) => (result ? <RoundTripSummary result={result as PrismRoundTrip} /> : null)}
          </JobCard>
        ) : null}

        <section aria-labelledby="prism-questions-title" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 id="prism-questions-title" className="text-[14px] font-semibold text-fg">
              Questions from Prism
            </h3>
            {proposals.length ? (
              <p className="text-[12px] text-muted">
                {count(waiting.length)} waiting · {count(decided.length)} decided
              </p>
            ) : null}
          </div>
          <StageInbox
            sid={workspace.key}
            stage="roundtrip"
            resultsVisible={workspace.results_visible}
            label="Questions from Prism"
            empty={
              <EmptyState icon={<InboxIcon />} title="No questions yet" compact>
                When the tables come back with a value changed, excluded or deleted, each one is
                asked here — with what it does to the conclusions.
              </EmptyState>
            }
            cardExtra={(p) =>
              basisStudy(p) && basisStudy(p) !== workspace.study_id ? (
                <p className="text-[12.5px] text-muted">
                  About a bundle sent for an earlier analysis.
                </p>
              ) : null
            }
            cardProps={(p) => ({ stale: stale[p.id] ?? null })}
          />
        </section>
      </CardBody>
    </Card>
  );
}

/** The study a round-trip consequence was computed for (its `basis`), when it says. */
function basisStudy(p: Proposal): string | null {
  const basis = (p.consequence as { basis?: { study_id?: unknown } } | null | undefined)?.basis;
  return typeof basis?.study_id === "string" ? basis.study_id : null;
}

function bundleLabel(b: PrismBundleView): string {
  return `Sent ${dateTime(b.at)} · ${b.current ? "this analysis" : "an earlier analysis"}`;
}

export function RoundTripSummary({ result }: { result: PrismRoundTrip }) {
  const byKind = result.items.reduce<Record<string, number>>(
    (acc, it) => ({ ...acc, [it.kind]: (acc[it.kind] ?? 0) + 1 }),
    {},
  );
  return (
    <div className="flex flex-col gap-2 text-[13px] text-fg">
      <p>
        {result.items.length
          ? result.message
          : "No differences: the tables hold exactly what qPilot wrote."}
      </p>
      {result.items.length ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Differences by kind">
          {Object.entries(byKind).map(([kind, n]) => (
            <li key={kind}>
              <Badge tone={kind === "changed" ? "danger" : "warn"}>
                {count(n)} {DIFF_KIND_WORDS[kind] ?? kind}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
      {result.refused.length ? (
        <div className="text-[12.5px] text-muted">
          <p>Not asked ({count(result.refused.length)}):</p>
          <ul className="list-disc pl-5">
            {result.refused.map((r, i) => (
              <li key={i}>
                {r.subject ? <span className="font-mono">{r.subject}</span> : null}
                {r.subject && r.reason ? ": " : null}
                {r.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {result.notes.length ? (
        <ul className="list-disc pl-5 text-[12.5px] text-muted">
          {result.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * Why each waiting question's consequence no longer holds (the exclusions accepted since, or the
 * decisions, moved): the card then hides its numbers, and the server would refuse it anyway.
 */
function useStaleConsequences(sid: string, waiting: Proposal[]): Record<string, string | null> {
  const views = useQueries({
    queries: waiting
      .filter((p) => p.kind === "prism.exclusion_reason")
      .map((p) => ({
        queryKey: ["w", sid, "proposal", p.id],
        queryFn: () =>
          unwrap(
            api.GET("/api/sessions/{sid}/proposals/{pid}", {
              params: { path: { sid, pid: p.id } },
            }),
          ),
      })),
  });
  const out: Record<string, string | null> = {};
  for (const v of views) if (v.data) out[v.data.proposal.id] = v.data.stale_consequence ?? null;
  return out;
}
