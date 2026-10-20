import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "@/features/record/test-utils";
// Recorded from the real API on the seeded store: see recorded/README.md.
import recorded from "./recorded/agents.json";
import { RequestItem } from "./RequestItem";
import type { AgentsView } from "./types";

const request = (recorded as unknown as AgentsView).pending[0]!;

afterEach(cleanup);

function show() {
  renderWithProviders(
    <ul>
      <RequestItem request={request} now={Date.parse(request.at)} />
    </ul>,
  );
}

describe("RequestItem", () => {
  it("says what the agent asked for and why, in words", () => {
    show();
    expect(screen.getByText(request.card_title)).toBeTruthy();
    expect(screen.getByText(request.option_label)).toBeTruthy();
    expect(screen.getByText(request.reason)).toBeTruthy();
    expect(screen.getByText(/asks for a choice that can change a conclusion/)).toBeTruthy();
  });

  it("needs the person's own reason before it approves", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Approve…" }));
    const confirm = screen.getByRole("button", { name: `Approve: use ${request.option_label}` });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Why you approve it/), { target: { value: "   " } });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Why you approve it/), { target: { value: "Matches our SOP" } });
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
  });

  it("turns down with a reason too, and Cancel goes back", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Turn down…" }));
    expect(screen.getByLabelText(/Why you turn it down/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Approve…" })).toBeTruthy();
  });
});
