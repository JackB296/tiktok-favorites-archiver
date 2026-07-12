import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/legacyBootstrap.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const legacy = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

assert.equal(legacy.parseLegacyMappingText(""), undefined);
assert.deepEqual(legacy.parseLegacyMappingText("20968:5833, 22315:5832"), [
  { start_id: 20968, offset: 5833 },
  { start_id: 22315, offset: 5832 },
]);
assert.deepEqual(legacy.parseLegacyMappingText("20968 : 5833\n22315: 5832"), [
  { start_id: 20968, offset: 5833 },
  { start_id: 22315, offset: 5832 },
]);
assert.throws(() => legacy.parseLegacyMappingText("20968=5833"), /start:offset/);
assert.throws(() => legacy.parseLegacyMappingText("0:5833"), /positive/);

console.log("PASS legacy mapping segment input parsing");
