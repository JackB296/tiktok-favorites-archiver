import { readdir } from "node:fs/promises";
import { basename } from "node:path";
import { fileURLToPath } from "node:url";

// Every test-*.mjs beside this runner is a suite. Discovering them here means
// a new file cannot be forgotten in a hand-kept list and silently never run.
// The runner excludes itself by its own filename rather than a hardcoded name.
const here = new URL("./", import.meta.url);
const self = basename(fileURLToPath(import.meta.url));
const suites = (await readdir(here))
  .filter((name) => /^test-.*\.mjs$/.test(name) && name !== self)
  .sort();

for (const suite of suites) {
  await import(`./${suite}`);
}

console.log(`PASS ${suites.length} frontend behavior suites`);
