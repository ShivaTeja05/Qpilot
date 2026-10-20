/**
 * Settings → Model: which model the AI layer uses (from the environment), whether it answers and
 * why not, what leaves this machine, and how to choose another one.
 */
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useState, type ReactNode } from "react";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CommandLine,
  Dot,
  ErrorPanel,
  KeyValues,
  LoadingBlock,
} from "@/ui";
import { dateTime } from "@/lib/format";
import { modelChip } from "@/shell/TopBar";
import { namesWords, providerWords, useModelStatus, type ModelStatus } from "./system";

/** How to start qPilot with each kind of model (the variables `qpilot/ai/config.py` reads). */
const HOW = [
  {
    title: "No model (the fixed rules propose alone)",
    command: "QPILOT_MODEL_PROVIDER=none qpilot app",
  },
  {
    title: "A local model (an OpenAI-compatible endpoint on this computer, e.g. Ollama)",
    command:
      "QPILOT_MODEL_PROVIDER=openai_compatible QPILOT_MODEL_ENDPOINT=http://127.0.0.1:11434/v1 QPILOT_MODEL_NAME=<model> qpilot app",
  },
  {
    title: "Anthropic (remote: sample names leave only as pseudonyms)",
    command: "QPILOT_MODEL_PROVIDER=anthropic QPILOT_API_KEY=<your key> qpilot app",
  },
];

function Status({ model }: { model: ModelStatus }) {
  const chip = modelChip(model);
  return (
    <span className="inline-flex items-center gap-2">
      <Dot tone={chip.tone} pulse={chip.pulse} />
      <span>{chip.status}</span>
    </span>
  );
}

export function ModelCard({
  initial,
  children,
}: {
  initial: ModelStatus | undefined;
  /** More actions next to Check connection (Test this model). */
  children?: ReactNode;
}) {
  const query = useModelStatus(initial);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const model = query.data;

  const check = async () => {
    await query.refetch();
    setCheckedAt(Date.now());
  };

  return (
    <Card as="section" aria-labelledby="settings-model">
      <CardHeader
        id="settings-model"
        title="Model"
        hint="Optional. With no model the fixed rules propose, and the engine computes every number either way."
      />
      <CardBody className="flex flex-col gap-4">
        {!model ? (
          query.error ? (
            <ErrorPanel
              compact
              error={query.error}
              title="The model's status could not be read"
              onRetry={() => void query.refetch()}
            />
          ) : (
            <LoadingBlock label="Reading the model's status" lines={3} />
          )
        ) : (
          <>
            <KeyValues
              rows={[
                ["Provider", providerWords(model)],
                ["Model", model.model ? <span className="font-mono">{model.model}</span> : "—"],
                ["Status", <Status key="status" model={model} />],
                ["Sample names", namesWords(model)],
                ["Outbound", model.outbound],
              ]}
            />
            {model.misconfigured ? (
              <div
                role="status"
                className="flex gap-2.5 rounded-lg border border-warn/30 bg-warn-soft/60 p-3 text-[13px]"
              >
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
                <p>
                  <span className="font-semibold text-fg">The model configuration is wrong.</span>{" "}
                  <span className="text-muted">
                    {model.reason ?? "qPilot could not read it."} Until it is fixed, the fixed rules
                    propose alone.
                  </span>
                </p>
              </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                icon={<RefreshCw />}
                loading={query.isFetching}
                onClick={() => void check()}
                disabled={!model.configured}
              >
                Check connection
              </Button>
              {children}
              <p className="text-xs text-muted" aria-live="polite">
                {!model.configured
                  ? "There is no model to check."
                  : checkedAt
                    ? `Latest answer read ${dateTime(checkedAt)}. qPilot asks the model a one-token question at most once a minute.`
                    : "qPilot asks the model a one-token question at most once a minute, in the background."}
              </p>
            </div>
          </>
        )}

        <details className="group rounded-lg border border-line bg-surface-2 open:pb-3">
          <summary className="cursor-pointer list-none rounded-lg px-3 py-2.5 text-[13px] font-medium text-fg select-none hover:bg-bg-subtle [&::-webkit-details-marker]:hidden">
            <span className="mr-1.5 inline-block text-faint transition-transform group-open:rotate-90">
              ›
            </span>
            How to choose a model
          </summary>
          <div className="flex flex-col gap-3 px-3">
            <p className="text-xs text-muted">
              qPilot reads the model from the environment when it starts. Stop{" "}
              <code className="font-mono">qpilot app</code> and start it again with one of these.
            </p>
            {HOW.map((h) => (
              <div key={h.title} className="flex flex-col gap-1.5">
                <p className="text-xs font-medium text-fg">{h.title}</p>
                <CommandLine command={h.command} />
              </div>
            ))}
          </div>
        </details>
      </CardBody>
    </Card>
  );
}
