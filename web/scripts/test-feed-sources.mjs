import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");
const transpile = (source) => ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const toUrl = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;

// feedSources leans on three sibling modules; point each import at a data: URL
// so the transpiled module resolves them outside the bundler (the same move
// test-feed-window.mjs makes for viewerFeed.js).
const viewerFeedUrl = toUrl(await read("../src/lib/viewerFeed.js"));
const feedWindowUrl = toUrl(transpile((await read("../src/lib/feedWindow.ts")).replace('"./viewerFeed.js"', JSON.stringify(viewerFeedUrl))));
const feedItemsUrl = toUrl(transpile(await read("../src/lib/feedItems.ts")));
const apiUrl = toUrl(transpile(await read("../src/lib/api.ts")));
const sources = await import(toUrl(transpile(
  (await read("../src/lib/feedSources.ts"))
    .replace('"./api"', JSON.stringify(apiUrl))
    .replace('"./feedItems"', JSON.stringify(feedItemsUrl))
    .replaceAll('"./feedWindow"', JSON.stringify(feedWindowUrl)),
)));
const fw = await import(feedWindowUrl);

/** A playable favorite the way isFeedItem sees one. */
const video = (id) => ({ id, status: "done", kind: "video", video_url: `/media/${id}.mp4`, images: [], offloaded: false });
/** A dead favorite with nothing to show — isFeedItem drops it from the window. */
const dead = (id) => ({ id, status: "pending", kind: "video", video_url: null, images: [], offloaded: false });

/** Fake FeedClient: records every call and replays the scripted responses. */
function fakeClient(script) {
  const calls = [];
  const wrap = (name) => (...args) => {
    calls.push([name, ...args]);
    if (!(name in script)) throw new Error(`unexpected ${name} call`);
    return script[name](...args);
  };
  return { calls, feedIds: wrap("feedIds"), itemIds: wrap("itemIds"), itemPage: wrap("itemPage"), itemSelection: wrap("itemSelection"), itemWindow: wrap("itemWindow") };
}

/** Install a source's init into a fresh window machine, like useFeedWindow does. */
const installed = (init) => fw.setInitial(fw.switchSource(fw.createFeedWindow()), 1, init);

// Filtered happy path: the clicked item is in the ids, so the source opens a
// window of 45 ids before it plus 50 from it — 95 ids, safely under
// itemSelection's 100-id cap — and reports the full match count.
{
  const ids = Array.from({ length: 200 }, (_, i) => i + 1);
  const client = fakeClient({
    feedIds: async (filterKey) => { assert.equal(filterKey, "kind=video"); return ids; },
    itemSelection: async (requested) => requested.map(video),
  });
  const source = sources.filteredFeedSource("kind=video", 101, "filtered:test", client);
  assert.equal(source.kind, "filtered");
  const init = await source.loadInitial();
  assert.deepEqual(client.calls[1], ["itemSelection", ids.slice(55, 150)]);
  assert.ok(client.calls[1][1].length <= 100);
  assert.equal(init.idStart, 55);
  assert.equal(init.idEnd, 150);
  assert.equal(init.activeId, 101);
  assert.equal(init.total, 200);
  assert.equal(init.scrollTo, "target");
  assert.equal(init.items.length, 95);
  assert.deepEqual(init.ids, ids);

  // With the id order known, loadBelow plans the next id slice…
  const state = installed(init);
  const below = source.loadBelow(state);
  assert.equal(below.consumeIds, 50);
  const batch = await below.fetch();
  assert.deepEqual(client.calls[2], ["itemSelection", ids.slice(150, 200)]);
  assert.equal(batch.items.length, 50);
  assert.equal(batch.cursor, undefined); // slice fetches leave the cursor alone

  // …and loadAbove plans the slice directly above the window.
  const above = source.loadAbove(state);
  assert.equal(above.idStart, 5);
  const prepended = await above.fetch();
  assert.deepEqual(client.calls[3], ["itemSelection", ids.slice(5, 55)]);
  assert.equal(prepended.length, 50);
}

// A click near the top of a short list clamps the window to the whole list.
{
  const client = fakeClient({
    feedIds: async () => [7, 8, 9, 10],
    itemSelection: async (requested) => requested.map(video),
  });
  const init = await sources.filteredFeedSource("", 8, "filtered:short", client).loadInitial();
  assert.deepEqual(client.calls[1], ["itemSelection", [7, 8, 9, 10]]);
  assert.equal(init.idStart, 0);
  assert.equal(init.idEnd, 4);
}

