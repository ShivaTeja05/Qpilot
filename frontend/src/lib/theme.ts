/**
 * The theme: the system's by default; "light" / "dark" saved per browser. `main.tsx` applies the
 * saved choice before the first paint; this hook changes it and tells every subscriber.
 */
import { useSyncExternalStore } from "react";

export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

const KEY = "qpilot.theme";
const listeners = new Set<() => void>();

function readChoice(): ThemeChoice {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "light" || t === "dark") return t;
  } catch {
    /* storage unavailable */
  }
  return "system";
}

let choice: ThemeChoice = typeof window === "undefined" ? "system" : readChoice();

const media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
media?.addEventListener?.("change", () => listeners.forEach((l) => l()));

function systemTheme(): Theme {
  return media?.matches ? "dark" : "light";
}

/** Set the theme for this browser (and apply it now). */
export function setTheme(next: ThemeChoice): void {
  choice = next;
  try {
    if (next === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  } catch {
    /* storage unavailable: this tab only */
  }
  if (next === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = next;
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** The saved choice and the theme in effect. */
export function useTheme(): { choice: ThemeChoice; theme: Theme; setTheme: typeof setTheme } {
  const snapshot = useSyncExternalStore(subscribe, () => `${choice}:${choice === "system" ? systemTheme() : choice}`);
  const [c, t] = snapshot.split(":") as [ThemeChoice, Theme];
  return { choice: c, theme: t, setTheme };
}
