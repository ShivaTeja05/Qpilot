/**
 * The Run Review and the Excel export on recorded API answers of the seeded demo session
 * (`recorded/`, written by `recorded/record.py` from a running `qpilot app`): the server's JSON is
 * served to the page's own requests by a fetch stub that keeps every request, so a test can check
 * what the page sent. Nothing here is typed-in data: genes, names, comments, heads and messages
 * are read from the recordings.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import type { Schemas } from "@/api/client";
import { count } from "@/lib/format";
import { SECTION, sectionPath, type SectionId } from "@/shell/sections";
import { TooltipProvider, toast } from "@/ui";
import type { RepeatView, RunReviewView, SignOffDone } from "./api";
import { ExportPanel, FORMATS } from "./ExportPanel";
import afterJson from "./recorded/review-after.json";
import signedJson from "./recorded/review-signed.json";
import staleJson from "./recorded/review-stale.json";
import repeatJson from "./recorded/repeat.json";
import reviewJson from "./recorded/review.json";
import sessionJson from "./recorded/session.json";
import { itemWords, plateWords, RepeatOffer, summaryWords } from "./RepeatPlan";
import { RunReview, RunReviewBody } from "./RunReview";
import { EVIDENCE } from "./words";

// The typed client keeps the `fetch` and `Request` it finds when its module loads, so the stub
// goes in before any import runs.
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
    const request = input instanceof Request ? input : new Request(input, init);
    const path = new URL(request.url).pathname;
    const text = request.method === "GET" ? "" : await request.text();
    const body: unknown = text ? JSON.parse(text) : null;
    state.sent.push({ method: request.method, path, body });
    const [status, answer] = state.answer(request.method, path, body);
    return new Response(
      JSON.stringify(answer ?? { error: { code: "not_found", message: "No such API route." } }),
      { status: answer === null ? 404 : status, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  return state;
});

const before = reviewJson as unknown as RunReviewView;
const after = afterJson as unknown as RunReviewView;
const signed = signedJson as unknown as SignOffDone;
const stale = staleJson as unknown as {
  status: number;
  body: { error: { code: string; message: string } };
};
const session = sessionJson as unknown as Schemas["WorkspaceView"];
const study = session.study_id!;
const route = `/api/studies/${study}/review`;
const mine = signed.sign_off;
const repeat = repeatJson as unknown as RepeatView;
const repeatRoute = `${route}/repeat`;

/** The recorded server: the review before the sign-off, the sign-off, the review after it. */
function recorded(): (method: string, path: string) => [number, unknown] {
  let done = false;
  return (method, path) => {
    if (path === route && method === "GET") return [200, done ? after : before];
    if (path === repeatRoute && method === "GET") return [200, repeat];
    if (path === `${route}/sign-off` && method === "POST") {
      done = true;
      return [200, signed];
    }
    return [404, null];
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  net.sent = [];
  net.answer = recorded();
});
net.answer = recorded();

