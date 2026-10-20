import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SectionBoundary } from "./SectionBoundary";

afterEach(cleanup);

describe("SectionBoundary", () => {
  it("shows a failed section in words and lets the person try again", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    let fail = true;
    function Section() {
      if (fail) throw new Error("Cannot read properties of undefined (reading 'M_initial')");
      return <p>Shown again</p>;
    }
    render(
      <SectionBoundary label="Results" resetKey="/s/abc/results">
        <Section />
      </SectionBoundary>,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Results");
    expect(screen.getByRole("alert").textContent).toContain("M_initial");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("Shown again")).toBeTruthy();
    quiet.mockRestore();
  });
});
