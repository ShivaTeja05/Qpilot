import { Fragment } from "react";
import { MOD } from "@/lib/hooks";
import { Dialog, Kbd } from "@/ui";
import { setShortcutsOpen, useShortcutsOpen } from "./actions";

const GROUPS: { title: string; rows: [string[][], string][] }[] = [
  {
    title: "Everywhere",
    rows: [
      [[[MOD, "K"]], "Search, go to a section or a gene, run an action"],
      [[[MOD, "J"]], "Ask your data"],
      [[[MOD, "O"]], "Open a file"],
      [[["?"]], "This list"],
    ],
  },
  {
    title: "Go to (press g, then the letter)",
    rows: [
      [[["g", "d"]], "Design"],
      [[["g", "c"]], "Curves"],
      [[["g", "r"]], "Results"],
      [[["g", "a"]], "Audit"],
      [[["g", "p"]], "Prism"],
      [[["g", "e"]], "Record"],
    ],
  },
  {
    title: "Proposals and Decision Cards",
    rows: [
      [[["j"], ["k"]], "Next / previous card"],
      [[["a"]], "Accept the focused proposal"],
      [[["e"]], "Edit the focused proposal"],
      [[["x"]], "Reject the focused proposal"],
      [[["Enter"]], "Write the reason on the focused card"],
      [[[MOD, "Enter"]], "Decide"],
    ],
  },
  {
    title: "Genes",
    rows: [[[["["], ["]"]], "Previous / next gene"]],
  },
];

/** The shortcut sheet (`?`). */
export function ShortcutSheet() {
  const open = useShortcutsOpen();
  return (
    <Dialog
      open={open}
      onOpenChange={setShortcutsOpen}
      title="Keyboard shortcuts"
      description="Letters work when you are not typing in a field."
      size="lg"
    >
      <div className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
        {GROUPS.map((g) => (
          <section key={g.title}>
            <h3 className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">
              {g.title}
            </h3>
            <dl className="flex flex-col gap-1.5">
              {g.rows.map(([combos, what]) => (
                <div key={what} className="flex items-center justify-between gap-4 text-[13px]">
                  <dt className="text-fg">{what}</dt>
                  <dd className="flex shrink-0 items-center gap-1 text-muted">
                    {combos.map((keys, i) => (
                      <Fragment key={i}>
                        {i > 0 ? <span className="text-xs">/</span> : null}
                        {keys.map((k) => (
                          <Kbd key={k}>{k}</Kbd>
                        ))}
                      </Fragment>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </Dialog>
  );
}
