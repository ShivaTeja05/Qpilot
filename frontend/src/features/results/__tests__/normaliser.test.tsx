/**
 * The reference panel's geNorm-and-NormFinder comparison and "Also test other normalisers", on
 * the API's own views of the demo session (recorded from the real server: ./recorded/README.md).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Schemas } from "@/api/client";
import { describeProposal, type Proposal } from "@/lib/vocab";
import { TooltipProvider } from "@/ui";
import {
  AXIS_STATUS,
  AxisPanel,
  axisWords,
  consequenceWords,
  type AxisView,
} from "../FurtherChoices";
import {
  ReferenceComparison,
  ReferenceComparisonView,
  VERDICT,
  type ReferencesView,
} from "../ReferenceComparison";
import off from "./recorded/normaliser-off.json";
import pendingInbox from "./recorded/proposals-normaliser-pending.json";
import references from "./recorded/references.json";
import swept from "./recorded/normaliser-swept.json";

const refs = references as unknown as ReferencesView;
const axisOf = (view: { axes: unknown[] }, name: string) =>
  (view.axes as AxisView[]).find((a) => a.name === name) as AxisView;
const offAxis = axisOf(off, "normaliser");
const sweptAxis = axisOf(swept, "normaliser");
const pending = pendingInbox as unknown as Schemas["ProposalList"];
const workspace = { key: off.session, kind: "session" } as unknown as Schemas["WorkspaceView"];

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) });
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

function serve(inbox: Schemas["ProposalList"]) {
  return vi
    .spyOn(api, "GET")
    .mockImplementation(((route: string) =>
      route === "/api/sessions/{sid}/proposals"
        ? ok(inbox)
        : ok({ entries: [], sheet_cells: {}, n_flagged: 0 })) as never);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("geNorm and NormFinder side by side", () => {
  it("shows both rankings of every candidate and says they agree on the best pair", () => {
    render(<ReferenceComparisonView view={refs} />);
    const box = screen.getByTestId("reference-comparison");
    expect(refs.verdict).toBe("agree");
    expect(within(box).getByText(VERDICT.agree.word)).toBeTruthy();
    expect(box.textContent).toContain(refs.words);
    const table = within(box).getByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(refs.rows.length + 1); // header + one per candidate
    for (const r of refs.rows) {
      const row = rows.find((tr) => tr.textContent?.startsWith(r.gene)) as HTMLElement;
      expect(row.textContent).toContain(r.genorm_m!.toFixed(2));
      expect(row.textContent).toContain(r.normfinder!.toFixed(3));
    }
    // the pair, the groups NormFinder used, and that the choice stays a person's
    expect(box.textContent).toContain(refs.normfinder_pair!.genes.join(" and "));
    expect(box.textContent).toContain("geNorm cannot order its last two genes");
    for (const g of Object.keys(refs.groups ?? {})) expect(box.textContent).toContain(g);
    expect(box.textContent).toContain(refs.choice_note);
    expect(box.textContent).toContain("left out");
  });

  it("names a disagreement and an unavailable NormFinder in plain words", () => {
    const apart: ReferencesView = {
      ...refs,
      verdict: "disagree",
      words:
        "geNorm and NormFinder disagree on the best pair: geNorm picks A and B, NormFinder C and D.",
    };
    const { unmount } = render(<ReferenceComparisonView view={apart} />);
    expect(screen.getByText(VERDICT.disagree.word)).toBeTruthy();
    expect(screen.getByText(apart.words)).toBeTruthy();
    unmount();
    const none: ReferencesView = {
      ...refs,
      verdict: "not_available",
      normfinder_pair: null,
      words:
        "NormFinder could not rank these candidates: NormFinder needs at least 3 candidate control genes, not 2.",
      rows: refs.rows.slice(0, 2).map((r) => ({ ...r, normfinder: null, normfinder_rank: null })),
    };
    render(<ReferenceComparisonView view={none} />);
    expect(screen.getByText(VERDICT.not_available.word)).toBeTruthy();
    expect(screen.queryByText(/NormFinder's best pair/)).toBeNull();
  });

  it("reads the route for the open study", async () => {
    const get = vi.spyOn(api, "GET").mockImplementation((() => ok(refs)) as never);
    wrap(<ReferenceComparison workspaceKey={off.session} studyId={refs.study_id} />);
    await screen.findByTestId("reference-comparison");
    expect(get).toHaveBeenCalledWith("/api/studies/{study_id}/references", {
      params: { path: { study_id: refs.study_id } },
    });
  });
});

describe("also test other normalisers", () => {
  it("is offered with its own words and proposes the normaliser axis", async () => {
    serve({ ...pending, proposals: [] });
    const post = vi
      .spyOn(api, "POST")
      .mockImplementation((() => ok({ outcome: null, message: "Proposed." })) as never);
    wrap(<AxisPanel axis={offAxis} workspace={workspace} />);
    const panel = screen.getByRole("region", { name: axisWords("normaliser").heading });
    expect(within(panel).getAllByText(AXIS_STATUS.off.word).length).toBeGreaterThan(0);
    expect(panel.textContent).toContain(offAxis.text.plain);
    const propose = await within(panel).findByRole("button", {
      name: "Propose testing the other normalisers",
    });
    fireEvent.click(propose);
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0]![1]).toMatchObject({ body: { axis: "normaliser", on: true } });
  });

  it("shows the rule's proposal in words, with what accepting does", async () => {
    serve(pending);
    wrap(<AxisPanel axis={offAxis} workspace={workspace} />);
    const proposal = pending.proposals.find((p) => p.kind === "choice.axis") as Proposal;
    expect(describeProposal(proposal)).toBe(
      "Also test what to normalise each gene to: NormFinder's best pair of reference genes; the " +
        "mean of every gene measured (global mean) (besides the reference genes chosen for this " +
        "study, the analysis in use)",
    );
    await screen.findByText(describeProposal(proposal));
    expect(consequenceWords(true, "normaliser")).toContain("stays the reference genes chosen");
  });

  it("after a person accepted it: tested, what each normaliser flips, its card", () => {
    serve({ ...pending, proposals: [] });
    wrap(<AxisPanel axis={sweptAxis} workspace={workspace} />);
    const panel = screen.getByRole("region", { name: axisWords("normaliser").heading });
    expect(within(panel).getByText(AXIS_STATUS.swept.word)).toBeTruthy();
    expect(sweptAxis.card_id).toBe("card_normaliser");
    expect(within(panel).getByRole("link", { name: /Go to its Decision Card/ })).toBeTruthy();
    const pair = sweptAxis.options.find((o) => o.id === "normfinder_pair")!;
    expect(pair.tested && pair.flips).toBeTruthy();
    expect(panel.textContent).toContain(`Alone, it changes ${pair.flips!.text}`);
    const genorm = sweptAxis.options.find((o) => o.id === "genorm_pair")!;
    expect(genorm.unavailable).toContain("NormFinder's best pair too");
    expect(within(panel).getByText("Does not apply")).toBeTruthy();
  });
});
