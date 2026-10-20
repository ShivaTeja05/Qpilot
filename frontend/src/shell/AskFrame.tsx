import { lazy, Suspense } from "react";
import { useMediaQuery } from "@/lib/hooks";
import { LoadingBlock, Sheet } from "@/ui";
import { setAskOpen, useAskOpen } from "./actions";
import type { WorkspaceView } from "./data";

const AskDrawer = lazy(() => import("@/features/ask/AskDrawer"));

/**
 * The Ask drawer's frame (right, 420 px, ⌘J). Its content is `@/features/ask/AskDrawer`. On wide
 * screens it sits beside the page (the page stays usable); on narrow ones it is modal.
 */
export function AskFrame({ frame }: { frame: WorkspaceView | null | undefined }) {
  const open = useAskOpen();
  const wide = useMediaQuery("(min-width: 1280px)");
  if (!frame) return null;
  return (
    <Sheet
      open={open}
      onOpenChange={setAskOpen}
      title="Ask your data"
      description="Answers come from this study's facts; each says which tool answered and who wrote the words."
      width={420}
      modal={!wide}
      offsetTop={wide ? 52 : undefined}
    >
      <Suspense fallback={<LoadingBlock className="p-4" label="Loading Ask" />}>
        <AskDrawer workspace={frame} open={open} onClose={() => setAskOpen(false)} />
      </Suspense>
    </Sheet>
  );
}
