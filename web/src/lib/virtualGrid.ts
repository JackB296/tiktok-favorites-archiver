export type GalleryDensity = "compact" | "comfortable";

export interface GridMetrics {
  columns: number;
  gap: number;
  cardHeight: number;
  rowStride: number;
}

/** Match the Gallery's responsive Tailwind grid without needing a layout library. */
export function gridMetrics(density: GalleryDensity, width: number, viewportWidth = width): GridMetrics {
  const compact = density === "compact";
  let columns = compact ? 3 : 2;
  if (viewportWidth >= 1280 && compact) columns = 10;
  else if (viewportWidth >= 1024) columns = compact ? 8 : 5;
  else if (viewportWidth >= 768) columns = compact ? 6 : 4;
  else if (viewportWidth >= 640) columns = compact ? 4 : 3;

  const gap = compact ? 8 : 12;
  const cardWidth = Math.max(0, (width - gap * (columns - 1)) / columns);
  const cardHeight = cardWidth * (16 / 9);
  return { columns, gap, cardHeight, rowStride: cardHeight + gap };
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
