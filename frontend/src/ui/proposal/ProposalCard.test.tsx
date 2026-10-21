// Recorded from the real Studio service (see ./recorded/README.md); nothing hand-written.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { describeProposal, type Proposal } from "@/lib/vocab";
import { TooltipProvider } from "../overlay";
import { ProposalCard, sameDecimals } from "./ProposalCard";
import { diffPayload } from "./edit";
import { BLIND_TEXT, MATTERS_TEXT } from "./parts";
import { INSTRUCTION_TEXT, visibleText, type QuarantineEntry } from "./words";
import recorded from "./recorded/demo-session.json";

const proposals = recorded.proposals as unknown as Proposal[];
const quarantine = recorded.quarantine as QuarantineEntry[];
const byId = new Map(quarantine.map((q) => [q.text_id, q]));
const quotes = (id: string) => byId.get(id) ?? null;

function find(kind: Proposal["kind"], check?: Proposal["check"]["status"]): Proposal {
  const p = proposals.find((x) => x.kind === kind && (!check || x.check.status === check));
  if (!p) throw new Error(`no recorded ${kind} ${check ?? ""}`);
  return p;
}

/** A recorded proposal as it was before a person decided it. */
function pending(p: Proposal): Proposal {
  return { ...p, status: "proposed", decided_by: null, decided_at: null, reason: null };
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

afterEach(cleanup);

describe("ProposalCard", () => {
  it("says every recorded kind of proposal in words, not JSON", () => {
    for (const p of proposals) {
      const { unmount } = wrap(<ProposalCard proposal={p} quotes={quotes} />);
      const heading = screen.getByRole("heading", { level: 3 });
      expect(heading.textContent).toBe(describeProposal(p));
      expect(heading.textContent).not.toMatch(/[{}]/);
      unmount();
    }
  }, 20_000); // eleven full cards; slow on a loaded machine

  it("shows a decided proposal's status and reason, without the actions", () => {
    const p = find("design.well_role", "contradicted");
    wrap(<ProposalCard proposal={p} quotes={quotes} onAccept={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getAllByText("Rejected").length).toBeGreaterThan(0);
    expect(screen.getByText(`“${p.reason}”`)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /accept/i })).toBeNull();
  });

  it("asks for a reason before accepting what the engine contradicts", async () => {
    const p = pending(find("design.well_role", "contradicted"));
    const onAccept = vi.fn().mockResolvedValue(undefined);
    wrap(<ProposalCard proposal={p} quotes={quotes} onAccept={onAccept} onReject={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Accept anyway…" }));
    expect(onAccept).not.toHaveBeenCalled();
    const submit = screen.getByRole("button", { name: "Accept anyway" });
    // Pressed without a reason: nothing is sent, and the card says what is missing.
    fireEvent.click(submit);
    expect(onAccept).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/Give a reason first/);
    fireEvent.change(screen.getByLabelText(/Say why you accept it anyway/), {
      target: { value: "the series is a standard curve" },
    });
    await act(async () => fireEvent.click(submit));
    expect(onAccept).toHaveBeenCalledWith("the series is a standard curve");
  });

  it("accepts a consistent proposal at once", async () => {
    const p = pending(find("design.gene_symbol", "consistent"));
    const onAccept = vi.fn().mockResolvedValue(undefined);
    wrap(<ProposalCard proposal={p} quotes={quotes} onAccept={onAccept} />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Accept" })));
    expect(onAccept).toHaveBeenCalledWith("");
  });

  it("needs a reason to reject, and shows a refusal on the card", async () => {
    const p = pending(find("design.gene_symbol", "consistent"));
    const onReject = vi.fn().mockRejectedValue(new Error("this proposal is already accepted"));
    wrap(<ProposalCard proposal={p} quotes={quotes} onAccept={vi.fn()} onReject={onReject} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject…" }));
    const submit = screen.getByRole("button", { name: "Reject" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    expect(onReject).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Why do you reject it?").getAttribute("aria-invalid")).toBe(
      "true",
    );
    fireEvent.change(screen.getByLabelText("Why do you reject it?"), {
      target: { value: "wrong assay" },
    });
    await act(async () => fireEvent.click(submit));
    expect(onReject).toHaveBeenCalledWith("wrong assay");
    expect(screen.getByText("this proposal is already accepted")).toBeTruthy();
  });

  it("edits send only the fields that changed", async () => {
    const p = pending(find("design.well_role", "contradicted"));
    const onEdit = vi.fn().mockResolvedValue(undefined);
    wrap(
      <ProposalCard
        proposal={p}
        quotes={quotes}
        onAccept={vi.fn()}
        onEdit={onEdit}
        onReject={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit…" }));
    const alt = p.alternatives[0] as Record<string, unknown>;
    // The proposer's other reading, loaded into the fields with one click.
    fireEvent.click(screen.getByRole("button", { name: "Sample" }));
    const form = screen.getByRole("group", { name: "Edit the proposal" });
    expect(within(form).getByText(describeProposal(p, { ...p.payload, ...alt }))).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Say why you accept your edit/), {
      target: { value: "a study sample" },
    });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Accept the edit" })));
    expect(onEdit).toHaveBeenCalledWith(alt, "a study sample");
  });

  it("keeps blind proposals blind: only whether it matters", () => {
    const call = find("curve.well_call", "contradicted");
    wrap(<ProposalCard proposal={pending(call)} quotes={quotes} resultsVisible />);
    expect(screen.getByText(MATTERS_TEXT)).toBeTruthy();
    cleanup();
    const series = pending(find("design.dilution_series", "consistent"));
    const ask = vi.fn();
    wrap(<ProposalCard proposal={series} quotes={quotes} onAskMatters={ask} onAccept={vi.fn()} />);
    expect(screen.getByText(BLIND_TEXT)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Does this matter?" }));
    expect(ask).toHaveBeenCalled();
  });

  it("shows an exclusion's numbers only once results are visible", () => {
    const p = find("prism.exclusion_reason");
    wrap(<ProposalCard proposal={p} quotes={quotes} resultsVisible={false} />);
    expect(screen.getByText(/Hidden: the design or the curves/)).toBeTruthy();
    cleanup();
    wrap(<ProposalCard proposal={p} quotes={quotes} resultsVisible />);
    expect(screen.getByText(/Excluding it changes no conclusion \(0 of 58\)/)).toBeTruthy();
  });

  it("opens the curve of a cited well", () => {
    const p = find("curve.well_call");
    const open = vi.fn();
    wrap(<ProposalCard proposal={p} quotes={quotes} onOpenWell={open} />);
    fireEvent.click(screen.getByRole("button", { name: /More about the why/ }));
    fireEvent.click(screen.getAllByRole("button", { name: "Open the curve" })[0]!);
    expect(open).toHaveBeenCalledWith(p.subject);
  });
});

describe("quoted text", () => {
  it("marks instruction-like text and never renders it as anything but text", () => {
    const entry = recorded.firewall as QuarantineEntry;
    const p = pending(find("design.well_role", "consistent"));
    const cited = { ...p, evidence: [{ kind: "text" as const, ref: entry.text_id, note: "" }] };
    wrap(<ProposalCard proposal={cited} quotes={(id) => (id === entry.text_id ? entry : null)} />);
    expect(screen.getByText(/reads like an instruction, never obeyed/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /More about the why/ }));
    expect(screen.getByText(INSTRUCTION_TEXT)).toBeTruthy();
    // The quote in the summary line and in the fold-out: text elements, never markup.
    expect(screen.getAllByText(entry.value).map((el) => el.tagName)).toEqual(["Q", "BLOCKQUOTE"]);
  });

  it("makes invisible and direction-changing characters visible", () => {
    expect(visibleText("a‮b​c")).toBe("a⟨U+202E⟩b⟨U+200B⟩c");
  });
});

describe("diffPayload", () => {
  it("keeps only changed fields", () => {
    const p = find("design.dilution_series");
    expect(diffPayload(p.payload, { ...p.payload })).toEqual({});
  });
});

describe("sameDecimals", () => {
  it("writes the exported value to the returned value's decimals", () => {
    expect(sameDecimals(1.5563229036983888, 2.5563)).toBe("1.5563");
    expect(sameDecimals(3.2, 2)).toBe("3.2000");
    expect(sameDecimals(null, 2.5)).toBe("—");
  });
});
