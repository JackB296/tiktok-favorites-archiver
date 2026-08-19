import assert from "node:assert/strict";
import { ownsWheel } from "../src/lib/panelLayout.js";

// Anywhere inside the comment list, the feed keeps its hands off — including
// at the very end of the conversation, which must not advance the post.
assert.equal(ownsWheel([{ ownsWheel: true }]), true);
assert.equal(ownsWheel([{ ownsWheel: false }, { ownsWheel: true }]), true);

// Over the video, or the panel's own header, the wheel still drives the feed.
assert.equal(ownsWheel([{ ownsWheel: false }]), false);
assert.equal(ownsWheel([]), false);
assert.equal(ownsWheel(undefined), false);
assert.equal(ownsWheel([null, { ownsWheel: false }]), false);

console.log("PASS Feed details panel wheel ownership");
