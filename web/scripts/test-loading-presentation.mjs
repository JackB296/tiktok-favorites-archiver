import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/loadingPresentation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const loading = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

assert.equal(loading.loadingPhase(true, 0, null), "quiet");
assert.equal(loading.loadingPhase(true, loading.LOADING_DELAY_MS - 1, null), "quiet");
assert.equal(loading.loadingPhase(true, loading.LOADING_DELAY_MS, 0), "indicator");
assert.equal(loading.loadingPhase(false, 300, 100), "indicator");
assert.equal(loading.loadingPhase(false, 700, loading.MINIMUM_INDICATOR_MS), "content");
assert.equal(loading.loadingPhase(false, 100, null), "content");

console.log("PASS delayed loading presentation policy");
