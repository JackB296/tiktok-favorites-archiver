export const LOADING_DELAY_MS = 250;
export const MINIMUM_INDICATOR_MS = 400;
export type LoadingPhase = "quiet" | "indicator" | "content";

export function loadingPhase(loading: boolean, requestElapsed: number, indicatorElapsed: number | null): LoadingPhase {
  if (!loading && indicatorElapsed == null) return "content";
  if (loading && requestElapsed < LOADING_DELAY_MS) return "quiet";
  if (indicatorElapsed != null && indicatorElapsed < MINIMUM_INDICATOR_MS) return "indicator";
  return loading ? "indicator" : "content";
}
