import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/loadingPresentation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const loading = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

// A request starts quiet and schedules the indicator to appear after the delay.
assert.deepEqual(loading.loadingStep(true, "content", null), {
  phase: "quiet",
  timer: { afterMs: loading.LOADING_DELAY_MS, phase: "indicator" },
});
// A new request restarts the same schedule regardless of what was showing.
assert.deepEqual(loading.loadingStep(true, "indicator", 120), {
  phase: "quiet",
  timer: { afterMs: loading.LOADING_DELAY_MS, phase: "indicator" },
});

// Finishing before the delay elapsed never shows the indicator.
assert.deepEqual(loading.loadingStep(false, "quiet", null), { phase: "content", timer: null });

// Finishing while the indicator is young holds it for the remaining minimum.
assert.deepEqual(loading.loadingStep(false, "indicator", 150), {
  phase: "indicator",
  timer: { afterMs: loading.MINIMUM_INDICATOR_MS - 150, phase: "content" },
});
assert.deepEqual(loading.loadingStep(false, "indicator", 1), {
  phase: "indicator",
  timer: { afterMs: loading.MINIMUM_INDICATOR_MS - 1, phase: "content" },
});

// Finishing once the indicator has held long enough settles immediately.
assert.deepEqual(loading.loadingStep(false, "indicator", loading.MINIMUM_INDICATOR_MS), { phase: "content", timer: null });
assert.deepEqual(loading.loadingStep(false, "indicator", null), { phase: "content", timer: null });
assert.deepEqual(loading.loadingStep(false, "content", null), { phase: "content", timer: null });

console.log("PASS delayed loading timer choreography");
