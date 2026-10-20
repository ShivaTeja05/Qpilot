/**
 * Step 4: the round trip. After editing in Prism, the scientist runs `send_back.pzc` there; qPilot
 * reads the folder Prism exported the tables into, checks the bundle's checksums, and turns every
 * change into a question with its consequence. Nothing is accepted silently.
 */
import { FolderInput, Inbox as InboxIcon } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, ErrorPanel, Field, Input, JobCard, LoadingBlock, Select } from "@/ui";
import { count, dateTime, ofTotal, plural, shortHash } from "@/lib/format";
import {
  activeJob,
  usePrismBundles,
  useStartRoundTrip,
  type BundleEntry,
  type ProposalList,
  type RoundTripResult,
  type Workspace,
} from "./api";
import { ProposalItem } from "./Inbox";
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
  const [jobId, setJobId] = useState<string | null>(null);
  const running = activeJob(workspace, "roundtrip");
  const shownJob = jobId ?? running?.id ?? null;

  const list = useMemo(() => [...(bundles.data ?? [])].reverse(), [bundles.data]);
  const [bundleId, setBundleId] = useState<string | undefined>(undefined);
  const bundle = list.find((b) => b.id === bundleId) ?? list[0];
  // The folder Prism sends this bundle's tables back to is suggested until the person types one.
  const [typed, setTyped] = useState<string | null>(null);
  const folder = typed ?? bundle?.sent_back_dir ?? bundle?.suggested_folder ?? "";
  const folderId = useId();
  const bundleSelectId = useId();

  const proposals = inbox.data?.proposals ?? [];
  const waiting = proposals.filter((p) => p.status === "proposed");
  const decided = proposals.filter((p) => p.status !== "proposed");

  return (
    <Card as="section" aria-labelledby="prism-roundtrip-title" id="prism-step-roundtrip" tabIndex={-1} className="scroll-mt-4 outline-none">
      <CardHeader
        id="prism-roundtrip-title"
        title="Round trip: what changed in Prism"
        hint="Every value changed, excluded or deleted in Prism comes back as a question, with what accepting it would change."
      />
      <CardBody className="flex flex-col gap-5">
        {bundles.isPending ? (
          <LoadingBlock label="Reading the bundles" lines={2} />
        ) : bundles.error ? (
          <ErrorPanel error={bundles.error} title="The bundles could not be listed" onRetry={() => void bundles.refetch()} compact />
        ) : !list.length ? (
          <EmptyState icon={<FolderInput />} title="Nothing has been sent to Prism yet" compact>
            Send to Prism first. After editing in Prism, run <span className="font-mono">send_back.pzc</span> there and come
            back here.
          </EmptyState>
        ) : (
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-[13px] text-fg marker:text-muted">
              <li>In Prism, make your edits and save the projects.</li>
              <li>
                Run <span className="font-mono">send_back.pzc</span> from the bundle folder: Prism exports each table to its{" "}
                <span className="font-mono">sent_back</span> folder.
              </li>
              <li>Choose the bundle, give that folder, and read what came back.</li>
            </ol>
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (!bundle || !folder.trim()) return;
                start.mutate(
                  { bundle: bundle.id, folder: folder.trim(), expected_head: inbox.data?.head ?? null },
                  { onSuccess: ({ job }) => setJobId(job.id) },
                );
              }}
            >
              <Field label="Bundle sent from this session" htmlFor={bundleSelectId}>
                <Select
                  id={bundleSelectId}
                  value={bundle?.id}
                  onValueChange={(v) => {
                    setBundleId(v);
                    setTyped(null);
                  }}
                  options={list.map((b) => ({ value: b.id, label: bundleLabel(b, workspace.study_id), hint: shortHash(b.bundle_sha256, 12) }))}
                />
              </Field>
              {bundle && !isCurrent(bundle, workspace.study_id) ? (
                <p className="text-[12.5px] text-warn">
                  This bundle was sent for an earlier analysis: the choices changed since, so no consequences can be computed.
                  Send again and edit the new projects.
                </p>
              ) : null}
              <Field
                label="Folder Prism sent the tables back to"
                htmlFor={folderId}
                hint="On this computer, inside your home folder or qPilot's export folder; links and the study store are refused."
              >
                <Input
                  id={folderId}
                  value={folder}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder="~/Documents/qpilot-prism/sent_back"
                  spellCheck={false}
                  autoComplete="off"
                  className="font-mono"
                />
              </Field>
              <div>
                <Button
                  type="submit"
                  variant="primary"
                  icon={<FolderInput />}
                  loading={start.isPending}
                  disabled={!bundle || !folder.trim() || Boolean(running)}
                >
                  Read what came back
                </Button>
              </div>
            </form>
          </div>
        )}

        {start.error ? <ErrorPanel error={start.error} title="Could not read what came back from Prism" compact /> : null}
        {shownJob ? (
          <JobCard id={shownJob} onDismiss={() => setJobId(null)}>
            {(result) => <RoundTripSummary result={(result ?? { items: [], notes: [] }) as RoundTripResult} />}
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
          {inbox.isPending ? (
            <LoadingBlock label="Reading the questions" lines={2} />
          ) : inbox.error ? (
            <ErrorPanel error={inbox.error} title="The questions could not be read" onRetry={() => void inbox.refetch()} compact />
          ) : !proposals.length ? (
            <EmptyState icon={<InboxIcon />} title="No questions yet" compact>
              When the tables come back with a value changed, excluded or deleted, each one is asked here — with what it does
              to the conclusions.
            </EmptyState>
          ) : (
            <ul className="flex flex-col gap-3">
              {[...waiting, ...decided].map((p) => (
                <li key={p.id}>
                  <ProposalItem sid={workspace.key} proposal={p} head={inbox.data?.head ?? null} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </CardBody>
    </Card>
  );
}

function isCurrent(b: BundleEntry, studyId: string | null | undefined): boolean {
  return b.current ?? b.study_id === studyId;
}

function bundleLabel(b: BundleEntry, studyId: string | null | undefined): string {
  return `Sent ${dateTime(b.at)} · ${isCurrent(b, studyId) ? "this analysis" : "an earlier analysis"}`;
}

export function RoundTripSummary({ result }: { result: RoundTripResult }) {
  const items = result.items ?? [];
  const added = result.inbox?.proposed?.length ?? 0;
  const combined = result.combined_consequence;
  const byKind = items.reduce<Record<string, number>>((acc, it) => ({ ...acc, [it.kind]: (acc[it.kind] ?? 0) + 1 }), {});
  return (
    <div className="flex flex-col gap-2 text-[13px] text-fg">
      <p>
        {items.length ? `${plural(items.length, "difference")} since the export` : "No differences: Prism sent back exactly what qPilot wrote"}
        {items.length ? `; ${plural(added, "question")} added below.` : "."}
      </p>
      {items.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {Object.entries(byKind).map(([kind, n]) => (
            <li key={kind}>
              <Badge tone={kind === "changed" ? "danger" : "warn"}>
                {count(n)} {DIFF_KIND_WORDS[kind] ?? kind}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
      {combined && combined.exclusions.length > 1 ? (
        <p>
          All {count(combined.exclusions.length)} exclusions together change{" "}
          <strong className={combined.n_conclusions_changed ? "text-danger" : "text-ok"}>
            {ofTotal(combined.n_conclusions_changed, combined.n_genes)}
          </strong>{" "}
          conclusions{combined.changed_genes.length ? ` (${combined.changed_genes.join(", ")})` : ""}.
        </p>
      ) : null}
      {result.notes?.length ? (
        <ul className="list-disc pl-5 text-[12.5px] text-muted">
          {result.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
