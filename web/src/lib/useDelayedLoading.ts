import { useEffect, useRef, useState } from "react";
import { loadingStep } from "./loadingPresentation";
import type { LoadingPhase } from "./loadingPresentation";

/** Avoid flashing a loading indicator for fast requests; stabilize it once shown.
    The timing policy lives in loadingStep (lib/loadingPresentation.ts); this hook
    only wires its schedule to real timers. */
export function useDelayedLoading(loading: boolean): LoadingPhase {
  const [phase, setPhase] = useState<LoadingPhase>(() => loadingStep(loading, "content", null).phase);
  const phaseRef = useRef(phase);
  const indicatorShownAt = useRef<number | null>(null);
  phaseRef.current = phase;

  useEffect(() => {
    const shownFor = indicatorShownAt.current == null ? null : Date.now() - indicatorShownAt.current;
    const step = loadingStep(loading, phaseRef.current, shownFor);
    setPhase(step.phase);
    if (!step.timer) {
      indicatorShownAt.current = null;
      return;
    }
    if (loading) indicatorShownAt.current = null;
    const next = step.timer.phase;
    const timer = window.setTimeout(() => {
      indicatorShownAt.current = next === "indicator" ? Date.now() : null;
      setPhase(next);
    }, step.timer.afterMs);
    return () => window.clearTimeout(timer);
  }, [loading]);

  return phase;
}
