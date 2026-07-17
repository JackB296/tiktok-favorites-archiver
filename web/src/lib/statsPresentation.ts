/** Pure shaping for the Stats tab: chart-ready series, ramp bucketing, and
 * formatters. No React, no DOM — tested by scripts/test-stats-presentation.mjs. */
import type { StatsHeatCell, StatsMonth, Status } from "./types";

/** Contiguous month axis from first to last seen month, gaps filled with 0,
 * plus the running total the cumulative area chart plots. */
export function monthlySeries(monthly: StatsMonth[]): { months: string[]; counts: number[]; cumulative: number[] } {
  if (!monthly.length) return { months: [], counts: [], cumulative: [] };
  const byMonth = new Map(monthly.map((m) => [m.month, m.count]));
  const months: string[] = [];
  let [year, month] = monthly[0].month.split("-").map(Number);
  const last = monthly[monthly.length - 1].month;
  // Defensive cap (~83 years of months): the backend returns sorted YYYY-MM
  // with first ≤ last, but a malformed payload must never spin forever.
  for (let guard = 0; guard < 1000; guard++) {
    const key = `${year}-${String(month).padStart(2, "0")}`;
    months.push(key);
    if (key === last) break;
    month += 1;
    if (month > 12) { month = 1; year += 1; }
  }
  const counts = months.map((m) => byMonth.get(m) ?? 0);
  let total = 0;
  const cumulative = counts.map((c) => (total += c));
  return { months, counts, cumulative };
}

/** 7×24 grid (rows = Sunday..Saturday, matching SQLite %w) and its peak. */
export function heatmapGrid(cells: StatsHeatCell[]): { grid: number[][]; max: number } {
  const grid = Array.from({ length: 7 }, () => Array<number>(24).fill(0));
  let max = 0;
  for (const c of cells) {
    if (c.dow < 0 || c.dow > 6 || c.hour < 0 || c.hour > 23) continue;
    grid[c.dow][c.hour] = c.count;
    if (c.count > max) max = c.count;
  }
  return { grid, max };
}

/** Ramp step for a heat cell: -1 = empty (surface), else 0..steps-1 low→high. */
export function rampStep(count: number, max: number, steps = 5): number {
  if (count <= 0 || max <= 0) return -1;
  return Math.min(steps - 1, Math.floor((count / max) * steps));
}

/** "MMM YYYY" for axis/tooltip labels; month keys stay data-side as YYYY-MM. */
export function monthLabel(month: string): string {
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const [y, m] = month.split("-").map(Number);
  return `${names[(m || 1) - 1]} ${y}`;
}

/** Clean y-axis ticks: 0..max rounded up to a 1/2/5×10^k step, ≤ five ticks.
 * Every chart here plots integer counts, so the step never drops below 1 —
 * a peak of 1 or 2 must not produce 0.5/1.5 gridline labels. */
export function axisTicks(max: number): number[] {
  if (max <= 0) return [0];
  const rough = max / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const raw = [1, 2, 5, 10].map((s) => s * power).find((s) => s >= rough) ?? power * 10;
  const step = Math.max(1, Math.ceil(raw));
  const ticks: number[] = [];
  for (let t = 0; ; t += step) {
    ticks.push(t);
    if (t >= max) break;
  }
  return ticks;
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

/** Stat-tile compact value: 1,284 / 12.9K / 1.2M. */
export function compactCount(n: number): string {
  if (n < 10000) return n.toLocaleString("en-US");
  if (n < 1000000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  return `${(n / 1000000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** Hero watch-length: days/hours for big libraries, minutes for small ones. */
export function formatWatchLength(totalSeconds: number): string {
  const s = Math.round(totalSeconds);
  if (s < 60) return `${s}s`;
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (days > 0) return hours ? `${days}d ${hours}h` : `${days}d`;
  if (hours > 0) return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
  return `${minutes}m`;
}

/** Median-style single duration: 45s / 2m 30s. */
export function formatSeconds(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return rest ? `${m}m ${rest}s` : `${m}m`;
}

export const DOW_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export interface DonutSegment {
  key: string;
  count: number;
  share: number; // 0..1
  /** SVG arc path angles, radians, clockwise from 12 o'clock. */
  start: number;
  end: number;
}

/** Donut segments in a fixed, meaningful order; zero-count states drop out. */
export function donutSegments(statuses: Partial<Record<Status, number>>): DonutSegment[] {
  const order: Status[] = ["done", "downloading", "resolving", "pending", "failed", "skipped", "ignored", "expired"];
  const entries = order
    .map((key) => ({ key, count: statuses[key] ?? 0 }))
    .filter((e) => e.count > 0);
  const total = entries.reduce((sum, e) => sum + e.count, 0);
  if (!total) return [];
  let angle = 0;
  return entries.map((e) => {
    const share = e.count / total;
    const start = angle;
    angle += share * Math.PI * 2;
    return { key: e.key, count: e.count, share, start, end: angle };
  });
}

/** Status → design-token CSS color for donut fills and legend keys. */
export function statusColor(status: string): string {
  switch (status) {
    case "done": return "var(--ok)";
    case "downloading":
    case "resolving": return "var(--active)";
    case "pending": return "var(--ink-faint)";
    case "failed": return "var(--bad)";
    case "skipped":
    case "expired": return "var(--warn)";
    case "ignored": return "var(--line)";
    default: return "var(--ink-faint)";
  }
}
