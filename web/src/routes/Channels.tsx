import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Play, Shuffle, Television, Trash } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { ArchiveChannel, GalleryPreset } from "../lib/types";
import { Button, EmptyState, Skeleton } from "../components/ui";

export function Channels() {
  const [channels, setChannels] = useState<ArchiveChannel[] | null>(null);
  const [presets, setPresets] = useState<GalleryPreset[]>([]);
  const [name, setName] = useState("");
  const [presetId, setPresetId] = useState("");
  const [shuffle, setShuffle] = useState(false);
  const [preferUnwatched, setPreferUnwatched] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.channels(), api.galleryPresets()])
      .then(([savedChannels, savedPresets]) => {
        setChannels(savedChannels);
        setPresets(savedPresets);
        setPresetId((value) => value || String(savedPresets[0]?.id ?? ""));
      })
      .catch((error) => { setChannels([]); setMessage((error as Error).message); });
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !Number(presetId)) return;
    setBusy(true);
    setMessage(null);
    try {
      const channel = await api.createChannel({
        name: name.trim(), preset_id: Number(presetId), shuffle,
        prefer_unwatched: preferUnwatched,
      });
      setChannels((value) => [...(value ?? []), channel].sort((a, b) => a.name.localeCompare(b.name)));
      setName("");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(channel: ArchiveChannel) {
    if (!window.confirm(`Delete channel "${channel.name}"? The Smart Collection and media are untouched.`)) return;
    setBusy(true);
    try {
      await api.deleteChannel(channel.id);
      setChannels((value) => value?.filter((entry) => entry.id !== channel.id) ?? []);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Your archive, always on</p>
          <h1 className="mt-1 text-2xl font-semibold text-ink">Archive Channels</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-dim">Turn a live Gallery Smart Collection into continuous playback. New matching favorites join automatically.</p>
        </div>

        <form onSubmit={create} className="grid gap-3 rounded-[var(--radius-media)] border border-line bg-surface p-5 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <label className="text-xs text-ink-dim">Channel name
            <input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder="Dinner TV" className="mt-1 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink placeholder:text-ink-faint" />
          </label>
          <label className="text-xs text-ink-dim">Smart Collection
            <select value={presetId} onChange={(event) => setPresetId(event.target.value)} className="mt-1 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink">
              <option value="">Choose a saved Gallery filter…</option>
              {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
            </select>
          </label>
          <Button type="submit" disabled={busy || !name.trim() || !presetId}>Create channel</Button>
          <div className="flex flex-wrap gap-4 md:col-span-3">
            <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={shuffle} onChange={(event) => setShuffle(event.target.checked)} />Shuffle the collection</label>
            <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={preferUnwatched} onChange={(event) => setPreferUnwatched(event.target.checked)} />Prefer unwatched favorites</label>
          </div>
          {!presets.length && <p className="text-xs text-ink-faint md:col-span-3">Save an advanced filter in Gallery first, then return here to make it a channel.</p>}
        </form>
        {message && <p role="alert" className="mt-3 text-sm text-bad">{message}</p>}

        {channels === null ? <div className="mt-5 space-y-3"><Skeleton className="h-28" /><Skeleton className="h-28" /></div> : channels.length ? (
          <ol className="mt-6 grid gap-3 sm:grid-cols-2">
            {channels.map((channel) => (
              <li key={channel.id} className="rounded-[var(--radius-media)] border border-line bg-surface p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 gap-3"><span className="rounded-[var(--radius-control)] bg-accent/10 p-2 text-accent"><Television size={22} /></span><div className="min-w-0"><h2 className="truncate font-semibold text-ink">{channel.name}</h2><p className="mt-0.5 truncate text-xs text-ink-faint">{channel.preset_name}</p></div></div>
                  <button onClick={() => void remove(channel)} disabled={busy} aria-label={`Delete ${channel.name}`} className="rounded p-1.5 text-ink-faint hover:bg-bad/10 hover:text-bad"><Trash size={16} /></button>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 text-xs text-ink-dim">
                  {channel.shuffle && <span className="inline-flex items-center gap-1 rounded-full bg-elevated px-2 py-1"><Shuffle size={12} />Shuffled</span>}
                  {channel.prefer_unwatched && <span className="rounded-full bg-elevated px-2 py-1">Unwatched first</span>}
                  {!channel.shuffle && !channel.prefer_unwatched && <span className="rounded-full bg-elevated px-2 py-1">Collection order</span>}
                </div>
                <Link to={`/?channel=${channel.id}`} className="mt-5 inline-flex h-9 w-full items-center justify-center gap-2 rounded-[var(--radius-control)] bg-accent text-sm font-medium text-on-accent hover:bg-accent-strong"><Play size={15} weight="fill" />Start channel</Link>
              </li>
            ))}
          </ol>
        ) : <EmptyState icon={<Television size={42} />} title="No channels yet" hint="Create one above from a saved Gallery Smart Collection." />}
      </div>
    </div>
  );
}

