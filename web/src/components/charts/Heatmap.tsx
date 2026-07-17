/** Day-of-week × hour heatmap. Sequential coral ramp (validated per theme);
 * empty cells stay on the elevated surface so zero reads as absence, not as
 * the lowest magnitude. Each cell is its own hover target. */
import { useState } from "react";
import { DOW_LABELS, formatCount, rampStep } from "../../lib/statsPresentation";
import { ChartTip, useMeasuredWidth } from "./common";
import type { TipState } from "./common";

const CELL_GAP = 2;
const LEFT = 34;
const TOP = 4;
const BOTTOM = 18;
const RAMP = ["var(--chart-ramp-1)", "var(--chart-ramp-2)", "var(--chart-ramp-3)", "var(--chart-ramp-4)", "var(--chart-ramp-5)"];

export function Heatmap({ grid, max }: { grid: number[][]; max: number }) {
  const [ref, width] = useMeasuredWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);

  const innerW = Math.max(width - LEFT, 0);
  const cell = Math.max((innerW - 23 * CELL_GAP) / 24, 4);
  const rowH = cell + CELL_GAP;
  const height = TOP + 7 * rowH + BOTTOM;

  const hourLabel = (h: number) => (h === 0 ? "12am" : h === 12 ? "12pm" : h < 12 ? `${h}am` : `${h - 12}pm`);

  function show(dow: number, hour: number, x: number, y: number) {
    setTip({
      x,
      y,
      value: formatCount(grid[dow][hour]),
      title: `${DOW_LABELS[dow]} ${hourLabel(hour)}`,
      detail: "favorites saved",
    });
  }

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Favoriting activity by day and hour; busiest cell has ${formatCount(max)} favorites`}
          onPointerLeave={() => setTip(null)}
        >
          {DOW_LABELS.map((label, dow) => (
            <text key={label} x={LEFT - 8} y={TOP + dow * rowH + cell / 2 + 3} textAnchor="end" fontSize={10} fill="var(--ink-faint)">
              {label}
            </text>
          ))}
          {[0, 6, 12, 18].map((h) => (
            <text key={h} x={LEFT + h * (cell + CELL_GAP) + cell / 2} y={height - 4} textAnchor="middle" fontSize={10} fill="var(--ink-faint)">
              {hourLabel(h)}
            </text>
          ))}
          {grid.map((row, dow) =>
            row.map((count, hour) => {
              const step = rampStep(count, max, RAMP.length);
              const x = LEFT + hour * (cell + CELL_GAP);
              const y = TOP + dow * rowH;
              return (
                <rect
                  key={`${dow}-${hour}`}
                  x={x}
                  y={y}
                  width={cell}
                  height={cell}
                  rx={2}
                  fill={step < 0 ? "var(--elevated)" : RAMP[step]}
                  onPointerMove={() => show(dow, hour, x + cell / 2, y)}
                />
              );
            }),
          )}
        </svg>
      )}
      <ChartTip tip={tip} width={width} />
    </div>
  );
}
