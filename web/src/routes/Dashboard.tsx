import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import {
  UploadSimple,
  Play,
  Pause,
  Stop,
  ArrowClockwise,
  Question,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { RunStatus, ProgressEvent, Status } from "../lib/types";
import { Button, StatusBadge, cx } from "../components/ui";

const COUNT_ORDER: Status[] = ["done", "downloading", "pending", "failed", "skipped", "expired"];

export function Dashboard() {
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [cobaltOk, setCobaltOk] = useState<boolean | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [howto, setHowto] = useState<string | null>(null);
  const [howtoOpen, setHowtoOpen] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [library, setLibrary] = useState<{ index_enabled: number; thumbnail_width: 320 | 480 } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => api.status().then(setStatus).catch(() => {});

  useEffect(() => {
    refresh();
    api.health().then((h) => setCobaltOk(h.cobalt_reachable)).catch(() => setCobaltOk(false));
    api.librarySettings().then(setLibrary).catch(() => {});
    const poll = window.setInterval(refresh, 2000);
    const off = api.events((e) => {
      setEvents((prev) => [e, ...prev].slice(0, 200));
      if (e.event === "complete") refresh();
    });
    return () => {
      window.clearInterval(poll);
      off();
    };
  }, []);

  const running = !!status?.running;
  const paused = status?.state === "paused";

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportMsg("Importing…");
    try {
      const r = await api.importExport(file);
      setImportMsg(`Imported ${r.favorites} favorites · ${r.existing_files} existing files matched.`);
      refresh();
    } catch (err) {
      setImportMsg(`Import failed: ${(err as Error).message}`);
    }
  }

  async function updateLibrary(settings: { index_enabled?: boolean; thumbnail_width?: 320 | 480 }) {
    const next = await api.updateLibrarySettings(settings).catch(() => null);
    if (next) setLibrary(next);
  }

  async function act(a: "start" | "backfill" | "pause" | "continue" | "stop") {
    await api.syncAction(a).catch(() => {});
    refresh();
  }

  async function toggleHowto() {
    if (!howto) setHowto(await api.howto().catch(() => "Could not load instructions."));
    setHowtoOpen((o) => !o);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-ink">Sync</h1>
          <span className="inline-flex items-center gap-2 text-xs text-ink-dim">
            <span
              className={cx(
                "h-2 w-2 rounded-full",
                cobaltOk == null ? "bg-ink-faint" : cobaltOk ? "bg-ok" : "bg-bad",
              )}
            />
            Cobalt {cobaltOk == null ? "…" : cobaltOk ? "reachable" : "unreachable"}
          </span>
        </div>

        {/* Import */}
        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">Your TikTok export</h2>
              <p className="mt-0.5 text-sm text-ink-dim">Upload `user_data_tiktok.json` to load your favorites.</p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={toggleHowto}>
                <Question size={16} /> How to get it
              </Button>
              <Button onClick={() => fileRef.current?.click()}>
                <UploadSimple size={16} /> Upload
              </Button>
              <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={onFile} />
            </div>
          </div>
          {howtoOpen && howto && (
            <pre className="mt-4 whitespace-pre-wrap rounded-[var(--radius-control)] bg-elevated p-4 text-xs leading-relaxed text-ink-dim">
              {howto}
            </pre>
          )}
          {importMsg && <p className="mt-3 text-sm text-ink-dim">{importMsg}</p>}
        </section>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Library indexing</h2>
          <p className="mt-1 text-sm text-ink-dim">Creates thumbnails and records duration, dimensions, size, and media type during Sync so large Galleries stay fast.</p>
          <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm text-ink">
            <input type="checkbox" checked={library?.index_enabled === 1} onChange={(e) => updateLibrary({ index_enabled: e.target.checked })} />
            <span><span className="font-medium">Build Gallery index</span><span className="mt-0.5 block text-ink-dim">Recommended. Turning this off saves CPU and thumbnail space, but removes stored thumbnails and media-property filters/sorts.</span></span>
          </label>
          <div className="mt-4">
            <label className="block text-sm font-medium text-ink" htmlFor="thumbnail-quality">Thumbnail quality</label>
            <select id="thumbnail-quality" disabled={library?.index_enabled !== 1} value={library?.thumbnail_width ?? 480} onChange={(e) => updateLibrary({ thumbnail_width: Number(e.target.value) as 320 | 480 })} className="mt-1 h-10 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink disabled:opacity-50">
              <option value={480}>High — 480px WebP (about 275–825 MB / 11,000)</option>
              <option value={320}>Standard — 320px WebP (about 165–550 MB / 11,000)</option>
            </select>
          </div>
        </section>

        {/* Controls */}
        <section className="mb-4 flex flex-wrap items-center gap-2">
          {!running ? (
            <>
              <Button onClick={() => act("start")}>
                <Play size={16} weight="fill" /> Start sync
              </Button>
              <Button variant="ghost" onClick={() => act("backfill")}>
                <ArrowClockwise size={16} /> Backfill assets
              </Button>
            </>
          ) : (
            <>
              {paused ? (
                <Button onClick={() => act("continue")}>
                  <Play size={16} weight="fill" /> Continue
                </Button>
              ) : (
                <Button variant="ghost" onClick={() => act("pause")}>
                  <Pause size={16} weight="fill" /> Pause
                </Button>
              )}
              <Button variant="danger" onClick={() => act("stop")}>
                <Stop size={16} weight="fill" /> Stop
              </Button>
              <span className="text-xs text-ink-faint">
                {status?.phase} · {status?.state}
              </span>
            </>
          )}
        </section>

        {/* Counts */}
        <section className="mb-6 grid grid-cols-3 gap-2 sm:grid-cols-6">
          {COUNT_ORDER.map((s) => (
            <div key={s} className="rounded-[var(--radius-control)] border border-line bg-surface px-3 py-3">
              <div className="tabular text-lg font-semibold text-ink">{status?.counts?.[s] ?? 0}</div>
              <StatusBadge status={s} />
            </div>
          ))}
        </section>

        {/* Live log */}
        <section>
          <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-faint">Activity</h2>
          <div className="max-h-96 overflow-y-auto rounded-[var(--radius-media)] border border-line bg-surface">
            {events.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-ink-faint">No activity yet.</p>
            ) : (
              <ul className="divide-y divide-line">
                {events.map((e, i) => (
                  <li key={i} className="flex items-center justify-between px-4 py-2 text-sm">
                    {e.event ? (
                      <span className="text-ink-dim">{e.event === "complete" ? "Run complete" : `Error: ${e.error}`}</span>
                    ) : (
                      <>
                        <span className="tabular text-ink-dim">#{e.id}</span>
                        <span className="flex items-center gap-3">
                          {e.kind && <span className="text-xs text-ink-faint">{e.kind}</span>}
                          {e.status && <StatusBadge status={e.status} />}
                        </span>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
