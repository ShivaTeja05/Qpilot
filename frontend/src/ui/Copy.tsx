import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { shortHash } from "@/lib/format";
import { Button, IconButton } from "./Button";
import { Tooltip } from "./overlay";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function useCopied(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return [
    copied,
    (text: string) => {
      void copyText(text).then((ok) => {
        if (!ok) return;
        setCopied(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), 1500);
      });
    },
  ];
}

/** Copies `text` to the clipboard; the icon turns into a check for a moment. */
export function CopyButton({
  text,
  label = "Copy",
  showLabel,
  size = "sm",
  className,
}: {
  text: string;
  /** Accessible name / visible label. */
  label?: string;
  /** Show the label next to the icon. */
  showLabel?: boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const [copied, copy] = useCopied();
  const icon = copied ? <Check className="text-ok" /> : <Copy />;
  if (showLabel) {
    return (
      <Button
        size={size}
        variant="secondary"
        icon={icon}
        onClick={() => copy(text)}
        className={className}
      >
        {copied ? "Copied" : label}
      </Button>
    );
  }
  return (
    <Tooltip content={copied ? "Copied" : label}>
      <IconButton
        label={copied ? "Copied" : label}
        size={size}
        onClick={() => copy(text)}
        className={className}
      >
        {icon}
      </IconButton>
    </Tooltip>
  );
}

/** A hash or id in mono, shortened; click copies the full value (tooltip shows it). */
export function Hash({
  value,
  length = 8,
  prefix,
  className,
}: {
  value: string | null | undefined;
  /** Characters shown (default 8). */
  length?: number;
  /** A word before the hash (e.g. "chain"). */
  prefix?: ReactNode;
  className?: string;
}) {
  const [copied, copy] = useCopied();
  if (!value) return <span className={cn("font-mono text-muted", className)}>—</span>;
  return (
    <Tooltip content={copied ? "Copied" : <span className="font-mono break-all">{value}</span>}>
      <button
        type="button"
        onClick={() => copy(value)}
        aria-label={`${prefix ? `${String(prefix)} ` : ""}${shortHash(value, length)}, copy the full value`}
        className={cn(
          "inline-flex items-center gap-1 rounded px-1 font-mono text-[12px] text-muted transition-colors hover:bg-bg-subtle hover:text-fg",
          className,
        )}
      >
        {prefix ? <span className="font-sans text-muted">{prefix}</span> : null}{" "}
        {shortHash(value, length)}
        {copied ? <Check className="size-3 text-ok" aria-hidden /> : null}
      </button>
    </Tooltip>
  );
}

/** A command line in mono with a copy button (`qpilot verify record.zip`). */
export function CommandLine({ command, className }: { command: string; className?: string }) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg border border-line bg-sunken py-1 pr-1 pl-3",
        className,
      )}
    >
      <code className="min-w-0 flex-1 overflow-x-auto py-1 font-mono text-[12.5px] whitespace-pre text-fg qp-scroll">
        {command}
      </code>
      <CopyButton text={command} label="Copy command" />
    </div>
  );
}
