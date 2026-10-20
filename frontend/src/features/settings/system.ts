/**
 * What this install is (`GET /api/system`) and the model's status (`GET /api/model`), shared by
 * the Open screen and Settings, plus the model's status in the page's words (docs/studio.md:
 * none / local / REMOTE — names pseudonymised; answers / checking / not answering).
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "@/api/client";
import type { Tone } from "@/ui";

export type SystemView = Schemas["SystemView"];
export type ModelStatus = Schemas["ModelStatus"];
export type Autonomy = SystemView["autonomy"];

/** This install: version, method, model, autonomy, demo, policy lines (query key `["system"]`). */
export function useSystem() {
  return useQuery({
    queryKey: ["system"],
    queryFn: () => unwrap(api.GET("/api/system")),
  });
}

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

/** The provider in words. */
export function providerWords(m: ModelStatus): string {
  if (m.provider === "anthropic") return "Anthropic (a remote model)";
  if (m.provider === "openai_compatible")
    return m.local
      ? "A local model (OpenAI-compatible endpoint)"
      : "A remote model (OpenAI-compatible endpoint)";
  return "No model";
}

export interface ModelWords {
  /** The chip's text: `no model`, `local qwen2.5:7b`, `REMOTE — names pseudonymised`. */
  label: string;
  /** Whether the model answers, in words. */
  state: string;
  /** The dot's tone (meaning is also in `state`). */
  tone: Tone;
  /** The dot pulses while the server is still asking. */
  pulse: boolean;
  /** The server's reason when it does not answer or is misconfigured. */
  reason: string | null;
  /** True when a remote model is configured (names leave this machine as pseudonyms). */
  remote: boolean;
}

/** The model's status as the page says it (one place, so the chip and Settings agree). */
export function modelWords(m: ModelStatus): ModelWords {
  const reason = m.reason?.trim() || null;
  if (!m.configured) {
    return {
      label: "no model",
      state: m.misconfigured ? "the model configuration is wrong" : "the rules propose alone",
      tone: m.misconfigured ? "warn" : "neutral",
      pulse: false,
      reason,
      remote: false,
    };
  }
  const remote = !m.local;
  const label = remote ? "REMOTE — names pseudonymised" : `local ${m.model ?? m.provider}`;
  if (m.answers === true)
    return { label, state: "answers", tone: "ok", pulse: false, reason: null, remote };
  if (m.checking || m.answers == null) {
    return {
      label,
      state: "checking whether it answers",
      tone: "neutral",
      pulse: true,
      reason: null,
      remote,
    };
  }
  return {
    label,
    state: "configured but not answering",
    tone: "danger",
    pulse: false,
    reason,
    remote,
  };
}
