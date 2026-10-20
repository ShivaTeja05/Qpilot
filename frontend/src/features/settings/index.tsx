/**
 * Settings (`#/settings`): the model and its status, what agents may do on their own, the theme,
 * and what qPilot never does, with this install's version. Everything is read from the API.
 */
import { Monitor, Moon, ShieldCheck, Sun } from "lucide-react";
import { useSystem, useWorkspaces } from "@/shell/data";
import type { SectionProps } from "@/shell/sections";
import {
  Card,
  CardBody,
  CardHeader,
  CopyButton,
  ErrorPanel,
  KeyValues,
  LoadingBlock,
  PageHeader,
  SegmentedControl,
} from "@/ui";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { AutonomyCard } from "./AutonomyCard";
import { FreshDemoCard } from "./FreshDemoCard";
import { ModelCard } from "./ModelCard";
import { useModelTest } from "./ModelTest";

function AppearanceCard() {
  const { choice, setTheme } = useTheme();
  return (
    <Card as="section" aria-labelledby="settings-theme">
      <CardHeader
        id="settings-theme"
        title="Theme"
        hint="Saved in this browser."
        actions={
          <SegmentedControl<ThemeChoice>
            label="Theme"
            value={choice}
            onValueChange={setTheme}
            options={[
              {
                value: "system",
                label: (
                  <>
                    <Monitor aria-hidden />
                    System
                  </>
                ),
              },
              {
                value: "light",
                label: (
                  <>
                    <Sun aria-hidden />
                    Light
                  </>
                ),
              },
              {
                value: "dark",
                label: (
                  <>
                    <Moon aria-hidden />
                    Dark
                  </>
                ),
              },
            ]}
          />
        }
      />
    </Card>
  );
}

export default function Section(_: SectionProps) {
  const system = useSystem();
  const workspaces = useWorkspaces();
  const test = useModelTest();
  const s = system.data;
  const demo = workspaces.data?.find((w) => w.is_demo && w.kind === "session");

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 pb-4">
      <PageHeader
        title="Settings"
        hint="The model, what agents may do on their own, and what never leaves this computer."
      />

      {system.error && !s ? (
        <ErrorPanel
          error={system.error}
          title="This install's settings could not be read"
          onRetry={() => void system.refetch()}
        />
      ) : null}

      <ModelCard initial={s?.model} actions={test.button} below={test.panel} />

      {s ? (
        <AutonomyCard system={s} />
      ) : !system.error ? (
        <Card className="p-4">
          <LoadingBlock label="Reading the autonomy setting" lines={3} />
        </Card>
      ) : null}

      <AppearanceCard />

      <FreshDemoCard demo={demo} />

      {s ? (
        <Card as="section" aria-labelledby="settings-never">
          <CardHeader id="settings-never" title="What qPilot never does" />
          <CardBody className="flex flex-col gap-4">
            <ul className="flex flex-col gap-2 text-sm">
              {s.never.map((line) => (
                <li key={line} className="flex gap-2.5">
                  <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                  <span className="text-fg">{line}</span>
                </li>
              ))}
            </ul>
            <div className="border-t border-line pt-4">
              <h3 className="mb-2 text-xs font-medium tracking-wide text-faint uppercase">
                This install
              </h3>
              <KeyValues
                rows={[
                  ["Version", `qPilot ${s.version}`],
                  [
                    "Curve method",
                    <span key="m" className="font-mono">
                      {s.method}
                    </span>,
                  ],
                  [
                    "Robustness audit",
                    s.simulator
                      ? "Installed"
                      : "Not installed: pip install -e '.[sim]' from the qPilot folder",
                  ],
                  ["Python", `${s.python} on ${s.platform}`],
                  [
                    "Studies folder",
                    <span key="d" className="inline-flex max-w-full items-center gap-1">
                      <span className="truncate font-mono text-xs" title={s.studies_dir}>
                        {s.studies_dir}
                      </span>
                      <CopyButton text={s.studies_dir} label="Copy the folder path" />
                    </span>,
                  ],
                ]}
              />
            </div>
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
