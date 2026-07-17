import { useEffect, useState } from "react";
import { ArrowClockwise, HardDrives, Plus, Trash } from "@phosphor-icons/react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import type { ProgressEvent, StorageLocation, StorageTransferPreview } from "../lib/types";
import { Button } from "../components/ui";
import { MOVE_CONFIRMATION, parseArchiveIds, transferSummary } from "../lib/storagePresentation";

export function Storage() {
  const [searchParams] = useSearchParams();
  const [locations, setLocations] = useState<StorageLocation[] | null>(null);
  const [drafts, setDrafts] = useState<Record<number, { name: string; path: string }>>({});
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [transferAction, setTransferAction] = useState<"copy" | "move" | "restore">("copy");
  const [transferLocation, setTransferLocation] = useState("");
  const [archiveIds, setArchiveIds] = useState(searchParams.get("ids") ?? "");
  const [preview, setPreview] = useState<StorageTransferPreview | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [progress, setProgress] = useState<ProgressEvent | null>(null);

  async function load() {
    setMessage(null);
    try {
      const next = await api.storageLocations();
      setLocations(next);
      setDrafts(Object.fromEntries(next.map((item) => [item.id, { name: item.name, path: item.path }])));
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  useEffect(() => {
    void load();
    return api.events((event) => {
      if (event.kind?.startsWith("storage-") || event.event === "transfer") setProgress(event);
    });
  }, []);

  async function perform(work: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage(null);
    try {
      await work();
      setMessage(success);
      await load();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function previewTransfer() {
    setBusy(true);
    setMessage(null);
    setPreview(null);
    try {
      const ids = parseArchiveIds(archiveIds);
      setPreview(await api.previewStorageTransfer(transferAction, Number(transferLocation), ids));
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function startTransfer() {
    if (!preview) return;
    setBusy(true);
    try {
      await api.startStorageTransfer(
        preview.plan_id,
        preview.action === "move" ? confirmation : undefined,
      );
      setMessage(`${preview.action} started. You can stop it and preview again to resume.`);
      setPreview(null);
      setProgress(null);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-xl font-semibold text-ink">Storage</h1>
        <p className="mt-1 text-sm text-ink-dim">Register local, USB, or NAS directories already mounted into the app container.</p>

        <form
          className="mt-6 grid gap-3 rounded-[var(--radius-media)] border border-line bg-surface p-5 sm:grid-cols-[1fr_2fr_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            void perform(
              () => api.createStorageLocation(name, path),
              "Storage location added.",
            ).then(() => { setName(""); setPath(""); });
          }}
        >
          <label className="text-sm text-ink">Name<input required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} className="mt-1 block h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-ink" /></label>
          <label className="text-sm text-ink">Mounted absolute path<input required value={path} onChange={(event) => setPath(event.target.value)} placeholder="/mnt/archive" className="mt-1 block h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 font-mono text-sm text-ink" /></label>
          <Button disabled={busy}><Plus size={16} /> Add</Button>
        </form>

        {message && <p className="mt-4 text-sm text-ink-dim" role="status" aria-live="polite">{message}</p>}
        {locations === null && !message && <p className="mt-8 text-sm text-ink-faint" role="status">Loading Storage locations…</p>}
        {locations?.length === 0 && <div className="mt-8 rounded-[var(--radius-media)] border border-dashed border-line py-14 text-center"><HardDrives size={28} className="mx-auto text-ink-faint" /><h2 className="mt-3 text-sm font-medium text-ink">No mounted storage yet</h2><p className="mt-1 text-sm text-ink-dim">Add a directory above before copying media or creating complete snapshots.</p></div>}

        {!!locations?.length && <section className="mt-6 rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink">Transfer Archive media</h2>
          <p className="mt-1 text-sm text-ink-dim">Copy keeps local media. Move verifies the external copy before deleting local files. Restore verifies local files and keeps the external copy.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="text-xs text-ink-dim">Action<select value={transferAction} onChange={(event) => { setTransferAction(event.target.value as typeof transferAction); setPreview(null); }} className="mt-1 block h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink"><option value="copy">Copy</option><option value="move">Move</option><option value="restore">Restore</option></select></label>
            <label className="text-xs text-ink-dim">Storage location<select required value={transferLocation} onChange={(event) => { setTransferLocation(event.target.value); setPreview(null); }} className="mt-1 block h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink"><option value="">Choose…</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
            <label className="text-xs text-ink-dim">Archive numbers<input value={archiveIds} onChange={(event) => { setArchiveIds(event.target.value); setPreview(null); }} placeholder="1, 2, 7" className="mt-1 block h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 font-mono text-sm text-ink" /></label>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant="ghost" size="sm" disabled={busy || !transferLocation || !archiveIds.trim()} onClick={() => void previewTransfer()}>Preview {transferAction}</Button>
            {progress?.event === "transfer" && <span className="text-sm text-ink-dim">{progress.completed ?? 0}/{progress.total ?? 0} Favorites · {progress.files ?? 0} files</span>}
            {progress?.kind?.startsWith("storage-") && progress.event === "complete" && <span className="text-sm text-ok">Transfer complete.</span>}
            {progress?.kind?.startsWith("storage-") && progress.event !== "complete" && <Button variant="danger" size="xs" onClick={() => void api.syncAction("stop")}>Stop</Button>}
          </div>
          {preview && <div className="mt-4 rounded-[var(--radius-control)] border border-line bg-elevated p-4">
            <p className="text-sm font-medium text-ink">{transferSummary(preview)}</p>
            {!!preview.conflicts && <p className="mt-1 text-sm text-warn">{preview.conflicts} destination conflicts will be replaced only after staged checksum verification.</p>}
            {!!preview.missing_verified?.length && <p className="mt-1 text-sm text-bad">{preview.missing_verified.length} Favorites have no verified copy to restore.</p>}
            {preview.action === "move" && <label className="mt-3 block text-xs text-ink-dim">Type <strong className="text-ink">{MOVE_CONFIRMATION}</strong> to allow verified local deletion.<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="mt-1 block h-9 w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 font-mono text-sm text-ink" /></label>}
            <Button className="mt-3" size="sm" disabled={busy || !!preview.missing_verified?.length || (preview.action === "move" && confirmation !== MOVE_CONFIRMATION)} onClick={() => void startTransfer()}>Start {preview.action}</Button>
          </div>}
        </section>}

        <ul className="mt-6 space-y-3">
          {locations?.map((location) => {
            const draft = drafts[location.id] ?? { name: location.name, path: location.path };
            return <li key={location.id} className="rounded-[var(--radius-media)] border border-line bg-surface p-4">
              <div className="grid gap-3 sm:grid-cols-[1fr_2fr]">
                <label className="text-xs text-ink-faint">Name<input value={draft.name} onChange={(event) => setDrafts((all) => ({ ...all, [location.id]: { ...draft, name: event.target.value } }))} className="mt-1 block h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink" /></label>
                <label className="text-xs text-ink-faint">Path<input value={draft.path} onChange={(event) => setDrafts((all) => ({ ...all, [location.id]: { ...draft, path: event.target.value } }))} className="mt-1 block h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 font-mono text-xs text-ink" /></label>
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <p className={location.available ? "text-xs text-ok" : "text-xs text-bad"}>{location.available ? "Available" : location.last_error ?? "Unavailable"}</p>
                <div className="flex gap-2">
                  <Button variant="ghost" size="xs" disabled={busy} onClick={() => void perform(() => api.checkStorageLocation(location.id), "Health check complete.")}><ArrowClockwise size={14} /> Check</Button>
                  <Button variant="ghost" size="xs" disabled={busy} onClick={() => void perform(() => api.updateStorageLocation(location.id, draft), "Storage location updated.")}>Save</Button>
                  <Button variant="danger" size="xs" disabled={busy} onClick={() => void perform(() => api.deleteStorageLocation(location.id), "Storage location deleted.")}><Trash size={14} /> Delete</Button>
                </div>
              </div>
            </li>;
          })}
        </ul>
      </div>
    </div>
  );
}
