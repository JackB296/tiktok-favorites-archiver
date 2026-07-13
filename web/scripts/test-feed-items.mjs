import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/feedItems.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const feed = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

assert.equal(feed.isFeedItem({ status: "done", video_url: "/media/1.mp4", images: [], offloaded: false }), true);
assert.equal(feed.isFeedItem({ status: "done", video_url: null, images: ["/media/2/1.jpg"], offloaded: false }), true);
assert.equal(feed.isFeedItem({ status: "expired", video_url: null, images: [], offloaded: false }), true);
assert.equal(feed.isFeedItem({ status: "done", video_url: null, images: [], offloaded: true }), true);
assert.equal(feed.isFeedItem({ status: "failed", video_url: null, images: [], offloaded: false }), false);

assert.equal(feed.feedMediaKind({ status: "done", video_url: "/media/1.mp4", images: [], offloaded: true }), "video");
assert.equal(feed.feedMediaKind({ status: "done", video_url: null, images: ["/media/2/1.jpg"], offloaded: true }), "slideshow");
assert.equal(feed.feedMediaKind({ status: "done", kind: "slideshow", video_url: "/media/2.mp4", images: ["/media/2/1.jpg"], offloaded: false }), "slideshow");
assert.equal(feed.feedMediaKind({ status: "done", video_url: null, images: [], offloaded: true }), "offloaded");
assert.equal(feed.feedMediaKind({ status: "expired", video_url: null, images: [], offloaded: false }), "expired");

console.log("PASS Feed retains unavailable originals without showing retryable failures");
