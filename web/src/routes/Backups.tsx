import { useEffect, useState } from "react";
import { Archive, ArrowClockwise, DownloadSimple } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { SnapshotResource, SnapshotRestorePlan, StorageLocation } from "../lib/types";
import { Button } from "../components/ui";
import { REPLACE_CONFIRMATION, restoreDisclosure } from "../lib/snapshotPresentation";

export function Backups() {
  const [locations, setLocations] = useState<StorageLocation[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotResource[] | null>(null);
  const [locationId, setLocationId] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"metadata" | "complete">("metadata");
  const [plan, setPlan] = useState<SnapshotRestorePlan | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const [nextLocations, nextSnapshots] = await Promise.all([api.storageLocations(), api.snapshots()]);
      setLocations(nextLocations);
      setSnapshots(nextSnapshots);
    } catch (error) {
      setMessage((error as Error).message);
    }
  }
  useEffect(() => {
    void load();
    return api.events((event) => {
      if (event.kind === "snapshot" || event.kind === "snapshot-restore") {
        setMessage(event.event === "complete" ? "Backup operation complete." : event.error ?? "Backup operation updated.");
        if (event.event === "complete") void load();
      }
    });
  }, []);

  async function act(work: () => Promise<unknown>, success: string) {
    setBusy(true); setMessage(null);
    try { await work(); setMessage(success); await load(); }
    catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }

  return <div className="h-full overflow-y-auto"><div className="mx-auto max-w-4xl px-4 py-8">
    <h1 className="text-xl font-semibold text-ink">Backups &amp; Restore</h1>
    <p className="mt-1 text-sm text-ink-dim">Portable checksummed snapshots with a consistent SQLite backup. Complete mode includes durable media.</p>
    <section className="mt-6 rounded-[var(--radius-media)] border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-ink">Create snapshot</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="text-xs text-ink-dim">Location<select value={locationId} onChange={(e) => setLocationId(e.target.value)} className="mt-1 block h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink"><option value="">Choose…</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
        <label className="text-xs text-ink-dim">Name<input value={name} onChange={(e) => setName(e.target.value)} className="mt-1 block h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink" /></label>
        <label className="text-xs text-ink-dim">Contents<select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)} className="mt-1 block h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink"><option value="metadata">Metadata only</option><option value="complete">Metadata + media</option></select></label>
      </div>
      <Button className="mt-3" size="sm" disabled={busy || !locationId || !name.trim()} onClick={() => void act(() => api.createSnapshot(Number(locationId), name, mode), "Snapshot started. Progress appears here.")}>Create snapshot</Button>
    </section>
    {message && <p className="mt-4 text-sm text-ink-dim" role="status" aria-live="polite">{message}</p>}
    {snapshots === null ? <p className="mt-8 text-sm text-ink-faint" role="status">Loading snapshots…</p> : snapshots.length === 0 ? <div className="mt-8 py-14 text-center"><Archive size={30} className="mx-auto text-ink-faint" /><h2 className="mt-3 text-sm font-medium text-ink">No snapshots yet</h2></div> :
      <ul className="mt-6 space-y-3">{snapshots.map((snapshot) => <li key={snapshot.id} className="rounded-[var(--radius-media)] border border-line bg-surface p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-medium text-ink">{snapshot.name}</h2><p className="mt-1 text-xs text-ink-dim">{snapshot.location_name} · {snapshot.state} · {snapshot.mode ?? "unknown"} · {snapshot.items ?? 0} Favorites</p>{snapshot.error && <p className="mt-1 text-xs text-bad">{snapshot.error}</p>}</div><div className="flex gap-2"><Button variant="ghost" size="xs" disabled={busy || snapshot.state !== "complete"} onClick={() => void act(() => api.validateSnapshot(snapshot.id), "Snapshot is valid.")}><ArrowClockwise size={14} /> Validate</Button>{snapshot.mode === "metadata" && snapshot.state === "complete" && <a className="inline-flex h-8 items-center gap-1 rounded-[var(--radius-control)] border border-line px-2.5 text-xs text-ink-dim" href={`/api/snapshots/${encodeURIComponent(snapshot.id)}/download`}><DownloadSimple size={14} /> ZIP</a>}<Button size="xs" disabled={busy || snapshot.state !== "complete"} onClick={() => void act(async () => setPlan(await api.previewSnapshotRestore(snapshot.id)), "Restore preview ready.")}>Restore…</Button></div></div></li>)}</ul>}
    {plan && <section className="mt-6 rounded-[var(--radius-media)] border border-warn/40 bg-warn/10 p-5"><h2 className="text-sm font-semibold text-ink">Restore preview</h2><p className="mt-2 text-sm text-ink-dim">{restoreDisclosure(plan)}</p>{plan.requires_replace && <label className="mt-3 block text-xs text-ink-dim">Type <strong className="text-ink">{REPLACE_CONFIRMATION}</strong>. A complete rollback snapshot is created first.<input value={confirmation} onChange={(e) => setConfirmation(e.target.value)} className="mt-1 block h-9 w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 font-mono text-sm text-ink" /></label>}<Button className="mt-3" size="sm" disabled={busy || (plan.requires_replace && confirmation !== REPLACE_CONFIRMATION)} onClick={() => void act(() => api.startSnapshotRestore(plan.plan_id, confirmation), "Restore started.")}>Apply restore</Button></section>}
  </div></div>;
}
