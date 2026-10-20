/**
 * The robustness map (`@/charts` RobustnessMap) that glides from one analysis to the next: when
 * the timeline moves, every gene travels from where it was to where it is now and its call turns
 * over half-way, so the genes a decision moved are seen moving. Nothing moves under
 * `prefers-reduced-motion`: the map shows the new analysis at once.
 */
import { useEffect, useRef, useState } from "react";
import { RobustnessMap, type MapPoint, type RobustnessMapProps } from "@/charts";
import { useReducedMotion } from "@/lib/hooks";
import { tween } from "./model";

export const GLIDE_MS = 700;

export function AnimatedMap({
  points,
  duration = GLIDE_MS,
  ...props
}: Omit<RobustnessMapProps, "points"> & { points: MapPoint[]; duration?: number }) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState<MapPoint[]>(points);
  // what the map shows now (mid-glide too), so a new target starts from where the genes are
  const shownRef = useRef<MapPoint[]>(points);

  useEffect(() => {
    const from = shownRef.current;
    const show = (next: MapPoint[]) => {
      shownRef.current = next;
      setShown(next);
    };
    if (reduced || duration <= 0 || !from.length || from === points) {
      show(points);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      show(tween(from, points, t));
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [points, reduced, duration]);

  return <RobustnessMap points={shown} {...props} />;
}
