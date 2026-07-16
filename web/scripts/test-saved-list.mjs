import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/savedList.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const lib = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

// sortedInsert keeps name order using localeCompare — the exact comparator all
// four saved-list copies used ("a".localeCompare("B") groups letters, so case
// does not split the alphabet the way byte order would).
const list = [
  { id: 1, name: "Beta" },
  { id: 2, name: "delta" },
];
assert.deepEqual(
  lib.sortedInsert(list, { id: 3, name: "alpha" }).map((entry) => entry.name),
  ["alpha", "Beta", "delta"],
);
assert.deepEqual(
  lib.sortedInsert(list, { id: 3, name: "charlie" }).map((entry) => entry.id),
  [1, 3, 2],
);
assert.deepEqual(
  lib.sortedInsert(list, { id: 3, name: "zeta" }).map((entry) => entry.id),
  [1, 2, 3],
);
// Duplicate names: the sort is stable, so the new entry lands after the old one.
assert.deepEqual(
  lib.sortedInsert([{ id: 1, name: "alpha" }], { id: 9, name: "alpha" }).map((entry) => entry.id),
  [1, 9],
);
// Inserting into an empty list works and inputs are never mutated.
assert.deepEqual(lib.sortedInsert([], { id: 5, name: "solo" }).map((entry) => entry.id), [5]);
assert.deepEqual(list.map((entry) => entry.id), [1, 2]);

// removeById filters the matching id out, preserves order, ignores misses.
const queues = [
  { id: 10, name: "a" },
  { id: 20, name: "b" },
  { id: 30, name: "c" },
];
assert.deepEqual(lib.removeById(queues, 20).map((entry) => entry.id), [10, 30]);
assert.deepEqual(lib.removeById(queues, 99).map((entry) => entry.id), [10, 20, 30]);
assert.deepEqual(lib.removeById([], 1), []);
assert.deepEqual(queues.map((entry) => entry.id), [10, 20, 30]);

console.log("saved list checks passed");
