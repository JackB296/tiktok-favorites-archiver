import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/storagePresentation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const storage = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

assert.deepEqual(storage.parseArchiveIds("7, 3 7"), [7, 3]);
assert.throws(() => storage.parseArchiveIds("0, nope"), /positive/);
assert.equal(storage.MOVE_CONFIRMATION, "MOVE AND DELETE LOCAL");
assert.equal(
  storage.transferSummary({ action: "copy", items: 2, files: 5, bytes: 12_400_000 }),
  "2 Favorites · 5 files · 12.4 MB",
);
console.log("PASS storage transfer presentation");
