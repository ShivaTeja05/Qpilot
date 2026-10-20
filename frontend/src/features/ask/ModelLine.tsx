import { Bot, Loader2 } from "lucide-react";
import type { Schemas } from "@/api/client";
import { cn } from "@/lib/cn";
import { Dot } from "@/ui";

/**
 * Which model words the answers, in one honest line: none configured (templates answer), the
 * model answering, checking, or not answering and why (templates answer meanwhile).
 */
export function ModelLine({
  model,
  className,
}: {
  model: Schemas["ModelStatus"] | undefined;
  className?: string;
}) {
  if (!model) return null;
  const name = model.model ?? model.provider;
  let tone: "neutral" | "ok" | "warn" = "neutral";
  let text: string;
  let detail: string | null = null;
  if (!model.configured) {
    text = "No model configured:";
    detail = "qPilot's templates write the answers.";
  } else if (model.misconfigured) {
    tone = "warn";
    text = `The model settings are incomplete${model.reason ? `: ${model.reason}` : ""}.`;
    detail = "Templates answer meanwhile. Fix it in Settings.";
  } else if (model.checking) {
    text = `Checking ${name}…`;
  } else if (model.answers === false || !model.available) {
    tone = "warn";
    text = `${name} is not answering${model.reason ? `: ${model.reason}` : ""}.`;
    detail = "Templates answer meanwhile.";
  } else {
    tone = "ok";
    text = `${model.local ? "Local model" : "Remote model"} ${name} words the answers; qPilot checks every number.`;
    if (!model.local) detail = `Sample names are ${model.sample_names}.`;
  }
  return (
    <div className={cn("flex items-start gap-2 text-[13px]", className)}>
      <span className="mt-0.5 flex shrink-0 items-center gap-1.5 text-muted">
        {model.checking ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : (
          <Bot className="size-3.5" aria-hidden />
        )}
        <Dot tone={tone} />
      </span>
      <p className="min-w-0 text-muted">
        <span className="text-fg">{text}</span>
        {detail ? <> {detail}</> : null}{" "}
        {model.configured && tone === "ok" ? null : (
          <a href="#/settings" className="text-accent underline-offset-4 hover:underline">
            Model settings
          </a>
        )}
      </p>
    </div>
  );
}
