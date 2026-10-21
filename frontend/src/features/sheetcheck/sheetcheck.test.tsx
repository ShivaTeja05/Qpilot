/**
 * The Sheet check on recorded answers of a running `qpilot app` (`recorded/`, written by
 * `recorded/record.py`: synthetic sheets made by the engine's own test helpers, uploaded and
 * checked as the page does). A fetch stub serves them to the page's own requests and keeps every
 * request, so a test can check what the page sent. Numbers, names and messages in the assertions
 * are read from the recorded JSON; nothing here is typed-in data.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { count, ofTotal } from "@/lib/format";
import { TooltipProvider } from "@/ui";
import type { SheetCheckView, SheetUploaded } from "./api";
import SheetCheckSection from "./index";
import badFileJson from "./recorded/bad-file.json";
import badSheetJson from "./recorded/bad-sheet.json";
import badUploadJson from "./recorded/bad-upload.json";
import cleanChangedJson from "./recorded/clean-changed.json";
import cleanConfirmedJson from "./recorded/clean-confirmed.json";
import cleanGuessedJson from "./recorded/clean-guessed.json";
import cleanUploadJson from "./recorded/clean-upload.json";
import datesGuessedJson from "./recorded/dates-guessed.json";
import datesUploadJson from "./recorded/dates-upload.json";
import demoStudyJson from "./recorded/demo-study.json";
import demoUploadJson from "./recorded/demo-upload.json";
import invertedGuessedJson from "./recorded/inverted-guessed.json";
import invertedUploadJson from "./recorded/inverted-upload.json";
import workspacesJson from "./recorded/workspaces.json";
import { CAUSE_WORDS, FINDING_STATUS, SLIP_WORDS, slipWords } from "./words";

interface Sent {
  method: string;
  path: string;
  body: unknown;
  /** The uploaded file's name (multipart `sheet`). */
  file?: string;
}

// The typed client keeps the `fetch` and `Request` it finds when its module loads, so the stub
// goes in before any import runs.
const net = vi.hoisted(() => {
  const state = {
    answer: (_s: Sent): [number, unknown] => [404, null],
    sent: [] as Sent[],
  };
  const NodeRequest = globalThis.Request;
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(
        typeof input === "string" && input.startsWith("/") ? `${location.origin}${input}` : input,
        init,
      );
    }
  } as typeof Request;
  const reply = (s: Sent) => {
    state.sent.push(s);
    const [status, answer] = state.answer(s);
    return new Response(
      JSON.stringify(answer ?? { error: { code: "not_found", message: "No such API route." } }),
      { status: answer === null ? 404 : status, headers: { "content-type": "application/json" } },
    );
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.body instanceof FormData) {
      const file = init.body.get("sheet") as File | null;
      return reply({
        method: init.method ?? "POST",
        path: String(input),
        body: null,
        file: file?.name,
      });
    }
    const request = input instanceof Request ? input : new Request(input, init);
    const path = new URL(request.url).pathname;
    const text = request.method === "GET" ? "" : await request.text();
    return reply({ method: request.method, path, body: text ? JSON.parse(text) : null });
  }) as typeof fetch;
  return state;
});

const workspaces = workspacesJson as unknown as Schemas["WorkspaceList"];
const cleanUpload = cleanUploadJson as SheetUploaded;
const invertedUpload = invertedUploadJson as SheetUploaded;
const datesUpload = datesUploadJson as SheetUploaded;
const demoUpload = demoUploadJson as SheetUploaded;
const badUpload = badUploadJson as SheetUploaded;
const guessed = cleanGuessedJson as unknown as SheetCheckView;
const changed = cleanChangedJson as unknown as SheetCheckView;
const confirmed = cleanConfirmedJson as unknown as SheetCheckView;
const inverted = invertedGuessedJson as unknown as SheetCheckView;
const dates = datesGuessedJson as unknown as SheetCheckView;
const demo = demoStudyJson as unknown as SheetCheckView;
const badSheet = badSheetJson as { status: number; body: { error: { message: string } } };
const badFile = badFileJson as { status: number; body: { error: { message: string } } };

const uploads = [cleanUpload, invertedUpload, datesUpload, demoUpload, badUpload];
/** The column a person set in the recording (its basis is "user"). */
const setColumn = changed.mapping.columns.find((c) => c.basis === "user")!;

