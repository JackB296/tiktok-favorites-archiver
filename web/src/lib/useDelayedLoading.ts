import { useEffect, useRef, useState } from "react";
import { loadingPhase, LOADING_DELAY_MS, MINIMUM_INDICATOR_MS } from "./loadingPresentation";
import type { LoadingPhase } from "./loadingPresentation";

/** Avoid flashing a loading indicator for fast requests; stabilize it once shown. */
export function useDelayedLoading(loading: boolean): LoadingPhase {
  const [phase, setPhase] = useState<LoadingPhase>(() => loadingPhase(loading, 0, null));
  const phaseRef = useRef(phase);
  const indicatorShownAt = useRef<number | null>(null);
  phaseRef.current = phase;

  useEffect(() => {
    if (loading) {
      indicatorShownAt.current = null;
      setPhase(loadingPhase(true, 0, null));
      const timer = window.setTimeout(() => {
        indicatorShownAt.current = Date.now();
        setPhase(loadingPhase(true, LOADING_DELAY_MS, 0));
      }, LOADING_DELAY_MS);
      return () => window.clearTimeout(timer);
    }

    const shownFor = indicatorShownAt.current == null ? null : Date.now() - indicatorShownAt.current;
    if (phaseRef.current === "indicator" && shownFor != null && shownFor < MINIMUM_INDICATOR_MS) {
      const timer = window.setTimeout(() => {
        indicatorShownAt.current = null;
        setPhase(loadingPhase(false, 0, MINIMUM_INDICATOR_MS));
      }, MINIMUM_INDICATOR_MS - shownFor);
      return () => window.clearTimeout(timer);
    }
    indicatorShownAt.current = null;
    setPhase(loadingPhase(false, 0, null));
  }, [loading]);

  return phase;
}
