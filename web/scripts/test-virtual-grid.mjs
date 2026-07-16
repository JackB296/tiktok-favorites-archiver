import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/virtualGrid.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const grid = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

// Size steps fill the available width with as many portrait cards as fit.
const large = grid.gridMetrics("l", 1236); // target 300, gap 12, floor 2
assert.equal(large.columns, 4);
assert.equal(large.gap, 12);
assert.equal(large.cardWidth.toFixed(2), "300.00");
assert.equal(large.cardHeight.toFixed(2), "533.33");
assert.equal(large.rowStride.toFixed(2), "545.33");

const extra = grid.gridMetrics("xl", 2156); // target 420, gap 14
assert.equal(extra.columns, 5);
assert.equal(extra.cardWidth.toFixed(2), "420.00");

// Same step packs a laptop densely and a 4K far denser — no fixed breakpoints.
assert.equal(grid.gridMetrics("s", 1450).columns, 9);
assert.equal(grid.gridMetrics("s", 3800).columns, 24);

// Never collapses below the per-size column floor on a narrow phone.
assert.equal(grid.gridMetrics("xl", 430).columns, 2);
assert.equal(grid.gridMetrics("s", 430).columns, 3);

// Column helpers for unmeasured/skeleton grids.
assert.equal(grid.sizeTarget("m"), 210);
assert.equal(grid.autoFillColumns("m"), "repeat(auto-fill, minmax(210px, 1fr))");

assert.deepEqual(
  grid.visibleRows({ itemCount: 11_000, columns: 10, rowStride: 250, scrollTop: 5_000, viewportHeight: 900, overscan: 500 }),
  { start: 18, end: 26, count: 1_100 },
);
assert.deepEqual(
  grid.visibleRows({ itemCount: 3, columns: 10, rowStride: 250, scrollTop: 0, viewportHeight: 900, overscan: 500 }),
  { start: 0, end: 1, count: 1 },
);

assert.equal(grid.canLoadNextPage(42, false), true);
assert.equal(grid.canLoadNextPage(null, false), false);
assert.equal(grid.canLoadNextPage(42, true), false);

// Near-bottom detection, the other half of the paging policy.
assert.equal(grid.shouldLoadMore(4_600, 700, 6_000, 800), true);
assert.equal(grid.shouldLoadMore(2_000, 700, 6_000, 800), false);
assert.equal(grid.shouldLoadMore(4_200, 700, 6_000), true); // default 1 200px threshold
assert.equal(grid.shouldLoadMore(3_000, 700, 6_000), false);
assert.equal(grid.shouldLoadMore(0, 0, 6_000, 800), false); // unmeasured scroller

// Persisted thumbnail-size step parsing.
assert.equal(grid.readGallerySize(null), "m");
assert.equal(grid.readGallerySize("xl"), "xl");
assert.equal(grid.readGallerySize("bogus"), "m");

console.log("PASS virtual grid geometry, visible-row bounds, and paging policy");
