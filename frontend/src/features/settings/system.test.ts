import { describe, expect, it } from "vitest";
import recorded from "@/features/home/recorded/system.json";
import { namesWords, policyParts, providerWords, type ModelStatus } from "./system";

// The recorded answer of a launch with no model (QPILOT_MODEL_PROVIDER=none); the other cases
// change only the provider flags of that same answer.
const none = recorded.model as ModelStatus;

describe("providerWords", () => {
  it("says no model when none is configured", () => {
    expect(none.configured).toBe(false);
    expect(providerWords(none)).toBe("No model");
    expect(namesWords(none)).toBe("Nothing: no model is called.");
  });

  it("tells a local endpoint from a remote one", () => {
    const local = { ...none, provider: "openai_compatible", configured: true, local: true };
    expect(providerWords(local)).toBe("A local model (OpenAI-compatible endpoint)");
    expect(providerWords({ ...local, local: false })).toBe(
      "A remote model (OpenAI-compatible endpoint)",
    );
    expect(providerWords({ ...local, provider: "anthropic", local: false })).toBe(
      "Anthropic (a remote model)",
    );
  });

  it("says where sample names go, in the server's words", () => {
    const local = { ...none, provider: "openai_compatible", configured: true, local: true };
    expect(namesWords(local)).toBe(
      `Sample names go only to this local endpoint, ${none.sample_names}.`,
    );
  });
});

describe("policyParts", () => {
  it("splits each served policy line into its level and its rule", () => {
    const parts = recorded.policy.map(policyParts);
    expect(parts.map(([head]) => head)).toEqual(["Automatic", "Agent may apply", "Human only"]);
    expect(parts[2]?.[1]).toBe(recorded.policy[2]!.slice("Human only: ".length));
  });

  it("keeps a line without a level whole", () => {
    expect(policyParts("No colon here")).toEqual([null, "No colon here"]);
  });
});
