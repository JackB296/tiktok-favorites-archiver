import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/galleryFilters.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const lib = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const full = {
  search: "cat videos", kind: "video", status: "failed", order: "duration_desc",
  minDuration: "5", maxDuration: "90", minSize: "1", maxSize: "250",
  minWidth: "480", maxWidth: "1920", minHeight: "600", maxHeight: "2400",
  minAttempts: "1", maxAttempts: "9", recovery: true, codec: "h264, hevc",
  dateFrom: "2024-01-01", dateTo: "2024-12-31", orientation: "portrait",
  assets: "with", audio: "without", offloaded: "with", indexState: "indexed",
  include: "@creator, #games", exclude: "#fyp",
  creator: "exactcreator", hashtag: "exacttag",
  starred: true, privateTag: "recipes",
};
const empty = lib.emptyFilters();

// The table covers every filter exactly once.
assert.equal(lib.GALLERY_FILTER_FIELDS.length, 29);
assert.equal(new Set(lib.GALLERY_FILTER_FIELDS.map((f) => f.key)).size, 29);

// URL round-trips: fully populated and empty states survive unchanged.
assert.deepEqual(lib.filtersFromUrl(lib.filtersToSearchParams(full)), full);
assert.deepEqual(lib.filtersFromUrl(new URLSearchParams("")), empty);
assert.equal(lib.filtersToSearchParams(empty).toString(), "");

// URL param names, order, and presence semantics pinned byte-for-byte against
// the old hand-rolled writer (codec between max_height and min_attempts;
// sort omitted when "latest"; recovery serialized as "1"; empties omitted).
assert.equal(
  lib.filtersToSearchParams(full).toString(),
  "q=cat+videos&kind=video&status=failed&sort=duration_desc&min_duration=5&max_duration=90&min_size=1&max_size=250&min_width=480&max_width=1920&min_height=600&max_height=2400&codec=h264%2C+hevc&min_attempts=1&max_attempts=9&recovery=1&from=2024-01-01&to=2024-12-31&orientation=portrait&assets=with&audio=without&offloaded=with&index=indexed&include=%40creator%2C+%23games&exclude=%23fyp&creator=exactcreator&hashtag=exacttag&starred=1&private_tag=recipes",
);
assert.equal(lib.filtersToSearchParams({ ...empty, order: "latest" }).toString(), "");
assert.equal(lib.filtersToSearchParams({ ...empty, order: "random" }).toString(), "sort=random");
assert.equal(lib.filtersFromUrl(new URLSearchParams("recovery=1")).recovery, true);
assert.equal(lib.filtersFromUrl(new URLSearchParams("recovery=0")).recovery, false);
assert.equal(lib.filtersFromUrl(new URLSearchParams("")).order, "latest");

// The page query emits exactly the params api.itemPage sent before: snake_case
// names, MB -> bytes, end-of-day date_to, allowlisted enums, page size 50.
assert.deepEqual(lib.filtersToPageQuery(full, 12345), {
  search: "cat videos", kind: "video", status: "failed", limit: 50, order: "duration_desc",
  seed: undefined,
  min_duration: 5, max_duration: 90,
  min_size: 1048576, max_size: 262144000,
  min_width: 480, max_width: 1920, min_height: 600, max_height: 2400,
  min_attempts: 1, max_attempts: 9,
  recovery: true, codec: "h264, hevc",
  date_from: "2024-01-01", date_to: "2024-12-31T23:59:59",
  orientation: "portrait", assets: "with", audio: "without", offloaded: "with",
  index_state: "indexed", include: "@creator, #games", exclude: "#fyp",
  creator: "exactcreator", hashtag: "exacttag",
  starred: true, private_tag: "recipes",
});
assert.deepEqual(lib.filtersToPageQuery(empty, 1), {
  search: "", kind: "", status: "", limit: 50, order: "latest", seed: undefined,
  min_duration: undefined, max_duration: undefined, min_size: undefined, max_size: undefined,
  min_width: undefined, max_width: undefined, min_height: undefined, max_height: undefined,
  min_attempts: undefined, max_attempts: undefined, recovery: undefined, codec: undefined,
  date_from: undefined, date_to: undefined, orientation: undefined,
  assets: undefined, audio: undefined, offloaded: undefined, index_state: undefined,
  include: "", exclude: "", creator: undefined, hashtag: undefined,
  starred: undefined, private_tag: undefined,
});
// The seed rides along only for Random order; 0-valued numbers still count.
assert.equal(lib.filtersToPageQuery({ ...empty, order: "random" }, 777).seed, 777);
assert.equal(lib.filtersToPageQuery({ ...empty, minAttempts: "0" }, 1).min_attempts, 0);
assert.equal(lib.filtersToPageQuery({ ...empty, minDuration: " " }, 1).min_duration, undefined);
// Fractional MB inputs land as whole byte counts (the server int()s them, so
// "0.1" MB as 104857.6 bytes would be a 400).
assert.equal(lib.filtersToPageQuery({ ...empty, minSize: "0.1" }, 1).min_size, 104858);
assert.equal(lib.filtersToPageQuery({ ...empty, maxSize: "1.5" }, 1).max_size, 1572864);
// Every table row names a param that the page query actually carries.
{
  const query = lib.filtersToPageQuery(full, 1);
  for (const field of lib.GALLERY_FILTER_FIELDS) assert.ok(Object.hasOwn(query, field.queryParam), field.queryParam);
}

