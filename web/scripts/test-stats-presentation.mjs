import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/statsPresentation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const lib = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

// monthlySeries fills interior gaps, spans a year boundary, and accumulates.
{
  const { months, counts, cumulative } = lib.monthlySeries([
    { month: "2023-11", count: 2 },
    { month: "2024-01", count: 3 },
  ]);
  assert.deepEqual(months, ["2023-11", "2023-12", "2024-01"]);
  assert.deepEqual(counts, [2, 0, 3]);
  assert.deepEqual(cumulative, [2, 2, 5]);
}
assert.deepEqual(lib.monthlySeries([]), { months: [], counts: [], cumulative: [] });

// heatmapGrid shapes 7x24, records the peak, and drops out-of-range cells.
{
  const { grid, max } = lib.heatmapGrid([
    { dow: 1, hour: 10, count: 4 },
    { dow: 0, hour: 23, count: 1 },
    { dow: 9, hour: 3, count: 99 }, // invalid: ignored
  ]);
  assert.equal(grid.length, 7);
  assert.equal(grid[0].length, 24);
  assert.equal(grid[1][10], 4);
  assert.equal(grid[0][23], 1);
  assert.equal(max, 4);
}

// rampStep: zero cells are "empty", the peak lands on the last step, and the
// bucketing never exceeds the ramp.
assert.equal(lib.rampStep(0, 10), -1);
assert.equal(lib.rampStep(10, 10), 4);
assert.equal(lib.rampStep(1, 10), 0);
assert.equal(lib.rampStep(5, 0), -1);

// Axis ticks are clean 1/2/5 steps that cover the max.
assert.deepEqual(lib.axisTicks(0), [0]);
{
  const ticks = lib.axisTicks(870);
  assert.equal(ticks[0], 0);
  assert.ok(ticks[ticks.length - 1] >= 870);
  assert.ok(ticks.length >= 3 && ticks.length <= 6);
}
// Integer-count charts never emit fractional gridline labels (peak 1 or 2).
for (const max of [1, 2, 3, 5]) {
  const ticks = lib.axisTicks(max);
  assert.ok(ticks.every((t) => Number.isInteger(t)), `axisTicks(${max}) => ${ticks}`);
  assert.ok(ticks[ticks.length - 1] >= max);
}
assert.deepEqual(lib.axisTicks(2), [0, 1, 2]);

// Formatters.
assert.equal(lib.formatCount(12847), "12,847");
assert.equal(lib.compactCount(1284), "1,284");
assert.equal(lib.compactCount(12900), "12.9K");
assert.equal(lib.compactCount(1200000), "1.2M");
assert.equal(lib.formatWatchLength(45), "45s");
assert.equal(lib.formatWatchLength(3 * 86400 + 4 * 3600), "3d 4h");
assert.equal(lib.formatWatchLength(2 * 3600 + 30 * 60), "2h 30m");
assert.equal(lib.formatSeconds(45), "45s");
assert.equal(lib.formatSeconds(150), "2m 30s");
assert.equal(lib.monthLabel("2023-05"), "May 2023");

// Donut segments: fixed order, zero states dropped, shares sum to 1,
// angles are contiguous.
{
  const segs = lib.donutSegments({ done: 3, failed: 1, pending: 0 });
  assert.deepEqual(segs.map((s) => s.key), ["done", "failed"]);
  assert.ok(Math.abs(segs[0].share - 0.75) < 1e-9);
  assert.equal(segs[0].start, 0);
  assert.ok(Math.abs(segs[1].end - Math.PI * 2) < 1e-9);
  assert.equal(segs[0].end, segs[1].start);
}
assert.deepEqual(lib.donutSegments({}), []);

// Status colors: reserved tokens, never a series hue.
assert.equal(lib.statusColor("done"), "var(--ok)");
assert.equal(lib.statusColor("failed"), "var(--bad)");
assert.equal(lib.statusColor("mystery"), "var(--ink-faint)");

console.log("PASS test-stats-presentation");
