/** Single-series area chart (change over time). 2px line, ~10% fill wash,
 * crosshair that snaps to the nearest x, one tooltip. No legend: one series —
 * the card title names it. */
import { useState } from "react";
import { axisTicks, formatCount } from "../../lib/statsPresentation";
import { ChartTip, useMeasuredWidth } from "./common";
import type { TipState } from "./common";

const HEIGHT = 200;
const PAD = { top: 12, right: 12, bottom: 22, left: 44 };

export function AreaChart({ labels, values, tipTitle }: {
  labels: string[];
  values: number[];
  /** Tooltip title per point, defaults to the label. */
  tipTitle?: (index: number) => string;
}) {
  const [ref, width] = useMeasuredWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);

  const innerW = Math.max(width - PAD.left - PAD.right, 0);
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const max = Math.max(...values, 0);
  const ticks = axisTicks(max);
  const yMax = ticks[ticks.length - 1] || 1;
  const n = values.length;

  const x = (i: number) => PAD.left + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - (v / yMax) * innerH;

  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = n
    ? `${line}L${x(n - 1).toFixed(1)},${(PAD.top + innerH).toFixed(1)}L${x(0).toFixed(1)},${(PAD.top + innerH).toFixed(1)}Z`
    : "";

  function nearestIndex(px: number): number {
    if (n <= 1) return 0;
    const t = (px - PAD.left) / innerW;
    return Math.max(0, Math.min(n - 1, Math.round(t * (n - 1))));
  }

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!n) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const i = nearestIndex(e.clientX - rect.left);
    setHoverX(x(i));
    setTip({
      x: x(i),
      y: y(values[i]),
      value: formatCount(values[i]),
      title: tipTitle ? tipTitle(i) : labels[i],
    });
  }

  const sparseEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 76))));

  return (
    <div ref={ref} className="relative">
      {width > 0 && n > 0 && (
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`Area chart, ${n} points, peak ${formatCount(max)}`}
          onPointerMove={onMove}
          onPointerLeave={() => { setTip(null); setHoverX(null); }}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
              <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" className="tabular" fontSize={10} fill="var(--ink-faint)">
                {formatCount(t)}
              </text>
            </g>
          ))}
          {labels.map((label, i) =>
            i % sparseEvery === 0 ? (
              <text key={label} x={x(i)} y={HEIGHT - 6} textAnchor="middle" fontSize={10} fill="var(--ink-faint)">
                {label}
              </text>
            ) : null,
          )}
          <path d={area} fill="var(--chart-mark)" opacity={0.1} />
          <path d={line} fill="none" stroke="var(--chart-mark)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hoverX !== null && (
            <line x1={hoverX} x2={hoverX} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--ink-faint)" strokeWidth={1} />
          )}
          {tip && (
            <circle cx={tip.x} cy={tip.y} r={4} fill="var(--chart-mark)" stroke="var(--surface)" strokeWidth={2} />
          )}
        </svg>
      )}
      <ChartTip tip={tip} width={width} />
    </div>
  );
}
