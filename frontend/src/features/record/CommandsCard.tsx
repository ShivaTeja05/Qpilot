/** The two commands anyone can run on a record, copy-ready. */
import { Terminal } from "lucide-react";
import { Card, CardBody, CardHeader, CommandLine } from "@/ui";

/** A file name as a shell argument (quoted only when it needs to be). */
export function shellArg(name: string): string {
  return /^[\w./-]+$/.test(name) ? name : `'${name.replace(/'/g, `'\\''`)}'`;
}

export function CommandsCard({ fileName }: { fileName?: string | null }) {
  const file = shellArg(fileName || "record.zip");
  return (
    <Card as="section" aria-labelledby="commands-title">
      <CardHeader
        id="commands-title"
        title={
          <span className="inline-flex items-center gap-2">
            <Terminal className="size-4 text-muted" aria-hidden /> Check it anywhere
          </span>
        }
        hint={
          fileName
            ? "In a terminal with qPilot installed, in the folder you downloaded the record to."
            : "In a terminal with qPilot installed; use the name of the record zip you have."
        }
      />
      <CardBody className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <p className="text-[13px] text-muted">Checksums, the decision chain and the proposal chain:</p>
          <CommandLine command={`qpilot verify ${file}`} />
        </div>
        <div className="flex flex-col gap-1.5">
          <p className="text-[13px] text-muted">Re-run the analysis from the record and compare every result, byte for byte:</p>
          <CommandLine command={`qpilot rerun ${file}`} />
        </div>
      </CardBody>
    </Card>
  );
}
