import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import recorded from "./recorded/workspaces.json";
import { Recent } from "./Recent";
import type { WorkspaceSummary } from "./workspace";

const workspaces = recorded.workspaces as WorkspaceSummary[];

afterEach(cleanup);

describe("Recent", () => {
  it("shows one card per workspace, each a link to where it stands", () => {
    render(<Recent workspaces={workspaces} loading={false} error={null} onRetry={() => {}} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(workspaces.length);
    const demo = workspaces.find((w) => w.is_demo)!;
    const demoLink = screen.getByRole("link", { name: demo.title });
    expect(demoLink.getAttribute("href")).toBe(`/s/${demo.key}/results`);
    // The description carries what the chips and badges show.
    const details = document.getElementById(
      demoLink.getAttribute("aria-describedby")!,
    )!.textContent!;
    expect(details).toContain(`${demo.n_plates} plates`);
    expect(details).toContain("Design: confirmed");
    expect(details).toContain("audited");
  });

  it("moves focus between cards with the arrow keys, Home and End", () => {
    render(<Recent workspaces={workspaces} loading={false} error={null} onRetry={() => {}} />);
    const links = screen.getAllByRole("link");
    links[0]!.focus();
    fireEvent.keyDown(links[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(links[1]);
    fireEvent.keyDown(links[1]!, { key: "Home" });
    expect(document.activeElement).toBe(links[0]);
    fireEvent.keyDown(links[0]!, { key: "End" });
    expect(document.activeElement).toBe(links[links.length - 1]);
  });

  it("says what to do when nothing has been opened", () => {
    render(<Recent workspaces={[]} loading={false} error={null} onRetry={() => {}} />);
    expect(screen.getByText("Nothing opened yet")).toBeTruthy();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });
});
