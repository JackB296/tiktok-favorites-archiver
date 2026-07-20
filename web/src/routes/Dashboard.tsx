import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  UploadSimple,
  Play,
  Pause,
  Stop,
  ArrowClockwise,
  Question,
  CaretDown,
  MusicNotes,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { RunStatus, ProgressEvent, Status, LibrarySettings, LibraryStatistics, VerifyReport, RunHistoryEntry, RunCatalogEntry, PipelineSettings, RunSchedule, SyncSettings } from "../lib/types";
import { Button, Stat, StatusBadge, cx } from "../components/ui";
import { LegacyBootstrapPanel } from "../components/LegacyBootstrapPanel";
import { OffloadPanel } from "../components/OffloadPanel";
import { formatRuntime, formatSize } from "../lib/format";
import { progressLabel } from "../lib/progressPresentation.js";
import { nextScheduleLabel, scheduleRule } from "../lib/schedulePresentation";

const COUNT_ORDER: Status[] = ["done", "downloading", "pending", "failed", "skipped", "ignored", "expired"];

type RunAction = "start" | "backfill" | "reindex" | "sidecars" | "enrich" | "identify" | "analyze" | "pause" | "continue" | "stop";

export function Dashboard() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [cobaltOk, setCobaltOk] = useState<boolean | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [howto, setHowto] = useState<string | null>(null);
  const [howtoOpen, setHowtoOpen] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [lastImportId, setLastImportId] = useState<number | null>(null);
  const [library, setLibrary] = useState<LibrarySettings | null>(null);
  const [statistics, setStatistics] = useState<LibraryStatistics | null>(null);
  const [indexProgress, setIndexProgress] = useState<ProgressEvent | null>(null);
  const [sidecarsProgress, setSidecarsProgress] = useState<ProgressEvent | null>(null);
  const [enrichmentProgress, setEnrichmentProgress] = useState<ProgressEvent | null>(null);
  const [identificationProgress, setIdentificationProgress] = useState<ProgressEvent | null>(null);
  const [backfillProgress, setBackfillProgress] = useState<ProgressEvent | null>(null);
  const [runActionError, setRunActionError] = useState<{ action: RunAction; message: string } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [verifyReport, setVerifyReport] = useState<VerifyReport | null>(null);
  const [verifyMsg, setVerifyMsg] = useState<string | null>(null);
  const [runHistory, setRunHistory] = useState<RunHistoryEntry[]>([]);
  const [syncSettings, setSyncSettings] = useState<SyncSettings | null>(null);
  const [runCatalog, setRunCatalog] = useState<RunCatalogEntry[]>([]);
  const [pipeline, setPipeline] = useState<PipelineSettings | null>(null);
  const [schedules, setSchedules] = useState<RunSchedule[]>([]);
  const [scheduleName, setScheduleName] = useState("Nightly Sync");
  const [scheduleKind, setScheduleKind] = useState("sync");
  const [scheduleCadence, setScheduleCadence] = useState<"daily" | "weekly">("daily");
  const [scheduleTime, setScheduleTime] = useState("02:00");
  const [scheduleWeekday, setScheduleWeekday] = useState(0);
  const [scheduleZone, setScheduleZone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [automationMessage, setAutomationMessage] = useState<string | null>(null);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const [songIdOpen, setSongIdOpen] = useState(false);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [audioMsg, setAudioMsg] = useState<string | null>(null);
  const [audioBusy, setAudioBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const defaultAudioRef = useRef<HTMLInputElement>(null);

  const refresh = () => api.status().then(setStatus).catch(() => {});
  const refreshLibrary = () => api.librarySettings().then(setLibrary).catch(() => {});
  const refreshStatistics = () => api.libraryStats().then(setStatistics).catch(() => {});
  const refreshRunHistory = () => api.runHistory().then(setRunHistory).catch(() => {});

  /** Initial page data. Unlike the silent periodic refreshes, a failure here means
      the dashboard would render as an empty library, so surface it with a retry. */
  async function loadCore() {
    setLoadError(null);
    const results = await Promise.allSettled([
      api.status().then(setStatus),
      api.librarySettings().then(setLibrary),
      api.libraryStats().then(setStatistics),
      api.runHistory().then(setRunHistory),
      api.syncSettings().then(setSyncSettings),
      api.runCatalog().then(setRunCatalog),
      api.pipelineSettings().then(setPipeline),
      api.runSchedules().then(setSchedules),
    ]);
    const failed = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
    if (failed) setLoadError((failed.reason as Error).message || "Request failed");
  }

  async function savePipeline(phases: string[]) {
    try {
      setPipeline(await api.updatePipelineSettings(phases));
      setAutomationMessage("Sync pipeline saved.");
    } catch (error) {
      setAutomationMessage((error as Error).message);
    }
  }

  async function addSchedule() {
    try {
      const created = await api.createRunSchedule({
        name: scheduleName, run_kind: scheduleKind, cadence: scheduleCadence,
        local_time: scheduleTime,
        weekday: scheduleCadence === "weekly" ? scheduleWeekday : null,
        timezone: scheduleZone, enabled: true,
      });
      setSchedules((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)));
      setAutomationMessage("Schedule created.");
    } catch (error) {
      setAutomationMessage((error as Error).message);
    }
  }

  async function toggleSchedule(schedule: RunSchedule) {
    try {
      const updated = await api.updateRunSchedule(schedule.id, { enabled: !schedule.enabled });
      setSchedules((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      setAutomationMessage((error as Error).message);
    }
  }

  async function removeSchedule(id: number) {
    try {
      await api.deleteRunSchedule(id);
      setSchedules((current) => current.filter((item) => item.id !== id));
    } catch (error) {
      setAutomationMessage((error as Error).message);
    }
  }

  async function retryRun(run: RunHistoryEntry) {
    try {
      await api.retryRun(run.id);
      setAutomationMessage(`Retry started from run #${run.id}.`);
      refresh();
    } catch (error) {
      setAutomationMessage((error as Error).message);
    }
  }

  useEffect(() => {
    void loadCore();
    api.health().then((h) => setCobaltOk(h.cobalt_reachable)).catch(() => setCobaltOk(false));
    const poll = window.setInterval(refresh, 2000);
    const off = api.events((e) => {
      setEvents((prev) => [e, ...prev].slice(0, 200));
      if (e.event === "indexing") setIndexProgress(e);
      if (e.event === "sidecars") setSidecarsProgress(e);
      if (e.event === "enrichment") setEnrichmentProgress(e);
      if (e.event === "identification") setIdentificationProgress(e);
      if (e.event === "backfill") setBackfillProgress(e);
      if (e.event === "complete") {
        refresh();
        refreshLibrary();
        refreshStatistics();
        refreshRunHistory();
      }
    });
    return () => {
      window.clearInterval(poll);
      off();
    };
  }, []);

  const running = !!status?.running;
  const paused = status?.state === "paused";

  useEffect(() => {
    if (!running) return;
    if (status?.phase === "enrich") setMetadataOpen(true);
    if (status?.phase === "identify") setSongIdOpen(true);
    if (["index", "sidecars", "backfill"].includes(status?.phase ?? "")) setMaintenanceOpen(true);
  }, [running, status?.phase]);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportMsg("Importing…");
    setLastImportId(null);
    try {
      const r = await api.importExport(file);
      const counts = r.import_record.comparison.counts;
      setImportMsg(`Imported ${r.favorites} favorites · ${counts.new} new · ${counts.removed} missing · ${counts.protected} safely archived.`);
      setLastImportId(r.import_record.id);
      refresh();
    } catch (err) {
      setImportMsg(`Import failed: ${(err as Error).message}`);
    }
  }

  async function updateLibrary(settings: { index_enabled?: boolean; thumbnail_width?: 320 | 480; song_id_enabled?: boolean }) {
    const next = await api.updateLibrarySettings(settings).catch(() => null);
    if (next) setLibrary(next);
  }

  async function updateSyncSettings(concurrency: number) {
    const next = await api.updateSyncSettings({ concurrency }).catch(() => null);
    if (next) setSyncSettings(next);
  }

  async function onDefaultAudio(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setAudioBusy(true);
    setAudioMsg(null);
    try {
      const next = await api.setDefaultAudio(file);
      setLibrary(next);
      setAudioMsg(`Now using ${next.default_audio_name} when a slideshow's original sound is gone.`);
    } catch (err) {
      setAudioMsg(`Upload failed: ${(err as Error).message}`);
    } finally {
      setAudioBusy(false);
    }
  }

  async function clearDefaultAudio() {
    setAudioBusy(true);
    setAudioMsg(null);
    try {
      setLibrary(await api.clearDefaultAudio());
      setAudioMsg("Reverted to the bundled default track.");
    } catch (err) {
      setAudioMsg((err as Error).message);
    } finally {
      setAudioBusy(false);
    }
  }

  async function act(a: RunAction) {
    setRunActionError(null);
    if (a === "enrich") setEnrichmentProgress(null);
    if (a === "identify") setIdentificationProgress(null);
    if (a === "backfill") setBackfillProgress(null);
    try {
      const result = await api.syncAction(a);
      if ("started" in result && result.started === false) setRunActionError({ action: a, message: "Another Archive run is already active." });
    } catch (error) {
      setRunActionError({ action: a, message: (error as Error).message });
    } finally {
      refresh();
    }
  }

  /** The error from the last run action, shown only next to the control that caused it. */
  function actionError(...actions: RunAction[]) {
    return runActionError && actions.includes(runActionError.action) ? runActionError.message : null;
  }

  async function runVerify() {
    setVerifyMsg("Checking…");
    try {
      setVerifyReport(await api.verify());
      setVerifyMsg(null);
    } catch (err) {
      setVerifyMsg((err as Error).message);
    }
  }

  async function requeueMissing() {
    try {
      const r = await api.requeueMissing();
      await runVerify();
      setVerifyMsg(`${r.requeued} favorites queued for the next sync.`);
      refresh();
    } catch (err) {
      setVerifyMsg((err as Error).message);
    }
  }

  async function toggleHowto() {
    if (!howto) setHowto(await api.howto().catch(() => "Could not load instructions."));
    setHowtoOpen((o) => !o);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        {loadError && (
          <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
            <span>Couldn't load the archive overview: {loadError}</span>
            <Button variant="ghost" size="sm" onClick={() => void loadCore()}>Try again</Button>
          </div>
        )}
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
          {importMsg && (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <p className="text-sm text-ink-dim" role="status">{importMsg}</p>
              {lastImportId != null && <Button variant="ghost" size="xs" onClick={() => navigate("/history")}>View comparison</Button>}
            </div>
          )}
        </section>

        <LegacyBootstrapPanel
          running={running}
          onApplied={() => Promise.all([refresh(), refreshLibrary(), refreshStatistics(), refreshRunHistory()]).then(() => {})}
        />

        <details open={metadataOpen} onToggle={(event) => setMetadataOpen(event.currentTarget.open)} className="group mb-4 rounded-[var(--radius-media)] border border-line bg-surface">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-semibold text-ink"><span>Gallery search metadata{running && status?.phase === "enrich" ? <span className="ml-2 text-xs font-normal text-active">running</span> : null}</span><CaretDown size={16} className="text-ink-faint transition group-open:rotate-180" /></summary>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4">
            <div>
              <p className="mt-1 text-sm text-ink-dim">Fetches missing captions and creators from TikTok so author, hashtag, and caption search cover more of the archive. This makes one rate-limited request per favorite that has no caption yet; it can be paused or stopped. It also runs automatically after every Sync, so new favorites get their metadata without another click.</p>
            </div>
            <Button variant="ghost" disabled={running} onClick={() => act("enrich")}>
              <ArrowClockwise size={16} /> Fetch missing metadata
            </Button>
          {enrichmentProgress?.event === "enrichment" && (
            <p className="mt-3 text-sm text-ink-dim">
              {`Checking ${enrichmentProgress.completed ?? 0} of ${enrichmentProgress.total ?? 0}: ${enrichmentProgress.enriched ?? 0} updated, ${enrichmentProgress.unavailable ?? 0} returned no metadata`}
            </p>
          )}
          {actionError("enrich") && <p className="mt-3 text-sm text-bad" role="alert">{actionError("enrich")}</p>}
          </div>
        </details>

        <details open={songIdOpen} onToggle={(event) => setSongIdOpen(event.currentTarget.open)} className="group mb-4 rounded-[var(--radius-media)] border border-line bg-surface">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-semibold text-ink"><span>Song identification{running && status?.phase === "identify" ? <span className="ml-2 text-xs font-normal text-active">running</span> : null}</span><CaretDown size={16} className="text-ink-faint transition group-open:rotate-180" /></summary>
          <div className="border-t border-line px-5 py-4">
            <p className="text-sm text-ink-dim">Identifies the song in each favorite with Shazam and shows it in Feed and Gallery. This is the one feature that leaves your machine: when enabled, a short audio clip per video is sent to Shazam's servers to match it. It runs one rate-limited request at a time and can be paused or stopped. While enabled, it also runs automatically after every Sync, so newly downloaded favorites get their songs without another click.</p>
            <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm text-ink">
              <input type="checkbox" checked={library?.song_id_enabled === 1} onChange={(e) => updateLibrary({ song_id_enabled: e.target.checked })} />
              <span><span className="font-medium">Enable song identification</span><span className="mt-0.5 block text-ink-dim">Off by default. Turning this on allows short audio clips to be sent to Shazam. While it is off, no audio ever leaves your machine and the run cannot start.</span></span>
            </label>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
              <p className="text-sm text-ink-dim">
                {identificationProgress?.event === "identification"
                  ? `Identifying ${identificationProgress.completed ?? 0} of ${identificationProgress.total ?? 0}: ${identificationProgress.identified ?? 0} found, ${identificationProgress.no_match ?? 0} no match${identificationProgress.errors ? `, ${identificationProgress.errors} errors` : ""}`
                  : "Runs over finished favorites that have audio and no song yet. Re-running skips ones already identified."}
              </p>
              <Button variant="ghost" disabled={running || library?.song_id_enabled !== 1} onClick={() => act("identify")}>
                <MusicNotes size={16} /> Identify songs
              </Button>
            </div>
            {actionError("identify") && <p className="mt-3 text-sm text-bad" role="alert">{actionError("identify")}</p>}
          </div>
        </details>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Archive at a glance</h2>
          <p className="mt-1 text-sm text-ink-dim">Totals use downloaded and indexed media already present in this archive.</p>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Favorites" value={statistics?.favorites ?? 0} hint={`${statistics?.ready ?? 0} ready`} />
            <Stat label="Media mix" value={`${statistics?.videos ?? 0} videos`} hint={`${statistics?.slideshows ?? 0} slideshows`} />
            <Stat label="Indexed runtime" value={formatRuntime(statistics?.duration_s ?? 0)} hint={`${statistics?.indexed ?? 0} indexed`} />
            <Stat label="Indexed media" value={formatSize(statistics?.media_size ?? 0)} hint="video files only" />
          </div>
        </section>

        <details open={maintenanceOpen} onToggle={(event) => setMaintenanceOpen(event.currentTarget.open)} className="group mb-4 rounded-[var(--radius-media)] border border-line bg-surface">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4"><span><span className="block text-sm font-semibold text-ink">Maintenance & settings</span><span className="mt-0.5 block text-xs font-normal text-ink-dim">Indexing, performance, inventory, media-server files, integrity, and run history</span></span><CaretDown size={16} className="shrink-0 text-ink-faint transition group-open:rotate-180" /></summary>
          <div className="border-t border-line p-4">

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Library indexing</h2>
          <p className="mt-1 text-sm text-ink-dim">Creates thumbnails and records duration, dimensions, size, and media type during Sync so large Galleries stay fast.</p>
          <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm text-ink">
            <input type="checkbox" checked={library?.index_enabled === 1} onChange={(e) => updateLibrary({ index_enabled: e.target.checked })} />
            <span><span className="font-medium">Build Gallery index</span><span className="mt-0.5 block text-ink-dim">Recommended. Turning this off saves CPU and thumbnail space, but removes stored thumbnails and media-property filters/sorts.</span></span>
          </label>
          <div className="mt-4">
            <label className="block text-sm font-medium text-ink" htmlFor="thumbnail-quality">Thumbnail quality</label>
            <select id="thumbnail-quality" disabled={library?.index_enabled !== 1} value={library?.thumbnail_width ?? 480} onChange={(e) => updateLibrary({ thumbnail_width: Number(e.target.value) as 320 | 480 })} className="mt-1 h-10 w-full max-w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink disabled:opacity-50 sm:w-auto">
              <option value={480}>High: 480px WebP (about 275-825 MB / 11,000)</option>
              <option value={320}>Standard: 320px WebP (about 165-550 MB / 11,000)</option>
            </select>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
            <p className="text-sm text-ink-dim">
              {indexProgress?.event === "indexing"
                ? `Indexing ${indexProgress.completed ?? 0} of ${indexProgress.total ?? 0} · ${indexProgress.failed ?? 0} failed`
                : `${library?.index.indexed ?? 0} of ${library?.index.total ?? 0} local favorites indexed${library?.index.pending ? `, ${library.index.pending} pending` : ""}${library?.index.failed ? `, ${library.index.failed} failed` : ""}`}
            </p>
            <Button variant="ghost" disabled={running || library?.index_enabled !== 1} onClick={() => act("reindex")}>
              <ArrowClockwise size={16} /> Rebuild index
            </Button>
          </div>
          {actionError("reindex") && <p className="mt-3 text-sm text-bad" role="alert">{actionError("reindex")}</p>}
          <p className="mt-2 text-xs text-ink-faint">Rebuild refreshes existing thumbnails and media facts. It is available when indexing is enabled and can be paused or stopped like Sync.</p>
        </section>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Slideshow fallback audio</h2>
          <p className="mt-1 text-sm text-ink-dim">Photo posts are rebuilt with their original sound. When TikTok has already deleted that audio, this track fills in instead. A change applies to slideshows built from now on; existing videos keep the audio they were made with.</p>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
            <p className="text-sm text-ink-dim">Current: {library?.default_audio_name ? <span className="font-medium text-ink">{library.default_audio_name}</span> : "Bundled default"}</p>
            <div className="flex items-center gap-2">
              {library?.default_audio_name && <Button variant="ghost" disabled={audioBusy} onClick={() => void clearDefaultAudio()}>Use bundled</Button>}
              <Button variant="ghost" disabled={audioBusy} onClick={() => defaultAudioRef.current?.click()}><UploadSimple size={16} /> {audioBusy ? "Uploading…" : "Upload MP3"}</Button>
              <input ref={defaultAudioRef} type="file" accept="audio/mpeg,.mp3" hidden onChange={onDefaultAudio} />
            </div>
          </div>
          {library?.default_audio_name && <audio controls src="/media/.archive/default-audio.mp3" className="mt-3 w-full" />}
          {audioMsg && <p className="mt-3 text-sm text-ink-dim">{audioMsg}</p>}
        </section>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Archive performance</h2>
          <p className="mt-1 text-sm text-ink-dim">Choose how many favorites Sync and Backfill process at once. This setting is saved locally and takes effect on the next run; keep it low if Cobalt is rate-limiting.</p>
          <label className="mt-4 block text-sm font-medium text-ink" htmlFor="sync-concurrency">Parallel downloads</label>
          <select id="sync-concurrency" value={syncSettings?.concurrency ?? status?.concurrency ?? 4} onChange={(e) => updateSyncSettings(Number(e.target.value))} className="mt-1 h-10 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink">
            {[1, 2, 4, 6, 8, 12, 16].map((value) => <option key={value} value={value}>{value} at a time{value === 4 ? " (recommended)" : ""}</option>)}
          </select>
          <p className="mt-2 text-xs text-ink-faint">Cobalt’s own rate limit remains a Docker setting so the two services stay in agreement.</p>
        </section>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">Archive inventory</h2>
              <p className="mt-1 text-sm text-ink-dim">Download a compact CSV of every favorite and its source link, status, retry history, file health, and indexed media facts. It is useful for backup records or spreadsheet analysis; media files are not copied.</p>
            </div>
            <a href="/api/archive-inventory.csv" download className="inline-flex h-9 items-center rounded-[var(--radius-control)] border border-line px-3 text-sm font-medium text-ink-dim transition-[background,color] duration-150 hover:bg-elevated hover:text-ink">Download CSV</a>
          </div>
        </section>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">Media server metadata</h2>
              <p className="mt-1 text-sm text-ink-dim">
                Writes an <code>.nfo</code> title file and a <code>.jpg</code> poster next to each video so Plex, Jellyfin, or Kodi show real titles and artwork instead of numbers. Your media files are never modified.
              </p>
            </div>
            <Button variant="ghost" disabled={running} onClick={() => act("sidecars")}>
              <ArrowClockwise size={16} /> Write metadata
            </Button>
          </div>
          {sidecarsProgress?.event === "sidecars" && (
            <p className="mt-3 text-sm text-ink-dim">
              {`Writing ${sidecarsProgress.completed ?? 0} of ${sidecarsProgress.total ?? 0}${sidecarsProgress.failed ? ` · ${sidecarsProgress.failed} failed` : ""}`}
            </p>
          )}
          {actionError("sidecars") && <p className="mt-3 text-sm text-bad" role="alert">{actionError("sidecars")}</p>}
        </section>

        <OffloadPanel
          running={running}
          onChanged={() => Promise.all([
            verifyReport ? api.verify().then(setVerifyReport).catch(() => {}) : Promise.resolve(),
            refreshStatistics(),
            refresh(),
          ]).then(() => {})}
        />

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">Archive integrity</h2>
              <p className="mt-1 text-sm text-ink-dim">Checks that every finished favorite has its video on disk and reports strays and leftover temp files. Read-only.</p>
            </div>
            <Button variant="ghost" onClick={runVerify}>
              <Question size={16} /> Verify archive
            </Button>
          </div>
          {verifyReport && (
            <div className="mt-3 space-y-1 text-sm text-ink-dim">
              {verifyReport.ok ? (
                <p>All good: {verifyReport.done} finished favorites, every file accounted for.</p>
              ) : (
                <>
                  {verifyReport.missing.count > 0 && (
                    <p>
                      {verifyReport.missing.count} finished favorites are missing their video
                      {" (e.g. "}{verifyReport.missing.examples.slice(0, 5).map((n) => `#${n}`).join(", ")}{")."}
                      <button type="button" onClick={requeueMissing} disabled={running} className="ml-2 text-ink underline underline-offset-2 disabled:opacity-40">Queue them for the next sync</button>
                    </p>
                  )}
                  {verifyReport.orphans.count > 0 && (
                    <p>{verifyReport.orphans.count} video files on disk have no matching favorite. Re-import your export to adopt them.</p>
                  )}
                  {verifyReport.leftovers.count > 0 && (
                    <p>{verifyReport.leftovers.count} leftover temp files from interrupted work (safe to delete): {verifyReport.leftovers.examples.slice(0, 3).join(", ")}{verifyReport.leftovers.count > 3 ? ", …" : ""}</p>
                  )}
                </>
              )}
              {verifyReport.offloaded > 0 && <p>{verifyReport.offloaded} favorites archived externally.</p>}
            </div>
          )}
          {verifyMsg && <p className="mt-2 text-sm text-ink-dim">{verifyMsg}</p>}
        </section>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Sync pipeline</h2>
          <p className="mt-1 text-sm text-ink-dim">Sync always downloads first. Choose and order the maintenance phases that follow it.</p>
          <ol className="mt-3 space-y-2 text-sm">
            <li className="flex items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 py-2"><span className="tabular text-ink-faint">1</span><strong className="text-ink">Sync</strong><span className="ml-auto text-xs text-ink-faint">required</span></li>
            {(pipeline?.phases.slice(1) ?? []).map((phase, index, phases) => {
              const entry = runCatalog.find((item) => item.kind === phase);
              return <li key={phase} className="flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 py-2">
                <span className="tabular text-ink-faint">{index + 2}</span><span className="font-medium text-ink">{entry?.label ?? phase}</span>
                <span className="ml-auto flex gap-1">
                  <Button variant="ghost" size="xs" disabled={index === 0} onClick={() => { const next = [...phases]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; void savePipeline(["sync", ...next]); }}>Up</Button>
                  <Button variant="ghost" size="xs" disabled={index === phases.length - 1} onClick={() => { const next = [...phases]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; void savePipeline(["sync", ...next]); }}>Down</Button>
                  <Button variant="ghost" size="xs" onClick={() => void savePipeline(["sync", ...phases.filter((item) => item !== phase)])}>Remove</Button>
                </span>
              </li>;
            })}
          </ol>
          <div className="mt-3 flex flex-wrap gap-2">
            {runCatalog.filter((entry) => entry.configurable_follow_up && !pipeline?.phases.includes(entry.kind)).map((entry) => <Button key={entry.kind} variant="ghost" size="xs" onClick={() => void savePipeline([...(pipeline?.phases ?? ["sync"]), entry.kind])}>Add {entry.label}</Button>)}
          </div>
        </section>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Run schedules</h2>
          <p className="mt-1 text-sm text-ink-dim">Runs inside this app. A missed run catches up once when the app is next open and idle.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-ink-dim">Name<input value={scheduleName} onChange={(event) => setScheduleName(event.target.value)} maxLength={80} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" /></label>
            <label className="text-xs text-ink-dim">Run<select value={scheduleKind} onChange={(event) => setScheduleKind(event.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink">{runCatalog.filter((entry) => ["sync", "backfill", "index", "sidecars", "enrich", "identify", "analyze"].includes(entry.kind)).map((entry) => <option key={entry.kind} value={entry.kind}>{entry.label}</option>)}</select></label>
            <label className="text-xs text-ink-dim">Cadence<select value={scheduleCadence} onChange={(event) => setScheduleCadence(event.target.value as "daily" | "weekly")} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>
            {scheduleCadence === "weekly" && <label className="text-xs text-ink-dim">Weekday<select value={scheduleWeekday} onChange={(event) => setScheduleWeekday(Number(event.target.value))} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink">{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, index) => <option key={day} value={index}>{day}</option>)}</select></label>}
            <label className="text-xs text-ink-dim">Local time<input type="time" value={scheduleTime} onChange={(event) => setScheduleTime(event.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" /></label>
            <label className="text-xs text-ink-dim">IANA timezone<input value={scheduleZone} onChange={(event) => setScheduleZone(event.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" /></label>
          </div>
          <Button className="mt-3" size="sm" onClick={() => void addSchedule()} disabled={!scheduleName.trim()}>Create schedule</Button>
          {schedules.length ? <ul className="mt-4 divide-y divide-line text-sm">{schedules.map((schedule) => <li key={schedule.id} className="flex flex-wrap items-center gap-2 py-3">
            <button type="button" onClick={() => void toggleSchedule(schedule)} aria-pressed={schedule.enabled} className={cx("rounded-full border px-2 py-1 text-xs", schedule.enabled ? "border-ok/40 text-ok" : "border-line text-ink-faint")}>{schedule.enabled ? "Enabled" : "Disabled"}</button>
            <span className="font-medium text-ink">{schedule.name}</span>
            <span className="text-ink-dim">{scheduleRule(schedule)}</span>
            <span className="ml-auto text-xs text-ink-faint">{nextScheduleLabel(schedule)}</span>
            <Button variant="danger" size="xs" onClick={() => void removeSchedule(schedule.id)}>Delete</Button>
          </li>)}</ul> : <p className="mt-4 text-sm text-ink-faint">No schedules yet.</p>}
          {automationMessage && <p className="mt-3 text-xs text-ink-dim" role="status">{automationMessage}</p>}
        </section>

        <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Recent archive runs</h2>
          <p className="mt-1 text-sm text-ink-dim">Stored locally so you can see what finished after the live activity log has cleared.</p>
          {runHistory.length ? <ul className="mt-3 divide-y divide-line text-sm">{runHistory.slice(0, 12).map((run) => <li key={run.id} className="flex flex-wrap items-center gap-2 py-2"><span className="tabular text-xs text-ink-faint">#{run.id}</span><span className="capitalize text-ink">{run.phase}</span><span className="text-ink-dim">{run.outcome ?? "running"}: {run.counts.done ?? 0} ready, {run.counts.failed ?? 0} failed</span>{run.retry_of && <span className="text-xs text-ink-faint">retry of #{run.retry_of}</span>}<time className="ml-auto text-xs text-ink-faint" dateTime={run.started_at}>{new Date(run.started_at).toLocaleString()}</time>{(run.outcome === "failed" || run.outcome === "stopped") && runCatalog.find((entry) => entry.kind === run.kind)?.resumable && <Button variant="ghost" size="xs" disabled={running} onClick={() => void retryRun(run)}>Retry</Button>}{run.error && <span className="w-full text-xs text-bad">{run.error}</span>}</li>)}</ul> : <p className="mt-3 text-sm text-ink-faint">No completed archive runs yet.</p>}
        </section>
          </div>
        </details>

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
              <Button variant="ghost" disabled={!status?.counts?.failed} onClick={() => navigate("/gallery?status=failed")}>
                Review {status?.counts?.failed ?? 0} failed
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
          {actionError("start", "backfill", "pause", "continue", "stop") && <p className="w-full text-sm text-bad" role="alert">{actionError("start", "backfill", "pause", "continue", "stop")}</p>}
          {backfillProgress?.event === "backfill" && (
            <span className="basis-full text-sm text-ink-dim">
              {`Backfill: checked ${backfillProgress.completed ?? 0} of ${backfillProgress.total ?? 0} favorites, ${backfillProgress.recovered ?? 0} slideshows recovered`}
            </span>
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
                      <span className={e.event === "error" ? "text-bad" : "text-ink-dim"}>{progressLabel(e) ?? e.event}</span>
                    ) : (
                      <>
                        <span className="tabular text-ink-dim">#{e.id}</span>
                        <span className="flex items-center gap-3">
                          {(e.item_kind ?? e.kind) && <span className="text-xs text-ink-faint">{e.item_kind ?? e.kind}</span>}
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
