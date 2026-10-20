/**
 * Requests that cross the shell and the sections, without prop drilling:
 *
 *   openAsk() / closeAsk() / useAskOpen()     the Ask drawer (⌘J)
 *   openPalette() / usePaletteOpen()          the command palette (⌘K)
 *   openShortcuts()                           the shortcut sheet (?)
 *   requestOpenFile() / useOpenFileRequest(cb)   ⌘O: Open (home) shows its file picker
 *   focusAction(label) / useFocusTarget(label)    the next-step banner's button focuses the
 *                                                 section's named action
 */
import { useEffect, useRef, useSyncExternalStore, type RefObject } from "react";

type Listener = () => void;

function store<T>(initial: T) {
  let value = initial;
  const listeners = new Set<Listener>();
  return {
    get: () => value,
    set: (next: T) => {
      if (Object.is(next, value)) return;
      value = next;
      listeners.forEach((l) => l());
    },
    subscribe: (l: Listener) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

const ask = store(false);
const palette = store(false);
const shortcuts = store(false);

export const openAsk = () => ask.set(true);
export const closeAsk = () => ask.set(false);
export const toggleAsk = () => ask.set(!ask.get());
export const setAskOpen = (open: boolean) => ask.set(open);
export function useAskOpen(): boolean {
  return useSyncExternalStore(ask.subscribe, ask.get);
}

export const openPalette = () => palette.set(true);
export const setPaletteOpen = (open: boolean) => palette.set(open);
export function usePaletteOpen(): boolean {
  return useSyncExternalStore(palette.subscribe, palette.get);
}

export const openShortcuts = () => shortcuts.set(true);
export const setShortcutsOpen = (open: boolean) => shortcuts.set(open);
export function useShortcutsOpen(): boolean {
  return useSyncExternalStore(shortcuts.subscribe, shortcuts.get);
}

// ---------------------------------------------------------------------------------------------
// ⌘O: open a file. The shell navigates to Open and raises the request; Open's drop zone
// subscribes and shows the file picker. A request raised before Open mounted is kept until
// it does (once).

const OPEN_FILE = "qpilot:open-file";
let pendingOpenFile = false;

export function requestOpenFile(): void {
  pendingOpenFile = true;
  window.dispatchEvent(new Event(OPEN_FILE));
}

/** Open (home) calls this with a function that opens its file picker. */
export function useOpenFileRequest(onRequest: () => void): void {
  const ref = useRef(onRequest);
  useEffect(() => {
    ref.current = onRequest;
  });
  useEffect(() => {
    const handle = () => {
      if (!pendingOpenFile) return;
      pendingOpenFile = false;
      ref.current();
    };
    window.addEventListener(OPEN_FILE, handle);
    handle();
    return () => window.removeEventListener(OPEN_FILE, handle);
  }, []);
}

// ---------------------------------------------------------------------------------------------
// The next step's button: go to the section, then focus the control named by the action.

const FOCUS = "qpilot:focus-action";
let pendingFocus: string | null = null;

const norm = (s: string) => s.trim().toLowerCase().replace(/[…."]/g, "");

/**
 * Focus the control for `label` once the section shows it: an element registered with
 * {@link useFocusTarget}, else an element with `data-action="<label>"`, else a button whose
 * text starts with the label. Gives up quietly after two seconds.
 */
export function focusAction(label: string | null | undefined): void {
  if (!label) return;
  pendingFocus = label;
  window.dispatchEvent(new CustomEvent(FOCUS, { detail: label }));
  const started = Date.now();
  const tryFocus = () => {
    if (pendingFocus !== label) return;
    const main = document.getElementById("main");
    const want = norm(label);
    const el =
      main?.querySelector<HTMLElement>(`[data-action="${CSS.escape(label)}"]`) ??
      Array.from(main?.querySelectorAll<HTMLElement>("button, a[href]") ?? []).find((b) =>
        norm(b.textContent ?? "").startsWith(want),
      );
    if (el && !el.hasAttribute("disabled")) {
      pendingFocus = null;
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      el.focus({ preventScroll: true });
      return;
    }
    if (Date.now() - started < 2000) setTimeout(tryFocus, 120);
    else pendingFocus = null;
  };
  setTimeout(tryFocus, 60);
}

/** Register an element as the target of a next-step action (e.g. "Decide", "Propose the design"). */
export function useFocusTarget(label: string, ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const handle = (e: Event) => {
      if (norm(String((e as CustomEvent).detail)) !== norm(label) || !ref.current) return;
      pendingFocus = null;
      ref.current.scrollIntoView({ block: "center", behavior: "smooth" });
      ref.current.focus({ preventScroll: true });
    };
    window.addEventListener(FOCUS, handle);
    if (pendingFocus && norm(pendingFocus) === norm(label))
      handle(new CustomEvent(FOCUS, { detail: pendingFocus }));
    return () => window.removeEventListener(FOCUS, handle);
  }, [label, ref]);
}
