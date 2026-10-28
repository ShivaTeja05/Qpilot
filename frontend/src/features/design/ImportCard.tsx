/**
 * "Imported from …": what qPilot read from the instrument's export this session was opened from
 * (`WorkspaceView.capture`). The source files by the names they had, each plate's shape, targets,
 * dyes and declared sample types, the vendor's Cq count and omitted wells (recorded, never
 * applied), and whether the curves were processed before export, with what that means for the
 * analysis. Counts and names only: no sample name, no Cq value, nothing about groups.
 */
import { CircleCheck, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { bytes, count, plural } from "@/lib/format";
import { ROLE_SHORT, ROLE_WORDS } from "@/lib/vocab";
import { Badge, Card, CardBody, CardHeader, KeyValues, Tooltip } from "@/ui";

type Capture = Schemas["CaptureSummary"];
type Plate = Schemas["CapturePlate"];

/** Warnings the raw-ness note already says in full (not repeated in the list). */
const RAWNESS_CODES = new Set([
  "CURVES_NOT_RAW",
  "RAWNESS_UNKNOWN",
  "CURVES_SCALED",
  "CQ_ONLY",
  "PASSIVE_REFERENCE",
]);

/** What each source file was read as. */
const ROLE_LABEL: Record<string, string> = {
  amplification: "amplification curves",
  cq: "Cq and sample types",
  melt: "melt curves",
  setup: "run information",
  plate: "the whole plate",
  ignored: "not needed (qPilot recomputes it)",
};

/** Curves LinRegPCR can use as they are: raw or passive-reference normalised. */
export function curvesUsable(capture: Pick<Capture, "rawness">): boolean {
  return capture.rawness.linregpcr_ok;
}

/** A plate's shape in words: `96-well plate (8 × 12) · 80 wells · 40 cycles`. */
export function plateLine(p: Plate): string {
  const parts = [`${count(p.rows * p.columns)}-well plate (${p.rows} × ${p.columns})`];
  parts.push(plural(p.n_wells, "well"));
  parts.push(p.n_cycles ? plural(p.n_cycles, "cycle") : "no curves");
  if (p.n_reactions > p.n_wells) parts.push(plural(p.n_reactions, "reaction"));
  return parts.join(" · ");
}

function SampleTypes({ types }: { types: Record<string, number> }) {
  const entries = Object.entries(types).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <span className="text-muted">none declared</span>;
  return (
    <span className="flex flex-wrap gap-1.5">
      {entries.map(([t, n]) => (
        <Tooltip key={t} content={`${count(n)} wells declared ${ROLE_WORDS[t] ?? t}`}>
          <Badge tabIndex={0}>
            {ROLE_SHORT[t] ?? t}{" "}
            <span className="font-mono tabular">
              {count(n)} well{n === 1 ? "" : "s"}
            </span>
          </Badge>
        </Tooltip>
      ))}
    </span>
  );
}

function names(items: readonly string[]): ReactNode {
  return items.length ? (
    <span className="font-mono break-all">{items.join(", ")}</span>
  ) : (
    <span className="text-muted">none</span>
  );
}

function PlateFacts({ plate, verdict }: { plate: Plate; verdict: string }) {
  const rows: [string, ReactNode][] = [
    ["Plate", <span className="font-mono break-all">{plate.run_id}</span>],
    ["Shape", plateLine(plate)],
    [plate.targets.length === 1 ? "Target" : "Targets", names(plate.targets)],
    [plate.dyes.length === 1 ? "Dye" : "Dyes", names(plate.dyes)],
    ["Wells by sample type", <SampleTypes types={plate.sample_types} />],
    [
      "Instrument Cq",
      plate.n_with_vendor_cq
        ? `${count(plate.n_with_vendor_cq)} of ${plural(plate.n_reactions, "reaction")} (kept for comparison; qPilot computes its own)`
        : "none in the export",
    ],
  ];
  if (plate.n_unmapped_types) {
    rows.push([
      "Unknown types",
      `${plural(plate.n_unmapped_types, "well")} with a sample type qPilot does not know, treated as samples until you type your controls`,
    ]);
  }
  if (plate.vendor_omitted.length) {
    rows.push([
      "Omitted by the instrument",
      <span>
        <span className="font-mono">{plate.vendor_omitted.join(", ")}</span>
        <span className="text-muted">
          {" "}
          · recorded, not applied: qPilot analyses every well; exclude them in Studio if you agree
        </span>
      </span>,
    ]);
  }
  if (plate.verdict !== verdict) rows.push(["Curves", plate.verdict.replace(/_/g, " ")]);
  return <KeyValues rows={rows} />;
}

export function ImportCard({ capture }: { capture: Capture | null | undefined }) {
  if (!capture) return null;
  const usable = curvesUsable(capture);
  const warnings = capture.warnings.filter((w) => !RAWNESS_CODES.has(w.code));
  const many = capture.plates.length > 1;
  return (
    <Card as="section" aria-labelledby="import-card">
      <CardHeader
        id="import-card"
        title={`Imported from ${capture.label}`}
        hint="What qPilot read from your instrument's files and wrote as the RDML file this session uses."
      />
      <CardBody className="flex flex-col gap-3">
        <div
          role="note"
          aria-label="Were the curves processed before export?"
          className={cn(
            "rounded-lg border p-3",
            usable ? "border-ok/25 bg-ok-soft" : "border-warn/30 bg-warn-soft",
          )}
        >
          <p className="flex items-center gap-1.5 text-[13px] font-semibold text-fg [&_svg]:size-4">
            {usable ? (
              <CircleCheck className="text-ok" aria-hidden />
            ) : (
              <TriangleAlert className="text-warn" aria-hidden />
            )}
            {capture.rawness.title}
          </p>
          <p className="mt-1 text-[13px] leading-relaxed text-fg">{capture.rawness.meaning}</p>
          {capture.rawness.import_trust ? (
            <p className="mt-1 text-[13px] leading-relaxed text-muted">
              Until a person decides what this means for the analysis, every gene's confidence is
              capped at Moderate. That choice (re-export, analyse as they are, or the instrument's
              Cq values only) is the Import Trust card on Results, once the design and the curves
              are confirmed.
            </p>
          ) : null}
        </div>

        <KeyValues
          rows={[
            [
              capture.sources.length === 1 ? "File" : "Files",
              <ul className="flex flex-col gap-0.5">
                {capture.sources.map((s) => (
                  <li key={s.name}>
                    <span className="font-mono break-all">{s.name}</span>{" "}
                    <span className="text-muted">
                      · {ROLE_LABEL[s.role] ?? s.role} · {bytes(s.bytes)}
                    </span>
                  </li>
                ))}
              </ul>,
            ],
            ...(capture.unused.length
              ? ([
                  [
                    "Not used",
                    <span>
                      {names(capture.unused)}
                      <span className="text-muted"> · qPilot does not read these files</span>
                    </span>,
                  ],
                ] as [string, ReactNode][])
              : []),
            ["Signal", capture.value_words],
            [
              "Contents",
              `${plural(capture.plates.length, "plate")}${capture.layers.melt ? " · melt curves" : ""}`,
            ],
          ]}
        />

        {many ? (
          <div
            className="qp-scroll flex max-h-80 flex-col gap-3 overflow-y-auto rounded-lg border border-line p-3 outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
            tabIndex={0}
            role="region"
            aria-label="Plates read"
          >
            {capture.plates.map((p) => (
              <PlateFacts key={p.run_id} plate={p} verdict={capture.rawness.verdict} />
            ))}
          </div>
        ) : (
          capture.plates.map((p) => (
            <PlateFacts key={p.run_id} plate={p} verdict={capture.rawness.verdict} />
          ))
        )}

        {warnings.length ? (
          <div>
            <p className="mb-1 text-xs font-medium text-muted">What to know</p>
            <ul className="list-disc pl-5 text-xs text-muted">
              {warnings.map((w, i) => (
                <li key={`${w.code}-${i}`}>{w.message}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="text-xs text-muted">
          {plural(capture.n_quarantined, "text")} from the files (sample and target names, header
          lines) are quarantined: shown as quoted text, never obeyed.
        </p>
      </CardBody>
    </Card>
  );
}
