/** Answers recorded from the real API: read, and shown with their tool, writer and cited facts. */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import auditFirst from "./__recorded__/ask-audit-first.json";
import whatIf from "./__recorded__/ask-audit-whatif.json";
import request from "./__recorded__/ask-request.json";
import robustness from "./__recorded__/ask-robustness.json";
import study from "./__recorded__/ask-study.json";
import { Answer } from "./Answer";
import { cardFocus, toAskAnswer, type AskAnswer } from "./types";
import { asWritten } from "./testText";

afterEach(cleanup);

const links = { gene: (g: string) => `#/r/s/gene/${g}`, results: "#/r/s/results" };
const read = (job: { result: unknown }) => toAskAnswer(job.result)!;

function factRows(): HTMLElement[] {
  return within(screen.getByRole("table")).getAllByRole("row").slice(1);
}

describe("toAskAnswer", () => {
  it("reads a recorded answer as the server wrote it", () => {
    const a = read(robustness);
    expect(a.answer).toBe(robustness.result.answer);
    expect(a.facts).toHaveLength(robustness.result.facts.length);
  });

  it("refuses a result without an answer", () => {
    expect(toAskAnswer(null)).toBeNull();
    expect(toAskAnswer({ ...robustness.result, answer: "" })).toBeNull();
    expect(toAskAnswer({ answer: robustness.result.answer })).toBeNull();
  });
});

describe("Answer", () => {
  it("shows the words, which tool answered, who picked it, who wrote them, and every cited fact", () => {
    render(<Answer answer={read(robustness)} links={links} />);
    expect(screen.getByText(robustness.result.answer, asWritten)).toBeTruthy();
    expect(screen.getByText(/robustness of one gene/i)).toBeTruthy();
    expect(screen.getByText(`Picked by ${robustness.result.routed_words}`, asWritten)).toBeTruthy();
    expect(screen.getByText(robustness.result.writer_words, asWritten)).toBeTruthy();
    const rows = factRows();
    expect(rows).toHaveLength(robustness.result.facts.length);
    robustness.result.facts.forEach((f, i) => {
      expect(within(rows[i]!).getByText(f.meaning, asWritten)).toBeTruthy();
      expect(within(rows[i]!).getByText(f.value, asWritten)).toBeTruthy();
    });
    const gene = robustness.result.args.gene;
    expect(screen.getByRole("link", { name: `Open ${gene}` }).getAttribute("href")).toBe(
      links.gene(gene),
    );
  });

  it("lists the study summary's numbers, and says so when an answer cites none", () => {
    render(<Answer answer={read(study)} links={links} />);
    for (const f of study.result.facts) expect(screen.getByText(f.value, asWritten)).toBeTruthy();
    cleanup();
    render(<Answer answer={read(request)} links={links} />);
    expect(request.result.facts).toHaveLength(0);
    expect(screen.getByText("This answer cites no numbers.")).toBeTruthy();
  });

  it("a change request writes nothing and opens the Decision Card it names", () => {
    const onOpenCard = vi.fn();
    expect(request.result.head_after).toBe(request.result.head_before);
    render(<Answer answer={read(request)} links={{ ...links, onOpenCard }} />);
    expect(screen.getByText(request.result.answer, asWritten)).toBeTruthy();
    expect(screen.getByText("A choice for a person")).toBeTruthy();
    expect(screen.getByText(request.result.note, asWritten)).toBeTruthy();
    const open = screen.getByRole("link", { name: "Open the card" });
    expect(open.getAttribute("href")).toBe(links.results);
    fireEvent.click(open);
    expect(onOpenCard).toHaveBeenCalledWith(request.result.focus);
    expect(cardFocus(read(request))).toBe(`card:${request.result.card_id}`);
  });

  it("says when the robustness audit answered, with its facts (text values wrap)", () => {
    render(<Answer answer={read(whatIf)} links={links} />);
    expect(screen.getByText("(the robustness audit)", { exact: false })).toBeTruthy();
    expect(screen.getByText(`Picked by ${whatIf.result.routed_words}`, asWritten)).toBeTruthy();
    const rows = factRows();
    expect(rows).toHaveLength(whatIf.result.facts.length);
    // The choices changed are words, not a number: a wrapping cell, not the mono number column.
    const changes = whatIf.result.facts.find((f) => f.id === "f_changes")!;
    const cell = within(rows[whatIf.result.facts.indexOf(changes)]!).getByText(
      changes.value,
      asWritten,
    );
    expect(cell.className).not.toMatch(/whitespace-nowrap/);
  });

  it("shows the audit's issue queue as cited facts", () => {
    const a: AskAnswer = read(auditFirst);
    render(<Answer answer={a} links={links} />);
    expect(a.tool).toBe("issues");
    const rows = factRows();
    expect(rows).toHaveLength(a.facts.length);
    a.facts.forEach((f, i) => expect(within(rows[i]!).getByText(f.value, asWritten)).toBeTruthy());
  });
});
