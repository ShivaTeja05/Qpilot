/** Answers recorded from the real API: read, and shown with their tool, writer and cited facts. */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import request from "./__recorded__/ask-request.json";
import robustness from "./__recorded__/ask-robustness.json";
import study from "./__recorded__/ask-study.json";
import { Answer } from "./Answer";
import { toAskView } from "./types";

afterEach(cleanup);

const links = { gene: (g: string) => `#/r/s/gene/${g}`, results: "#/r/s/results" };

describe("toAskView", () => {
  it("reads a recorded answer as the server wrote it", () => {
    const view = toAskView(robustness.result)!;
    expect(view.answer).toBe(robustness.result.answer);
    expect(view.tool).toBe(robustness.result.tool);
    expect(view.writtenBy).toBe("template");
    expect(view.routedBy).toBe("keywords");
    expect(view.facts.map((f) => [f.meaning, f.value])).toEqual(
      robustness.result.facts.map((f) => [f.meaning, f.value]),
    );
    expect(view.headBefore).toBe(view.headAfter);
  });

  it("refuses a result without an answer", () => {
    expect(toAskView(null)).toBeNull();
    expect(toAskView({ ...robustness.result, answer: "" })).toBeNull();
  });
});

describe("Answer", () => {
  it("shows the words, which tool answered, who wrote them, and every cited fact", () => {
    render(<Answer answer={toAskView(robustness.result)!} links={links} />);
    expect(screen.getByText(robustness.result.answer)).toBeTruthy();
    expect(screen.getByText(/robustness of one gene/i)).toBeTruthy();
    expect(screen.getByText(`Picked by ${robustness.result.routed_words}`)).toBeTruthy();
    expect(screen.getByText(robustness.result.writer_words)).toBeTruthy();
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(robustness.result.facts.length);
    robustness.result.facts.forEach((f, i) => {
      expect(within(rows[i]!).getByText(f.meaning)).toBeTruthy();
      expect(within(rows[i]!).getByText(f.value)).toBeTruthy();
    });
    const gene = robustness.result.args.gene;
    expect(screen.getByRole("link", { name: `Open ${gene}` }).getAttribute("href")).toBe(
      links.gene(gene),
    );
  });

  it("lists the study summary's numbers, and says so when an answer cites none", () => {
    render(<Answer answer={toAskView(study.result)!} links={links} />);
    for (const f of study.result.facts) expect(screen.getByText(f.value)).toBeTruthy();
    cleanup();
    render(<Answer answer={toAskView(request.result)!} links={links} />);
    expect(request.result.facts).toHaveLength(0);
    expect(screen.getByText("This answer cites no numbers.")).toBeTruthy();
  });

  it("says a change request waits for a person and opens its card", () => {
    const onOpenCard = vi.fn();
    render(<Answer answer={toAskView(request.result)!} links={{ ...links, onOpenCard }} />);
    expect(screen.getByText("Waiting for a person")).toBeTruthy();
    expect(screen.getByText(request.result.note)).toBeTruthy();
    const open = screen.getByRole("link", { name: "Open the card" });
    expect(open.getAttribute("href")).toBe(links.results);
    fireEvent.click(open);
    expect(onOpenCard).toHaveBeenCalledWith(`card:${request.result.card_id}`);
  });
});
