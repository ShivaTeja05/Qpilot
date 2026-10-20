/** Small hooks the shell and the sections share. */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

/** Whether a media query matches (re-renders on change). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** True when the person asked the system for less motion. */
export function useReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

/** True when focus is in a field where typed keys are text, not shortcuts. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (el as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit", "range"].includes(type);
  }
  return Boolean(el.closest?.("[role='dialog'] input, [cmdk-root]"));
}

/**
 * Keyboard shortcuts. Keys are single keys (`?`, `j`, `[`), modified keys (`mod+k`: ⌘ on a Mac,
 * Ctrl elsewhere) or two-key sequences (`g d`). Ignored while typing in a field.
 */
export function useHotkeys(bindings: Record<string, (e: KeyboardEvent) => void>, enabled = true): void {
  const ref = useRef(bindings);
  useEffect(() => {
    ref.current = bindings;
  });
  useEffect(() => {
    if (!enabled) return;
    let pending: string | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      const mod = e.metaKey || e.ctrlKey;
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const map = ref.current;
      if (mod) {
        const handler = map[`mod+${key}`];
        if (handler) {
          e.preventDefault();
          handler(e);
        }
        return;
      }
      if (e.altKey || isTyping(e.target)) return;
      const k = e.key.length === 1 ? e.key : key;
      if (pending) {
        const handler = map[`${pending} ${k}`];
        pending = null;
        clearTimeout(timer);
        if (handler) {
          e.preventDefault();
          handler(e);
          return;
        }
      }
      if (Object.keys(map).some((b) => b.startsWith(`${k} `))) {
        pending = k;
        clearTimeout(timer);
        timer = setTimeout(() => (pending = null), 1200);
        return;
      }
      const handler = map[k];
      if (handler) {
        e.preventDefault();
        handler(e);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(timer);
    };
  }, [enabled]);
}

/** A ticking clock (ms), for elapsed times and "2 min ago" labels. */
export function useNow(intervalMs = 1000, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
  return now;
}

/** The modifier key's symbol on this platform (⌘ on a Mac, Ctrl elsewhere). */
export const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";
