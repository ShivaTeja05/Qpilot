/**
 * The Instruments section on the recorded API answers of a running `qpilot app` (`recorded/`,
 * written by `recorded/record.py`): two registered instruments, an agent's proposed incident, a
 * confirmed open one and a fixed one, a synthetic `.eds` with an expired calibration and a pause,
 * a public CFX export, and a lookback over the demo study. A fetch stub serves the server's JSON to
 * the page's own requests and keeps every request, so a test can check what the page sent.
 * Nothing here is typed-in data: names, ids, numbers and serials are read from the recordings.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { plural } from "@/lib/format";
import { TooltipProvider } from "@/ui";
import type {
  InstrumentsView,
  InstrumentView,
  Linked,
  Logged,
  LookbackView,
  RunFileView,
} from "./api";
import InstrumentsSection from "./index";
import { LookbackResult } from "./Lookback";
import brokenOneJson from "./recorded/broken-one.json";
import brokenJson from "./recorded/broken.json";
import confirmedJson from "./recorded/confirmed.json";
import fixedJson from "./recorded/fixed.json";
import instrumentJson from "./recorded/instrument.json";
import instrumentsJson from "./recorded/instruments.json";
import linkedJson from "./recorded/linked.json";
import lookbackJobJson from "./recorded/lookback-job.json";
import lookbackStartedJson from "./recorded/lookback-started.json";
import neverJson from "./recorded/never.json";
import runCfxJson from "./recorded/run-cfx.json";
import runKnownJson from "./recorded/run-known.json";
import runUnknownJson from "./recorded/run-unknown.json";
import workspacesJson from "./recorded/workspaces.json";
import { GATE_WORD, asGateStatus, lookbackHeadline, sentence, serialsSentence } from "./words";

// The typed client keeps the `fetch` and `Request` it finds when its module loads, so the stub
// goes in before any import runs. Multipart bodies (a run file) are kept as their field names.
const net = vi.hoisted(() => {
  const state = {
    answer: (_method: string, _path: string, _body: unknown): [number, unknown] => [404, null],
    sent: [] as { method: string; path: string; body: unknown }[],
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
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    let method: string;
    let path: string;
    let body: unknown = null;
    if (input instanceof Request) {
      method = input.method;
      path = new URL(input.url).pathname;
      const text = method === "GET" ? "" : await input.text();
      body = text ? JSON.parse(text) : null;
    } else {
      method = init?.method ?? "GET";
      path = new URL(String(input), location.origin).pathname;
      if (init?.body instanceof FormData) {
        const fields: Record<string, string> = {};
        init.body.forEach((v, k) => {
          fields[k] = typeof v === "string" ? v : (v as File).name;
        });
        body = fields;
      } else if (typeof init?.body === "string") body = JSON.parse(init.body);
    }
    state.sent.push({ method, path, body });
    const [status, answer] = state.answer(method, path, body);
    return new Response(
      JSON.stringify(answer ?? { error: { code: "not_found", message: "No such API route." } }),
      { status: answer === null ? 404 : status, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  return state;
});

const instruments = instrumentsJson as unknown as InstrumentsView;
const broken = brokenJson as unknown as InstrumentsView;
const instrument = instrumentJson as unknown as InstrumentView;
const confirmed = confirmedJson as unknown as Logged;
const fixed = fixedJson as unknown as Logged;
const linked = linkedJson as unknown as Linked;
const runUnknown = runUnknownJson as unknown as RunFileView;
const runKnown = runKnownJson as unknown as RunFileView;
const runCfx = runCfxJson as unknown as RunFileView;
const lookbackJob = lookbackJobJson as unknown as { id: string; result: LookbackView };
const lookback = lookbackJob.result;
const never = (neverJson as { serials: string[] }).serials;
const id = instrument.instrument.instrument_id;
const proposed = instrument.incidents.find((i) => i.can_confirm)!;
const open = instrument.incidents.find((i) => i.can_fix)!;

function recorded(method: string, path: string): [number, unknown] {
  if (method === "GET" && path === "/api/instruments") return [200, instruments];
  if (method === "GET" && path === `/api/instruments/${id}`) return [200, instrument];
  if (method === "GET" && path === "/api/workspaces") return [200, workspacesJson];
  if (method === "POST" && path.endsWith("/confirm")) return [200, confirmed];
  if (method === "POST" && path.endsWith("/reject")) return [200, confirmed];
  if (method === "POST" && path.endsWith("/fix")) return [200, fixed];
  if (method === "POST" && path.endsWith("/link")) return [200, linked];
  if (method === "POST" && path.endsWith("/lookback")) return [202, lookbackStartedJson];
  if (method === "GET" && path === `/api/jobs/${lookbackJob.id}`) return [200, lookbackJob];
  return [404, null];
}

afterEach(() => {
  cleanup();
  net.sent = [];
  net.answer = recorded;
});
net.answer = recorded;

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>,
  );
}

/** Elements whose whole text is `text` (a FactText draws its facts in their own spans). */
const whole = (text: string) => screen.getAllByText((_, el) => el?.textContent === text);

