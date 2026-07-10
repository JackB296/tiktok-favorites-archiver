import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { gridMetrics, visibleRows } from "../lib/virtualGrid";
import type { GalleryDensity } from "../lib/virtualGrid";

const OVERSCAN_PX = 900;

function gridClassName(density: GalleryDensity) {
  return density === "compact"
    ? "grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10"
    : "grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5";
}

interface Layout {
  width: number;
  viewportWidth: number;
  scrollTop: number;
  gridTop: number;
  viewportHeight: number;
}

/**
 * A fixed-aspect responsive grid that only mounts rows near the scroll viewport.
 * The full-height spacer preserves normal scrollbar length and scroll position.
 */
export function VirtualGalleryGrid<T>({
  items, density, scrollRef, renderItem,
}: {
  items: T[];
  density: GalleryDensity;
  scrollRef: RefObject<HTMLDivElement>;
  renderItem: (item: T) => ReactNode;
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
      viewportWidth: window.innerWidth,
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

  const metrics = layout && layout.width > 0 ? gridMetrics(density, layout.width, layout.viewportWidth) : null;
  if (!metrics || !layout) return <div ref={gridRef} className={gridClassName(density)}>{items.map(renderItem)}</div>;

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
          <div key={row} className={`absolute left-0 w-full ${gridClassName(density)}`} style={{ top: `${row * metrics.rowStride}px` }}>
            {items.slice(first, first + metrics.columns).map(renderItem)}
          </div>
        );
      })}
    </div>
  );
}
