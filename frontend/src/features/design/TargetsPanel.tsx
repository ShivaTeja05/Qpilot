/**
 * The target list of the Design editor: each target's role (reference gene, gene of interest,
 * left out), set with one control per target. A change goes to the draft; nothing is recorded
 * until the person reviews it.
 */
import { CircleDot } from "lucide-react";
import { count } from "@/lib/format";
import { Badge, SegmentedControl, Table, TBody, TD, TH, THead, TR } from "@/ui";
import { visibleText, type QuoteLookup } from "@/ui/proposal";
import { targetNow, targetRoleItem, type Draft, type EditItem, type EditorView } from "./draft";
import { purposeNow } from "./PurposePanel";

type Role = "ref" | "toi" | "ignore";
const ROLE_LABEL: Record<Role, string> = {
  ref: "Reference gene",
  toi: "Gene of interest",
  ignore: "Leave out",
};
const DECLARED: Record<string, string> = { ref: "a reference gene", toi: "a target" };

export function TargetsPanel({
  view,
  draft,
  quotes,
  onChange,
  disabled,
}: {
  view: EditorView;
  draft: Draft;
  quotes: QuoteLookup;
  onChange: (items: EditItem[]) => void;
  disabled?: boolean;
}) {
  const everyRef = view.targets.length > 1 && view.targets.every((t) => t.declared_type === "ref");
  return (
    <div className="flex flex-col gap-3">
      {purposeNow(view, draft) === "quantify" ? (
        <p className="max-w-prose text-[13px] text-muted">
          This study quantifies samples: every target with standards is quantified, and no reference
          gene is needed. <span className="font-medium text-fg">Leave out</span> takes a target out
          of the study (an empty channel, an assay not part of this experiment): none of its wells
          is used.
        </p>
      ) : (
        <p className="max-w-prose text-[13px] text-muted">
          Mark at least one <span className="font-medium text-fg">reference gene</span> (a
          housekeeping gene the others are normalised to) and the{" "}
          <span className="font-medium text-fg">genes of interest</span> you compare.{" "}
          <span className="font-medium text-fg">Leave out</span> takes a target out of the study (an
          empty channel, a spike-in, an assay not part of this experiment): none of its wells is
          used.
        </p>
      )}
      {everyRef ? (
        <p className="rounded-lg border border-warn/30 bg-warn-soft/40 px-3 py-2 text-[13px] text-fg">
          The file declares every target a reference gene. Some instruments write that for every
          target, so it does not say which ones are: choose here.
        </p>
      ) : null}
      <div className="overflow-x-auto rounded-lg border border-line">
        <Table caption="Targets and their roles">
          <THead>
            <TR>
              <TH>Target</TH>
              <TH numeric>Wells</TH>
              <TH>The file says</TH>
              <TH>Role in this study</TH>
            </TR>
          </THead>
          <TBody>
            {view.targets.map((t) => {
              const now = targetNow(t, draft);
              const original = t.text_id ? quotes(t.text_id)?.value : null;
              const shown = original && original !== t.target ? visibleText(original) : null;
              return (
                <TR key={t.target}>
                  <TD className="max-w-[16rem]">
                    <div className="flex flex-col">
                      <span className="truncate font-mono text-[12.5px] text-fg" title={t.target}>
                        {t.target}
                      </span>
                      {shown ? (
                        <span className="truncate text-xs text-muted" title={shown}>
                          in the file: “{shown.slice(0, 60)}”
                        </span>
                      ) : null}
                    </div>
                  </TD>
                  <TD numeric>{count(t.n_wells)}</TD>
                  <TD className="text-muted">{DECLARED[t.declared_type] ?? t.declared_type}</TD>
                  <TD>
                    <div className="flex flex-wrap items-center gap-2">
                      <SegmentedControl<Role | "">
                        label={`Role of target ${t.target}`}
                        size="sm"
                        value={(now.role as Role | null) ?? ""}
                        onValueChange={(v) => v && onChange([targetRoleItem(t.target, v)])}
                        options={(Object.keys(ROLE_LABEL) as Role[]).map((r) => ({
                          value: r,
                          label: ROLE_LABEL[r],
                          disabled,
                        }))}
                      />
                      {now.changed ? (
                        <Badge tone="accent" icon={<CircleDot />}>
                          not recorded yet
                        </Badge>
                      ) : now.role == null ? (
                        <span className="text-xs text-muted">not decided</span>
                      ) : null}
                      {t.waiting.length ? <Badge tone="info">a proposal waits</Badge> : null}
                    </div>
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </div>
    </div>
  );
}
