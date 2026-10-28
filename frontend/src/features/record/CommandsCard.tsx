/** The two commands anyone can run on a record, copy-ready. */
import { Terminal } from "lucide-react";
import { Card, CardBody, CardHeader, CommandLine } from "@/ui";

/** A file name as a shell argument: quoted when it holds anything but plain characters. */
export function shellArg(name: string): string {
  return /^[\w.\-+@%/]+$/.test(name) ? name : `'${name.replace(/'/g, "'\\''")}'`;
}

/**
 * The commands for the record zip the person just dropped (named as they named it), else the
 * latest export's, else a record zip in general.
 */
export function CommandsCard({
  commands,
  dropped,
}: {
  commands?: { verify: string; rerun: string } | null;
  /** The name of the file dropped on "Verify a record", if any. */
  dropped?: string | null;
}) {
  const file = dropped ? shellArg(dropped) : "record.zip";
  const mine = dropped ? { verify: `qpilot verify ${file}`, rerun: `qpilot rerun ${file}` } : null;
  const shown = mine ?? commands ?? null;
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
          mine
            ? "In a terminal with qPilot installed, in the folder that holds the file you dropped."
            : commands
              ? "In a terminal with qPilot installed, in the folder you downloaded the record to."
              : "In a terminal with qPilot installed; use the name of the record zip you have."
        }
      />
      <CardBody className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <p className="text-[13px] text-muted">
            Checksums, the decision chain and the proposal chain:
          </p>
          <CommandLine command={shown?.verify ?? `qpilot verify ${file}`} />
        </div>
        <div className="flex flex-col gap-1.5">
          <p className="text-[13px] text-muted">
            Re-run the analysis from the record and compare every result, byte for byte:
          </p>
          <CommandLine command={shown?.rerun ?? `qpilot rerun ${file}`} />
        </div>
      </CardBody>
    </Card>
  );
}