const posts = (suffix: string) =>
  net.sent.filter((s) => s.method === "POST" && s.path.endsWith(suffix));

describe("the instrument list", () => {
  it("shows each instrument, its calibrations' age, open incidents and the chain's check", async () => {
    wrap(<InstrumentsSection workspace={null} rest={[]} />);
    for (const i of instruments.instruments) {
      expect(await screen.findByRole("link", { name: i.display_name })).toBeTruthy();
      for (const c of i.calibrations)
        expect(screen.getAllByText(plural(c.age_days, "day")).length).toBeGreaterThan(0);
    }
    const waiting = instruments.instruments.find((i) => i.n_proposed > 0)!;
    expect(
      screen.getByText(`${waiting.n_proposed} proposed by an agent, waiting for you`),
    ).toBeTruthy();
    expect(screen.getAllByText("Logbook chain verifies")).toHaveLength(
      instruments.instruments.length,
    );
    expect(screen.getByText(instruments.note)).toBeTruthy();
  });

  it("lists a chain's problems in words when it does not verify", async () => {
    net.answer = (m, p) =>
      m === "GET" && p === "/api/instruments" ? [200, broken] : recorded(m, p);
    wrap(<InstrumentsSection workspace={null} rest={[]} />);
    const bad = broken.instruments.find((i) => !i.chain_ok)!;
    expect(await screen.findByText("Logbook chain does not verify")).toBeTruthy();
    for (const p of bad.problems) expect(screen.getByText(sentence(p))).toBeTruthy();
  });

  it("opens a broken logbook as the server's refusal, with the chain's problems", async () => {
    const bad = broken.instruments.find((i) => !i.chain_ok)!;
    const refusal = brokenOneJson as { status: number; body: { error: { message: string } } };
    net.answer = (m, p) =>
      m === "GET" && p === "/api/instruments"
        ? [200, broken]
        : m === "GET" && p === `/api/instruments/${bad.instrument_id}`
          ? [refusal.status, refusal.body]
          : recorded(m, p);
    wrap(<InstrumentsSection workspace={null} rest={[bad.instrument_id]} />);
    expect(await screen.findByText(refusal.body.error.message)).toBeTruthy();
    for (const p of bad.problems) expect(screen.getByText(sentence(p))).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Log an event" })).toBeNull();
  });

  it("says what the section is for when nothing is registered", async () => {
    net.answer = (m, p) =>
      m === "GET" && p === "/api/instruments"
        ? [200, { ...instruments, instruments: [] }]
        : recorded(m, p);
    wrap(<InstrumentsSection workspace={null} rest={[]} />);
    expect(await screen.findByText("No instrument registered yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Register an instrument" })).toBeTruthy();
  });
});

