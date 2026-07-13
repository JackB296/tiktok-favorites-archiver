import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { gridMetrics, visibleRows, autoFillColumns, sizeTarget } from "../lib/virtualGrid";
import type { GallerySize } from "../lib/virtualGrid";

const OVERSCAN_PX = 900;

interface Layout {
  width: number;
  scrollTop: number;
  gridTop: number;
  viewportHeight: number;
}

/**
 * A fixed-aspect responsive grid that only mounts rows near the scroll viewport.
 * The full-height spacer preserves normal scrollbar length and scroll position.
 * Each rendered card is handed its measured width so overlay text can scale with it.
 */
export function VirtualGalleryGrid<T>({
  items, size, scrollRef, renderItem,
}: {
  items: T[];
  size: GallerySize;
  scrollRef: RefObject<HTMLDivElement>;
  renderItem: (item: T, cardWidth: number) => ReactNode;
}) {
  const gridRef = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<Layout | null>(null);

  const measure = useCallback(() => {
    const scroller = scrollRef.current;
    const grid = gridRef.current;
    if (!scroller || !grid) return;
    const gridRect = grid.getBoundingClientRect();
    const scrollRect = scroller.getBoundingClientRect();
    const next = {
      width: grid.clientWidth,
      scrollTop: scroller.scrollTop,
      gridTop: gridRect.top - scrollRect.top + scroller.scrollTop,
      viewportHeight: scroller.clientHeight,
    };
    setLayout((current) => current && Object.entries(next).every(([key, value]) => current[key as keyof Layout] === value) ? current : next);
  }, [scrollRef]);

  // The grid moves when filters expand/collapse, so measure after each Gallery render.
  useLayoutEffect(() => { measure(); });

  useEffect(() => {
    const scroller = scrollRef.current;
    const grid = gridRef.current;
    if (!scroller || !grid) return;
    const observer = new ResizeObserver(measure);
    observer.observe(scroller);
    observer.observe(grid);
    scroller.addEventListener("scroll", measure, { passive: true });
    return () => {
      observer.disconnect();
      scroller.removeEventListener("scroll", measure);
    };
  }, [measure, scrollRef]);

  const metrics = layout && layout.width > 0 ? gridMetrics(size, layout.width) : null;
  if (!metrics || !layout) {
    return (
      <div ref={gridRef} style={{ display: "grid", gap: "12px", gridTemplateColumns: autoFillColumns(size) }}>
        {items.map((item) => renderItem(item, sizeTarget(size)))}
      </div>
    );
  }

  const rows = visibleRows({
    itemCount: items.length,
    columns: metrics.columns,
    rowStride: metrics.rowStride,
    scrollTop: Math.max(0, layout.scrollTop - layout.gridTop),
    viewportHeight: layout.viewportHeight,
    overscan: OVERSCAN_PX,
  });
  const totalHeight = Math.max(0, rows.count * metrics.rowStride - metrics.gap);

  return (
    <div ref={gridRef} role="list" className="relative w-full" style={{ height: `${totalHeight}px` }}>
      {Array.from({ length: rows.end - rows.start }, (_, offset) => rows.start + offset).map((row) => {
        const first = row * metrics.columns;
        return (
          <div
            key={row}
            className="absolute left-0 w-full"
            style={{
              top: `${row * metrics.rowStride}px`,
              display: "grid",
              gridTemplateColumns: `repeat(${metrics.columns}, minmax(0, 1fr))`,
              gap: `${metrics.gap}px`,
            }}
          >
            {items.slice(first, first + metrics.columns).map((item) => renderItem(item, metrics.cardWidth))}
          </div>
        );
      })}
    </div>
  );
}
