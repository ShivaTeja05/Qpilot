/** Hooks the charts share: measured width, the tooltip, keyboard movement between marks. */
import { useCallback, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

/** The element's content width, kept current with a ResizeObserver (jsdom: the fallback). */
export function useWidth<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = Math.floor(el.clientWidth);
      setWidth(w > 0 ? Math.max(260, w) : fallback);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, width] as const;
}

/** What a tooltip says: the value leads, the name and context follow. */
export interface TipContent {
  title: string;
  value?: string;
  lines?: (string | false | null | undefined)[];
}

export interface Tip {
  /** Anchor in the chart's pixel space (the SVG is drawn 1:1 with CSS pixels). */
  x: number;
  y: number;
  content: TipContent;
}

export function useTip() {
  const [tip, setTip] = useState<Tip | null>(null);
  const show = useCallback(
    (x: number, y: number, content: TipContent) => setTip({ x, y, content }),
    [],
  );
  const hide = useCallback(() => setTip(null), []);
  return { tip, show, hide };
}

/**
 * Keyboard movement between a chart's marks: one tab stop for the whole chart, arrows (or j/k) move,
 * Home/End jump, Enter opens, Escape leaves. `count` marks are in reading order.
 */
export function usePointNav(count: number, onActivate?: (index: number) => void) {
  const [active, setActive] = useState<number | null>(null);
  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (count === 0) return;
      const cur = active ?? -1;
      let next: number | null = null;
      switch (e.key) {
        case "ArrowRight":
        case "ArrowDown":
          next = Math.min(count - 1, cur + 1);
          break;
        case "ArrowLeft":
        case "ArrowUp":
          next = cur < 0 ? 0 : Math.max(0, cur - 1);
          break;
        case "Home":
          next = 0;
          break;
        case "End":
          next = count - 1;
          break;
        case "Enter":
        case " ":
          if (active != null && onActivate) {
            e.preventDefault();
            onActivate(active);
          }
          return;
        case "Escape":
          setActive(null);
          return;
        default:
          return;
      }
      e.preventDefault();
      setActive(next);
    },
    [active, count, onActivate],
  );
  const onBlur = useCallback(() => setActive(null), []);
  // Keep the index inside the data when the data shrinks.
  const safe = active != null && active < count ? active : null;
  return { active: safe, setActive, onKeyDown, onBlur };
}
