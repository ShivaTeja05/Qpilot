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

const media =
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

function systemTheme(): Theme {
  return media?.matches ? "dark" : "light";
}

/**
 * Put the theme in effect on <html data-theme>, also when it follows the system, so the
 * `dark:` variant (which reads data-theme) and the tokens always agree.
 */
function apply(): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = choice === "system" ? systemTheme() : choice;
}

apply();
media?.addEventListener?.("change", () => {
  apply();
  listeners.forEach((l) => l());
});

/** Set the theme for this browser (and apply it now). */
export function setTheme(next: ThemeChoice): void {
  choice = next;
  try {
    if (next === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  } catch {
    /* storage unavailable: this tab only */
  }
  apply();
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** The saved choice and the theme in effect. */
export function useTheme(): { choice: ThemeChoice; theme: Theme; setTheme: typeof setTheme } {
  const snapshot = useSyncExternalStore(
    subscribe,
    () => `${choice}:${choice === "system" ? systemTheme() : choice}`,
  );
  const [c, t] = snapshot.split(":") as [ThemeChoice, Theme];
  return { choice: c, theme: t, setTheme };
}
