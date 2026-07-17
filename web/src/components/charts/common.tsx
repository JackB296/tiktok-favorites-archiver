/** Shared chart plumbing: container measurement and the hover tooltip.
 * Mark specs follow the dataviz method: 2px lines, ≤24px bars with 4px
 * rounded data-ends, hairline solid gridlines, text in ink tokens (never the
 * series color), and a hover layer on every plot. */
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

export function useMeasuredWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setWidth((prev) => (Math.abs(prev - w) < 1 ? prev : w));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

export interface TipState {
  x: number; // px within the chart container
  y: number;
  title: string;
  value: string;
  detail?: string;
}

/** One tooltip per chart: value leads (strong), label follows (dim). */
export function ChartTip({ tip, width }: { tip: TipState | null; width: number }) {
  if (!tip) return null;
  const clampedX = Math.max(8, Math.min(tip.x, width - 8));
  const flip = clampedX > width * 0.62;
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 -translate-y-full rounded-[var(--radius-control)] border border-line bg-elevated px-2.5 py-1.5 shadow-lg"
      style={{ left: clampedX, top: Math.max(tip.y - 8, 0), transform: `translate(${flip ? "-100%" : "0"}, -100%)` }}
    >
      <p className="whitespace-nowrap text-sm font-semibold text-ink">{tip.value}</p>
      <p className="whitespace-nowrap text-xs text-ink-dim">{tip.title}</p>
      {tip.detail && <p className="whitespace-nowrap text-xs text-ink-faint">{tip.detail}</p>}
    </div>
  );
}

/** Chart card: title + one-line caption saying what the chart answers. */
export function ChartCard({ title, caption, children, note }: {
  title: string;
  caption: string;
  children: ReactNode;
  note?: string;
}) {
  return (
    <section className="rounded-[var(--radius-media)] border border-line bg-surface p-4">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      <p className="mt-0.5 text-xs text-ink-dim">{caption}</p>
      <div className="mt-3">{children}</div>
      {note && <p className="mt-2 text-xs text-ink-faint">{note}</p>}
    </section>
  );
}
