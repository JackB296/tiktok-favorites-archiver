import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/viewerShortcuts.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const shortcuts = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

assert.equal(shortcuts.viewerShortcut({ key: "f", code: "KeyF", repeat: false, editing: false }), "fullscreen");
assert.equal(shortcuts.viewerShortcut({ key: "F", code: "KeyF", repeat: true, editing: false }), null);
assert.equal(shortcuts.viewerShortcut({ key: " ", code: "Space", repeat: false, editing: false }), "pause");
assert.equal(shortcuts.viewerShortcut({ key: "m", code: "KeyM", repeat: false, editing: true }), null);
assert.equal(shortcuts.viewerShortcut({ key: "ArrowDown", code: "ArrowDown", repeat: false, editing: false }), "next");
assert.equal(shortcuts.viewerShortcut({ key: "ArrowUp", code: "ArrowUp", repeat: false, editing: false }), "previous");
assert.equal(shortcuts.viewerShortcut({ key: "ArrowRight", code: "ArrowRight", repeat: false, editing: false }), "nextImage");
assert.equal(shortcuts.viewerShortcut({ key: "ArrowLeft", code: "ArrowLeft", repeat: false, editing: false }), "prevImage");

console.log("PASS viewer keyboard shortcut mapping");