// The mark-by-filter selector: the page query's own key/value strings minus
// exactly the paging/sort params the server rejects inside a filter
// (order/seed/limit/cursor — mirroring server/archive_items.py), empties dropped.
assert.deepEqual(lib.filtersToMarkSelector(full), {
  search: "cat videos", kind: "video", status: "failed",
  min_duration: "5", max_duration: "90", min_size: "1048576", max_size: "262144000",
  min_width: "480", max_width: "1920", min_height: "600", max_height: "2400",
  min_attempts: "1", max_attempts: "9", recovery: "true", codec: "h264, hevc",
  date_from: "2024-01-01", date_to: "2024-12-31T23:59:59",
  orientation: "portrait", assets: "with", audio: "without", offloaded: "with",
  index_state: "indexed", include: "@creator, #games", exclude: "#fyp",
  creator: "exactcreator", hashtag: "exacttag",
  starred: "true", private_tag: "recipes",
});
for (const key of ["order", "seed", "limit", "cursor"]) {
  assert.ok(!(key in lib.filtersToMarkSelector(full)), `${key} must not reach the mark filter`);
}
assert.deepEqual(lib.filtersToMarkSelector(empty), {});
assert.deepEqual(lib.filtersToMarkSelector({ ...empty, order: "random" }), {}); // sort/seed never leak
assert.equal(lib.filtersToMarkSelector({ ...empty, minAttempts: "0" }).min_attempts, "0"); // 0 still counts

// Presets carry every GalleryPresetFilters key (the server validates presets
// by key set — order has no wire meaning), and apply round-trips.
assert.deepEqual(Object.keys(lib.filtersToPreset(empty)).sort(), [
  "search", "kind", "status", "order", "minDuration", "maxDuration", "minSize", "maxSize",
  "minWidth", "maxWidth", "minHeight", "maxHeight", "minAttempts", "maxAttempts", "recovery",
  "codec", "dateFrom", "dateTo", "orientation", "assets", "audio", "offloaded", "indexState",
  "include", "exclude", "creator", "hashtag", "starred", "privateTag",
].sort());
assert.deepEqual(lib.filtersToPreset(full), full);
assert.deepEqual(lib.applyPreset(lib.filtersToPreset(full)), full);
assert.deepEqual(lib.applyPreset({}), empty);
assert.equal(lib.applyPreset({ order: "" }).order, "latest");
assert.equal(lib.applyPreset({ order: "random" }).order, "random");
assert.equal(lib.applyPreset({ recovery: true }).recovery, true);
assert.equal(lib.applyPreset({ search: "kept" }).search, "kept");

// Active-filter chips match the old addFilter() texts and order exactly.
assert.deepEqual(lib.activeChips(full).map((chip) => chip.label), [
  "Search: cat videos", "Videos", "Status: failed", "Sort: duration desc",
  "≥ 5s", "≤ 90s", "≥ 1 MB", "≤ 250 MB",
  "width ≥ 480", "width ≤ 1920", "height ≥ 600", "height ≤ 2400",
  "≥ 1 attempts", "≤ 9 attempts", "Recovery inbox", "Codec: h264, hevc",
  "After: 2024-01-01", "Before: 2024-12-31", "portrait", "Has raw assets",
  "No audio", "Offloaded", "Index: indexed", "Include: @creator, #games", "Exclude: #fyp",
  "Creator: exactcreator", "Hashtag: #exacttag", "Starred", "Private tag: recipes",
]);
assert.deepEqual(lib.activeChips(empty), []);
assert.deepEqual(lib.activeChips({ ...empty, include: "a,b" }), [{ key: "include", label: "Include: a,b" }]);
assert.equal(lib.activeChips({ ...empty, audio: "with" })[0].label, "Has audio");
assert.equal(lib.activeChips({ ...empty, offloaded: "without" })[0].label, "Stored locally");
assert.equal(lib.activeChips({ ...empty, assets: "without" })[0].label, "No raw assets");
assert.equal(lib.activeChips({ ...empty, kind: "slideshow" })[0].label, "Slideshows");
assert.equal(lib.activeChips({ ...empty, indexState: "indexed" })[0].label, "Index: indexed");

// The effect key is the URL serialization: stable, and distinct per state.
assert.equal(lib.filtersKey(full), lib.filtersToSearchParams(full).toString());
assert.equal(lib.filtersKey(empty), "");
assert.notEqual(lib.filtersKey(full), lib.filtersKey({ ...full, search: "dog videos" }));
assert.notEqual(lib.filtersKey(empty), lib.filtersKey({ ...empty, recovery: true }));

console.log("gallery filter checks passed");
