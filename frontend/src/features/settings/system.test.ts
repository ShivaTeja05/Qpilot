import { describe, expect, it } from "vitest";
import recorded from "@/features/home/recorded/system.json";
import { modelWords, providerWords, type ModelStatus } from "./system";

// The recorded answer of a launch with no model (QPILOT_MODEL_PROVIDER=none); the other states
// change only the status flags of that same answer.
const none = recorded.model as ModelStatus;
const configured: ModelStatus = {
  ...none,
  provider: "openai_compatible",
  model: "the-configured-model",
  configured: true,
  reason: null,
};

describe("modelWords", () => {
  it("says no model when none is configured", () => {
    expect(none.configured).toBe(false);
    expect(modelWords(none)).toMatchObject({ label: "no model", tone: "neutral", remote: false });
    expect(providerWords(none)).toBe("No model");
  });

  it("names a local model and whether it answers", () => {
    const w = modelWords({ ...configured, local: true, answers: true, available: true });
    expect(w).toMatchObject({
      label: "local the-configured-model",
      state: "answers",
      tone: "ok",
      pulse: false,
    });
  });

  it("says it is checking until the first answer", () => {
    const w = modelWords({ ...configured, local: true, answers: null, checking: true });
    expect(w).toMatchObject({ state: "checking whether it answers", pulse: true });
  });

  it("gives the reason when a configured model does not answer", () => {
    const w = modelWords({
      ...configured,
      local: true,
      answers: false,
      reason: "the endpoint refused the connection",
    });
    expect(w).toMatchObject({
      state: "configured but not answering",
      tone: "danger",
      reason: "the endpoint refused the connection",
    });
  });

  it("marks a remote model: names leave this machine only as pseudonyms", () => {
    const w = modelWords({ ...configured, provider: "anthropic", local: false, answers: true });
    expect(w).toMatchObject({ label: "REMOTE — names pseudonymised", remote: true });
    expect(providerWords({ ...configured, provider: "anthropic", local: false })).toBe(
      "Anthropic (a remote model)",
    );
  });

  it("says a wrong configuration is wrong, not merely absent", () => {
    const w = modelWords({
      ...none,
      misconfigured: true,
      reason: "QPILOT_MODEL_PROVIDER must be none, anthropic or openai_compatible",
    });
    expect(w).toMatchObject({
      label: "no model",
      state: "the model configuration is wrong",
      tone: "warn",
    });
  });
});
