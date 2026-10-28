/** What the opened file declares: counts and names only, nothing analysed. */
import type { ReactNode } from "react";
import type { Schemas } from "@/api/client";
import { count, plural } from "@/lib/format";
import { ROLE_SHORT, ROLE_WORDS } from "@/lib/vocab";
import { Badge, Card, CardBody, CardHeader, Hash, KeyValues, Tooltip } from "@/ui";

export function FileFacts({
  facts,
  summary,
  analysed,
  warming,
}: {
  facts: Schemas["FileFacts"] | null | undefined;
  summary: Schemas["InspectSummary"] | null | undefined;
  /** Results exist (both blind stages confirmed). */
  analysed?: boolean;
  /** The server is reading the file for the first time since it started. */
  warming?: boolean;
}) {
  if (!facts && warming) {
    return (
      <Card as="section">
        <CardHeader
          title="The file"
          hint="Being read for the first time since qPilot started; its facts appear here when that is done."
        />
      </Card>
    );
  }
  if (!facts) {
    return (
      <Card as="section">
        <CardHeader
          title="The file"
          hint="The input file cannot be read now: it is missing or has changed since it was opened."
        />
      </Card>
    );
  }
  const types = Object.entries(facts.declared_types).sort((a, b) => b[1] - a[1]);
  const experiments = Object.entries(summary?.experiments ?? {});
  const rows: [string, ReactNode][] = [
    ["File", <span className="font-mono break-all">{facts.file_name ?? "—"}</span>],
    [
      "Sample sheet",
      facts.sheet_name ? (
        <span className="font-mono break-all">{facts.sheet_name}</span>
      ) : (
        <span className="text-muted">none</span>
      ),
    ],
    ["SHA-256", <Hash value={facts.input_sha256} length={12} />],
    [
      "Contents",
      `${plural(facts.n_plates, "plate")} · ${count(facts.n_wells)} wells · ${plural(facts.n_samples, "sample")} · ${plural(facts.n_targets, "target")}`,
    ],
  ];
  if (experiments.length) {
    rows.push([
      experiments.length === 1 ? "Experiment" : "Experiments",
      <span className="flex flex-col gap-0.5">
        {experiments.map(([e, n]) => (
          <span key={e}>
            <span className="font-mono">{e}</span>{" "}
            <span className="text-muted">· {plural(n, "plate")}</span>
          </span>
        ))}
      </span>,
    ]);
  }
  return (
    <Card as="section" aria-labelledby="file-facts">
      <CardHeader
        id="file-facts"
        title="The file"
        hint={analysed ? "What it declares." : "What it declares. Nothing is analysed yet."}
      />
      <CardBody className="flex flex-col gap-3">
        <KeyValues rows={rows} />
        {types.length ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted">
              Samples by declared type (samples, not wells)
            </p>
            <div className="flex flex-wrap gap-1.5">
              {types.map(([t, n]) => (
                <Tooltip key={t} content={`${plural(n, "sample")} declared ${ROLE_WORDS[t] ?? t}`}>
                  <Badge tabIndex={0}>
                    {ROLE_SHORT[t] ?? t}{" "}
                    <span className="font-mono tabular">
                      {count(n)} sample{n === 1 ? "" : "s"}
                    </span>
                  </Badge>
                </Tooltip>
              ))}
            </div>
          </div>
        ) : null}
        {summary?.notes.length ? (
          <ul className="list-disc pl-5 text-xs text-muted">
            {summary.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ) : null}
      </CardBody>
    </Card>
  );
}
