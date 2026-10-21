/**
 * Where to look on the API's own answers for the seeded demo study (recorded/record_where.py):
 * a gene with a place whose options change its call, a gene no place changes, a sample, a well,
 * a sample in no comparison, the same gene after a person's Decide…, and a refused (stale)
 * Decide…. No number, gene, sample or well is typed in: every expectation is read from them.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { count } from "@/lib/format";
import { toast } from "@/ui";
import type { PlaceOpened, WhereRoot, WhereView } from "../api";
import { WhereResult, WhereToLook, analysisLine } from "../WhereToLook";
import { cannotWords, checkedWords, placeWords } from "../words";
import absentJson from "./recorded/where-absent.json";
import calmJson from "./recorded/where-calm.json";
import geneJson from "./recorded/where-gene.json";
import openedViewJson from "./recorded/where-gene-opened.json";
import openedJson from "./recorded/place-opened.json";
import staleJson from "./recorded/place-stale.json";
import sampleJson from "./recorded/where-sample.json";
import wellJson from "./recorded/where-well.json";

const GENE = geneJson as unknown as WhereView;
const CALM = calmJson as unknown as WhereView;
const SAMPLE = sampleJson as unknown as WhereView;
const WELL = wellJson as unknown as WhereView;
const ABSENT = absentJson as unknown as WhereView;
const OPENED_VIEW = openedViewJson as unknown as WhereView;
const OPENED = openedJson as PlaceOpened;
const STALE = staleJson as { status: number; body: { error: { code: string; message: string } } };
const WS = { key: "bc1d233e3866", kind: "session" as const };
const noop = () => undefined;
const rootOf = (v: WhereView) => ({ kind: v.root.kind, id: v.root.id }) as WhereRoot;
/** Testing Library folds the page's narrow no-break spaces into plain ones. */
const text = (formatted: string) => formatted.replace(/\s+/g, " ");

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

function result(view: WhereView, events: Partial<Parameters<typeof WhereResult>[0]> = {}) {
  return render(
    <WhereResult
      workspace={WS}
      view={view}
      root={rootOf(view)}
      deciding={null}
      onDecide={noop}
      onOpenCard={noop}
      onMore={noop}
      onSample={noop}
      {...events}
    />,
  );
}

/** The places' own rows (each holds lists of its own). */
const places = () =>
  [...screen.getByRole("list", { name: "Places to look" }).children] as HTMLElement[];
const decideButtons = () => screen.queryAllByRole("button", { name: /^Decide…/ });

describe("where to look, read", { timeout: 30_000 }, () => {
  it("shows the engine's sentences, every number a cited fact", () => {
    const { container } = result(GENE);
    const lines = GENE.text;
    for (const t of lines) expect(container.textContent).toContain(t.plain);
    const cited = container.querySelectorAll("span[title^='From the trace']");
    expect(cited).toHaveLength(lines.flatMap((t) => t.segments.filter((s) => s.fact)).length);
    expect(screen.getByText(analysisLine(GENE))).toBeTruthy();
  });

  it("lists each place with what it fails, what each option does, and Decide… where it can", () => {
    const decidable = GENE.places.filter((p) => p.can_decide && !p.card_status);
    expect(decidable.length).toBeGreaterThan(0);
    const onDecide = vi.fn();
    result(GENE, { onDecide });
    const rows = places();
    expect(rows).toHaveLength(GENE.places.length);
    for (const [i, row] of rows.entries()) {
      const p = GENE.places[i]!;
      expect(row.textContent).toContain(placeWords(p));
      for (const c of p.checks) {
        expect(row.textContent).toContain(c.looks_like);
        expect(row.textContent).toContain(c.what_to_check);
        expect(row.textContent).not.toContain(c.code);
      }
      for (const o of p.options) {
        expect(row.textContent).toContain(o.label);
        expect(row.textContent).toContain(o.consequence_word);
        for (const g of o.changed_calls)
          expect(within(row).getAllByRole("link", { name: g }).length).toBeGreaterThan(0);
      }
      expect(within(row).queryAllByRole("button", { name: /^Decide…/ })).toHaveLength(
        p.can_decide && !p.card_status ? 1 : 0,
      );
    }
    expect(decideButtons()).toHaveLength(decidable.length);
    fireEvent.click(decideButtons()[0]!);
    expect(onDecide).toHaveBeenCalledWith(decidable[0]);
    expect(screen.getByText(GENE.decide_note)).toBeTruthy();
    expect(screen.getByText(new RegExp(`^${GENE.n_more} more places found`))).toBeTruthy();
  });

  it("offers no Decide… where no option changes the call", () => {
    expect(CALM.places.length).toBeGreaterThan(0);
    expect(CALM.places.some((p) => p.can_decide)).toBe(false);
    result(CALM);
    expect(places()).toHaveLength(CALM.places.length);
    expect(decideButtons()).toHaveLength(0);
    expect(screen.getAllByText(/^Nothing to decide from here/)).toHaveLength(CALM.places.length);
    expect(screen.queryByText(CALM.decide_note)).toBeNull();
  });

  it("says a place already opened is on Results, and goes there", () => {
    const opened = OPENED_VIEW.places.find((p) => p.card_id === OPENED.card_id)!;
    expect(opened.card_status).toBeTruthy();
    const onOpenCard = vi.fn();
    result(OPENED_VIEW, { onOpenCard });
    const row = places()[OPENED_VIEW.places.indexOf(opened)]!;
    expect(within(row).queryByRole("button", { name: /^Decide…/ })).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: /^Open on Results/ }));
    expect(onOpenCard).toHaveBeenCalledWith(OPENED.card_id);
  });

  it("says what was checked and what the data cannot show in words, not codes", () => {
    for (const view of [GENE, SAMPLE, WELL]) {
      cleanup();
      result(view);
      const checked = checkedWords(view.checked_nothing_found);
      const cannot = cannotWords(view.cannot_show);
      for (const words of checked) expect(words).not.toMatch(/^S\d/);
      for (const words of cannot) expect(words).not.toMatch(/^S\d|_/);
      const shown = [...document.querySelectorAll("li")].map((li) => text(li.textContent ?? ""));
      for (const w of [...checked, ...cannot])
        expect(shown).toContain(text(w[0]!.toUpperCase() + w.slice(1)));
    }
    // the plates whose no-template controls were checked are gathered into one line
    const plates = SAMPLE.checked_nothing_found.filter((c) => c.startsWith("S6:"));
    expect(plates.length).toBeGreaterThan(6);
    expect(text(checkedWords(SAMPLE.checked_nothing_found)[0]!)).toContain(
      text(`${count(plates.length)} plates`),
    );
    const few = GENE.checked_nothing_found.filter((c) => c.startsWith("S6:"));
    for (const c of few) expect(checkedWords(GENE.checked_nothing_found)[0]).toContain(c.slice(3));
  });

  it("names the samples in no comparison and why, each one traceable", () => {
    const onSample = vi.fn();
    result(GENE, { onSample });
    expect(GENE.n_absent).toBeGreaterThan(0);
    for (const a of GENE.absent) expect(document.body.textContent).toContain(a.why);
    const first = GENE.absent[0]!;
    fireEvent.click(screen.getByRole("button", { name: `Sample ${first.sample}` }));
    expect(onSample).toHaveBeenCalledWith(first.sample);
    cleanup();
    // a sample traced on its own: in no comparison, and not a link to itself
    result(ABSENT);
    expect(ABSENT.answer).toBe("absent");
    expect(ABSENT.places).toHaveLength(0);
    expect(screen.queryByRole("button", { name: `Sample ${ABSENT.root.id}` })).toBeNull();
    expect(document.body.textContent).toContain(ABSENT.absent[0]!.why);
  });
});

