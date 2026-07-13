export function activeFeedIndex(scrollTop: number, viewportHeight: number, itemCount: number): number;
export function feedTrimPlan(activeIndex: number, scrollTop: number, viewportHeight: number, keepBehind: number): {
  removeCount: number;
  restoredScrollTop: number;
};
export function nextWheelTargetIndex(activeIndex: number, pendingIndex: number, direction: number, itemCount: number): number;
export function shouldCommitWheelTarget(scrollTop: number, viewportHeight: number, targetIndex: number): boolean;
