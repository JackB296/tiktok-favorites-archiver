import assert from "node:assert/strict";
import {
  archiveItemUrl,
  importDisplayDate,
  importSummary,
} from "../src/lib/historyPresentation.js";

assert.equal(
  importSummary({ new: 3, removed: 1, unchanged: 9, protected: 1 }),
  "3 new · 1 missing · 9 unchanged · 1 safely archived",
);
assert.equal(
  importSummary({ new: 0, removed: 0, unchanged: 2, protected: 0 }),
  "0 new · 0 missing · 2 unchanged",
);
assert.equal(importSummary(null), "No comparison available");
assert.equal(importDisplayDate("not-a-date"), "Unknown date");
assert.equal(archiveItemUrl(42), "/?item=42");

console.log("history presentation checks passed");