describe("one instrument", () => {
  it("offers Confirm and Turn down for an agent's proposal, and each posts to its own path", async () => {
    wrap(<InstrumentsSection workspace={null} rest={[id]} />);
    const card = (await screen.findByRole("heading", { name: /Waiting for you/ })).closest(
      "section",
    )!;
    expect(within(card).getByText(/seen before/)).toBeTruthy();
    expect(within(card).getByText(/matches nothing/)).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: /^Confirm/ }));
    await waitFor(() => expect(posts("/confirm")).toHaveLength(1));
    expect(posts("/confirm")[0]!.path).toBe(
      `/api/instruments/${id}/incidents/${proposed.seq}/confirm`,
    );
    cleanup();

    wrap(<InstrumentsSection workspace={null} rest={[id]} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Turn down/ }));
    await waitFor(() => expect(posts("/reject")).toHaveLength(1));
    expect(posts("/reject")[0]!.path).toBe(
      `/api/instruments/${id}/incidents/${proposed.seq}/reject`,
    );
  });

  it("needs a note before it records what fixed an incident", async () => {
    wrap(<InstrumentsSection workspace={null} rest={[id]} />);
    const form = await screen.findByRole("form", {
      name: `What fixed the incident at entry ${open.seq}`,
    });
    fireEvent.click(within(form).getByRole("button", { name: "Note what fixed it" }));
    expect(await within(form).findByText("Say what fixed it.")).toBeTruthy();
    expect(posts("/fix")).toHaveLength(0);

    const note = fixed.instrument.incidents.flatMap((i) => i.fixes).at(-1)!.note;
    fireEvent.change(within(form).getByLabelText("What fixed it"), { target: { value: note } });
    fireEvent.click(within(form).getByRole("button", { name: "Note what fixed it" }));
    await waitFor(() => expect(posts("/fix")).toHaveLength(1));
    expect(posts("/fix")[0]).toMatchObject({
      path: `/api/instruments/${id}/incidents/${open.seq}/fix`,
      body: { note },
    });
  });

  it("shows notes as text: markup someone typed stays literal", async () => {
    wrap(<InstrumentsSection workspace={null} rest={[id]} />);
    await screen.findByRole("heading", { name: "Logbook" });
    const typed = [
      ...instrument.events.map((e) => e.note),
      ...instrument.incidents.map((i) => i.note),
    ].filter((n) => /<[a-z]/i.test(n));
    expect(typed.length).toBeGreaterThan(0);
    for (const note of typed) {
      const shown = screen.getAllByText(note);
      for (const el of shown) {
        expect(el.textContent).toBe(note);
        expect(el.children).toHaveLength(0);
      }
    }
    expect(document.querySelector("main b, section b, section i, section a[href='#']")).toBeNull();
  });

  it("shows the logbook in chain order with who wrote each entry", async () => {
    wrap(<InstrumentsSection workspace={null} rest={[id]} />);
    const table = await screen.findByRole("table", { name: /Logbook of/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(instrument.events.length);
    instrument.events.forEach((e, i) => {
      expect(within(rows[i]!).getByText(e.kind_word)).toBeTruthy();
    });
    expect(within(table).getAllByText("An agent").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("A person").length).toBeGreaterThan(0);
  });
});

