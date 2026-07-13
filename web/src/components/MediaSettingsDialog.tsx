import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { UploadSimple, X } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item } from "../lib/types";
import { useDialogFocusTrap } from "./ui";

function fileSummary(file: File | null) {
  if (!file) return "No file selected";
  const size = file.size >= 1_000_000
    ? `${(file.size / 1_000_000).toFixed(1)} MB`
    : `${Math.max(1, Math.round(file.size / 1_000))} KB`;
  return `${file.name} · ${size}`;
}

export function MediaSettingsDialog({ item, onClose, onSaved }: { item: Item; onClose: () => void; onSaved: (item: Item) => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLFormElement>(null);
  useDialogFocusTrap(panelRef);
  const [video, setVideo] = useState<File | null>(null);
  const [thumbnail, setThumbnail] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, saving]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!video && !thumbnail) return;
    setSaving(true);
    setError(null);
    try {
      onSaved(await api.replaceItemMedia(item.id, {
        ...(video ? { video } : {}),
        ...(thumbnail ? { thumbnail } : {}),
      }));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Media could not be replaced.");
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4" role="dialog" aria-modal="true" aria-labelledby="media-settings-title">
      <form ref={panelRef} onSubmit={(event) => void submit(event)} className="w-full max-w-lg rounded-[var(--radius-media)] border border-white/15 bg-surface p-5 text-ink shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="tabular text-xs text-ink-faint">Favorite #{item.id}</p>
            <h2 id="media-settings-title" className="mt-1 text-lg font-semibold">Media settings</h2>
            <p className="mt-1 text-sm leading-relaxed text-ink-dim">Replace the local file or choose a custom Gallery thumbnail. Caption, creator, source link, and archive number stay unchanged.</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} disabled={saving} aria-label="Close media settings" className="rounded-[var(--radius-control)] p-2 text-ink-dim hover:bg-elevated hover:text-ink disabled:opacity-40"><X size={18} /></button>
        </div>

        <div className="mt-5 grid gap-4">
          <label className="block rounded-[var(--radius-control)] border border-line bg-elevated p-3">
            <span className="text-sm font-medium text-ink">Replacement video</span>
            <span className="mt-1 block text-xs leading-relaxed text-ink-dim">MP4 only, up to 1 GB. A valid upload replaces <span className="tabular">downloads/{item.id}.mp4</span> and refreshes its thumbnail and audio status.</span>
            <input type="file" accept="video/mp4,.mp4" onChange={(event) => setVideo(event.target.files?.[0] ?? null)} className="mt-3 block w-full text-xs text-ink-dim file:mr-3 file:rounded-[var(--radius-control)] file:border-0 file:bg-surface file:px-3 file:py-2 file:text-xs file:font-medium file:text-ink hover:file:bg-canvas" />
            <span className="mt-2 block truncate text-xs text-ink-faint">{fileSummary(video)}</span>
          </label>

          <label className="block rounded-[var(--radius-control)] border border-line bg-elevated p-3">
            <span className="text-sm font-medium text-ink">Custom thumbnail</span>
            <span className="mt-1 block text-xs leading-relaxed text-ink-dim">JPEG, PNG, or WebP, up to 20 MB. This remains your Gallery thumbnail when the media index is rebuilt.</span>
            <input type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" onChange={(event) => setThumbnail(event.target.files?.[0] ?? null)} className="mt-3 block w-full text-xs text-ink-dim file:mr-3 file:rounded-[var(--radius-control)] file:border-0 file:bg-surface file:px-3 file:py-2 file:text-xs file:font-medium file:text-ink hover:file:bg-canvas" />
            <span className="mt-2 block truncate text-xs text-ink-faint">{fileSummary(thumbnail)}</span>
          </label>
        </div>

        {error && <p role="alert" className="mt-4 rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{error}</p>}

        <div className="mt-5 flex justify-end gap-2 border-t border-line pt-4">
          <button type="button" onClick={onClose} disabled={saving} className="rounded-[var(--radius-control)] border border-line px-3 py-2 text-sm text-ink-dim hover:text-ink disabled:opacity-40">Cancel</button>
          <button type="submit" disabled={saving || (!video && !thumbnail)} className="inline-flex items-center gap-2 rounded-[var(--radius-control)] bg-accent px-3 py-2 text-sm font-semibold text-on-accent hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-40"><UploadSimple size={16} />{saving ? "Saving…" : "Save media"}</button>
        </div>
      </form>
    </div>
  );
}