function recorded(s: Sent): [number, unknown] {
  if (s.method === "GET" && s.path === "/api/workspaces") return [200, workspaces];
  if (s.path === "/api/sheets") {
    if (s.file === "notes.pdf") return [badFile.status, badFile.body];
    const kept = uploads.find((u) => u.name === s.file);
    return kept ? [200, kept] : [404, null];
  }
  const id = /^\/api\/sheets\/([0-9a-f]+)\/check$/.exec(s.path)?.[1];
  const body = (s.body ?? {}) as { columns?: unknown[]; confirm?: boolean; study_id?: string };
  if (id === cleanUpload.sheet_id) {
    if (!body.columns) return [200, guessed];
    return [200, body.confirm ? confirmed : changed];
  }
  if (id === invertedUpload.sheet_id) return [200, inverted];
  if (id === datesUpload.sheet_id) return [200, dates];
  if (id === demoUpload.sheet_id && body.study_id === demo.study_id) return [200, demo];
  if (id === badUpload.sheet_id) return [badSheet.status, badSheet.body];
  return [404, null];
}

beforeAll(() => {
  // Radix Select asks the pointer and scrolls its list; jsdom has neither.
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(() => {
  cleanup();
  net.sent = [];
  net.answer = recorded;
});
net.answer = recorded;

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <SheetCheckSection workspace={null} rest={[]} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

/** Choose a file as the hidden file input would give it. */
function choose(container: HTMLElement, name: string) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [new File(["x"], name)] } });
}

/** Open a Radix select by keyboard and pick an option by its words. */
async function pick(trigger: HTMLElement, option: string) {
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter" });
  fireEvent.click(await screen.findByRole("option", { name: option }));
}

const checks = () => net.sent.filter((s) => s.path.endsWith("/check"));

/** Every digit inside `el` sits in a fact the answer cites (no number is re-typed). */
function numbersAreFacts(el: HTMLElement, facts: { id: string; text: string }[]) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let digits = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!/\d/.test(node.textContent ?? "")) continue;
    digits += 1;
    const fact = node.parentElement?.closest<HTMLElement>("[data-fact]");
    expect(fact, `"${node.textContent}" is not a fact`).toBeTruthy();
    expect(facts.find((f) => f.id === fact!.dataset.fact)?.text).toBe(fact!.textContent);
  }
  return digits;
}

