/**
 * The model's status (`GET /api/model`) for the Open screen and Settings. What this install is
 * (`GET /api/system`) comes from the shell's `useSystem`; the chip's words from the shell's
 * `modelChip`, so the top bar, the Open screen and Settings say the same thing.
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";

export type ModelStatus = Schemas["ModelStatus"];
export type Autonomy = Schemas["SystemView"]["autonomy"];

/**
 * The model's status alone (`["system", "model"]`, so a settings change refreshes it too). While
 * the server is still asking the model its one-token question, look again every few seconds.
 */
export function useModelStatus(initial?: ModelStatus) {
  return useQuery({
    queryKey: ["system", "model"],
    queryFn: () => unwrap(api.GET("/api/model")),
    initialData: initial,
    refetchInterval: (q) => (q.state.data?.checking ? 3000 : false),
  });
}

/** The provider in words (from the environment: none, a local endpoint, Anthropic). */
export function providerWords(m: ModelStatus): string {
  if (m.provider === "anthropic") return "Anthropic (a remote model)";
  if (m.provider === "openai_compatible")
    return m.local
      ? "A local model (OpenAI-compatible endpoint)"
      : "A remote model (OpenAI-compatible endpoint)";
  return "No model";
}

/** What leaves this machine when the model is asked, in words. */
export function namesWords(m: ModelStatus): string {
  if (!m.configured) return "Nothing: no model is called.";
  return m.local
    ? `Sample names go only to this local endpoint, ${m.sample_names}.`
    : `Sample names are ${m.sample_names}.`;
}
