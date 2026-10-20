/** Honest model states, recorded from the real API: not answering (and why), and what it saw. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import modelDown from "./__recorded__/ask-model-down.json";
import notAnswering from "./__recorded__/model-not-answering.json";
import none from "./__recorded__/model-none.json";
import seen from "./__recorded__/model-seen-shown.json";
import { Answer } from "./Answer";
import { ModelLine } from "./ModelLine";
import { ModelSaw } from "./ModelSaw";
import { TooltipProvider } from "@/ui";
import { toAskAnswer } from "./types";

const notAnsweringModel = notAnswering as Schemas["ModelStatus"];
const noneModel = none as Schemas["ModelStatus"];

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} })),
  );
  Element.prototype.scrollIntoView = () => {};
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("model states", () => {
  it("says the configured model is not answering, why, and that templates answer meanwhile", () => {
    render(<ModelLine model={notAnsweringModel} />);
    const line = screen.getByText(/is not answering/);
    expect(line.textContent).toContain(notAnsweringModel.model!);
    expect(line.textContent).toContain(notAnsweringModel.reason!);
    expect(screen.getByText(/Templates answer meanwhile/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Model settings" }).getAttribute("href")).toBe(
      "#/settings",
    );
  });

  it("shows why the template answered when the model was tried and failed", () => {
    render(<Answer answer={toAskAnswer(modelDown.result)!} links={{}} />);
    expect(screen.getByText(modelDown.result.note)).toBeTruthy();
    expect(screen.getByText(modelDown.result.writer_words)).toBeTruthy();
  });
});

describe("What the model saw", () => {
  function renderSaw(model: Schemas["ModelStatus"]) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(seen), { headers: { "content-type": "application/json" } }),
        ),
      ),
    );
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <ModelSaw workspaceKey="bc1d233e3866" model={model} asked={1} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
  }

  it("is folded until opened, then shows the exact payload with its hash", async () => {
    renderSaw(notAnsweringModel);
    const toggle = screen.getByRole("button", { name: /What the model saw/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    await screen.findByText(
      (_, el) => el?.tagName === "P" && el.textContent?.startsWith(seen.message) === true,
    );
    expect(vi.mocked(fetch).mock.calls[0]![0]).toBe("/api/model/seen?study=bc1d233e3866");
    const pre = document.querySelector("pre")!;
    expect(pre.textContent).toBe(seen.payload_text);
    expect(screen.getByRole("button", { name: "Copy the payload" })).toBeTruthy();
  });

  it("with no model configured and no call yet, says nothing is sent", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const empty = {
      state: "none",
      message: "No model call yet in this qPilot process.",
      interpreter: false,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify(empty)))),
    );
    render(
      <QueryClientProvider client={qc}>
        <ModelSaw workspaceKey="bc1d233e3866" model={noneModel} asked={0} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /What the model saw/ }));
    await screen.findByText(/No model is configured, so nothing is sent to one/);
  });
});
