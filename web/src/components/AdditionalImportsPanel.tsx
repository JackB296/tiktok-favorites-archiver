import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, InputHTMLAttributes } from "react";
import { CaretDown, FolderOpen, UserPlus } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { CreatorMonitor, MyfaveTTPlan } from "../lib/types";
import { Button } from "./ui";

function relativePath(file: File) {
  return (file.webkitRelativePath || file.name).replace(/\\/g, "/");
}

export function AdditionalImportsPanel({ running, onChanged }: {
  running: boolean;
  onChanged: () => void;
}) {
  const [username, setUsername] = useState("");
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileMsg, setProfileMsg] = useState<string | null>(null);
  const [startSync, setStartSync] = useState(true);
  const [monitorCreator, setMonitorCreator] = useState(true);
  const [monitorInterval, setMonitorInterval] = useState(6);
  const [archiveMode, setArchiveMode] = useState<"all" | "matching">("all");
  const [keywords, setKeywords] = useState("");
  const [excludeReposts, setExcludeReposts] = useState(false);
  const [backlogDays, setBacklogDays] = useState("");
  const [collectComments, setCollectComments] = useState(true);
  const [analyzeNew, setAnalyzeNew] = useState(false);
  const [identifySongs, setIdentifySongs] = useState(false);
  const [monitors, setMonitors] = useState<CreatorMonitor[]>([]);
  const [folderFiles, setFolderFiles] = useState<Map<string, File>>(new Map());
  const [plan, setPlan] = useState<MyfaveTTPlan | null>(null);
  const [folderBusy, setFolderBusy] = useState(false);
  const [folderMsg, setFolderMsg] = useState<string | null>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  const refreshMonitors = () => api.creatorMonitors().then(setMonitors).catch(() => setMonitors([]));
  useEffect(() => { void refreshMonitors(); }, []);

  async function importUsername() {
    if (!username.trim()) return;
    setProfileBusy(true);
    setProfileMsg(`Reading @${username.replace(/^@/, "")}…`);
    try {
      const result = await api.importProfile(username, startSync, monitorCreator, monitorInterval, {
        archive_mode: archiveMode,
        keywords: keywords.split(",").map((value) => value.trim()).filter(Boolean),
        exclude_reposts: excludeReposts,
        max_backlog_days: backlogDays ? Number(backlogDays) : null,
        collect_comments: collectComments,
        analyze_new: analyzeNew,
        identify_songs: identifySongs,
      });
      setProfileMsg(
        `Found ${result.discovered} videos · ${result.added} added · ${result.existing} already known` +
        (startSync ? (result.sync_started ? " · Sync started." : " · Added, but Sync could not start.") : "."),
      );
      onChanged();
      await refreshMonitors();
    } catch (error) {
      setProfileMsg(`Profile import failed: ${(error as Error).message}`);
    } finally {
      setProfileBusy(false);
    }
  }

  async function chooseFolder(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []);
    const byPath = new Map(selected.map((file) => [relativePath(file), file]));
    setFolderFiles(byPath);
    setPlan(null);
    setFolderBusy(true);
    setFolderMsg("Scanning myfaveTT filenames…");
    try {
      const next = await api.planMyfaveTTImport([...byPath.keys()]);
      setPlan(next);
      setFolderMsg(
        `Found ${next.video_files} videos · ${next.counts.ready} ready to import · ` +
        `${next.counts.already_archived} already archived.`,
      );
    } catch (error) {
      setFolderMsg(`Folder scan failed: ${(error as Error).message}`);
    } finally {
      setFolderBusy(false);
    }
  }

  async function importFolder() {
    if (!plan) return;
    const ready = plan.items.filter((item) => item.status === "ready");
    setFolderBusy(true);
    let imported = 0;
    try {
      for (const item of ready) {
        const file = folderFiles.get(item.relative_path);
        if (!file) throw new Error(`Selected folder no longer contains ${item.relative_path}`);
        setFolderMsg(`Importing ${imported + 1} of ${ready.length}: ${item.video_id}.mp4…`);
        await api.importMyfaveTTVideo(item.video_id, item.relative_path, file);
        imported += 1;
      }
      setFolderMsg(
        `Imported ${imported} videos · filled ${ready.filter((item) => item.match === "archive_slot").length} existing archive slots · ` +
        `created ${ready.filter((item) => item.match === "new_local_item").length} local-only items.`,
      );
      setPlan(null);
      setFolderFiles(new Map());
      if (folderRef.current) folderRef.current.value = "";
      onChanged();
    } catch (error) {
      setFolderMsg(`Stopped after ${imported} imports: ${(error as Error).message}`);
    } finally {
      setFolderBusy(false);
    }
  }

  const directoryAttributes = { webkitdirectory: "", directory: "" } as InputHTMLAttributes<HTMLInputElement>;

  return (
    <details className="group mb-4 rounded-[var(--radius-media)] border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-semibold text-ink">
        <span>More ways to add videos</span>
        <CaretDown size={16} className="text-ink-faint transition group-open:rotate-180" />
      </summary>
      <div className="space-y-5 border-t border-line px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">Archive a public username</h3>
          <p className="mt-1 text-sm text-ink-dim">Discover all public posts from a TikTok creator, add new ones oldest-first, then download them through the normal Sync pipeline.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="@username" className="h-10 min-w-48 flex-1 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink" />
            <Button onClick={importUsername} disabled={running || profileBusy || folderBusy || !username.trim()}><UserPlus size={16} /> {profileBusy ? "Discovering…" : "Add creator"}</Button>
          </div>
          <label className="mt-2 flex items-center gap-2 text-xs text-ink-dim"><input type="checkbox" checked={startSync} onChange={(event) => setStartSync(event.target.checked)} /> Start Sync after discovery</label>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-ink-dim">
            <label className="flex items-center gap-2"><input type="checkbox" checked={monitorCreator} onChange={(event) => setMonitorCreator(event.target.checked)} /> Keep checking this creator automatically</label>
            {monitorCreator && <label className="flex items-center gap-2">Every <select value={monitorInterval} onChange={(event) => setMonitorInterval(Number(event.target.value))} className="h-8 rounded border border-line bg-elevated px-2 text-ink"><option value={1}>hour</option><option value={6}>6 hours</option><option value={12}>12 hours</option><option value={24}>day</option><option value={168}>week</option></select></label>}
          </div>
          <details className="mt-3 rounded-[var(--radius-control)] border border-line bg-elevated/40 p-3 text-xs text-ink-dim">
            <summary className="cursor-pointer font-medium text-ink">Creator rules and automatic enrichment</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label>Archive <select value={archiveMode} onChange={(event) => setArchiveMode(event.target.value as "all" | "matching")} className="ml-2 h-8 rounded border border-line bg-surface px-2 text-ink"><option value="all">all posts</option><option value="matching">matching captions</option></select></label>
              {archiveMode === "matching" && <label>Keywords <input value={keywords} onChange={(event) => setKeywords(event.target.value)} placeholder="recipe, pottery" className="ml-2 h-8 rounded border border-line bg-surface px-2 text-ink" /></label>}
              <label>Backlog limit <select value={backlogDays} onChange={(event) => setBacklogDays(event.target.value)} className="ml-2 h-8 rounded border border-line bg-surface px-2 text-ink"><option value="">all existing posts</option><option value="30">last 30 days</option><option value="90">last 90 days</option><option value="365">last year</option></select></label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={excludeReposts} onChange={(event) => setExcludeReposts(event.target.checked)} /> Skip detected reposts</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={collectComments} onChange={(event) => setCollectComments(event.target.checked)} /> Archive comments when available</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={analyzeNew} onChange={(event) => setAnalyzeNew(event.target.checked)} /> Generate local transcripts and OCR</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={identifySongs} onChange={(event) => setIdentifySongs(event.target.checked)} /> Identify songs (requires opt-in)</label>
            </div>
          </details>
          {profileMsg && <p className="mt-2 text-sm text-ink-dim" role="status">{profileMsg}</p>}
          {monitors.length > 0 && <div className="mt-4 border-t border-line pt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Monitored creators</p>
            <ul className="mt-2 divide-y divide-line">{monitors.map((monitor) => <li key={monitor.id} className="flex flex-wrap items-center gap-2 py-2 text-xs">
              <span className="font-medium text-ink">@{monitor.username}</span>
              <span className="text-ink-faint">every {monitor.interval_hours}h{monitor.last_new_count ? ` · ${monitor.last_new_count} new last check` : ""}</span>
              <span className="text-ink-faint">· {monitor.archive_mode === "matching" ? `matching ${monitor.keywords.join(", ")}` : "all posts"}{monitor.max_backlog_days ? ` · ${monitor.max_backlog_days}d backlog` : ""}</span>
              {monitor.last_error && <span className="text-bad" title={monitor.last_error}>last check failed</span>}
              {monitor.last_changed_count > 0 && <span className="text-warn">{monitor.last_changed_count} changed</span>}
              {monitor.last_missing_count > 0 && <span className="text-warn">{monitor.last_missing_count} disappeared from the public feed</span>}
              <span className="ml-auto flex gap-1">
                <Button variant="ghost" size="xs" disabled={running} onClick={async () => { await api.updateCreatorMonitor(monitor.id, { enabled: !monitor.enabled }); await refreshMonitors(); }}>{monitor.enabled ? "Pause" : "Enable"}</Button>
                <Button variant="ghost" size="xs" disabled={running || !monitor.enabled} onClick={async () => { await api.checkCreatorMonitor(monitor.id); await refreshMonitors(); }}>Check now</Button>
                <Button variant="danger" size="xs" disabled={running} onClick={async () => { await api.deleteCreatorMonitor(monitor.id); await refreshMonitors(); }}>Remove</Button>
              </span>
            </li>)}</ul>
          </div>}
        </div>

        <div className="border-t border-line pt-5">
          <h3 className="text-sm font-semibold text-ink">Import a myfaveTT archive</h3>
          <p className="mt-1 text-sm text-ink-dim">Choose the myfaveTT root folder. Videos are matched by TikTok ID to existing placeholders; already archived files are skipped, and unmatched files become local-only items.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="ghost" onClick={() => { if (folderRef.current) { folderRef.current.value = ""; folderRef.current.click(); } }} disabled={running || folderBusy || profileBusy}><FolderOpen size={16} /> Choose folder</Button>
            {plan && plan.counts.ready > 0 && <Button onClick={importFolder} disabled={running || folderBusy || profileBusy}>Import {plan.counts.ready} videos</Button>}
            <input ref={folderRef} type="file" multiple hidden onChange={chooseFolder} {...directoryAttributes} />
          </div>
          {folderMsg && <p className="mt-2 text-sm text-ink-dim" role="status">{folderMsg}</p>}
        </div>
      </div>
    </details>
  );
}
