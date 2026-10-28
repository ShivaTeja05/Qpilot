/**
 * Where to look on the API's own answers for the seeded demo study (recorded/record_where.py):
 * a gene with a place whose options change its call, a gene no place changes, a sample, a well,
 * a sample in no comparison, and a refused (stale) Decide…, all at a Studio session's current
 * analysis (Decide… applies the option: wells left out, the study analysed again); a person's
 * applied Decide… and what is set aside after it; and the demo analysed outside Studio, where
 * Decide… opens the place as a Decision Card (and the gene after it). No number, gene, sample or
 * well is typed in: every expectation is read from them.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { count } from "@/lib/format";
import { toast } from "@/ui";
import type { PlaceOpened, SetAsideView, TraceDecided, WhereRoot, WhereView } from "../api";
import { appliedWords } from "../SetAside";
import { WhereResult, WhereToLook, analysisLine } from "../WhereToLook";
import { cannotWords, checkedWords, placeWords } from "../words";
import absentJson from "./recorded/where-absent.json";
import calmJson from "./recorded/where-calm.json";
import geneJson from "./recorded/where-gene.json";
import openedViewJson from "./recorded/where-gene-opened.json";
import requestedJson from "./recorded/where-gene-requested.json";
import outsideJson from "./recorded/where-gene-outside.json";
import openedJson from "./recorded/place-opened.json";
import decidedJson from "./recorded/place-decided.json";
import setAsideJson from "./recorded/set-aside.json";
import staleJson from "./recorded/place-stale.json";
import sampleJson from "./recorded/where-sample.json";
import wellJson from "./recorded/where-well.json";

const GENE = geneJson as unknown as WhereView;
const REQUESTED = requestedJson as unknown as WhereView;
const CALM = calmJson as unknown as WhereView;
const SAMPLE = sampleJson as unknown as WhereView;
const WELL = wellJson as unknown as WhereView;
const ABSENT = absentJson as unknown as WhereView;
const OPENED_VIEW = openedViewJson as unknown as WhereView;
const OPENED = openedJson as PlaceOpened;
const OUTSIDE = outsideJson as unknown as WhereView;
const DECIDED = decidedJson as unknown as TraceDecided;
const SET_ASIDE = setAsideJson as unknown as SetAsideView;
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
    expect(OUTSIDE.can_apply).toBe(false);
    const decidable = OUTSIDE.places.filter((p) => p.can_decide && !p.card_status);
    expect(decidable.length).toBeGreaterThan(0);
    const onDecide = vi.fn();
    result(OUTSIDE, { onDecide });
    const rows = places();
    expect(rows).toHaveLength(OUTSIDE.places.length);
    for (const [i, row] of rows.entries()) {
      const p = OUTSIDE.places[i]!;
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
    expect(screen.getByText(OUTSIDE.decide_note)).toBeTruthy();
    // outside Studio the panel says how to leave the wells out: open the file in Studio
    expect(screen.getByText(OUTSIDE.apply_note)).toBeTruthy();
    expect(OUTSIDE.apply_note).toMatch(/open the study's file in Studio/);
    expect(screen.getByText(new RegExp(`^${OUTSIDE.n_more} more places found`))).toBeTruthy();
  });

  it("in a Studio session, Decide… opens the options and a reason, and applies the choice", () => {
    expect(GENE.can_apply).toBe(true);
    const place = GENE.places.find((p) => p.can_decide)!;
    const onApply = vi.fn();
    const onDecide = vi.fn();
    result(GENE, { onApply, onDecide });
    expect(screen.getByText(GENE.decide_note)).toBeTruthy();
    expect(screen.queryByText(GENE.apply_note, { selector: "p.mt-1" })).toBeNull();
    const row = places()[GENE.places.indexOf(place)]!;
    fireEvent.click(within(row).getByRole("button", { name: /^Decide…/ }));
    const group = within(row).getByRole("radiogroup", { name: "What to do at this place" });
    const radios = within(group).getAllByRole("radio") as HTMLInputElement[];
    expect(radios).toHaveLength(place.options.length);
    for (const [i, o] of place.options.entries()) {
      expect(radios[i]!.disabled).toBe(!o.applies);
      expect(group.textContent).toContain(appliedWords(o));
    }
    // reading a well from the other wells is a what-if: it cannot be chosen
    const whatIf = place.options.find((o) => !o.applies);
    if (whatIf) expect(appliedWords(whatIf)).toMatch(/what-if only/);
    const aside = place.options.find((o) => o.id === "set_aside")!;
    expect(aside.applies && aside.n_wells > 0).toBe(true);
    fireEvent.click(radios[place.options.indexOf(aside)]!);
    const decide = within(row).getByRole("button", { name: `Decide: ${aside.label}` });
    expect((decide as HTMLButtonElement).disabled).toBe(true); // a reason first
    fireEvent.change(within(row).getByRole("textbox"), {
      target: { value: "  The well never rose. " },
    });
    fireEvent.click(decide);
    expect(onApply).toHaveBeenCalledWith(place, "set_aside", "The well never rose.");
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("shows an agent's request at the place; a person approves it or turns it down", () => {
    // recorded/record_request.py: an agent asked (qpcr_request_set_aside) to set a value aside
    const place = REQUESTED.places[0]!;
    const [asked] = place.requests!;
    expect(asked).toBeTruthy();
    expect(place.can_decide).toBe(true);
    const onApply = vi.fn();
    result(REQUESTED, { onApply });
    const row = places()[0]!;
    expect(within(row).getByText("Agent asked")).toBeTruthy();
    const banner = within(row).getByRole("status");
    expect(banner.textContent).toContain("An agent asked to");
    expect(banner.textContent).toContain(asked!.option_label.toLowerCase());
    expect(banner.textContent).toContain(`${asked!.reason}`);
    expect(banner.textContent).toContain("Nothing changes until a person");
    fireEvent.click(within(row).getByRole("button", { name: /^Decide…/ }));
    // the requested option is offered first, and choosing it is an approval
    const radios = within(row).getAllByRole("radio") as HTMLInputElement[];
    expect(radios.find((r) => r.checked)!.value).toBe(asked!.option);
    const approve = within(row).getByRole("button", { name: /^Approve: / });
    expect((approve as HTMLButtonElement).disabled).toBe(true); // a reason first
    const down = within(row).getByRole("button", { name: "Turn down the request" });
    expect((down as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(row).getByRole("textbox"), { target: { value: " Agreed. " } });
    fireEvent.click(approve);
    expect(onApply).toHaveBeenLastCalledWith(place, asked!.option, "Agreed.");
    // turning it down keeps what is there, with the person's reason
    fireEvent.click(down);
    expect(onApply).toHaveBeenLastCalledWith(place, "keep", "Agreed.");
  });

  it("shows nothing about agents where none asked", () => {
    result(GENE);
    expect(screen.queryByText("Agent asked")).toBeNull();
    expect(screen.queryByText(/An agent asked to/)).toBeNull();
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
  const outside = { key: OUTSIDE.study_id, studyId: OUTSIDE.study_id, kind: "study" as const };
  const ok = (data: unknown) =>
    Promise.resolve({ data, response: new Response(null, { status: 200 }) });
  /** GET answers by route: the trace, and what is set aside (nothing unless given). */
  const answers =
    (view: WhereView, aside: SetAsideView = { ...SET_ASIDE, set_aside: [] }) =>
    (route: string) =>
      ok(route.endsWith("/set-aside") ? aside : view);
  const whereCalls = (get: { mock: { calls: unknown[][] } }) =>
    get.mock.calls.filter((c) => String(c[0]).endsWith("/where-to-look"));

  it("outside Studio, opens the place as a Decision Card, sending the head the view was read at", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation((() => ok(OUTSIDE)) as never);
    const post = vi.spyOn(api, "POST").mockImplementation((() => ok(OPENED)) as never);
    const success = vi.spyOn(toast, "success");
    const GENE = OUTSIDE;
    render(
      wrap(
        <WhereToLook
          workspace={{ key: outside.key, kind: "study" }}
          scope={outside}
          genes={[]}
          initial={rootOf(GENE)}
        />,
      ),
    );
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

  it("applies a person's choice in a Studio session, sending both heads", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation(answers(GENE) as never);
    const post = vi.spyOn(api, "POST").mockImplementation((() => ok(DECIDED)) as never);
    const success = vi.spyOn(toast, "success");
    render(wrap(<WhereToLook workspace={WS} scope={scope} genes={[]} initial={rootOf(GENE)} />));
    fireEvent.click((await screen.findAllByRole("button", { name: /^Decide…/ }))[0]!);
    const place = GENE.places.find((p) => p.can_decide)!;
    const aside = place.options.find((o) => o.id === "set_aside")!;
    const group = screen.getByRole("radiogroup", { name: "What to do at this place" });
    fireEvent.click(within(group).getAllByRole("radio")[place.options.indexOf(aside)]!);
    fireEvent.change(screen.getByRole("textbox", { name: /^Why this option/ }), {
      target: { value: "The well never rose." },
    });
    fireEvent.click(screen.getByRole("button", { name: `Decide: ${aside.label}` }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [path, sent] = post.mock.calls[0] as unknown as [
      string,
      { body: Record<string, unknown> },
    ];
    expect(path).toBe("/api/studies/{study_id}/where-to-look/decide");
    expect(sent.body).toEqual({
      kind: GENE.root.kind,
      id: GENE.root.id,
      rank: place.rank,
      option: "set_aside",
      reason: "The well never rose.",
      expected_head: GENE.head,
      expected_inbox: GENE.inbox_head,
    });
    await waitFor(() => expect(success).toHaveBeenCalled());
    const [, options] = success.mock.calls[0] as unknown as [string, { description: string }];
    expect(options.description).toBe(DECIDED.message);
    expect(DECIDED.status).toBe("left_out");
    expect(DECIDED.left_out.length).toBe(aside.n_wells);
    expect(DECIDED.job?.kind).toBe("analyse");
    await waitFor(() => expect(whereCalls(get).length).toBeGreaterThan(1));
  });

  it("reads the trace again and says so when something was decided since", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation(answers(GENE) as never);
    vi.spyOn(api, "POST").mockImplementation((() =>
      Promise.resolve({
        error: STALE.body,
        response: new Response(null, { status: STALE.status }),
      })) as never);
    render(wrap(<WhereToLook workspace={WS} scope={scope} genes={[]} initial={rootOf(GENE)} />));
    fireEvent.click((await screen.findAllByRole("button", { name: /^Decide…/ }))[0]!);
    fireEvent.change(screen.getByRole("textbox", { name: /^Why this option/ }), {
      target: { value: "Looked at the curve." },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Decide: / }));
    expect(await screen.findByText(STALE.body.error.message)).toBeTruthy();
    expect(STALE.body.error.code).toBe("stale");
    await waitFor(() => expect(whereCalls(get).length).toBeGreaterThan(1));
  });

  it("lists what a person set aside, and puts the wells back with a reason", async () => {
    expect(SET_ASIDE.set_aside.length).toBeGreaterThan(0);
    const entry = SET_ASIDE.set_aside[0]!;
    vi.spyOn(api, "GET").mockImplementation(answers(GENE, SET_ASIDE) as never);
    const post = vi
      .spyOn(api, "POST")
      .mockImplementation((() =>
        ok({ ...DECIDED, status: "put_back", left_out: [], put_back: entry.wells })) as never);
    const scoped = { ...scope, studyId: SET_ASIDE.study_id };
    render(wrap(<WhereToLook workspace={WS} scope={scoped} genes={[]} />));
    const list = await screen.findByRole("region", { name: "Set aside from Trace" });
    expect(list.textContent).toContain(`Sample ${entry.sample}`);
    expect(list.textContent).toContain(entry.reason);
    expect(list.textContent).toContain(entry.option_label);
    fireEvent.click(within(list).getByRole("button", { name: /^Put the wells back/ }));
    const put = within(list).getByRole("button", { name: "Put the wells back" });
    expect((put as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(list).getByRole("textbox"), {
      target: { value: "The repeat agrees." },
    });
    fireEvent.click(put);
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [path, sent] = post.mock.calls[0] as unknown as [
      string,
      { body: Record<string, unknown> },
    ];
    expect(path).toBe("/api/studies/{study_id}/where-to-look/put-back");
    expect(sent.body).toEqual({
      card_id: entry.card_id,
      reason: "The repeat agrees.",
      expected_inbox: SET_ASIDE.inbox_head,
    });
  });

  it("traces exactly one thing: a well typed as PLATE:WELL", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation(answers(WELL) as never);
    render(wrap(<WhereToLook workspace={WS} scope={scope} genes={[]} />));
    expect(whereCalls(get)).toHaveLength(0);
    fireEvent.click(screen.getByRole("radio", { name: "A well" }));
    const place = WELL.places[0]!;
    const box = screen.getByRole("textbox", { name: "Well" });
    fireEvent.change(box, { target: { value: `${place.plate}` } });
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(whereCalls(get)).toHaveLength(0);
    fireEvent.change(box, { target: { value: `${place.plate}:${place.well}` } });
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    await waitFor(() => expect(whereCalls(get).length).toBeGreaterThan(0));
    const [, init] = whereCalls(get)[0] as unknown as [
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
