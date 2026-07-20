import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  activeTranscriptCaption,
  analysisCompletionMessage,
  analysisCoverageLabel,
  analysisProgressLabel,
  automaticAnalysisPhases,
  lensSnippetParts,
  lensSourceLabel,
  mediaStartRequest,
  readCaptionPreference,
  readLensStartTime,
} from "../src/lib/lensPresentation.js";

assert.deepEqual(lensSnippetParts("before [[crispy]] after"), [
  { text: "before ", highlight: false },
  { text: "crispy", highlight: true },
  { text: " after", highlight: false },
]);
assert.deepEqual(lensSnippetParts("[[one]] and [[two]]"), [
  { text: "one", highlight: true },
  { text: " and ", highlight: false },
  { text: "two", highlight: true },
]);
assert.deepEqual(lensSnippetParts("plain"), [{ text: "plain", highlight: false }]);
assert.equal(lensSourceLabel("transcript"), "Spoken match");
assert.equal(lensSourceLabel("ocr"), "Text in frame");
assert.equal(readLensStartTime("18.25"), 18.25);
assert.equal(readLensStartTime("-1"), null);
assert.equal(readLensStartTime("NaN"), null);
assert.equal(readLensStartTime(null), null);
assert.deepEqual(mediaStartRequest("/media/1.mp4", 18.25, 30), {
  signature: "/media/1.mp4:18.25",
  time: 18.25,
});
assert.deepEqual(mediaStartRequest("/media/1.mp4", 45, 30), {
  signature: "/media/1.mp4:45",
  time: 30,
});
assert.deepEqual(mediaStartRequest("/media/1.mp4", 18.25, Number.NaN), {
  signature: "/media/1.mp4:18.25",
  time: 18.25,
});
assert.equal(mediaStartRequest("/media/1.mp4", null, 30), null);

assert.equal(readCaptionPreference(null), false);
assert.equal(readCaptionPreference("false"), false);
assert.equal(readCaptionPreference("true"), true);
assert.deepEqual(
  automaticAnalysisPhases(["sync", "enrich", "identify"], true),
  ["sync", "enrich", "identify", "analyze"],
);
assert.deepEqual(
  automaticAnalysisPhases(["sync", "analyze", "enrich"], false),
  ["sync", "enrich"],
);
assert.deepEqual(
  automaticAnalysisPhases(["sync", "analyze"], true),
  ["sync", "analyze"],
);
assert.equal(
  analysisCoverageLabel({
    complete: 8, manual: 2, generated: 6, pending: 2, failed: 1,
  }, 10),
  "8 of 10 ready · 2 pending · 1 failed",
);
assert.equal(
  analysisProgressLabel({
    completed: 4, total: 10, completed_sources: 7,
    failed_sources: 1, segments: 42, skipped: 2,
  }),
  "Checked 4 of 10 · 7 sources completed · 1 failed · 2 skipped · 42 segments",
);
assert.equal(
  analysisCompletionMessage("Stopping after the current local file…", {
    event: "complete", kind: "analyze",
  }),
  null,
);
assert.equal(
  analysisCompletionMessage("Automatic local analysis is off.", {
    event: "complete", kind: "sync",
  }),
  "Automatic local analysis is off.",
);

const inferredCaptionSegments = [
  { id: 1, item_id: 1, source: "transcript", text: "First", start_s: 0, end_s: null },
  { id: 2, item_id: 1, source: "transcript", text: "Second", start_s: 3, end_s: 5 },
  { id: 3, item_id: 1, source: "transcript", text: "Final", start_s: 8, end_s: null },
];
assert.equal(activeTranscriptCaption(inferredCaptionSegments, 2.99)?.text, "First");
assert.equal(activeTranscriptCaption(inferredCaptionSegments, 3)?.text, "Second");
assert.equal(activeTranscriptCaption(inferredCaptionSegments, 5.5), null);
assert.equal(activeTranscriptCaption(inferredCaptionSegments, 8)?.text, "Final");
assert.equal(activeTranscriptCaption(inferredCaptionSegments, 11.99)?.text, "Final");
assert.equal(activeTranscriptCaption(inferredCaptionSegments, 12), null);
assert.equal(activeTranscriptCaption(inferredCaptionSegments, -1), null);
assert.equal(activeTranscriptCaption(inferredCaptionSegments, Number.NaN), null);

const explicitlyEndedCaptionSegments = [
  { id: 4, item_id: 1, source: "transcript", text: "Short", start_s: 0, end_s: 2 },
  { id: 5, item_id: 1, source: "transcript", text: "Later", start_s: 3, end_s: 4 },
];
assert.equal(activeTranscriptCaption(explicitlyEndedCaptionSegments, 2.5), null);

const lensRoute = await readFile(
  new URL("../src/routes/Lens.tsx", import.meta.url),
  "utf8",
);
const importStart = lensRoute.indexOf("async function importAnalysis");
const importAnalysis = lensRoute.slice(
  importStart,
  lensRoute.indexOf("\n\n  return (", importStart),
);
assert.match(
  importAnalysis,
  /api\.lensStatus\(\)/,
  "Lens imports must refresh archive-wide status rather than displaying batch counts",
);
assert.match(
  lensRoute,
  /<summary[^>]*>Manual import<\/summary>/,
  "Manual Lens import must stay available inside a closed details disclosure",
);

console.log("PASS lens presentation behavior");
