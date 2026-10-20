/** The audit cannot describe this study: the reason in words, and what to do instead. */
import { Ban, PackageX, ShieldAlert } from "lucide-react";
import { Link } from "wouter";
import { sectionPath, type SectionProps } from "@/shell/sections";
import { Button, Card, CardBody, CommandLine } from "@/ui";
import type { AuditStatus } from "./types";
import { INSTALL_COMMAND, STATUS_WORDS } from "./words";

/** The service's reason as a sentence ("the design has technical replicates…" → "The design…."). */
export function asSentence(reason: string | null | undefined): string | null {
  const text = (reason ?? "").trim();
  if (!text) return null;
  const capital = text[0]!.toUpperCase() + text.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}

export function CannotRun({
  workspace,
  status,
  title,
}: {
  workspace: NonNullable<SectionProps["workspace"]>;
  status: Pick<AuditStatus, "status" | "reason">;
  /** Overrides the heading (an attached folder that cannot be shown). */
  title?: string;
}) {
  const kind =
    status.status === "refused" || status.status === "unavailable"
      ? status.status
      : "not_applicable";
  const words = STATUS_WORDS[kind];
  const icon =
    kind === "refused" ? <ShieldAlert /> : kind === "unavailable" ? <PackageX /> : <Ban />;
  const reason = asSentence(status.reason);
  return (
    <Card as="section" aria-labelledby="audit-cannot" className="max-w-3xl">
      <CardBody className="flex gap-4 pt-5">
        <div
          aria-hidden
          className="flex size-10 shrink-0 items-center justify-center rounded-full bg-bg-subtle text-muted [&_svg]:size-5"
        >
          {icon}
        </div>
        <div className="min-w-0 space-y-3">
          <h2 id="audit-cannot" className="text-[15px] font-semibold text-fg">
            {title ?? words.title}
          </h2>
          {reason ? (
            <p className="rounded-lg border-l-4 border-line-strong bg-sunken px-3 py-2 text-sm text-fg">
              {reason}
            </p>
          ) : null}
          <p className="text-sm text-muted">{words.todo}</p>
          {kind === "unavailable" ? <CommandLine command={INSTALL_COMMAND} /> : null}
          {kind !== "unavailable" ? (
            <Button asChild variant="secondary" size="sm">
              <Link href={sectionPath(workspace, "results")}>Open Results</Link>
            </Button>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}
