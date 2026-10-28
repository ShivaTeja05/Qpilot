/**
 * Paste a sample → group list (two columns copied from Excel; a third column is the
 * biological unit). Each line is matched to a sample of the file (its name in the file, its
 * id, or a unique match ignoring case and separators); what does not match is named back.
 */
import { ClipboardPaste } from "lucide-react";
import { useMemo, useState } from "react";
import { count } from "@/lib/format";
import { Badge, Button, Field, Table, TBody, TD, TH, THead, TR, Textarea } from "@/ui";
import { visibleText, type QuoteLookup } from "@/ui/proposal";
import {
  parsePasted,
  pastedItems,
  sampleMatcher,
  withItems,
  type Draft,
  type EditorView,
} from "./draft";

const MAX_PASTE = 200_000;

export function PastePanel({
  view,
  draft,
  quotes,
  onDraft,
  onDone,
}: {
  view: EditorView;
  draft: Draft;
  quotes: QuoteLookup;
  onDraft: (next: Draft) => void;
  /** After the list is added to the draft (e.g. show the samples). */
  onDone?: () => void;
}) {
  const [text, setText] = useState("");
  const match = useMemo(
    () => sampleMatcher(view.samples, (id) => (id ? (quotes(id)?.value ?? null) : null)),
    [view.samples, quotes],
  );
  const rows = useMemo(() => parsePasted(text, match), [text, match]);
  const items = pastedItems(rows);
  const usable = rows.filter((r) => !r.problem).length;
  const problems = rows.filter((r) => r.problem);
  return (
    <div className="flex flex-col gap-3">
      <Field
        label="Paste a sample list"
        htmlFor="design-paste"
        hint="Copy two columns from Excel (sample, group) and paste them here; a third column, if any, is the biological unit (the animal or donor). A header row is skipped."
      >
        <Textarea
          id="design-paste"
          rows={6}
          value={text}
          maxLength={MAX_PASTE}
          placeholder={"S1\tcontrol\nS2\tcontrol\nS3\ttreated"}
          onChange={(e) => setText(e.target.value)}
          className="font-mono text-[12.5px]"
        />
      </Field>
      {rows.length ? (
        <>
          <p className="text-[13px] text-fg" aria-live="polite">
            {count(usable)} of {count(rows.length)} line{rows.length === 1 ? "" : "s"} match a
            sample
            {problems.length ? `; ${count(problems.length)} cannot be used (listed first)` : ""}.
          </p>
          <div className="max-h-64 overflow-auto rounded-lg border border-line qp-scroll">
            <Table caption="The pasted lines and the samples they match">
              <THead>
                <TR>
                  <TH numeric>Line</TH>
                  <TH>Pasted</TH>
                  <TH>Sample</TH>
                  <TH>Group</TH>
                  <TH>Unit</TH>
                </TR>
              </THead>
              <TBody>
                {[...problems, ...rows.filter((r) => !r.problem)].slice(0, 400).map((r) => (
                  <TR key={r.line}>
                    <TD numeric>{r.line}</TD>
                    <TD className="max-w-[12rem] truncate font-mono text-xs" title={r.text}>
                      {visibleText(r.text)}
                    </TD>
                    <TD>
                      {r.problem ? (
                        <Badge tone="warn">{r.problem}</Badge>
                      ) : (
                        <span className="font-mono text-[12.5px]">{r.sample}</span>
                      )}
                    </TD>
                    <TD>{r.problem ? null : (r.group ?? "—")}</TD>
                    <TD>{r.problem ? null : (r.unit ?? "—")}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        </>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          icon={<ClipboardPaste />}
          disabled={!items.length}
          onClick={() => {
            onDraft(withItems(draft, items));
            setText("");
            onDone?.();
          }}
        >
          {items.length
            ? `Add ${count(usable)} sample${usable === 1 ? "" : "s"} to the changes`
            : "Add to the changes"}
        </Button>
        {text ? (
          <Button variant="ghost" onClick={() => setText("")}>
            Clear
          </Button>
        ) : null}
      </div>
    </div>
  );
}
