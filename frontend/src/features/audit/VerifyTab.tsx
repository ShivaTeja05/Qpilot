/**
 * Verify: the audit's checksums (every file listed in AUDIT.sha256 still matches), and its
 * binding to the record (the same study and input file, the decision chain it describes, and
 * whether decisions were made since). With the command that checks it outside the page.
 */
import { CheckCircle2, CircleAlert, History, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import { cn } from "@/lib/cn";
import { bytes, count, plural } from "@/lib/format";
import { sectionPath, type SectionProps } from "@/shell/sections";
import {
  Card,
  CardBody,
  CardHeader,
  CommandLine,
  ErrorPanel,
  Hash,
  KeyValues,
  LoadingBlock,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { useAuditVerify, type AuditTarget } from "./api";
import { scientific } from "./HowTab";
import type { AuditManifest, AuditVerify } from "./types";

type Tone = "ok" | "warn" | "bad";

export function VerifyTab({
  workspace,
  target,
  manifest,
  dir,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  target: AuditTarget;
  manifest: AuditManifest;
  /** The audit's folder on this computer, when the server says it. */
  dir?: string | null;
}) {
  const verify = useAuditVerify(target);
  const v = verify.data;
  const audited = v?.binding?.audited_head ?? manifest.chain_head ?? null;
  const current = v?.binding?.current_head ?? workspace.decisions_head ?? null;
  const isCurrent = v?.binding?.is_current ?? (audited && current ? audited === current : null);
  const inChain = v?.binding?.head_in_chain ?? null;
  const since = v?.binding?.decisions_since ?? null;
  const r = manifest.reproduces_qpilot;

  return (
    <div className="space-y-5">
      <Card as="section" aria-labelledby="verify-checks">
        <CardHeader
          id="verify-checks"
          title="Is this audit intact, and is it this study's?"
          hint="Checked by qPilot when you opened this tab, from the files on this computer."
        />
        <CardBody>
          {verify.isError ? (
            <ErrorPanel
              compact
              error={verify.error}
              title="The audit could not be checked"
              onRetry={() => void verify.refetch()}
            />
          ) : null}
          <ul className="divide-y divide-line">
            <Check
              tone={!v ? null : v.ok ? "ok" : "bad"}
              title={
                !v
                  ? "Checking the files…"
                  : v.ok
                    ? "Every file matches its checksum"
                    : "The audit's files do not match their checksums"
              }
            >
              {v ? (
                v.ok ? (
                  <>
                    {plural(v.files?.length ?? 0, "file")} listed in AUDIT.sha256, none changed,
                    none missing, none added; the lock matches the manifest and the input file.
                  </>
                ) : (
                  <ul className="list-disc pl-5">
                    {v.problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                )
              ) : null}
            </Check>
            <Check
              tone={r ? (r.ok ? "ok" : "bad") : null}
              title={
                r?.ok
                  ? "It reproduces qPilot's result"
                  : r
                    ? "It did not reproduce qPilot's result"
                    : "Reproduction not recorded"
              }
            >
              {r?.ok ? (
                <>
                  With every choice as planned,{" "}
                  {r.genes != null ? plural(r.genes, "gene") : "every gene"} gave qPilot's own fold
                  change and p-value: the largest difference was {scientific(r.max_abs_diff_log2fc)}{" "}
                  in log2 fold change (allowed: {scientific(r.tolerance)}).
                </>
              ) : null}
            </Check>
            <Check
              tone={
                manifest.study_id ? (manifest.study_id === target.studyId ? "ok" : "bad") : null
              }
              title={
                manifest.study_id === target.studyId
                  ? "It is this study's audit"
                  : "It names another study"
              }
            >
              Study {manifest.study_id ?? "—"}, from the file {manifest.source_file ?? "—"} (sha256{" "}
              <Hash value={manifest.input_sha256 ?? ""} length={12} />
              ).
            </Check>
            <Check
              tone={
                isCurrent == null ? null : isCurrent ? "ok" : inChain === false ? "bad" : "warn"
              }
              icon={isCurrent === false && inChain !== false ? <History /> : undefined}
              title={
                isCurrent == null
                  ? "The decision chain it describes"
                  : isCurrent
                    ? "It describes the current decisions"
                    : inChain === false
                      ? "Its decision chain is not this study's"
                      : "Decisions were made since it ran"
              }
            >
              Audited at chain <Hash value={audited ?? ""} length={12} />
              {current && !isCurrent ? (
                <>
                  ; the study is now at <Hash value={current} length={12} />
                  {since != null ? ` (${plural(since, "decision")} later)` : ""}. Its verdicts hold
                  for the earlier state; run the audit again to include them.
                </>
              ) : (
                "."
              )}
            </Check>
          </ul>
        </CardBody>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card as="section" aria-labelledby="verify-binding">
          <CardHeader
            id="verify-binding"
            title="What it is bound to"
            hint="From the audit's manifest."
          />
          <CardBody>
            <KeyValues
              rows={[
                [
                  "Study",
                  <span key="s" className="font-mono">
                    {manifest.study_id ?? "—"}
                  </span>,
                ],
                ["Input file", manifest.source_file ?? "—"],
                ["Input sha256", <Hash key="i" value={manifest.input_sha256 ?? ""} length={16} />],
                ["Design", <Hash key="d" value={manifest.design_hash ?? ""} length={16} />],
                ["Decision chain", <Hash key="c" value={manifest.chain_head ?? ""} length={16} />],
                [
                  "Lock (the plan)",
                  <Hash key="l" value={manifest.lock_sha256 ?? ""} length={16} />,
                ],
                ["Analyses", count(manifest.analyses)],
                [
                  "Checksums file",
                  v?.checksums_sha256 ? (
                    <Hash key="k" value={v.checksums_sha256} length={16} />
                  ) : (
                    "—"
                  ),
                ],
                ["Versions", versions(manifest)],
                ["Settings", settings(manifest)],
              ]}
            />
          </CardBody>
        </Card>
        <Card as="section" aria-labelledby="verify-cli">
          <CardHeader
            id="verify-cli"
            title="Check it yourself"
            hint="The same check from a terminal; with an exported Analysis Record it also checks the record verifies and contains the audited chain."
          />
          <CardBody className="space-y-3">
            <CommandLine
              command={`python -m qpilot.integration verify ${quote(dir ?? `simulator_audits/${target.studyId}`)}`}
            />
            <CommandLine
              command={`python -m qpilot.integration verify ${quote(dir ?? `simulator_audits/${target.studyId}`)} --record <record.zip>`}
            />
            <p className="text-[13px] text-muted">
              {dir ? null : <>The folder is in qPilot's study store, next to the study. </>}
              Export the record from{" "}
              <Link
                href={sectionPath(workspace, "record")}
                className="text-accent underline-offset-2 hover:underline"
              >
                Record
              </Link>
              ; the audit sits beside it, never inside it.
            </p>
          </CardBody>
        </Card>
      </div>

      <Files verify={v} loading={verify.isPending} />
    </div>
  );
}

function Check({
  tone,
  title,
  icon,
  children,
}: {
  tone: Tone | null;
  title: string;
  icon?: ReactNode;
  children?: ReactNode;
}) {
  const glyph =
    icon ??
    (tone === "ok" ? (
      <CheckCircle2 />
    ) : tone === "bad" ? (
      <XCircle />
    ) : tone === "warn" ? (
      <CircleAlert />
    ) : (
      <CircleAlert />
    ));
  const word =
    tone === "ok" ? "Passed" : tone === "bad" ? "Failed" : tone === "warn" ? "Note" : "Not known";
  return (
    <li className="flex gap-3 py-3 first:pt-0 last:pb-0">
      <span
        className={cn(
          "mt-0.5 shrink-0 [&_svg]:size-4",
          tone === "ok" && "text-ok",
          tone === "bad" && "text-danger",
          tone === "warn" && "text-info",
          tone == null && "text-faint",
        )}
      >
        {glyph}
        <span className="sr-only">{word}: </span>
      </span>
      <div className="min-w-0 text-sm">
        <p className="font-medium text-fg">{title}</p>
        {children ? <div className="mt-0.5 text-[13px] text-muted">{children}</div> : null}
      </div>
    </li>
  );
}

function Files({ verify, loading }: { verify: AuditVerify | undefined; loading: boolean }) {
  return (
    <Card as="section" aria-labelledby="verify-files">
      <CardHeader
        id="verify-files"
        title="The audit's files"
        hint="Each file's sha256, as listed in AUDIT.sha256."
      />
      <CardBody>
        {loading ? (
          <LoadingBlock lines={5} />
        ) : verify?.files?.length ? (
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>File</TH>
                  <TH numeric>Size</TH>
                  <TH>sha256</TH>
                </TR>
              </THead>
              <TBody>
                {verify.files.map((f) => (
                  <TR key={f.name}>
                    <TD className="font-mono text-xs">{f.name}</TD>
                    <TD numeric>{bytes(f.bytes)}</TD>
                    <TD>
                      <Hash value={f.sha256} length={16} />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        ) : (
          <p className="text-[13px] text-muted">The file list is not available.</p>
        )}
      </CardBody>
    </Card>
  );
}

function versions(m: AuditManifest): string {
  const v = m.versions ?? {};
  const parts = Object.entries(v).map(([k, x]) => `${k} ${x}`);
  return parts.length ? parts.join(" · ") : "—";
}

function settings(m: AuditManifest): string {
  const s = m.settings ?? {};
  const parts = [
    typeof s.permutations === "number" ? `${count(s.permutations)} permutations` : null,
    typeof s.seed === "number" ? `seed ${s.seed}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "—";
}

/** A path as one shell word. */
function quote(path: string): string {
  return /^[\w./-]+$/.test(path) ? path : `'${path.replace(/'/g, "'\\''")}'`;
}
