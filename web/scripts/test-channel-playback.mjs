import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/channelPlayback.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const lib = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const firstBatch = [{ id: 49 }, { id: 50 }];

assert.equal(lib.channelAdvanceTarget(firstBatch, 50), null);
assert.equal(lib.channelAdvanceTarget([...firstBatch, { id: 51 }], 50), 51);
assert.equal(lib.channelAdvanceTarget(firstBatch, null), null);
assert.equal(lib.channelAdvanceAction(firstBatch, 50, 49, 100).kind, "wait");
assert.equal(lib.channelAdvanceAction(firstBatch, 50, 1, 2).kind, "restart");
assert.equal(lib.channelAdvanceAction(firstBatch, 49, 48, 2).itemId, 50);
assert.equal(lib.channelAdvanceAction(firstBatch, 50, null, 50).kind, "wait");
assert.notEqual(lib.channelMediaKey(50, true, 0), lib.channelMediaKey(50, true, 1));
assert.equal(lib.channelMediaKey(50, false, 1), "50");

console.log("channel playback checks passed");
