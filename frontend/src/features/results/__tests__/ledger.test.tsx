/**
 * The Evidence Ledger panel and a Decision Card opened from Trace, on the API's own answers for
 * the seeded demo study (recorded/record_ledger.py). No number, gene or sample is typed in: every
 * expectation is read from a recording.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import type { CardsView, EvidenceView } from "../api";
import { DecisionCards, placeAddress } from "../DecisionCards";
import { EvidencePanel, Ledger, itemSentence, ledgerParts } from "../EvidencePanel";
import cardsJson from "./recorded/cards-trace.json";
import evidenceJson from "./recorded/evidence.json";

// JSON imports widen literal unions ("absent") to string; the recordings are the API's answers.
const EVIDENCE = evidenceJson as unknown as EvidenceView;
const CARDS = cardsJson as unknown as CardsView;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function wrap(children: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response(null, { status: 200 }) });

describe("the Evidence Ledger", { timeout: 30_000 }, () => {
  it("lists what the study cannot tell first, each status as a glyph and a word", () => {
    const { cannot, shows } = ledgerParts(EVIDENCE);
    expect(cannot.length).toBeGreaterThan(0);
    expect(shows.length).toBeGreaterThan(0);
    render(<Ledger view={EVIDENCE} />);
    const first = screen.getByRole("list", { name: "What this study cannot tell you" });
    const rows = within(first).getAllByRole("listitem");
    expect(rows.map((r) => r.getAttribute("data-item"))).toEqual(cannot.map((i) => i.id));
    for (const [i, row] of rows.entries()) {
      const item = cannot[i]!;
      expect(within(row).getByText(item.title)).toBeTruthy();
      const chip = within(row).getByText(item.status_word);
      expect(chip.querySelector("svg")).not.toBeNull(); // a glyph with the word, never colour alone
    }
    // the rest is folded under "What it does show", after what it cannot tell
    const rest = screen.getByRole("list", { name: "What it does show", hidden: true });
    expect(rest.closest("details")?.open).toBe(false);
    expect(
      within(rest)
        .getAllByRole("listitem", { hidden: true })
        .map((r) => r.getAttribute("data-item")),
    ).toEqual(shows.map((i) => i.id));
    expect(first.compareDocumentPosition(rest) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.body.textContent).toContain(EVIDENCE.rule);
  });

  it("shows every number only as one of the ledger's cited facts", () => {
    const { container } = render(<Ledger view={EVIDENCE} />);
    const items = EVIDENCE.items ?? [];
    const lines = [
      { p: container.querySelector("p")!, text: EVIDENCE.summary! },
      ...items.map((item) => ({
        p: container.querySelector(`li[data-item="${item.id}"] p`)!,
        text: itemSentence(item),
      })),
    ];
    for (const { p, text } of lines) {
      expect(p.textContent).toBe(text.plain);
      const cited = p.querySelectorAll("span[title]");
      expect(cited).toHaveLength(text.segments.filter((s) => s.fact).length);
      // every digit on the line is inside a cited fact
      const loose = [...p.querySelectorAll("span > span:not([title])")]
        .map((s) => s.textContent)
        .join("");
      expect(loose).not.toMatch(/\d/);
    }
    expect(lines.some(({ p }) => p.querySelector("span[title]"))).toBe(true);
    // the row shows the title and the status, so the sentence starts after them
    for (const item of items) expect(itemSentence(item).plain.startsWith(item.title)).toBe(false);
  });

  it("reads the ledger for the open study", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation((() => ok(EVIDENCE)) as never);
    render(wrap(<EvidencePanel workspaceKey="w" studyId={EVIDENCE.study_id} />));
    expect(screen.getByRole("heading", { name: "What this study cannot tell you" })).toBeTruthy();
    const first = ledgerParts(EVIDENCE).cannot[0]!;
    expect(await screen.findByText(first.title)).toBeTruthy();
    const [route, init] = get.mock.calls[0] as unknown as [
      string,
      { params: { path: { study_id: string } } },
    ];
    expect(route).toBe("/api/studies/{study_id}/evidence");
    expect(init.params.path.study_id).toBe(EVIDENCE.study_id);
  });
});

describe("a Decision Card opened from Trace", { timeout: 30_000 }, () => {
  const view = CARDS.cards.find((c) => c.place)!;
  const place = view.place!;

  it("says where it came from, its place, what to check and that the numbers stay", () => {
    vi.spyOn(api, "GET").mockImplementation((() => new Promise(() => {})) as never);
    render(wrap(<DecisionCards view={CARDS} workspaceKey="w" studyId={CARDS.study_id} />));
    const others = CARDS.cards.filter((c) => !c.place);
    const article = screen
      .getAllByRole("article")
      .find((a) => a.textContent?.includes(placeAddress(place)))!;
    expect(article).toBeTruthy();
    expect(within(article).getByText("Opened from Trace")).toBeTruthy();
    expect(article.textContent).toContain(place.sample);
    if (place.plate) expect(article.textContent).toContain(place.plate);
    if (place.well) expect(article.textContent).toContain(place.well);
    for (const c of place.what_to_check ?? [])
      expect(within(article).getByText(c[0]!.toUpperCase() + c.slice(1))).toBeTruthy();
    expect(within(article).getByText(place.note)).toBeTruthy();
    // no other card says it came from Trace
    expect(screen.getAllByText("Opened from Trace")).toHaveLength(1);
    expect(others.length).toBeGreaterThan(0);
  });

  it("shows only the calls an option changes, and decides like any card: with a reason", async () => {
    const changing = new Set(
      view.options.flatMap((o) => o.effects.filter((e) => e.changes_call).map((e) => e.gene)),
    );
    expect(changing.size).toBeGreaterThan(0);
    const quiet = view.genes.filter((g) => !changing.has(g));
    expect(quiet.length).toBeGreaterThan(0);
    const post = vi.spyOn(api, "POST").mockImplementation((() => new Promise(() => {})) as never);
    vi.spyOn(api, "GET").mockImplementation((() => new Promise(() => {})) as never);
    render(wrap(<DecisionCards view={CARDS} workspaceKey="w" studyId={CARDS.study_id} />));
    const article = screen
      .getAllByRole("article")
      .find((a) => a.textContent?.includes(placeAddress(place)))!;
    for (const g of changing) expect(within(article).getAllByText(g).length).toBeGreaterThan(0);
    for (const g of quiet) expect(within(article).queryByText(g)).toBeNull();

    const decide = within(article).getByRole("button", { name: /^Decide:/ }) as HTMLButtonElement;
    expect(decide.disabled).toBe(true);
    fireEvent.change(within(article).getByRole("textbox"), {
      target: { value: "Re-ran the well; it failed" },
    });
    expect(decide.disabled).toBe(false);
    fireEvent.click(decide);
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [route, init] = post.mock.calls[0] as unknown as [
      string,
      {
        params: { path: { card_id: string } };
        body: { option: string; reason: string; expected_head: string };
      },
    ];
    expect(route).toBe("/api/studies/{study_id}/cards/{card_id}/decide");
    expect(init.params.path.card_id).toBe(view.card.id);
    expect(init.body.expected_head).toBe(CARDS.head);
    expect(init.body.reason).toBe("Re-ran the well; it failed");
    expect(view.options.map((o) => o.id)).toContain(init.body.option);
  });
});
