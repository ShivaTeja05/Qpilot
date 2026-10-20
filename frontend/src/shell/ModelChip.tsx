/**
 * The model in one chip (top bar, Open's system strip, Settings): `no model`, `local qwen2.5:7b`,
 * `REMOTE — names pseudonymised`, with a dot for answering / checking / not answering and the
 * reason in words. One wording everywhere: use {@link modelChip} or {@link ModelChip}.
 */
import { Link } from "wouter";
import type { Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { Dot, Tooltip, type Tone } from "@/ui";

export type ModelStatus = Schemas["ModelStatus"];

export interface ModelChipWords {
  label: string;
  tone: Tone;
  status: string;
  pulse: boolean;
}

/** The model's label, dot tone and status sentence. */
export function modelChip(model: ModelStatus | null | undefined): ModelChipWords {
  if (!model)
    return {
      label: "model …",
      tone: "neutral",
      status: "Reading the model's status",
      pulse: false,
    };
  // A wrong configuration is not "no model": say what is wrong (docs/studio.md).
  if (model.misconfigured)
    return {
      label: model.configured ? modelLabel(model) : "no model",
      tone: "warn",
      status: `The model configuration is wrong: ${model.reason ?? "check QPILOT_MODEL_PROVIDER and QPILOT_MODEL_ENDPOINT"}. qPilot's templates answer meanwhile.`,
      pulse: false,
    };
  if (!model.configured || model.provider === "none")
    return {
      label: "no model",
      tone: "neutral",
      status: "No model is configured: qPilot's templates answer.",
      pulse: false,
    };
  const label = modelLabel(model);
  if (model.checking)
    return { label, tone: "warn", status: "Checking whether the model answers", pulse: true };
  if (model.answers) return { label, tone: "ok", status: "Answering", pulse: false };
  return {
    label,
    tone: "danger",
    status: `Not answering${model.reason ? `: ${model.reason}` : ""}`,
    pulse: false,
  };
}

function modelLabel(model: ModelStatus): string {
  return model.local ? `local ${model.model ?? model.provider}` : "REMOTE — names pseudonymised";
}

/** True when a configured model sends to another machine (names are pseudonymised first). */
export function isRemote(model: ModelStatus | null | undefined): boolean {
  return Boolean(model && model.configured && !model.misconfigured && !model.local);
}

/**
 * The chip: dot + label, the status and the `outbound` line on hover. Links to Settings unless
 * `href` is null (e.g. on Settings itself).
 */
export function ModelChip({
  model,
  href = "/settings",
  className,
}: {
  model: ModelStatus | null | undefined;
  /** Where a click goes (default Settings); null: not a link. */
  href?: string | null;
  className?: string;
}) {
  const chip = modelChip(model);
  const classes = cn(
    "inline-flex h-7 max-w-56 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium",
    isRemote(model) ? "border-warn/40 bg-warn-soft text-warn" : "border-line text-muted",
    href && "transition-colors hover:bg-bg-subtle",
    className,
  );
  const tip = (
    <span className="flex flex-col gap-0.5">
      <span>{chip.status}</span>
      {model?.outbound ? <span className="opacity-80">{model.outbound}</span> : null}
    </span>
  );
  const body = (
    <>
      <Dot tone={chip.tone} pulse={chip.pulse} />
      <span className="truncate">{chip.label}</span>
      <span className="sr-only">. {chip.status}</span>
    </>
  );
  return (
    <Tooltip content={tip}>
      {href ? (
        <Link href={href} className={classes}>
          {body}
        </Link>
      ) : (
        <span tabIndex={0} className={classes}>
          {body}
        </span>
      )}
    </Tooltip>
  );
}
