/**
 * How the sheet was read — a guess until a person confirms it. The banner says so at the top of
 * the page; the card lists every column (its letter, what it is taken to hold, its gene, where the
 * guess came from) with a role select each, the reference genes, and **Confirm this mapping**.
 * Changing a column re-checks at once, as a guess; confirming sends the same choices with
 * `confirm: true`.
 */
import { Check, ShieldAlert, ShieldCheck } from "lucide-react";
import { useId, useState, type Ref } from "react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Field,
  Input,
  Select,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/ui";
import { cn } from "@/lib/cn";
import { count, MISSING } from "@/lib/format";
import type { SheetCheckView, SheetRole } from "./api";
import type { SheetCheck } from "./useSheetCheck";
import { BASIS_WORDS, LAYOUT_WORDS, listWords } from "./words";

/** The mapping's status, prominently: a guess (with the way to review it) or confirmed. */
export function MappingBanner({ view, onReview }: { view: SheetCheckView; onReview: () => void }) {
  const confirmed = view.mapping.confirmed;
  return (
    <section
      aria-label="Column mapping"
      className={cn(
        "flex flex-wrap items-start gap-3 rounded-xl border p-4",
        confirmed ? "border-ok/30 bg-ok-soft/50" : "border-warn/30 bg-warn-soft/50",
      )}
    >
      <span
        className={cn("mt-0.5 shrink-0 [&_svg]:size-5", confirmed ? "text-ok" : "text-warn")}
        aria-hidden
      >
        {confirmed ? <ShieldCheck /> : <ShieldAlert />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-fg">Column mapping: {view.mapping.status}</p>
        <p className="mt-0.5 text-[13px] text-muted">
          {confirmed
            ? "You confirmed what each column holds. Changing a column makes the mapping a guess again until you confirm it."
            : "qPilot guessed what each column holds from its header and its values. Everything below rests on that guess: look at the columns, change any it got wrong, then confirm."}
        </p>
      </div>
      {confirmed ? null : (
        <Button size="sm" onClick={onReview}>
          Review the columns
        </Button>
      )}
    </section>
  );
}

/**
 * The reference genes: the guess (or what a person named), editable as a list. Shown in the
 * mapping card, and on its own when a first check could not tell the references.
 */
export function References({ state, current }: { state: SheetCheck; current: string[] }) {
  const [text, setText] = useState(current.join(", "));
  const named = text
    .split(/[,;]/)
    .map((s) => s.trim())
    .filter(Boolean);
  const same = named.join("|") === current.join("|");
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (named.length && !same) state.setReferences(named);
      }}
    >
      <Field
        label="Reference genes"
        hint={
          state.choice.references
            ? "Named by you. ΔCq subtracts the mean Cq of these genes."
            : current.length
              ? "Recognised by name or header. ΔCq subtracts the mean Cq of these genes; separate names with commas."
              : "Name them as the sheet's headers write them, separated by commas."
        }
      >
        <Input value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" type="submit" disabled={!named.length || same || state.busy !== null}>
          Use these references
        </Button>
        {state.choice.references ? (
          <Button size="sm" variant="ghost" onClick={() => state.setReferences(null)}>
            Back to the guess
          </Button>
        ) : null}
      </div>
    </form>
  );
}

export function MappingCard({
  state,
  view,
  headingRef,
}: {
  state: SheetCheck;
  view: SheetCheckView;
  headingRef?: Ref<HTMLHeadingElement>;
}) {
  const titleId = useId();
  const m = view.mapping;
  const options = m.roles.map((r) => ({ value: r.id, label: r.word }));
  const changed = Object.keys(state.choice.columns);
  const blocked = state.busy !== null || state.error !== null;

  return (
    <Card as="section" aria-labelledby={titleId}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-4 pt-4 pb-3">
        <div className="min-w-0">
          <h2
            id={titleId}
            ref={headingRef}
            tabIndex={-1}
            className="text-[15px] font-semibold tracking-tight text-fg outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
          >
            How the sheet was read
          </h2>
          <p className="mt-0.5 text-[13px] text-muted">
            Sheet <span className="tabular">{count(m.sheet)}</span>, header in row{" "}
            <span className="tabular">{count(m.header_row)}</span>; {LAYOUT_WORDS[m.layout]}.
          </p>
        </div>
        {m.confirmed ? (
          <Badge tone="ok" icon={<ShieldCheck />}>
            Confirmed
          </Badge>
        ) : (
          <Badge tone="warn" icon={<ShieldAlert />}>
            A guess
          </Badge>
        )}
      </div>

      <div className="overflow-x-auto border-y border-line">
        <Table caption="What each column of the sheet holds">
          <THead>
            <tr>
              <TH>Column</TH>
              <TH>Holds</TH>
              <TH>Gene</TH>
              <TH>Guessed from</TH>
            </tr>
          </THead>
          <TBody>
            {m.columns.map((c) => {
              const role = state.roleOf(c.column);
              const set = c.column in state.choice.columns;
              return (
                <TR key={c.column} className={cn(set && "bg-accent-soft/30")}>
                  <TD className="font-mono font-medium">{c.column}</TD>
                  <TD className="min-w-44 py-1">
                    <Select<SheetRole>
                      size="sm"
                      value={role}
                      onValueChange={(r) => state.setRole(c.column, r)}
                      options={options}
                      label={`What column ${c.column} holds`}
                    />
                  </TD>
                  <TD className={cn("font-mono text-[12.5px]", !c.gene && "text-muted")}>
                    {c.gene ?? MISSING}
                  </TD>
                  <TD className="whitespace-nowrap text-muted">{BASIS_WORDS[c.basis]}</TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </div>

      <CardBody className="flex flex-col gap-4 pt-4">
        <References
          key={`${view.sheet_id}:${(state.choice.references ?? m.references).join("|")}`}
          state={state}
          current={state.choice.references ?? m.references}
        />
        <div className="flex flex-col gap-2 border-t border-line pt-4">
          {m.confirmed ? (
            <p className="flex items-start gap-2 text-[13px] text-fg">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
              You confirmed this mapping
              {changed.length ? ` with ${listWords(changed.map((c) => `column ${c}`))} set` : ""}.
            </p>
          ) : (
            <>
              <p className="text-[13px] text-muted">
                The check is only as right as this mapping.{" "}
                {changed.length
                  ? `You set ${listWords(changed.map((c) => `column ${c}`))}; the others keep the guess.`
                  : "Every column keeps the guess."}{" "}
                Confirm when each column says what it holds.
              </p>
              <div>
                <Button
                  variant="primary"
                  icon={<Check />}
                  onClick={state.confirm}
                  disabled={blocked}
                  title={
                    state.error
                      ? "The last change could not be checked; change it back or try again first."
                      : undefined
                  }
                >
                  Confirm this mapping
                </Button>
              </div>
            </>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
