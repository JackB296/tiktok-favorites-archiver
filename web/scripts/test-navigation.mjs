import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/navigation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const { navigationGroups, primaryNavigation } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`,
);

assert.deepEqual(primaryNavigation.map((item) => item.label), ["Feed", "Gallery", "Sync"]);
assert.deepEqual(navigationGroups.map((group) => group.label), ["Watch", "Browse", "Organize", "Manage"]);
assert.equal(navigationGroups.flatMap((group) => group.items).length, 15);
assert.equal(
  navigationGroups.flatMap((group) => group.items).filter((item) => item.to === "/stories").length,
  0,
);

console.log("PASS navigation groups keep primary archive work visible and retire Stories");