describe("the Sheet check", () => {
  it("says what the check does before a sheet is chosen", async () => {
    show();
    expect(screen.getByRole("heading", { name: "What the check does" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Which sheets it reads" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Choose a sheet" })).toBeTruthy();
    // the analysed studies to compare with come from the workspace list
    await waitFor(() =>
      expect(
        (screen.getByRole("combobox", { name: /Compare with a study/ }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
  });

  it("says the guessed mapping is a guess, and lists every column", async () => {
    const { container } = show();
    choose(container, cleanUpload.name);
    const banner = await screen.findByRole("region", { name: "Column mapping" });
    expect(guessed.mapping.confirmed).toBe(false);
    expect(within(banner).getByText(`Column mapping: ${guessed.mapping.status}`)).toBeTruthy();
    expect(screen.getByText("A guess")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Confirm this mapping" })).toBeTruthy();
    // uploaded once, then checked with nothing set and nothing confirmed
    expect(net.sent.filter((s) => s.path === "/api/sheets")).toHaveLength(1);
    expect(checks()[0]?.body).toEqual({ confirm: false });
    const table = screen.getByRole("table", { name: "What each column of the sheet holds" });
    for (const c of guessed.mapping.columns) {
      const select = within(table).getByRole("combobox", { name: `What column ${c.column} holds` });
      expect(select.textContent).toBe(c.role_word);
    }
  });

  it("re-checks a changed column as a guess, and confirming sends confirm: true with it", async () => {
    const { container } = show();
    choose(container, cleanUpload.name);
    await screen.findByRole("region", { name: "Column mapping" });
    const word = guessed.mapping.roles.find((r) => r.id === setColumn.role)!.word;
    await pick(
      screen.getByRole("combobox", { name: `What column ${setColumn.column} holds` }),
      word,
    );
    const change = { column: setColumn.column, role: setColumn.role };
    await waitFor(() =>
      expect(checks().at(-1)?.body).toEqual({ confirm: false, columns: [change] }),
    );
    // still a guess, now with the person's column
    await screen.findByText(`You set column ${setColumn.column}; the others keep the guess.`, {
      exact: false,
    });
    expect(changed.mapping.confirmed).toBe(false);
    expect(screen.getByText(`Column mapping: ${changed.mapping.status}`)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Confirm this mapping" }));
    await waitFor(() =>
      expect(checks().at(-1)?.body).toEqual({ confirm: true, columns: [change] }),
    );
    expect(confirmed.mapping.confirmed).toBe(true);
    expect(await screen.findByText(`Column mapping: ${confirmed.mapping.status}`)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Confirm this mapping" })).toBeNull();
  });

  it("names the first place to look: its column, its step and the slip in words", async () => {
    const { container } = show();
    choose(container, invertedUpload.name);
    const card = await screen.findByRole("region", { name: "First place to look" });
    const first = inverted.findings[0]!;
    expect(first.paths.length).toBeGreaterThan(0);
    expect(within(card).getAllByText(first.column).length).toBeGreaterThan(0);
    expect(within(card).getByText(`${first.step_word} for ${first.gene}`)).toBeTruthy();
    const slips = within(card).getByRole("list", { name: "What reproduces it" });
    for (const path of first.paths) {
      expect(SLIP_WORDS[path]).toBeDefined(); // a known slip, said in words, never its id
      expect(within(slips).getByText(slipWords(path))).toBeTruthy();
      expect(card.textContent).not.toContain(path);
    }
    expect(within(card).getByText(FINDING_STATUS[first.status].word)).toBeTruthy();
    expect(card.textContent).toContain(`First at row ${count(first.first_row)}`);
    // every recomputed column, with its result
    const columns = screen.getByRole("table", { name: "Each recomputed column and its result" });
    expect(within(columns).getAllByRole("row")).toHaveLength(inverted.columns.length + 1);
    expect(within(columns).getAllByText("Differs")).toHaveLength(
      inverted.columns.filter((c) => c.status === "differs").length,
    );
  });

  it("shows numbers in sentences only as the check's facts, and counts as its counts", async () => {
    const { container } = show();
    choose(container, invertedUpload.name);
    const found = await screen.findByRole("region", { name: "What the check found" });
    const headline = within(found).getByText(
      (_, el) => el?.tagName === "P" && el.textContent === inverted.headline.plain,
    );
    expect(numbersAreFacts(headline, inverted.headline.facts)).toBeGreaterThan(0);
    const look = screen.getByRole("region", { name: "First place to look" });
    const words = within(look).getByText(
      (_, el) => el?.tagName === "P" && el.textContent === inverted.findings_text.plain,
    );
    expect(numbersAreFacts(words, inverted.findings_text.facts)).toBeGreaterThan(0);
    const c = inverted.counts;
    expect(within(found).getByText(ofTotal(c.reproduced, c.fold_changes))).toBeTruthy();
    expect(
      within(found).getByText("With a named cause").parentElement?.querySelector("dd")?.textContent,
    ).toBe(count(c.named));
  });

  it("compares with a study and shows its hand-overs in the check's words", async () => {
    const { container } = show();
    const study = workspaces.workspaces.find((w) => w.study_id === demo.study_id)!;
    const select = screen.getByRole("combobox", { name: /Compare with a study/ });
    await waitFor(() => expect((select as HTMLButtonElement).disabled).toBe(false));
    await pick(select, study.title);
    choose(container, demoUpload.name);
    const card = await screen.findByRole("region", { name: "Handed over to the study" });
    expect(checks()[0]?.body).toEqual({ confirm: false, study_id: demo.study_id });
    expect(demo.hand_overs.length).toBeGreaterThan(0);
    for (const h of demo.hand_overs) {
      const line = within(card).getByText(
        (_, el) => el?.tagName === "P" && el.textContent === h.line.plain,
      );
      numbersAreFacts(line, h.line.facts);
      for (const cause of h.causes) {
        expect(CAUSE_WORDS[cause]).toBeDefined();
        expect(within(card).getAllByText(CAUSE_WORDS[cause]!).length).toBeGreaterThan(0);
      }
    }
    const audit = within(card).getByRole("link", { name: /robustness audit/ });
    expect(audit.getAttribute("href")).toContain(study.key);
  });

  it("flags a gene name that looks like a date, with the check's note", async () => {
    const { container } = show();
    choose(container, datesUpload.name);
    const list = await screen.findByRole("list", { name: "Gene names to check" });
    const flagged = dates.genes.filter((g) => g.flagged);
    expect(flagged.length).toBeGreaterThan(0);
    for (const g of flagged) {
      expect(within(list).getByText(g.key)).toBeTruthy();
      expect(within(list).getByText(g.note)).toBeTruthy();
    }
  });

  it("shows an error answer in the server's own words", async () => {
    const { container } = show();
    choose(container, badUpload.name);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(badSheet.body.error.message);
    expect(within(alert).getByText("The sheet was not checked")).toBeTruthy();
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeTruthy();

    choose(container, "notes.pdf");
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(badFile.body.error.message),
    );
    expect(screen.getByText("The sheet was not uploaded")).toBeTruthy();
  });
});
