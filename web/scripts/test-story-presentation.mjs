import assert from "node:assert/strict";
import {
  moveStoryChapter,
  readStoryQueue,
  storyDuration,
} from "../src/lib/storyPresentation.js";

assert.deepEqual(readStoryQueue("3,2,3,nope,-1,4"), [3, 2, 4]);
const chapters = [{ item_id: 1 }, { item_id: 2 }, { item_id: 3 }];
assert.deepEqual(moveStoryChapter(chapters, 1, -1).map((item) => item.item_id), [2, 1, 3]);
assert.strictEqual(moveStoryChapter(chapters, 0, -1), chapters);
assert.equal(storyDuration([
  { item_id: 1, start_s: 2, end_s: 5 },
  { item_id: 2, start_s: 1, end_s: null },
], [
  { id: 1, duration_s: 10 },
  { id: 2, duration_s: 9 },
]), 11);

console.log("story presentation checks passed");
