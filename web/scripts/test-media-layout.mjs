import assert from "node:assert/strict";
import { containedMediaBox } from "../src/lib/mediaLayout.js";

// Portrait clip in a wide 4K viewport: letterboxed, wide side margins, no top/bottom.
const portrait = containedMediaBox(2560, 1400, 1080, 1920);
assert.equal(portrait.width.toFixed(2), "787.50");
assert.equal(portrait.height.toFixed(2), "1400.00");
assert.equal(portrait.marginX.toFixed(2), "886.25");
assert.equal(portrait.marginY.toFixed(2), "0.00");

// Landscape clip in a squarish box: full width, pillarboxed top/bottom.
const landscape = containedMediaBox(800, 800, 1920, 1080);
assert.equal(landscape.width.toFixed(2), "800.00");
assert.equal(landscape.height.toFixed(2), "450.00");
assert.equal(landscape.marginX.toFixed(2), "0.00");
assert.equal(landscape.marginY.toFixed(2), "175.00");

// Unknown media dimensions (metadata not loaded) -> occupy the whole container.
assert.deepEqual(containedMediaBox(1000, 800, 0, 0), { width: 1000, height: 800, marginX: 0, marginY: 0 });
assert.deepEqual(containedMediaBox(0, 0, 1080, 1920), { width: 0, height: 0, marginX: 0, marginY: 0 });

console.log("PASS contained media box geometry");
