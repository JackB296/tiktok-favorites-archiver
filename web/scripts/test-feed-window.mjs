import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

// feedWindow.ts reuses feedTrimPlan from viewerFeed.js; point that import at a
// data: URL so the transpiled module resolves it outside the bundler.
const trimSource = await readFile(new URL("../src/lib/viewerFeed.js", import.meta.url), "utf8");
const trimUrl = `data:text/javascript;base64,${Buffer.from(trimSource).toString("base64")}`;
const source = (await readFile(new URL("../src/lib/feedWindow.ts", import.meta.url), "utf8"))
  .replace('"./viewerFeed.js"', JSON.stringify(trimUrl));
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const fw = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const { feedTrimPlan } = await import(trimUrl);

const items = (...ids) => ids.map((id) => ({ id }));
const itemIds = (state) => state.items.map((item) => item.id);

// A fresh machine, then a source takes over: switchSource bumps the generation
// and cancels pending loads; setInitial installs the window under that generation.
let state = fw.createFeedWindow();
assert.equal(state.generation, 0);
state = fw.switchSource(state);
assert.equal(state.generation, 1);
state = fw.setInitial(state, state.generation, { items: items(10, 11, 12), ids: [10, 11, 12, 13, 14, 15], idStart: 0, idEnd: 3 });
assert.deepEqual(itemIds(state), [10, 11, 12]);
assert.equal(state.idEnd, 3);
assert.equal(state.cursor, null);

// An initial window arriving from a superseded load is discarded (SAME state back).
assert.equal(fw.setInitial(state, state.generation - 1, { items: items(99) }), state);

// Race 1 pin: an in-flight below batch must die when the source switches.
// Begin under the old generation, switch, then complete with the old generation → no-op.
const inFlight = fw.beginLoadBelow(state, 2);
assert.notEqual(inFlight, null);
assert.equal(inFlight.loadingBelow, true);
assert.equal(inFlight.idEnd, 5); // the slice is consumed up front
const oldGeneration = inFlight.generation;
const switched = fw.switchSource(inFlight);
assert.equal(switched.generation, oldGeneration + 1);
assert.equal(switched.loadingBelow, false); // pending loads are cancelled by the switch
const stale = fw.completeLoadBelow(switched, oldGeneration, items(13, 14));
assert.equal(stale, switched); // SAME reference — a stale completion changes nothing
assert.deepEqual(itemIds(stale), [10, 11, 12]);
assert.equal(fw.failLoadBelow(switched, oldGeneration), switched); // stale failures too
assert.equal(fw.completeLoadAbove(switched, oldGeneration, items(9), 0), switched);
assert.equal(fw.failLoadAbove(switched, oldGeneration), switched);

// Install a filtered-style window (idStart > 0 → there is history above).
state = fw.setInitial(switched, switched.generation, {
  items: items(20, 21, 22),
  ids: [18, 19, 20, 21, 22, 23, 24, 25],
  idStart: 2,
  idEnd: 5,
});
const generation = state.generation;

// Slice helpers respect the id window.
assert.deepEqual(fw.belowIdSlice(state, 2), [23, 24]);
assert.deepEqual(fw.aboveIdSlice(state, 50), { start: 0, ids: [18, 19] });

// Race 2 pin, part 1: begin refuses while its own direction is pending…
const below = fw.beginLoadBelow(state, 3);
assert.equal(fw.beginLoadBelow(below, 3), null);
// …but above may coexist with below (each claims its own slot).
const both = fw.beginLoadAbove(below);
assert.notEqual(both, null);
assert.equal(fw.beginLoadAbove(both), null);

