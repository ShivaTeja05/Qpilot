import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "@/features/record/test-utils";
import { ActivityList } from "./ActivityList";
// Recorded from the real API on the seeded store: see recorded/README.md.
import recorded from "./recorded/agents.json";
import { ConnectCard, RulesCard, ToolsCard } from "./ToolsCard";
import type { AgentsView } from "./types";

const view = recorded as AgentsView;

afterEach(cleanup);

describe("Agents parts", () => {
  it("lists every tool qpilot serve serves, grouped by what it can change", () => {
    renderWithProviders(<ToolsCard tools={view.tools} simulator={view.simulator} />);
    for (const t of view.tools) expect(screen.getByText(t.name)).toBeTruthy();
    const request = view.tools.filter((t) => t.access === "request");
    const heading = screen.getByRole("heading", { name: new RegExp(`^Request a decision\\s*${request.length}$`) });
    expect(heading).toBeTruthy();
  });

  it("shows the connect command and the rules, as the server words them", () => {
    renderWithProviders(
      <>
        <ConnectCard command={view.connect} note={view.connect_note} storeNote={view.store_note} />
        <RulesCard rules={view.rules} />
      </>,
    );
    expect(screen.getByText(view.connect)).toBeTruthy();
    for (const r of view.rules) expect(screen.getByText(r)).toBeTruthy();
  });

  it("lists recent agent activity in the server's words, newest first", () => {
    renderWithProviders(<ActivityList items={view.activity} now={Date.parse(view.activity[0]!.at)} where={() => null} />);
    const list = screen.getByRole("list", { name: /recent agent activity/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(view.activity.length);
    view.activity.forEach((a, i) => expect(within(items[i]!).getByText(a.summary)).toBeTruthy());
  });
});
