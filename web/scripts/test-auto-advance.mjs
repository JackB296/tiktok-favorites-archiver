import assert from "node:assert/strict";
import { nextAutoAdvanceItem } from "../src/lib/viewerFeed.js";

const items = [{ id: 10 }, { id: 20 }, { id: 30 }];
assert.equal(nextAutoAdvanceItem(items, 10), 20);
assert.equal(nextAutoAdvanceItem(items, 30), null);
assert.equal(nextAutoAdvanceItem(items, 999), null);
console.log("PASS optional Feed auto-advance chooses only the next loaded post");