// Race 2 pin, part 2: a below completion during a pending above load leaves the
// window start alone — the two directions mutate disjoint state.
const afterBelow = fw.completeLoadBelow(both, generation, items(23, 24));
assert.equal(afterBelow.idStart, 2); // untouched by the below path
assert.equal(afterBelow.loadingAbove, true); // above is still pending
assert.equal(afterBelow.loadingBelow, false);
assert.deepEqual(itemIds(afterBelow), [20, 21, 22, 23, 24]);
const afterAbove = fw.completeLoadAbove(afterBelow, generation, items(18, 19), 0);
assert.equal(afterAbove.idStart, 0);
assert.equal(afterAbove.loadingAbove, false);
assert.deepEqual(itemIds(afterAbove), [18, 19, 20, 21, 22, 23, 24]);
assert.equal(fw.aboveIdSlice(afterAbove, 50), null); // now at the top of the list

// A failed below slice is skipped, not retried: idEnd stays advanced (matching
// the original loaders, so the feed always progresses past a broken batch).
const failed = fw.failLoadBelow(fw.beginLoadBelow(afterAbove, 1), generation);
assert.equal(failed.loadingBelow, false);
assert.equal(failed.idEnd, afterAbove.idEnd + 1);

// A retryable selection batch leaves its ids unconsumed after a transient
// failure, then consumes them exactly once on the successful retry.
const retryPending = fw.beginLoadBelow(afterAbove, 1, true);
assert.equal(retryPending.idEnd, afterAbove.idEnd);
const retryFailed = fw.failLoadBelow(retryPending, generation);
assert.equal(retryFailed.idEnd, afterAbove.idEnd);
const retryDone = fw.completeLoadBelow(
  fw.beginLoadBelow(retryFailed, 1, true), generation, items(25),
);
assert.equal(retryDone.idEnd, afterAbove.idEnd + 1);

// Cursor streams: a below completion replaces the cursor (null = exhausted);
// slice completions leave it alone.
let stream = fw.setInitial(fw.switchSource(failed), failed.generation + 1, { items: items(1, 2), cursor: 42 });
stream = fw.completeLoadBelow(fw.beginLoadBelow(stream, 0), stream.generation, items(3), 41);
assert.equal(stream.cursor, 41);
stream = fw.completeLoadBelow(fw.beginLoadBelow(stream, 0), stream.generation, items(4), null);
assert.equal(stream.cursor, null);
const sliceDone = fw.completeLoadBelow(fw.beginLoadBelow(afterAbove, 1), generation, items(25));
assert.equal(sliceDone.cursor, afterAbove.cursor);

// Trim integration: the machine's trim produces exactly the plan feedTrimPlan
// yields (values pinned in test-ui-behavior.mjs) and drops that many items.
const wide = fw.setInitial(fw.switchSource(stream), stream.generation + 1, {
  items: items(...Array.from({ length: 20 }, (_, i) => 100 + i)),
  cursor: 777,
});
const trimmed = fw.trimWindow(wide, 16, 10_300, 664, 5);
assert.deepEqual(trimmed.plan, feedTrimPlan(16, 10_300, 664, 5));
assert.deepEqual(trimmed.plan, { removeCount: 11, restoredScrollTop: 2_996 });
assert.equal(trimmed.state.items.length, 9);
assert.equal(trimmed.state.items[0].id, 111);
assert.equal(trimmed.state.idStart, wide.idStart); // id bookkeeping is left alone
const untrimmed = fw.trimWindow(wide, 4, 2_656, 664, 5);
assert.equal(untrimmed.state, wide); // SAME reference when nothing to drop

// Prepend compensation: scroll down one viewport per prepended item.
assert.equal(fw.prependScrollAdjustment(2, 664), 1_328);
assert.equal(fw.prependScrollAdjustment(0, 664), 0);

// clearWindow empties everything but keeps the generation (hard load failure).
const cleared = fw.clearWindow(wide);
assert.deepEqual(cleared.items, []);
assert.equal(cleared.cursor, null);
assert.equal(cleared.ids.length, 0);
assert.equal(cleared.generation, wide.generation);

console.log("PASS feed window machine pins the generation guard, load exclusivity, and trim math");
