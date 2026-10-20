/** The question box: Enter sends, Shift+Enter does not, ↑ recalls earlier questions, ↓ comes back. */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

afterEach(cleanup);

function box(): HTMLTextAreaElement {
  return screen.getByLabelText("Your question about this study");
}

function type(text: string) {
  fireEvent.change(box(), { target: { value: text } });
}

describe("Composer", () => {
  it("sends on Enter and clears the box", () => {
    const onSend = vi.fn(() => true);
    render(<Composer onSend={onSend} recall={[]} />);
    type("  Is the result robust?  ");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Is the result robust?");
    expect(box().value).toBe("");
  });

  it("keeps the text when Shift+Enter is pressed or sending is refused", () => {
    const onSend = vi.fn(() => false);
    render(<Composer onSend={onSend} recall={[]} />);
    type("first line");
    fireEvent.keyDown(box(), { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(box().value).toBe("first line");
  });

  it("does not send an empty question, and the Ask button is disabled", () => {
    const onSend = vi.fn(() => true);
    render(<Composer onSend={onSend} recall={[]} />);
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("recalls earlier questions with ↑ and returns to the draft with ↓", () => {
    render(<Composer onSend={() => true} recall={["newest question", "older question"]} />);
    type("");
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().value).toBe("newest question");
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().value).toBe("older question");
    // No older one: stays.
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().value).toBe("older question");
    box().setSelectionRange(box().value.length, box().value.length);
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(box().value).toBe("newest question");
    box().setSelectionRange(box().value.length, box().value.length);
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(box().value).toBe("");
  });

  it("limits a question to 500 characters and says how many are used", () => {
    render(<Composer onSend={() => true} recall={[]} />);
    expect(box().maxLength).toBe(500);
    type("abc");
    expect(screen.getByText(/3 \/ 500/)).toBeTruthy();
  });
});
