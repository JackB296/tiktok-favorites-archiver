import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = (await readFile(new URL("../src/lib/schedulePresentation.ts", import.meta.url), "utf8")).replace('import type { RunSchedule } from "./types";', "");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const lib = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
assert.equal(lib.scheduleRule({ cadence: "weekly", weekday: 4, local_time: "02:30", timezone: "America/New_York" }), "weekly · Fri · 02:30 America/New_York");
assert.equal(lib.nextScheduleLabel({ enabled: false, next_due_at: "2026-01-01T00:00:00Z", last_outcome: "completed" }), "No next run · last completed");
console.log("schedule presentation checks passed");

