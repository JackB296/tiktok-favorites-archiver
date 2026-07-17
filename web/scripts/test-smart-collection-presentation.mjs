import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../src/lib/smartCollectionPresentation.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const lib = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
assert.equal(lib.smartCollectionConfirmation("offload", 1), "Mark 1 current favorite? Membership will be checked again when applied.");
assert.equal(lib.smartCollectionConfirmation("ignore", 4), "Ignore 4 current favorites? Membership will be checked again when applied.");
console.log("smart collection presentation checks passed");

