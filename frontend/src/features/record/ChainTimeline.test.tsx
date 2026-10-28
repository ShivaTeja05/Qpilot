import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ChainTimeline } from "./ChainTimeline";
// Recorded from the real API on the seeded store: see recorded/README.md.
import agentChain from "./recorded/decisions-e300000d4f9a.json";
import humanChain from "./recorded/decisions-cf49ccd72052.json";
import { renderWithProviders } from "./test-utils";
import { fromApi, type DecisionsApi } from "./types";

const withAgents = fromApi(agentChain as unknown as DecisionsApi);
const decided = fromApi(humanChain as unknown as DecisionsApi);

afterEach(cleanup);

function entries() {
  return within(screen.getByRole("list", { name: /decision chain entries/i })).getAllByRole(
    "article",
  );
}

describe("ChainTimeline", () => {
  it("lists every entry newest first, each linked to the one before it", () => {
    renderWithProviders(
      <ChainTimeline
        entries={decided.entries}
        root={decided.root}
        head={decided.head}
        intact={decided.chain_intact}
      />,
    );
    const shown = entries();
    expect(shown).toHaveLength(decided.entries.length);
    const seqs = shown.map((a) => Number(/#(\d+)/.exec(a.textContent ?? "")?.[1]));
    expect(seqs).toEqual([...decided.entries.map((e) => e.seq)].sort((a, b) => b - a));
    // the oldest links to the input file, every other one to its predecessor
    expect(within(shown[shown.length - 1]!).getByText(/links to the input file/)).toBeTruthy();
    expect(within(shown[0]!).getByText(`links to #${decided.entries.length - 1}`)).toBeTruthy();
    expect(screen.queryByText(/does not link/)).toBeNull();
    // the server's own check of every hash shows only when it sends one
    expect(Boolean(screen.queryByText(/Intact: every hash checks out/))).toBe(
      decided.chain_intact === true,
    );
  });

  it("shows option labels only, with the id in a tooltip, and calls the person 'You'", () => {
    renderWithProviders(
      <ChainTimeline entries={decided.entries} root={decided.root} head={decided.head} />,
    );
    const text = screen.getByRole("list", { name: /decision chain entries/i }).textContent ?? "";
    for (const e of decided.entries) {
      if (!e.option_label || e.option_label === e.option) continue;
      expect(text).not.toContain(`${e.option_label}${e.option}`); // "…was found)linregpcr"
      const label = screen.getAllByText(e.option_label)[0]!;
      expect(label.getAttribute("title")).toBe(`Option id: ${e.option}`);
    }
    if (decided.entries.some((e) => e.actor === "human"))
      expect(screen.getAllByRole("img", { name: "You" }).length).toBeGreaterThan(0);
    expect(screen.queryByText(/human/i)).toBeNull();
  });

  it("says who decided, the card's question and the option in words", () => {
    renderWithProviders(
      <ChainTimeline entries={decided.entries} root={decided.root} head={decided.head} />,
    );
    for (const e of decided.entries) {
      expect(screen.getAllByText(e.card_title!).length).toBeGreaterThan(0);
      expect(screen.getAllByText(e.option_label!).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("Decided automatically")).toBeTruthy();
    expect(screen.getAllByText("Applied")).toHaveLength(
      decided.entries.filter((e) => e.status === "applied").length,
    );
  });

  it("shows which agent requests still wait, and filters by actor", () => {
    renderWithProviders(
      <ChainTimeline
        entries={withAgents.entries}
        root={withAgents.root}
        head={withAgents.head}
        waiting={withAgents.waiting}
        attempts={withAgents.attempts}
      />,
    );
    const requests = withAgents.entries.filter((e) => e.status === "pending_human");
    const waiting = requests.filter((e) => withAgents.waiting.includes(e.hash));
    expect(waiting.length).toBeGreaterThan(0);
    expect(screen.getAllByText("Waiting for a person")).toHaveLength(waiting.length);
    expect(screen.getAllByText("Request, answered")).toHaveLength(requests.length - waiting.length);
    fireEvent.click(screen.getByRole("radio", { name: /Agents/ }));
    expect(entries()).toHaveLength(withAgents.entries.filter((e) => e.actor === "agent").length);
    expect(screen.getByText(/hidden by the filter/)).toBeTruthy();
  });

  it("lists the attempts that did not change the study beside the chain", () => {
    renderWithProviders(
      <ChainTimeline
        entries={withAgents.entries}
        root={withAgents.root}
        head={withAgents.head}
        attempts={withAgents.attempts}
      />,
    );
    expect(withAgents.attempts.length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        new RegExp(`${withAgents.attempts.length} attempts? did not change the study`),
      ),
    ).toBeTruthy();
    for (const a of withAgents.attempts) expect(screen.getByText(`“${a.reason}”`)).toBeTruthy();
  });

  it("marks a link that does not match its predecessor", () => {
    const changed = decided.entries.map((e, i) =>
      i === 1 ? { ...e, prev_hash: decided.entries[2]!.hash } : e,
    );
    renderWithProviders(
      <ChainTimeline entries={changed} root={decided.root} head={decided.head} intact={false} />,
    );
    expect(screen.getByText("does not link to #1")).toBeTruthy();
    expect(screen.getByText(/Broken: a line was changed/)).toBeTruthy();
  });

  it("puts the head first and marks it", () => {
    renderWithProviders(
      <ChainTimeline entries={decided.entries} root={decided.root} head={decided.head} />,
    );
    expect(within(entries()[0]!).getByText("Head")).toBeTruthy();
  });
});
