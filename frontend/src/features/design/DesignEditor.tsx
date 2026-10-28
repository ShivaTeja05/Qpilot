/**
 * "Set the design on this page": the person's own editor for what the rules and the model did
 * not propose (targets' roles, samples' groups, types and units, the comparison, a sample
 * sheet). Changes collect in a draft; "Review and record…" shows the engine's check of each and
 * records them as the person's decisions, with one reason. No model is needed for any of it.
 */
import { PencilRuler, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { count } from "@/lib/format";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorPanel,
  LoadingBlock,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/ui";
import { isWarming, Warming, type QuoteLookup } from "@/ui/proposal";
import { ComparisonPanel } from "./ComparisonPanel";
import { EMPTY_DRAFT, type Draft, type EditorView } from "./draft";
import { PastePanel } from "./PastePanel";
import { ReviewDialog } from "./ReviewDialog";
import { SamplesPanel, type Proposed } from "./SamplesPanel";
import { SheetPanel } from "./SheetPanel";
import { TargetsPanel } from "./TargetsPanel";

export type EditorTab = "targets" | "samples" | "paste" | "comparison" | "sheet";
export const EDITOR_ID = "design-editor";

export function DesignEditor({
  sid,
  view,
  error,
  loading,
  quotes,
  tab,
  onTab,
  draft,
  onDraft,
  selected,
  onSelect,
  proposed,
}: {
  sid: string;
  view: EditorView | undefined;
  error: unknown;
  loading: boolean;
  quotes: QuoteLookup;
  tab: EditorTab;
  onTab: (tab: EditorTab) => void;
  draft: Draft;
  onDraft: (next: Draft) => void;
  selected: ReadonlySet<string>;
  onSelect: (next: Set<string>) => void;
  proposed: ReadonlyMap<string, Proposed>;
}) {
  const [review, setReview] = useState(false);
  const n = draft.size;
  const confirmed = Boolean(view?.confirmed);
  const groups = useMemo(() => Object.keys(view?.groups ?? {}).length, [view]);
  return (
    <Card as="section" aria-labelledby={EDITOR_ID} id={`${EDITOR_ID}-card`}>
      <CardHeader
        id={EDITOR_ID}
        title="Set the design on this page"
        hint="No model needed. You choose what each target and sample is; the engine checks every choice; each change is recorded as your decision, with your reason. Nothing changes until you record it."
        level={2}
      />
      <CardBody className="flex flex-col gap-4">
        {isWarming(error) ? (
          <Warming message="The editor appears when qPilot has read the file." />
        ) : error ? (
          <ErrorPanel error={error} compact />
        ) : null}
        {!view && loading ? (
          <LoadingBlock label="Reading the samples and targets" lines={4} />
        ) : null}
        {view ? (
          <>
            {view.preset ? (
              <p className="rounded-lg border border-info/25 bg-info-soft/40 px-3 py-2 text-[13px] text-fg">
                This study uses a built-in design ({view.preset}): its groups come from the data,
                not from the samples. Setting groups here would replace it.
              </p>
            ) : null}
            {confirmed ? (
              <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13px] text-muted">
                The design is confirmed. A change recorded here re-opens the design stage (the
                curves and the results wait for it to be confirmed again).
              </p>
            ) : null}
            <Tabs value={tab} onValueChange={(v) => onTab(v as EditorTab)}>
              <TabsList label="What to set">
                <TabsTrigger value="targets" count={view.targets.length}>
                  Targets
                </TabsTrigger>
                <TabsTrigger value="samples" count={view.samples.length}>
                  Samples
                </TabsTrigger>
                <TabsTrigger value="paste">Paste a list</TabsTrigger>
                <TabsTrigger value="comparison" count={groups || undefined}>
                  Comparison
                </TabsTrigger>
                <TabsTrigger value="sheet">Sample sheet</TabsTrigger>
              </TabsList>
              <TabsContent value="targets">
                <TargetsPanel
                  view={view}
                  draft={draft}
                  quotes={quotes}
                  onChange={(items) => {
                    const next = new Map(draft);
                    for (const i of items) next.set(`${i.kind}\u0000${i.subject}`, i);
                    onDraft(next);
                  }}
                />
              </TabsContent>
              <TabsContent value="samples">
                <SamplesPanel
                  view={view}
                  draft={draft}
                  quotes={quotes}
                  selected={selected}
                  onSelect={onSelect}
                  onDraft={onDraft}
                  proposed={proposed}
                />
              </TabsContent>
              <TabsContent value="paste">
                <PastePanel
                  view={view}
                  draft={draft}
                  quotes={quotes}
                  onDraft={onDraft}
                  onDone={() => onTab("samples")}
                />
              </TabsContent>
              <TabsContent value="comparison">
                <ComparisonPanel
                  view={view}
                  draft={draft}
                  onDraft={onDraft}
                  onGoSamples={() => onTab("samples")}
                />
              </TabsContent>
              <TabsContent value="sheet">
                <SheetPanel sid={sid} view={view} />
              </TabsContent>
            </Tabs>
            <div
              className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 shadow-sm"
              aria-live="polite"
            >
              <PencilRuler className="size-4 text-muted" aria-hidden />
              <p className="text-[13px] text-fg">
                {n ? (
                  <>
                    <span className="font-semibold">{count(n)}</span> change{n === 1 ? "" : "s"} not
                    recorded yet
                  </>
                ) : (
                  <span className="text-muted">
                    No change yet: set targets, samples or the comparison above.
                  </span>
                )}
              </p>
              <div className="ml-auto flex gap-2">
                {n ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<RotateCcw />}
                    onClick={() => onDraft(EMPTY_DRAFT)}
                  >
                    Discard
                  </Button>
                ) : null}
                <Button size="sm" variant="primary" disabled={!n} onClick={() => setReview(true)}>
                  Review and record…
                </Button>
              </div>
            </div>
            <ReviewDialog
              sid={sid}
              draft={draft}
              open={review}
              onOpenChange={setReview}
              onDraft={onDraft}
              onRecorded={() => {
                onDraft(EMPTY_DRAFT);
                onSelect(new Set());
              }}
            />
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}
