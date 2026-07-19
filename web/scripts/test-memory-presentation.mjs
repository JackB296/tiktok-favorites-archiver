import assert from "node:assert/strict";
import { memoryDateLabel, memoryFeedUrl } from "../src/lib/memoryPresentation.js";

assert.equal(memoryFeedUrl([], 1), "/");
assert.equal(memoryFeedUrl([4, 4, 2, -1], 2), "/?queue=2%2C4&item=2");
assert.equal(memoryFeedUrl([4, 2], 99), "/?queue=4%2C2&item=4");
assert.match(memoryDateLabel("2026-07-19"), /2026/);

console.log("memory presentation checks passed");
