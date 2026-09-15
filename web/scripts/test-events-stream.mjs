import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

// api.ts only imports types, so the transpiled module loads in Node without a
// browser; subscribeEvents takes its EventSource factory and timer as
// parameters so no globals are needed.
const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const { subscribeEvents } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`,
);

class FakeSource {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.closed = false;
    FakeSource.instances.push(this);
  }
  close() {
    this.closed = true;
  }
}
FakeSource.instances = [];
const scheduled = [];
const events = [];
const off = subscribeEvents(
  (e) => events.push(e),
  (url) => new FakeSource(url),
  (fn, ms) => scheduled.push({ fn, ms }),
);
assert.equal(FakeSource.instances[0].url, "/api/events");

// 1. a data frame reaches the callback; keep-alives do not
FakeSource.instances[0].onmessage({ data: JSON.stringify({ event: "complete" }) });
FakeSource.instances[0].onmessage({ data: "" });
assert.deepEqual(events, [{ event: "complete" }]);

// 2. a permanently closed source is reopened with backoff
FakeSource.instances[0].readyState = 2;
FakeSource.instances[0].onerror();
assert.equal(FakeSource.instances[0].closed, true);
assert.deepEqual(scheduled.map((s) => s.ms), [1000]);
scheduled.shift().fn();
assert.equal(FakeSource.instances.length, 2);
FakeSource.instances[1].readyState = 2;
FakeSource.instances[1].onerror();
assert.deepEqual(scheduled.map((s) => s.ms), [2000]);

// 3. a transient error (readyState CONNECTING) is left to the browser
scheduled.shift().fn();
FakeSource.instances[2].readyState = 0;
FakeSource.instances[2].onerror();
assert.equal(scheduled.length, 0);
assert.equal(FakeSource.instances[2].closed, false);

// a successful open resets the backoff
FakeSource.instances[2].onopen();
FakeSource.instances[2].readyState = 2;
FakeSource.instances[2].onerror();
assert.deepEqual(scheduled.map((s) => s.ms), [1000]);
scheduled.shift().fn();
assert.equal(FakeSource.instances.length, 4);

// 4. unsubscribe closes and stops reconnecting
off();
assert.equal(FakeSource.instances[3].closed, true);
FakeSource.instances[3].readyState = 2;
FakeSource.instances[3].onerror();
assert.equal(scheduled.length, 0);
assert.equal(FakeSource.instances.length, 4);
console.log("PASS events stream reconnects after a closed EventSource and stops on unsubscribe");
