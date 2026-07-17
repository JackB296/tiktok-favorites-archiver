/** Lifecycle donut. Status colors are reserved tokens (never series hues) and
 * every segment is named in the always-present legend beside the plot — color
 * is never the only identity channel. Segments separate with a 2px surface
 * stroke; the center carries the total. */
import { useState } from "react";
import { compactCount, donutSegments, formatCount, statusColor } from "../../lib/statsPresentation";
import type { Status } from "../../lib/types";

const SIZE = 168;
const R_OUTER = 74;
const R_INNER = 48;

const STATUS_LABELS: Record<string, string> = {
  done: "Archived",
  downloading: "Downloading",
  resolving: "Resolving",
  pending: "Pending",
  failed: "Failed",
  skipped: "Skipped",
  ignored: "Ignored",
  expired: "Unavailable",
};

function arcPath(start: number, end: number): string {
  // Angles are clockwise from 12 o'clock; guard the full-circle case.
  const sweep = Math.min(end - start, Math.PI * 2 - 1e-4);
  const a0 = start - Math.PI / 2;
  const a1 = a0 + sweep;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const large = sweep > Math.PI ? 1 : 0;
  const p = (r: number, a: number) => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
  return [
    `M${p(R_OUTER, a0)}`,
    `A${R_OUTER},${R_OUTER} 0 ${large} 1 ${p(R_OUTER, a1)}`,
    `L${p(R_INNER, a1)}`,
    `A${R_INNER},${R_INNER} 0 ${large} 0 ${p(R_INNER, a0)}`,
    "Z",
  ].join("");
}

export function Donut({ statuses }: { statuses: Partial<Record<Status, number>> }) {
  const [hover, setHover] = useState<string | null>(null);
  const segments = donutSegments(statuses);
  const total = segments.reduce((sum, s) => sum + s.count, 0);
  if (!total) return null;

  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg width={SIZE} height={SIZE} role="img" aria-label={`Archive lifecycle: ${formatCount(total)} favorites`}>
        {segments.map((s) => (
          <path
            key={s.key}
            d={arcPath(s.start, s.end)}
            fill={statusColor(s.key)}
            stroke="var(--surface)"
            strokeWidth={2}
            opacity={hover === null || hover === s.key ? 1 : 0.45}
            onPointerEnter={() => setHover(s.key)}
            onPointerLeave={() => setHover(null)}
          />
        ))}
        <text x={SIZE / 2} y={SIZE / 2 - 2} textAnchor="middle" fontSize={22} fontWeight={600} fill="var(--ink)">
          {compactCount(total)}
        </text>
        <text x={SIZE / 2} y={SIZE / 2 + 16} textAnchor="middle" fontSize={10} fill="var(--ink-dim)">
          favorites
        </text>
      </svg>
      <ul className="min-w-40 flex-1 space-y-1.5">
        {segments.map((s) => (
          <li
            key={s.key}
            className="flex items-center gap-2 text-sm"
            onPointerEnter={() => setHover(s.key)}
            onPointerLeave={() => setHover(null)}
          >
            <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: statusColor(s.key) }} />
            <span className="text-ink-dim">{STATUS_LABELS[s.key] ?? s.key}</span>
            <span className="tabular ml-auto text-ink">{formatCount(s.count)}</span>
            <span className="tabular w-12 text-right text-xs text-ink-faint">{(s.share * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
