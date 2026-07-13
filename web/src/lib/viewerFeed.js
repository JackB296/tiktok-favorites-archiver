/** Return the card nearest the viewport snap point. */
export function activeFeedIndex(scrollTop, viewportHeight, itemCount) {
  if (!itemCount || viewportHeight <= 0) return 0;
  return Math.max(0, Math.min(itemCount - 1, Math.round(scrollTop / viewportHeight)));
}

/** Plan a bounded feed trim while preserving the same visible Favorite. */
export function feedTrimPlan(activeIndex, scrollTop, viewportHeight, keepBehind) {
  const removeCount = Math.max(0, activeIndex - keepBehind);
  return {
    removeCount,
    restoredScrollTop: Math.max(0, scrollTop - removeCount * viewportHeight),
  };
}

/** Advance from the latest requested snap target, not the animation's stale visible card. */
export function nextWheelTargetIndex(activeIndex, pendingIndex, direction, itemCount) {
  if (!itemCount) return 0;
  const base = pendingIndex >= 0 ? pendingIndex : Math.max(0, activeIndex);
  return Math.max(0, Math.min(itemCount - 1, base + (direction < 0 ? -1 : 1)));
}

/** Handoff playback only when the smooth scroll is effectively at its destination. */
export function shouldCommitWheelTarget(scrollTop, viewportHeight, targetIndex) {
  if (viewportHeight <= 0 || targetIndex < 0) return false;
  return Math.abs(scrollTop - targetIndex * viewportHeight) <= viewportHeight * 0.08;
}