describe("Decide…", { timeout: 30_000 }, () => {
  const scope = { key: WS.key, studyId: GENE.study_id, kind: WS.kind };
  const ok = (data: unknown) =>
    Promise.resolve({ data, response: new Response(null, { status: 200 }) });

  it("opens the place as a Decision Card, sending the head the view was read at", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation((() => ok(GENE)) as never);
    const post = vi.spyOn(api, "POST").mockImplementation((() => ok(OPENED)) as never);
    const success = vi.spyOn(toast, "success");
    render(wrap(<WhereToLook workspace={WS} scope={scope} genes={[]} initial={rootOf(GENE)} />));
    const decide = (await screen.findAllByRole("button", { name: /^Decide…/ }))[0]!;
    const [route, init] = get.mock.calls[0] as unknown as [
      string,
      { params: { query: Record<string, unknown> } },
    ];
    expect(route).toBe("/api/studies/{study_id}/where-to-look");
    expect(init.params.query[rootOf(GENE).kind]).toBe(GENE.root.id);
    fireEvent.click(decide);
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [path, sent] = post.mock.calls[0] as unknown as [
      string,
      {
        params: { path: { study_id: string } };
        body: { kind: string; id: string; rank: number; expected_head: string };
      },
    ];
    const place = GENE.places.find((p) => p.can_decide)!;
    expect(path).toBe("/api/studies/{study_id}/where-to-look/open");
    expect(sent.params.path.study_id).toBe(GENE.study_id);
    expect(sent.body).toEqual({
      kind: GENE.root.kind,
      id: GENE.root.id,
      rank: place.rank,
      expected_head: GENE.head,
    });
    await waitFor(() => expect(success).toHaveBeenCalled());
    const [, options] = success.mock.calls[0] as unknown as [
      string,
      { description: string; action: { label: string } },
    ];
    expect(options.description).toBe(OPENED.message);
    expect(options.action.label).toBe("Go to the card");
    // the view is read again (the place now names its card)
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(1));
  });

  it("reads the trace again and says so when something was decided since", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation((() => ok(GENE)) as never);
    vi.spyOn(api, "POST").mockImplementation((() =>
      Promise.resolve({
        error: STALE.body,
        response: new Response(null, { status: STALE.status }),
      })) as never);
    render(wrap(<WhereToLook workspace={WS} scope={scope} genes={[]} initial={rootOf(GENE)} />));
    fireEvent.click((await screen.findAllByRole("button", { name: /^Decide…/ }))[0]!);
    expect(await screen.findByText(STALE.body.error.message)).toBeTruthy();
    expect(STALE.body.error.code).toBe("stale");
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(1));
  });

  it("traces exactly one thing: a well typed as PLATE:WELL", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation((() => ok(WELL)) as never);
    render(wrap(<WhereToLook workspace={WS} scope={scope} genes={[]} />));
    expect(get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("radio", { name: "A well" }));
    const place = WELL.places[0]!;
    const box = screen.getByRole("textbox", { name: "Well" });
    fireEvent.change(box, { target: { value: `${place.plate}` } });
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(get).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: `${place.plate}:${place.well}` } });
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    await waitFor(() => expect(get).toHaveBeenCalled());
    const [, init] = get.mock.calls[0] as unknown as [
      string,
      { params: { query: Record<string, unknown> } },
    ];
    expect(init.params.query).toMatchObject({
      well: `${place.plate}:${place.well}`,
      gene: undefined,
      sample: undefined,
    });
    await waitFor(() => expect(document.body.textContent).toContain(WELL.text[0]!.plain));
  });
});
