export type GallerySize = "s" | "m" | "l" | "xl";

export interface GridMetrics {
  columns: number;
  gap: number;
  cardWidth: number;
  cardHeight: number;
  rowStride: number;
}

/** Target card width (px), gap, and a floor on columns for each size step. The
    user picks a step; columns are then derived from the available width so the
    grid fills any screen — denser on a laptop, denser still on a 4K — instead of
    snapping to fixed breakpoints. */
const SIZE_STEPS: Record<GallerySize, { target: number; gap: number; minColumns: number }> = {
  s: { target: 150, gap: 8, minColumns: 3 },
  m: { target: 210, gap: 10, minColumns: 2 },
  l: { target: 300, gap: 12, minColumns: 2 },
  xl: { target: 420, gap: 14, minColumns: 2 },
};

function step(size: GallerySize) {
  return SIZE_STEPS[size] ?? SIZE_STEPS.m;
}

/** CSS columns for unmeasured/skeleton grids: let the browser pack the row. */
export function autoFillColumns(size: GallerySize): string {
  return `repeat(auto-fill, minmax(${step(size).target}px, 1fr))`;
}

/** A representative card width to use before the grid has been measured. */
export function sizeTarget(size: GallerySize): number {
  return step(size).target;
}

/** Fill the available width with as many portrait cards as the chosen size fits. */
export function gridMetrics(size: GallerySize, width: number): GridMetrics {
  const { target, gap, minColumns } = step(size);
  const columns = Math.max(minColumns, Math.floor((width + gap) / (target + gap)));
  const cardWidth = Math.max(0, (width - gap * (columns - 1)) / columns);
  const cardHeight = cardWidth * (16 / 9);
  return { columns, gap, cardWidth, cardHeight, rowStride: cardHeight + gap };
}

/** Return the half-open range of rows that must stay mounted. */
export function visibleRows({
  itemCount, columns, rowStride, scrollTop, viewportHeight, overscan,
}: {
  itemCount: number;
  columns: number;
  rowStride: number;
  scrollTop: number;
  viewportHeight: number;
  overscan: number;
}) {
  const count = Math.ceil(itemCount / columns);
  const start = Math.max(0, Math.floor((scrollTop - overscan) / rowStride));
  const end = Math.min(count, Math.ceil((scrollTop + viewportHeight + overscan) / rowStride));
  return { start: Math.min(start, count), end, count };
}

/** Guard the bottom observer so paging stays cursor-bounded and single-flight. */
export function canLoadNextPage(nextCursor: number | null, loading: boolean): nextCursor is number {
  return nextCursor !== null && !loading;
}
