export const LOADING_DELAY_MS = 250;
export const MINIMUM_INDICATOR_MS = 400;
export type LoadingPhase = "quiet" | "indicator" | "content";

export interface LoadingStep {
  /** What to show right now. */
  phase: LoadingPhase;
  /** The transition to schedule next, or null when the phase is settled. */
  timer: { afterMs: number; phase: LoadingPhase } | null;
}

/** Pure timer choreography for the delayed loading indicator: a request stays
    "quiet" until it has run for LOADING_DELAY_MS (fast responses never flash a
    spinner), and once the indicator is shown it holds for MINIMUM_INDICATOR_MS
    so it never blinks. `indicatorShownFor` is how long the indicator has been
    visible so far, or null when it never appeared. The caller applies `phase`
    immediately and runs `timer.phase` after `timer.afterMs`. */
export function loadingStep(loading: boolean, currentPhase: LoadingPhase, indicatorShownFor: number | null): LoadingStep {
  if (loading) return { phase: "quiet", timer: { afterMs: LOADING_DELAY_MS, phase: "indicator" } };
  if (currentPhase === "indicator" && indicatorShownFor != null && indicatorShownFor < MINIMUM_INDICATOR_MS) {
    return { phase: "indicator", timer: { afterMs: MINIMUM_INDICATOR_MS - indicatorShownFor, phase: "content" } };
  }
  return { phase: "content", timer: null };
}
