import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { NeedsKey } from "@/shell/NeedsKey";
import { Textarea } from "./controls";
import { ErrorPanel } from "./ErrorPanel";
import { ConclusionTag, LevelTag, VerdictTag } from "./tags";
import { TooltipProvider } from "./overlay";

afterEach(cleanup);

describe("ErrorPanel", () => {
  it("shows a refusal in the server's own words", () => {
    render(<ErrorPanel error={new ApiError(409, "studio", "Confirm the design first.")} />);
    expect(screen.getByRole("alert").textContent).toContain("Confirm the design first.");
  });
  it("says what to do for a missing key, a stale view and a stopped server", () => {
    const { rerender } = render(<ErrorPanel error={new ApiError(401, "no_token", "x")} />);
    expect(screen.getByText("Open the link qPilot printed in your terminal")).toBeTruthy();
    rerender(<ErrorPanel error={new ApiError(409, "stale", "x")} />);
    expect(screen.getByText("Something was decided since you loaded this")).toBeTruthy();
    rerender(
      <ErrorPanel
        error={
          new ApiError(0, "offline", "qPilot is not answering. Is `qpilot app` still running?")
        }
      />,
    );
    expect(screen.getByText("qPilot is not answering")).toBeTruthy();
  });
  it("offers Try again", () => {
    const retry = vi.fn();
    render(<ErrorPanel error={new Error("boom")} onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalledOnce();
  });
});

describe("meaning never by colour alone", () => {
  it("writes conclusions as arrow + word", () => {
    const { container } = render(
      <>
        <ConclusionTag conclusion="up" />
        <ConclusionTag conclusion="none" />
        <ConclusionTag conclusion="down" compact />
      </>,
    );
    expect(container.textContent).toBe("▲up—no call▼down");
  });
  it("writes levels as bars + word and verdicts as glyph + word", () => {
    const { container } = render(
      <>
        <LevelTag level="Moderate" />
        <VerdictTag verdict="depends on your choices" />
        <VerdictTag verdict="no call" />
      </>,
    );
    expect(container.textContent).toContain("Moderate confidence (3 of 4)");
    expect(container.textContent).toContain("Depends on your choices");
    expect(container.textContent).toContain("No change called");
  });
});

describe("Textarea", () => {
  it("counts characters against the limit", () => {
    render(
      <Textarea
        aria-label="sentence"
        value={"LPS vs PBS"}
        maxLength={500}
        showCount
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("10 / 500")).toBeTruthy();
  });
});

describe("NeedsKey", () => {
  it("tells the person to open the printed link and how to restart", () => {
    const retry = vi.fn();
    render(
      <TooltipProvider>
        <NeedsKey onRetry={retry} />
      </TooltipProvider>,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Open the link qPilot printed in your terminal",
    );
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
