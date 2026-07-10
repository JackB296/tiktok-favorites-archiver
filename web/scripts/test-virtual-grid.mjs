import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/virtualGrid.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const grid = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const wideGrid = grid.gridMetrics("compact", 1248, 1400);
assert.equal(wideGrid.columns, 10);
assert.equal(wideGrid.gap, 8);
assert.equal(wideGrid.cardHeight.toFixed(2), "209.07");
assert.equal(wideGrid.rowStride.toFixed(2), "217.07");
assert.equal(grid.gridMetrics("compact", 900).columns, 6);
assert.equal(grid.gridMetrics("comfortable", 1050).columns, 5);

assert.deepEqual(
  grid.visibleRows({ itemCount: 11_000, columns: 10, rowStride: 250, scrollTop: 5_000, viewportHeight: 900, overscan: 500 }),
  { start: 18, end: 26, count: 1_100 },
);
assert.deepEqual(
  grid.visibleRows({ itemCount: 3, columns: 10, rowStride: 250, scrollTop: 0, viewportHeight: 900, overscan: 500 }),
  { start: 0, end: 1, count: 1 },
);

console.log("PASS virtual grid geometry and visible-row bounds");
