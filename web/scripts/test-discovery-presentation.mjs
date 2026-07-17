import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../src/lib/discoveryPresentation.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const lib = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
assert.equal(lib.discoveryGalleryUrl("creator", "café name"), "/gallery?creator=caf%C3%A9%20name");
assert.equal(lib.discoveryFeedUrl("hashtag", "cats", 42), "/?hashtag=cats&item=42");
console.log("discovery presentation checks passed");

