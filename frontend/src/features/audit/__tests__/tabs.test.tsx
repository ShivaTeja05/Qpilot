/**
 * The audit's tabs on the recorded real audit of the demo study (src/test/recorded, made by
 * record.py from a Studio walk and its audit). The API is answered from those recordings.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import how from "@/test/recorded/audit-how.json";
import overview from "@/test/recorded/audit-overview.json";
import study from "@/test/recorded/audit-study.json";
import whatif from "@/test/recorded/audit-whatif.json";
import results from "@/test/recorded/results.json";
import { TooltipProvider } from "@/ui";
import { sectionPath } from "@/shell/sections";
import { studyAudit } from "../api";
import { HowTab } from "../HowTab";
import { StudyTab } from "../StudyTab";
import type { AuditHow, AuditOverview, AuditWhatif } from "../types";
import { WhatifTab } from "../WhatifTab";

const ov = overview as AuditOverview;
const studyId = results.study_id;
const key = results.input_sha256.slice(0, 12);
// The frame of the Studio session the recordings come from (ids only; no numbers).
const workspace = { key, kind: "session", study_id: studyId } as Schemas["WorkspaceView"];
const target = studyAudit(key, studyId);
const geneHref = (gene: string) => sectionPath(workspace, "gene", gene);

let calls: { method: string; url: string; body: unknown }[] = [];

// The charts render real data; the shared machine can be slow.
vi.setConfig({ testTimeout: 20_000 });

function respond(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    const base = `/api/studies/${studyId}/audit`;
    if (url === `${base}/study`) return Promise.resolve(respond(200, study));
    if (url === `${base}/how`) return Promise.resolve(respond(200, how));
    if (url === `${base}/whatif`) return Promise.resolve(respond(200, whatif));
    return Promise.resolve(
      respond(404, { error: { code: "not_found", message: "Not recorded.", details: {} } }),
    );
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("Study tab", () => {
  it("shows every verdict, every gene, and filters the list by verdict", async () => {
    wrap(<StudyTab target={target} overview={ov} geneHref={geneHref} onOpenLab={() => {}} />);
    const list = screen.getByRole("list", { name: "Genes" });
    expect(within(list).getAllByRole("link")).toHaveLength(ov.genes.length);

    const fragile = ov.verdicts.find((v) => v.key === "fragile")!;
    const strip = document.getElementById("audit-verdicts")!.closest("section")!;
    fireEvent.click(
      within(strip).getByRole("button", { name: new RegExp(`^${fragile.count}\\s*Fragile`) }),
    );
    expect(within(screen.getByRole("list", { name: "Genes" })).getAllByRole("link")).toHaveLength(
      fragile.count,
    );
    // the map and the bars arrive with the study view
    expect(await screen.findByText("Calls changed by one choice alone")).toBeTruthy();
    await waitFor(() =>
      expect(document.querySelector('svg[role="img"][aria-label^="Map of "]')).not.toBeNull(),
    );
  });

  it("falls back to the overview's issues when the full queue is not served", async () => {
    wrap(<StudyTab target={target} overview={ov} geneHref={geneHref} onOpenLab={() => {}} />);
    const queue = await screen.findByRole("region", { name: "What to check first" });
    expect(within(queue).getByText(ov.issues[0]!.title)).toBeTruthy();
    expect(within(queue).getByText(new RegExp(`the first of ${ov.n_issues}`))).toBeTruthy();
    expect(within(queue).queryByRole("alert")).toBeNull();
  });

  it("lists genes without links when the audit is not about this study", () => {
    wrap(<StudyTab target={target} overview={ov} geneHref={null} onOpenLab={() => {}} />);
    const list = screen.getByRole("list", { name: "Genes" });
    expect(within(list).queryAllByRole("link")).toHaveLength(0);
    expect(within(list).getAllByRole("listitem")).toHaveLength(ov.genes.length);
  });

  it("opens a gene from the list", () => {
    wrap(<StudyTab target={target} overview={ov} geneHref={geneHref} onOpenLab={() => {}} />);
    const first = ov.genes[0]!.gene;
    const link = within(screen.getByRole("list", { name: "Genes" })).getAllByRole("link")[0]!;
    expect(link.getAttribute("href")).toContain(`/s/${key}/gene/${first}`);
  });
});

describe("What-if lab", () => {
  it("re-runs the engine with the URL's choices and says what changes", async () => {
    const w = whatif as AuditWhatif;
    const onChanges = vi.fn();
    wrap(
      <WhatifTab
        geneHref={geneHref}
        target={target}
        overview={ov}
        manifest={{}}
        changes={{ late_cq: "cq35" }}
        onChanges={onChanges}
      />,
    );
    expect(await screen.findByText(`of ${w.n_genes} calls change`)).toBeTruthy();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ changes: { late_cq: "cq35" }, genes: [] });
    const changed = screen.getByRole("list", { name: "Genes whose call changes" });
    expect(within(changed).getAllByRole("button")).toHaveLength(w.n_changed);

    fireEvent.click(screen.getByRole("button", { name: "Back to your planned analysis" }));
    expect(onChanges).toHaveBeenCalledWith({});
  });

  it("one dropdown per decision, the moved one marked", async () => {
    wrap(
      <WhatifTab
        geneHref={geneHref}
        target={target}
        overview={ov}
        manifest={{}}
        changes={{ late_cq: "cq35" }}
        onChanges={() => {}}
      />,
    );
    expect(screen.getAllByRole("combobox")).toHaveLength(ov.decisions.length);
    expect(screen.getAllByText("Changed")).toHaveLength(1);
  });

  it("names a link's unknown choices and leaves them out", async () => {
    wrap(
      <WhatifTab
        geneHref={geneHref}
        target={target}
        overview={ov}
        manifest={{}}
        changes={{ nope: "x" }}
        onChanges={() => {}}
      />,
    );
    expect(screen.getByText(/this audit does not have \(nope=x\)/)).toBeTruthy();
    await screen.findByText("Your planned analysis");
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ changes: {}, genes: [] });
  });
});

describe("How it works", () => {
  it("shows the stages, every verdict rule and the checks this audit did not run", async () => {
    const h = how as AuditHow;
    wrap(<HowTab target={target} manifest={{}} />);
    for (const stage of h.stages) expect(await screen.findByText(stage.title)).toBeTruthy();
    for (const rule of Object.values(h.rules)) expect(screen.getByText(rule)).toBeTruthy();
    if (h.not_run.length) expect(screen.getByText("Not run on this audit")).toBeTruthy();
  });
});
