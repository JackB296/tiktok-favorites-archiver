import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/commentsPresentation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const lib = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const comments = [
  { id: "reply-first", parent: "top", author: "Reply", text: "nested" },
  { id: "orphan", parent: "missing", author: "Orphan", text: "still visible" },
  { id: "top", parent: "root", author: "Top", text: "root comment" },
  { id: "second", parent: "0", author: "Second", text: "another root" },
];

assert.deepEqual(lib.commentThreads(comments), [
  { comment: comments[2], replies: [comments[0]] },
  { comment: comments[3], replies: [] },
  { comment: comments[1], replies: [] },
]);
assert.equal(lib.savedCommentsSummary(4, 10), "Showing 4 saved of 10 reported comments.");
assert.equal(lib.savedCommentsSummary(10, 10), "10 saved comments.");
assert.equal(lib.savedCommentsSummary(0, 3), "TikTok reported 3 comments, but none were available to save.");
assert.equal(lib.savedCommentsSummary(0, 0), "No public comments were reported.");
assert.equal(
  lib.commentSnapshotSummary({ added: 2, removed: 1, changed: 3 }),
  "2 new, 1 unavailable, 3 updated",
);
assert.equal(lib.commentSnapshotSummary({ added: 0, removed: 0, changed: 0 }), "No changes from the previous snapshot");

console.log("comments presentation checks passed");