// Fallback rung 1: the ids fetch fails → plain latest feed, no total to report,
// and pagination continues by cursor.
{
  const client = fakeClient({
    feedIds: async () => { throw new Error("boom"); },
    itemPage: async (query) => (query.cursor === 28
      ? { items: [video(27)], next_cursor: null }
      : { items: [video(30), dead(29), video(28)], next_cursor: 28 }),
  });
  const source = sources.filteredFeedSource("q=x", 30, "filtered:fallback", client);
  const init = await source.loadInitial();
  assert.deepEqual(client.calls[1], ["itemPage", { limit: 50, order: "latest", feed: true }]);
  assert.deepEqual(init.items.map((item) => item.id), [30, 28]); // unplayable entries dropped
  assert.equal(init.cursor, 28);
  assert.equal(init.activeId, 30);
  assert.equal(init.total, undefined); // the ids fetch died before reporting a count
  assert.equal(init.ids, undefined);

  const plan = source.loadBelow(installed(init)); // no ids → cursor paging
  assert.equal(plan.consumeIds, 0);
  assert.deepEqual(await plan.fetch(), { items: [video(27)], cursor: null });
}

// Fallback rung 2: the ids load but the clicked item is not in them (a dead
// favorite) → latest feed again, but the match count is retained.
{
  const client = fakeClient({
    feedIds: async () => [1, 2, 3],
    itemPage: async () => ({ items: [video(3), video(2)], next_cursor: 2 }),
  });
  const init = await sources.filteredFeedSource("q=x", 99, "filtered:missing", client).loadInitial();
  assert.equal(init.total, 3);
  assert.deepEqual(init.items.map((item) => item.id), [3, 2]);
  assert.equal(init.cursor, 2);
}

// Queue source: plays exactly the picked ids, drops unplayable ones from the
// window but reports them via total, and never pages — which is why
// useFeedWindow exempts queues from trimming (dropped items would be gone).
{
  const client = fakeClient({
    itemSelection: async (requested) => { assert.deepEqual(requested, [5, 6, 7]); return [dead(5), video(6), video(7)]; },
  });
  const source = sources.queueFeedSource([5, 6, 7], "queue:test", client);
  assert.equal(source.kind, "queue");
  const init = await source.loadInitial();
  assert.deepEqual(init.items.map((item) => item.id), [6, 7]);
  assert.equal(init.activeId, 6);
  assert.equal(init.total, 2); // ready count, not the selection size
  assert.deepEqual(init.ids, [5, 6, 7]);
  assert.equal(init.idEnd, 3);
  assert.equal(source.loadBelow, undefined);
  assert.equal(source.loadAbove, undefined);
}

// Latest cursor flow: first page in latest order, then cursor pages until the
// server reports the stream exhausted (null cursor → loadBelow returns null).
{
  const pages = new Map([
    [undefined, { items: [video(50), video(49)], next_cursor: 49 }],
    [49, { items: [video(48)], next_cursor: null }],
  ]);
  const client = fakeClient({ itemPage: async (query) => pages.get(query.cursor) });
  const source = sources.latestFeedSource("latest:test", {}, client);
  assert.equal(source.kind, "latest");
  const init = await source.loadInitial();
  assert.deepEqual(client.calls[0], ["itemPage", { limit: 50, order: "latest", feed: true }]);
  assert.equal(init.cursor, 49);
  assert.equal(init.activeId, 50);
  assert.equal(init.scrollTo, undefined);

  let state = installed(init);
  const plan = source.loadBelow(state);
  assert.equal(plan.consumeIds, 0);
  const batch = await plan.fetch();
  assert.deepEqual(client.calls[1], ["itemPage", { limit: 50, cursor: 49, order: "latest", feed: true }]);
  assert.deepEqual(batch, { items: [video(48)], cursor: null });
  state = fw.completeLoadBelow(fw.beginLoadBelow(state, 0), state.generation, batch.items, batch.cursor);
  assert.equal(source.loadBelow(state), null);

  // The ordered-feed variant asks the hook to scroll back to the top.
  const top = await sources.latestFeedSource("latest:top", { scrollToTop: true }, client).loadInitial();
  assert.equal(top.scrollTo, "top");
}

// A failed shuffle keeps the current feed (loadInitial resolves null).
{
  const client = fakeClient({ itemIds: async () => { throw new Error("down"); } });
  assert.equal(await sources.randomFeedSource("random:test", client).loadInitial(), null);
}

console.log("feed source checks passed");
