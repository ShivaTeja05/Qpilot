/**
 * Open (`#/`): what qPilot does in one sentence, then the three ways in — drop a file, open the
 * demo study, or go back to a recent workspace — and what this install is. The whole screen is a
 * drop target for the RDML file and its sample sheet.
 */
import { BookCheck, Cpu, Sparkles, UserCheck } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useSystem, useWorkspaces } from "@/shell/data";
import type { SectionProps } from "@/shell/sections";
import { DemoCard } from "./DemoCard";
import { OpenFile } from "./OpenFile";
import { useIntake } from "./useIntake";
import { Recent } from "./Recent";
import { SystemStrip } from "./SystemStrip";

const STEPS = [
  {
    icon: <Sparkles />,
    title: "The AI proposes",
    detail: "what the samples are, the groups, and which wells amplified.",
  },
  {
    icon: <Cpu />,
    title: "The engine checks",
    detail: "every proposal, and computes every number with one published method.",
  },
  {
    icon: <UserCheck />,
    title: "You decide",
    detail:
      "every choice that could change a conclusion. Results stay hidden until the design and the curves are confirmed.",
  },
  {
    icon: <BookCheck />,
    title: "The record keeps it",
    detail:
      "every decision with its reason and who made it, hash-chained, so anyone can re-run it.",
  },
];

/** How qPilot works, as a short vertical path (the hero's right column on wide screens). */
function HowItWorks() {
  return (
    <ol className="relative flex flex-col gap-4 rounded-2xl border border-line bg-surface/80 p-5 shadow-sm backdrop-blur-sm sm:p-6">
      {STEPS.map((s, i) => (
        <li key={s.title} className="relative flex gap-3">
          {i < STEPS.length - 1 ? (
            <span
              aria-hidden
              className="absolute top-8 bottom-[-1rem] left-[13px] w-px bg-line-strong"
            />
          ) : null}
          <span
            className="relative flex size-7 shrink-0 items-center justify-center rounded-full border border-accent/25 bg-accent-soft text-accent-strong [&_svg]:size-3.5"
            aria-hidden
          >
            {s.icon}
          </span>
          <p className="min-w-0 pt-0.5 text-[13px] leading-snug">
            <span className="sr-only">{i + 1}. </span>
            <span className="font-semibold text-fg">{s.title}</span>{" "}
            <span className="text-muted">{s.detail}</span>
          </p>
        </li>
      ))}
    </ol>
  );
}

function hasFiles(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes("Files");
}

export default function Section(_: SectionProps) {
  const system = useSystem();
  const workspaces = useWorkspaces();
  const intake = useIntake();
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);

  const list = workspaces.data;
  const demoWorkspace = list?.find((w) => w.is_demo && w.kind === "session" && w.file_present);

  const drag = {
    onDragEnter: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    onDragOver: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    onDrop: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setDragging(false);
      intake.add(Array.from(e.dataTransfer.files));
    },
  };

  return (
    <div className="relative isolate min-h-full" {...drag}>
      {/* A faint plate-well dot grid and a soft accent glow behind the hero (decoration). */}
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-x-4 -top-6 -z-10 h-[560px] overflow-hidden sm:-inset-x-6 lg:-inset-x-8"
      >
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: "radial-gradient(var(--line-strong) 1.2px, transparent 1.6px)",
            backgroundSize: "22px 22px",
            maskImage: "radial-gradient(ellipse 80% 70% at 75% 0%, black 10%, transparent 75%)",
            WebkitMaskImage:
              "radial-gradient(ellipse 80% 70% at 75% 0%, black 10%, transparent 75%)",
          }}
        />
        <div
          className="absolute -top-40 right-[-10%] h-[440px] w-[640px] rounded-full opacity-60 blur-3xl"
          style={{ background: "radial-gradient(closest-side, var(--accent-soft), transparent)" }}
        />
      </div>

      <div className="mx-auto max-w-6xl pt-2 pb-4 sm:pt-6 lg:pt-8">
        <header className="grid items-center gap-8 lg:grid-cols-12 lg:gap-10">
          <div className="lg:col-span-7">
            <h1 className="text-2xl leading-tight font-semibold tracking-tight text-balance text-fg sm:text-[32px] sm:leading-[1.15]">
              Know which of your qPCR conclusions hold.
            </h1>
            <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-pretty text-muted sm:text-base">
              qPilot analyses every plate from the raw amplification curves with one published
              method, shows which of your analysis choices could change a conclusion, and leaves
              those choices to you.
            </p>
            <p className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] font-medium text-fg lg:hidden">
              {STEPS.slice(0, 3).map((s, i) => (
                <span key={s.title} className="inline-flex items-center gap-2">
                  {i ? (
                    <span className="text-faint" aria-hidden>
                      ·
                    </span>
                  ) : null}
                  {s.title}
                </span>
              ))}
            </p>
          </div>
          <div className="hidden lg:col-span-5 lg:block">
            <HowItWorks />
          </div>
        </header>

        <div className="mt-8 grid items-stretch gap-4 lg:mt-10 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <OpenFile intake={intake} dragging={dragging} />
          </div>
          <div className="lg:col-span-5">
            <DemoCard
              demo={system.data?.demo}
              workspace={demoWorkspace}
              loading={system.isPending || workspaces.isPending}
            />
          </div>
        </div>

        <div className="mt-12">
          <Recent
            workspaces={list}
            loading={workspaces.isPending}
            error={workspaces.error}
            onRetry={() => void workspaces.refetch()}
          />
        </div>

        <div className="mt-12">
          <SystemStrip
            system={system.data}
            error={system.error}
            onRetry={() => void system.refetch()}
          />
        </div>
      </div>
    </div>
  );
}
