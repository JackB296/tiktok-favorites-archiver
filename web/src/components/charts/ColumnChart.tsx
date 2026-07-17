/** Single-series column chart (magnitude per bucket). Columns cap at 24px,
 * 4px rounded cap, square baseline, ≥2px gaps; each column's full band is the
 * hover/focus hit target. One series — no legend. */
import { useState } from "react";
import { axisTicks, formatCount } from "../../lib/statsPresentation";
import { ChartTip, useMeasuredWidth } from "./common";
import type { TipState } from "./common";

const HEIGHT = 190;
const PAD = { top: 12, right: 8, bottom: 22, left: 44 };
const MAX_BAR = 24;

export function ColumnChart({ labels, values, tipTitle, formatValue = formatCount }: {
  labels: string[];
  values: number[];
  tipTitle?: (index: number) => string;
  formatValue?: (value: number) => string;
}) {
  const [ref, width] = useMeasuredWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  const innerW = Math.max(width - PAD.left - PAD.right, 0);
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const max = Math.max(...values, 0);
  const ticks = axisTicks(max);
  const yMax = ticks[ticks.length - 1] || 1;
  const n = values.length;

  const band = n ? innerW / n : 0;
  const barW = Math.min(MAX_BAR, Math.max(band - 2, 1));
  const xMid = (i: number) => PAD.left + band * i + band / 2;
  const yTop = (v: number) => PAD.top + innerH - (v / yMax) * innerH;

  /** Column with a 4px rounded cap and a square baseline. */
  function columnPath(i: number, v: number): string {
    const left = xMid(i) - barW / 2;
    const top = yTop(v);
    const bottom = PAD.top + innerH;
    const r = Math.min(4, barW / 2, Math.max(bottom - top, 0));
    return [
      `M${left},${bottom}`,
      `L${left},${top + r}`,
      `Q${left},${top} ${left + r},${top}`,
      `L${left + barW - r},${top}`,
      `Q${left + barW},${top} ${left + barW},${top + r}`,
      `L${left + barW},${bottom}`,
      "Z",
    ].join("");
  }

  function show(i: number) {
    setHover(i);
    setTip({
      x: xMid(i),
      y: yTop(values[i]),
      value: formatValue(values[i]),
      title: tipTitle ? tipTitle(i) : labels[i],
    });
  }
  function hide() {
    setHover(null);
    setTip(null);
  }

  // A handful of buckets (histogram) always shows every label; long month
  // axes thin out to what the width can fit.
  const sparseEvery = n <= 8 ? 1 : Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 76))));

  return (
    <div ref={ref} className="relative">
      {width > 0 && n > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={`Column chart, ${n} buckets, peak ${formatValue(max)}`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={yTop(t)} y2={yTop(t)} stroke="var(--line)" strokeWidth={1} />
              <text x={PAD.left - 6} y={yTop(t) + 3} textAnchor="end" className="tabular" fontSize={10} fill="var(--ink-faint)">
                {formatCount(t)}
              </text>
            </g>
          ))}
          {labels.map((label, i) =>
            i % sparseEvery === 0 ? (
              <text key={`${label}-${i}`} x={xMid(i)} y={HEIGHT - 6} textAnchor="middle" fontSize={10} fill="var(--ink-faint)">
                {label}
              </text>
            ) : null,
          )}
          {values.map((v, i) => (
            <path key={i} d={columnPath(i, v)} fill="var(--chart-mark)" opacity={hover === null || hover === i ? 1 : 0.55} />
          ))}
          {/* Hit layer: the whole band, well past the painted pixels. */}
          {values.map((_, i) => (
            <rect
              key={`hit-${i}`}
              x={PAD.left + band * i}
              y={PAD.top}
              width={band}
              height={innerH}
              fill="transparent"
              tabIndex={0}
              aria-label={`${tipTitle ? tipTitle(i) : labels[i]}: ${formatValue(values[i])}`}
              onPointerMove={() => show(i)}
              onFocus={() => show(i)}
              onPointerLeave={hide}
              onBlur={hide}
            />
          ))}
        </svg>
      )}
      <ChartTip tip={tip} width={width} />
    </div>
  );
}