describe("reading a run file", () => {
  function upload(answer: RunFileView) {
    net.answer = (m, p) =>
      m === "POST" && p === "/api/instruments/runs" ? [200, answer] : recorded(m, p);
    wrap(<InstrumentsSection workspace={null} rest={[]} />);
    return screen.findByLabelText("Run file").then((input) => {
      fireEvent.change(input, { target: { files: [new File(["run"], answer.name)] } });
    });
  }

  it("names no serial, says what the file says, and asks which instrument it is", async () => {
    await upload(runUnknown);
    const question = await screen.findByText(runUnknown.question!.question);
    expect(posts("/api/instruments/runs")[0]!.body).toEqual({ run: runUnknown.name });
    for (const line of runUnknown.gate) {
      expect(whole(line.text.plain).length).toBeGreaterThan(0);
      expect(screen.getAllByText(GATE_WORD[asGateStatus(line.status)]).length).toBeGreaterThan(0);
    }
    const serials = runUnknown.context.serials_present as string[];
    expect(serials.length).toBeGreaterThan(0);
    expect(screen.getByText(serialsSentence(serials))).toBeTruthy();
    for (const serial of never) expect(document.body.textContent).not.toContain(serial);

    const box = question.closest("fieldset")!;
    const choice = runUnknown.question!.choices.find(
      (c) => c.instrument_id === linked.instrument_id,
    )!;
    fireEvent.click(within(box).getByLabelText(choice.display_name!));
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    await waitFor(() => expect(posts("/link")).toHaveLength(1));
    expect(posts("/link")[0]).toMatchObject({
      path: `/api/instruments/runs/${runUnknown.run_id}/link`,
      body: { instrument_id: linked.instrument_id },
    });
    expect(await screen.findByText(linked.message)).toBeTruthy();
  });

  it("names the instrument once the file is linked, and asks nothing", async () => {
    await upload(runKnown);
    const name = instruments.instruments.find((i) => i.instrument_id === runKnown.instrument_id)!;
    expect(await screen.findByText(/recognised from the file itself/)).toBeTruthy();
    expect(screen.getAllByRole("link", { name: name.display_name }).length).toBeGreaterThan(0);
    expect(screen.queryByText(runUnknown.question!.question)).toBeNull();
    for (const serial of never) expect(document.body.textContent).not.toContain(serial);
  });

  it("never shows a CFX export's serials either", async () => {
    await upload(runCfx);
    await screen.findByText(runCfx.question!.question);
    for (const line of runCfx.gate) expect(whole(line.text.plain).length).toBeGreaterThan(0);
    for (const serial of never) expect(document.body.textContent).not.toContain(serial);
  });
});

describe("the lookback", () => {
  it("shows the caveat when every run was assumed to be on the instrument", () => {
    expect(lookback.assumed_all_runs).toBe(true);
    wrap(<LookbackResult view={lookback} />);
    expect(screen.getByText(lookbackHeadline(lookback))).toBeTruthy();
    expect(screen.getByRole("note").textContent).toMatch(/every run was counted as run on/);
    for (const c of lookback.changed) expect(screen.getByText(c.gene)).toBeTruthy();
    for (const r of lookback.runs_in_window) expect(screen.getByText(r)).toBeTruthy();
    cleanup();
    wrap(<LookbackResult view={{ ...lookback, assumed_all_runs: false }} />);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("runs as a job from an instrument's page and shows what changes", async () => {
    wrap(<InstrumentsSection workspace={null} rest={[id]} />);
    const card = (await screen.findByRole("heading", { name: "Lookback" })).closest("section")!;
    await within(card).findAllByText(
      (workspacesJson as { workspaces: { title: string }[] }).workspaces[0]!.title,
    );
    fireEvent.change(within(card).getByLabelText("First day"), {
      target: { value: lookback.start },
    });
    fireEvent.change(within(card).getByLabelText("Last day"), { target: { value: lookback.end } });
    fireEvent.click(within(card).getByRole("button", { name: "Look back" }));
    await waitFor(() => expect(posts("/lookback")).toHaveLength(1));
    expect(posts("/lookback")[0]).toMatchObject({
      path: `/api/studies/${lookback.study_id}/lookback`,
      body: { instrument_id: id, start: lookback.start, end: lookback.end },
    });
    expect(await within(card).findByText(lookbackHeadline(lookback))).toBeTruthy();
    expect(within(card).getByRole("note")).toBeTruthy();
  });
});
