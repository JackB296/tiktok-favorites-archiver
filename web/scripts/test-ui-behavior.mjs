import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

async function load(relativePath) {
  const source = await readFile(new URL(relativePath, import.meta.url), "utf8");
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
}

const feed = await load("../src/lib/viewerFeed.js");
assert.equal(feed.activeFeedIndex(10_300, 664, 50), 16);
assert.deepEqual(feed.feedTrimPlan(16, 10_300, 664, 5), {
  removeCount: 11,
  restoredScrollTop: 2_996,
});
assert.deepEqual(feed.feedTrimPlan(4, 2_656, 664, 5), {
  removeCount: 0,
  restoredScrollTop: 2_656,
});
assert.equal(feed.nextWheelTargetIndex(5, -1, 1, 20), 6);
assert.equal(feed.nextWheelTargetIndex(5, 6, 1, 20), 7);
assert.equal(feed.nextWheelTargetIndex(5, 4, -1, 20), 3);
assert.equal(feed.nextWheelTargetIndex(0, -1, -1, 20), 0);
assert.equal(feed.shouldCommitWheelTarget(900, 664, 2), false);
assert.equal(feed.shouldCommitWheelTarget(1_310, 664, 2), true);
assert.equal(feed.shouldCommitWheelTarget(1_328, 664, 2), true);
assert.equal(feed.playbackItemId(12, null), 12);
assert.equal(feed.playbackItemId(12, 13), 13);
assert.equal(feed.shouldPreloadItem(13, 5, 13, null), true);
assert.equal(feed.shouldPreloadItem(14, 5, 14, null), false);
assert.equal(feed.shouldPreloadItem(40, 5, 40, 40), true);

const progress = await load("../src/lib/progressPresentation.js");
assert.equal(
  progress.progressLabel({ event: "enrichment", completed: 11, total: 18_467, enriched: 9 }),
  "Metadata 11/18467 · 9 updated",
);
assert.equal(
  progress.progressLabel({ event: "identification", completed: 7, total: 40, identified: 5, errors: 1 }),
  "Songs 7/40 · 5 identified · 1 errors",
);
assert.equal(progress.progressLabel({ event: "error", error: "TikTok unavailable" }), "Error: TikTok unavailable");
assert.equal(progress.progressLabel({ event: "complete" }), "Run complete");

const gallery = await load("../src/lib/galleryPresentation.js");
assert.equal(gallery.DEFAULT_GALLERY_DETAILS.resolution, false);
assert.equal(gallery.DEFAULT_GALLERY_DETAILS.duration, true);
assert.equal(gallery.readGalleryDetails('{"caption":false,"resolution":true}').caption, false);
assert.equal(gallery.readGalleryDetails('{"caption":false,"resolution":true}').author, true);
assert.deepEqual(gallery.readGalleryDetails("not json"), gallery.DEFAULT_GALLERY_DETAILS);

const volume = await load("../src/lib/playbackVolume.js");
assert.equal(volume.readPlaybackVolume(null), 1);
assert.equal(volume.readPlaybackVolume(""), 1);
assert.equal(volume.readPlaybackVolume("0.65"), 0.65);
assert.equal(volume.readPlaybackVolume("not a number"), 1);
assert.equal(volume.normalizationGain(0), 1);
assert.ok(volume.normalizationGain(0.5) < 1);
assert.ok(volume.normalizationGain(0.05) > 1);
assert.equal(volume.normalizationGain(0.001), 2.5);
assert.equal(volume.normalizationGain(1), 0.35);
assert.equal(volume.formatAutoGain(1), "Auto 1.00×");
assert.equal(volume.formatAutoGain(1.347), "Auto 1.35×");

const media = await load("../src/lib/mediaPresentation.js");
assert.equal(media.audioStatus(false), "No audio");
assert.equal(media.audioStatus(true), "Has audio");
assert.equal(media.audioStatus(null), "Not checked");
assert.equal(media.audioStatus(true, true), "Silent");
assert.equal(media.audioStatus(false, false), "No audio");
assert.equal(media.readGallerySize(null), "m");
assert.equal(media.readGallerySize("xl"), "xl");
assert.equal(media.readGallerySize("bogus"), "m");
assert.equal(media.formatMediaTime(0), "0:00");
assert.equal(media.formatMediaTime(65.4), "1:05");
assert.equal(media.formatMediaTime(Number.NaN), "0:00");

const captions = await load("../src/lib/captionPresentation.js");
assert.deepEqual(captions.captionParts("free will #tenet and #TenetEdit."), [
  { text: "free will ", hashtag: null },
  { text: "#tenet", hashtag: "#tenet" },
  { text: " and ", hashtag: null },
  { text: "#TenetEdit", hashtag: "#TenetEdit" },
  { text: ".", hashtag: null },
]);
assert.equal(captions.hashtagGalleryUrl("#TenetEdit"), "/gallery?q=%23TenetEdit");
assert.equal(captions.cleanMetadataText("\uFFF6\n Alice "), "Alice");
assert.equal(captions.cleanMetadataText("\uFFF4\uFFF6"), "");

const galleryPaging = await load("../src/lib/galleryPaging.js");
assert.equal(galleryPaging.shouldLoadMore(4_600, 700, 6_000, 800), true);
assert.equal(galleryPaging.shouldLoadMore(2_000, 700, 6_000, 800), false);

console.log("PASS UI behavior helpers cover scrolling, metadata labels, card details, and loudness leveling");
