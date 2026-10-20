import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ChainTimeline } from "./ChainTimeline";
// Recorded from the real seeded store: see recorded/record_chain.py.
import agentChain from "./recorded/decisions-e300000d4f9a.json";
import humanChain from "./recorded/decisions-cf49ccd72052.json";
import { renderWithProviders } from "./test-utils";
import type { DecisionsView } from "./types";

const withAgents = agentChain as DecisionsView;
const decided = humanChain as DecisionsView;

afterEach(cleanup);

function entries() {
  return within(screen.getByRole("list", { name: /decision chain entries/i })).getAllByRole("article");
}

describe("ChainTimeline", () => {
  it("lists every entry newest first, each linked to the one before it", () => {
    renderWithProviders(<ChainTimeline entries={decided.entries} root={decided.root} head={decided.head} intact={decided.chain_intact} />);
    const shown = entries();
    expect(shown).toHaveLength(decided.entries.length);
    const seqs = shown.map((a) => Number(/#(\d+)/.exec(a.textContent ?? "")?.[1]));
    expect(seqs).toEqual([...decided.entries.map((e) => e.seq)].sort((a, b) => b - a));
    // the oldest links to the input file, every other one to its predecessor
    expect(within(shown[shown.length - 1]!).getByText(/links to the input file/)).toBeTruthy();
    expect(within(shown[0]!).getByText(`links to #${decided.entries.length - 1}`)).toBeTruthy();
    expect(screen.queryByText(/does not link/)).toBeNull();
    expect(screen.getByText(/Intact: every hash checks out/)).toBeTruthy();
  });

  it("says who decided, the card's question and the option in words", () => {
    renderWithProviders(<ChainTimeline entries={decided.entries} root={decided.root} head={decided.head} />);
    for (const e of decided.entries) {
      expect(screen.getAllByText(e.card_title!).length).toBeGreaterThan(0);
      expect(screen.getAllByText(e.option_label!).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("Decided automatically")).toBeTruthy();
    expect(screen.getAllByText("Applied")).toHaveLength(decided.entries.filter((e) => e.status === "applied").length);
  });

  it("shows an agent's requests as waiting, and filters by actor", () => {
    renderWithProviders(<ChainTimeline entries={withAgents.entries} root={withAgents.root} head={withAgents.head} />);
    const agents = withAgents.entries.filter((e) => e.actor === "agent");
    expect(screen.getAllByText("Waiting for a person")).toHaveLength(agents.length);
    fireEvent.click(screen.getByRole("radio", { name: /Agents/ }));
    expect(entries()).toHaveLength(agents.length);
    expect(screen.getByText(/hidden by the filter/)).toBeTruthy();
  });

  it("marks a link that does not match its predecessor", () => {
    const changed = decided.entries.map((e, i) => (i === 1 ? { ...e, prev_hash: decided.entries[2]!.hash } : e));
    renderWithProviders(<ChainTimeline entries={changed} root={decided.root} head={decided.head} intact={false} />);
    expect(screen.getByText("does not link to #1")).toBeTruthy();
    expect(screen.getByText(/Broken: a line was changed/)).toBeTruthy();
  });

  it("puts the head first and marks it", () => {
    renderWithProviders(<ChainTimeline entries={decided.entries} root={decided.root} head={decided.head} />);
    expect(within(entries()[0]!).getByText("Head")).toBeTruthy();
  });
});