function show(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { hook } = memoryLocation({ path: "/" });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <Router hook={hook}>{ui}</Router>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const showReview = () =>
  show(<RunReview workspace={session} workspaceKey={session.key} studyId={study} />);

const label = (id: string) => before.outcomes.find((o) => o.id === id)!.label;
const signButton = () => screen.getByRole("button", { name: "Sign off" }) as HTMLButtonElement;
const comment = () => screen.getByRole("textbox", { name: "Comment" }) as HTMLTextAreaElement;
const name = () => screen.getByRole("textbox", { name: "Your name" }) as HTMLInputElement;

/** Fill the form with the recorded sign-off's outcome, comment and name. */
function fill() {
  fireEvent.click(screen.getByRole("radio", { name: label(mine.outcome) }));
  fireEvent.change(comment(), { target: { value: mine.comment } });
  fireEvent.change(name(), { target: { value: mine.reviewer } });
}

describe("Run Review", () => {
  it("shows the headline genes, the ledger (cannot-tell first) and what is not built yet", async () => {
    const { container } = showReview();
    expect(await screen.findByText(before.purpose)).toBeTruthy();
    expect(container.textContent).toContain(before.title.plain);
    const genes = screen.getByRole("list", { name: "Headline genes" });
    for (const h of before.headline) expect(genes.textContent).toContain(h.line.plain);

    const items = before.evidence.items ?? [];
    const rows = [...container.querySelectorAll<HTMLElement>("[data-evidence]")];
    expect(rows).toHaveLength(items.length);
    const cannot = items.filter((i) => i.cannot_tell);
    expect(cannot.length).toBeGreaterThan(0);
    expect(rows.slice(0, cannot.length).map((r) => r.dataset.evidence)).toEqual(
      cannot.map((i) => i.id),
    );
    for (const row of rows) {
      const item = items.find((i) => i.id === row.dataset.evidence)!;
      // status as glyph + the server's word; the line without the title and status it repeats
      expect(row.textContent).toContain(item.title);
      expect(row.textContent).toContain(`${EVIDENCE[item.status].glyph} ${item.status_word}`);
      expect(row.textContent).toContain(
        item.line.plain.slice(`${item.title}: ${item.status_word}. `.length),
      );
    }

    for (const n of before.not_built) {
      expect(screen.getByText(n.title)).toBeTruthy();
      expect(screen.getByText(n.reason)).toBeTruthy();
      if (n.section && n.section in SECTION) {
        const section = SECTION[n.section as SectionId];
        const link = screen.getByRole("link", { name: `Open ${section.label}` });
        expect(link.getAttribute("href")).toContain(sectionPath(session, section.id));
      }
    }
    if (!before.sign_offs.length)
      expect(screen.getByText("No one has signed off this run yet.")).toBeTruthy();
  });

  it("enables Sign off only with an outcome, a comment and a name", async () => {
    showReview();
    await screen.findByText(before.purpose);
    expect(signButton().disabled).toBe(true);
    for (const o of before.outcomes) {
      const radio = screen.getByRole("radio", { name: o.label });
      const meaning = document.getElementById(radio.getAttribute("aria-describedby")!);
      expect(meaning?.textContent).toBe(o.meaning);
    }
    fireEvent.click(screen.getByRole("radio", { name: label(mine.outcome) }));
    expect(signButton().disabled).toBe(true);
    fireEvent.change(comment(), { target: { value: "   " } });
    expect(signButton().disabled).toBe(true);
    fireEvent.change(comment(), { target: { value: mine.comment } });
    expect(signButton().disabled).toBe(true);
    fireEvent.change(name(), { target: { value: mine.reviewer } });
    expect(signButton().disabled).toBe(false);
    expect(comment().maxLength).toBe(before.max_comment);
    expect(name().maxLength).toBe(before.max_reviewer);
    expect(
      screen.getByText(`${count(mine.comment.length)} / ${count(before.max_comment)}`),
    ).toBeTruthy();
  });

  it("sends the head it was read at, says what the server said and clears the comment", async () => {
    const said = vi.spyOn(toast, "success");
    const { container } = showReview();
    await screen.findByText(before.purpose);
    fill();
    fireEvent.click(signButton());
    await waitFor(() => expect(said).toHaveBeenCalled());
    const post = net.sent.find((s) => s.method === "POST");
    expect(post?.path).toBe(`${route}/sign-off`);
    expect(post?.body).toEqual({
      outcome: mine.outcome,
      comment: mine.comment,
      reviewer: mine.reviewer,
      expected_head: before.head,
    });
    expect(said.mock.calls[0]![0]).toBe(signed.message);
    await waitFor(() => expect(comment().value).toBe(""));
    const list = screen.getByRole("list", { name: "Recorded sign-offs, newest first" });
    expect(within(list).getByText(`“${mine.comment}”`)).toBeTruthy();
    expect(within(list).getByText(mine.reviewer)).toBeTruthy();
    expect(container.querySelector("b")).toBeNull();
  });

  it("re-reads the review on a stale answer and says something was decided since", async () => {
    net.answer = (method, path) => {
      if (path === route && method === "GET") return [200, before];
      if (path === repeatRoute && method === "GET") return [200, repeat];
      if (path === `${route}/sign-off`) return [stale.status, stale.body];
      return [404, null];
    };
    const told = vi.spyOn(toast, "info");
    showReview();
    await screen.findByText(before.purpose);
    fill();
    fireEvent.click(signButton());
    const status = await screen.findByText(stale.body.error.message);
    expect(status.closest("[role=status]")).toBeTruthy();
    await waitFor(() =>
      expect(net.sent.filter((s) => s.method === "GET" && s.path === route).length).toBe(2),
    );
    expect(told).toHaveBeenCalled();
    // the person's words stay, to sign off again once they have read it
    expect(comment().value).toBe(mine.comment);
    expect(name().value).toBe(mine.reviewer);
  });

  it("says what to repeat and why, most consequential first, with the plate to download", async () => {
    const plan = repeat.plan;
    expect(plan.items.length).toBeGreaterThan(0);
    const { container } = showReview();
    const list = await screen.findByRole("list", {
      name: "What to repeat, most consequential first",
    });
    expect(container.textContent).toContain(summaryWords(plan));
    expect(container.textContent).toContain(plateWords(plan));
    expect(container.textContent).toContain(repeat.note);
    const rows = within(list)
      .getAllByRole("listitem")
      .filter((li) => li.dataset.rank);
    expect(rows).toHaveLength(Math.min(plan.items.length, 8));
    for (const [i, row] of rows.entries()) {
      const item = plan.items[i]!;
      expect(row.textContent).toContain(itemWords(item));
      for (const r of item.reasons) expect(row.textContent).toContain(r.words);
      for (const g of item.changed_calls) expect(row.textContent).toContain(g);
    }
    const download = screen.getAllByRole("link", { name: "Download the repeat plate (CSV)" })[0]!;
    expect(download.getAttribute("href")).toBe(repeat.csv_url);
    expect(download.getAttribute("download")).toBe(repeat.csv_name);
    // nothing on the page says the repeat plan or the Run Gate lines are not built
    expect(container.textContent).not.toMatch(/not built|repeat plan is not/i);
    for (const n of before.not_built) expect(n.id).not.toBe("repeat");
    // putting every item on the plate asks again with include=all
    fireEvent.click(screen.getByRole("checkbox", { name: /Put every item on the plate/ }));
    await waitFor(() =>
      expect(net.sent.some((s) => s.path === repeatRoute && s.method === "GET")).toBe(true),
    );
  });

  it("shows the Run Gate lines per plate and links to Controls", async () => {
    const flagged = repeat.plan.gate_lines.filter((l) => l.worst === "fail" || l.worst === "warn");
    expect(flagged.length).toBeGreaterThan(0);
    showReview();
    const plates = await screen.findByRole("list", {
      name: "Plates with a rule that warns or fails",
    });
    expect(
      within(plates)
        .getAllByRole("listitem")
        .filter((li) => li.textContent?.startsWith("Plate")),
    ).toHaveLength(flagged.length);
    for (const line of flagged) {
      expect(plates.textContent).toContain(`Plate ${line.plate}`);
      for (const f of line.findings) expect(plates.textContent).toContain(f.words);
    }
    const link = screen.getByRole("link", { name: /^Open Controls/ });
    expect(link.getAttribute("href")).toBe(sectionPath(session, "gate"));
  });

  it("offers the repeat plate from Controls, and the way to the Run Review", async () => {
    show(<RepeatOffer workspace={session} studyId={study} />);
    expect(await screen.findByText(summaryWords(repeat.plan))).toBeTruthy();
    const link = screen.getByRole("link", { name: /See what to repeat and why/ });
    expect(link.getAttribute("href")).toBe(sectionPath(session, "report", "run-review"));
    expect(
      screen.getByRole("link", { name: "Download the repeat plate (CSV)" }).getAttribute("href"),
    ).toBe(repeat.csv_url);
  });

  it("shows a recorded comment and name as text, never as markup", () => {
    expect(mine.comment).toMatch(/<\w+>/); // the recording holds markup on purpose
    const { container } = show(
      <RunReviewBody view={after} workspace={session} workspaceKey={session.key} />,
    );
    const list = screen.getByRole("list", { name: "Recorded sign-offs, newest first" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(Math.min(after.sign_offs.length, 3));
    const newest = [...after.sign_offs].sort((a, b) => b.seq - a.seq)[0]!;
    expect(items[0]!.textContent).toContain(newest.comment);
    expect(items[0]!.textContent).toContain(label(newest.outcome));
    expect(container.querySelector("b, i, script, img")).toBeNull();
  });
});

describe("ExportPanel", () => {
  it("offers the Excel workbook and asks for it with the page's head", async () => {
    const xlsx = FORMATS.find((f) => f.format === "xlsx")!;
    show(
      <ExportPanel
        workspaceKey={session.key}
        studyId={study}
        head={before.head}
        jobs={{}}
        onJob={() => undefined}
        exports={[]}
      />,
    );
    expect(screen.getByText(xlsx.title)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: xlsx.action }));
    await waitFor(() => expect(net.sent.some((s) => s.method === "POST")).toBe(true));
    const post = net.sent.find((s) => s.method === "POST")!;
    expect(post.path).toBe(`/api/studies/${study}/report/export`);
    expect(post.body).toEqual({ format: "xlsx", expected_head: before.head });
  });
});
