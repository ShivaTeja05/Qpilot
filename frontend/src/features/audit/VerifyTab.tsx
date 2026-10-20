/**
 * Verify: the audit's checksums (every file listed in AUDIT.sha256 still matches), and its
 * binding to the record (the same study and input file, the decision chain it describes, and
 * whether decisions were made since). With the command that checks it outside the page.
 */
import { CheckCircle2, CircleAlert, History, RefreshCw, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import { cn } from "@/lib/cn";
import { bytes, count, duration, plural } from "@/lib/format";
import { sectionPath, type SectionProps } from "@/shell/sections";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CommandLine,
  ErrorPanel,
  Hash,
  KeyValues,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { useAuditVerify, type AuditTarget } from "./api";
import { asSentence } from "./CannotRun";
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
  const r = manifest.reproduces_qpilot;
  // verify_audit's problems: the files' own, then (with the record) the binding's.
  const bindingProblems = (v?.problems ?? []).filter(isBindingProblem);
  const fileProblems = (v?.problems ?? []).filter((p) => !isBindingProblem(p));
  const audited = v?.audit_chain_head ?? manifest.chain_head ?? null;
  const head = v?.record_chain_head ?? workspace.decisions_head ?? null;
  const since = v?.decisions_since ?? null;
  const current = since != null ? since === 0 : audited && head ? audited === head : null;

  return (
    <div className="space-y-5">
      <Card as="section" aria-labelledby="verify-checks">
        <CardHeader
          id="verify-checks"
          title="Is this audit intact, and is it this study's?"
          hint="Checked by qPilot now, from the files on this computer: the audit's checksums, and the study's record written to a scratch folder and read back (nothing is kept)."
          actions={
            v ? (
              <Button
                size="sm"
                variant="ghost"
                icon={<RefreshCw />}
                loading={verify.isFetching}
                onClick={() => void verify.refetch()}
              >
                Check again
              </Button>
            ) : null
          }
        />
        <CardBody>
          {verify.isError ? (
            <ErrorPanel
              compact
              className="mb-3"
              error={verify.error}
              title="The audit could not be checked"
              onRetry={() => void verify.refetch()}
            />
          ) : null}
          <ul className="divide-y divide-line">
            <Check
              tone={!v ? null : fileProblems.length ? "bad" : "ok"}
              title={
                !v
                  ? verify.isError
                    ? "The files were not checked"
                    : "Checking the files…"
                  : fileProblems.length
                    ? "The audit's files do not match their checksums"
                    : "Every file matches its checksum"
              }
            >
              {v ? (
                fileProblems.length ? (
                  <Problems items={fileProblems} />
                ) : (
                  <>
                    {v.files_checked != null
                      ? `${plural(v.files_checked, "file")} listed in AUDIT.sha256: `
                      : ""}
                    none changed, none missing, none added; the lock matches the manifest and the
                    input file.
                  </>
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
              tone={!v ? null : !v.bound_to_record ? null : bindingProblems.length ? "bad" : "ok"}
              title={
                !v || !v.bound_to_record
                  ? "Its binding to the study's record"
                  : bindingProblems.length
                    ? "It does not belong to this study's record"
                    : "It belongs to this study's record"
              }
            >
              {v?.bound_to_record ? (
                bindingProblems.length ? (
                  <Problems items={bindingProblems} />
                ) : (
                  <>
                    The record verifies, names study {manifest.study_id ?? "—"} and the file{" "}
                    {manifest.source_file ?? "—"} (sha256{" "}
                    <Hash value={manifest.input_sha256 ?? ""} length={12} />) and contains the
                    decision chain the audit describes.
                  </>
                )
              ) : v ? (
                "Not checked against the record."
              ) : null}
            </Check>
            <Check
              tone={current == null ? null : current ? "ok" : "warn"}
              icon={current === false ? <History /> : undefined}
              title={
                current == null
                  ? "The decisions it describes"
                  : current
                    ? "It describes the current decisions"
                    : "Decisions were made since it ran"
              }
            >
              Audited at decision chain <Hash value={audited ?? ""} length={12} />
              {current === false ? (
                <>
                  ; the study is now at <Hash value={head ?? ""} length={12} />
                  {since ? ` (${plural(since, "decision")} later)` : ""}
                  <span className="block">
                    Its verdicts hold for the earlier state; run the audit again to include them.
                  </span>
                </>
              ) : null}
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
                ...(manifest.seconds != null
                  ? [["Run time", duration(manifest.seconds)] as [string, string]]
                  : []),
                ["Versions", versions(manifest)],
                ...(manifest.settings
                  ? [["Settings", settings(manifest)] as [string, string]]
                  : []),
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

      {v?.files?.length ? <Files files={v.files} studyId={target.studyId} /> : null}
    </div>
  );
}

/** A problem `verify_audit` reports about the record binding (not the audit's own files). */
function isBindingProblem(p: string): boolean {
  return /^the record|^the audited decision chain/i.test(p);
}

function Problems({ items }: { items: string[] }) {
  return (
    <ul className="list-disc pl-5">
      {items.map((p) => (
        <li key={p}>{asSentence(p)}</li>
      ))}
    </ul>
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

/** The audit's files with their checksums; each one downloads (only files AUDIT.sha256 lists). */
function Files({ files, studyId }: { files: NonNullable<AuditVerify["files"]>; studyId: string }) {
  return (
    <Card as="section" aria-labelledby="verify-files">
      <CardHeader
        id="verify-files"
        title="The audit's files"
        hint="Each file's sha256, as listed in AUDIT.sha256. Click a name to save the file."
      />
      <CardBody>
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
              {files.map((f) => (
                <TR key={f.name}>
                  <TD className="font-mono text-xs">
                    <a
                      href={`/api/studies/${encodeURIComponent(studyId)}/audit/files/${encodeURIComponent(f.name)}`}
                      download={f.name}
                      className="text-accent underline-offset-2 hover:underline"
                    >
                      {f.name}
                    </a>
                  </TD>
                  <TD numeric>{bytes(f.bytes)}</TD>
                  <TD>
                    <Hash value={f.sha256} length={16} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
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
