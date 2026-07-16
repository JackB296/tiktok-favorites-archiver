import { useState } from "react";
import { ArrowClockwise, CaretDown } from "@phosphor-icons/react";
import { api } from "../lib/api";
import { parseLegacyMappingText } from "../lib/legacyBootstrap";
import { isSafeHttpUrl } from "../lib/format";
import type { LegacyBootstrapPreview, LegacyMappingSegment } from "../lib/types";
import { Button, ConfirmDialog, Stat } from "./ui";

/** One-time migration wizard for archives numbered by the pre-database CLI. */
export function LegacyBootstrapPanel({ running, onApplied }: { running: boolean; onApplied: () => Promise<void> }) {
  const [oldExport, setOldExport] = useState<File | null>(null);
  const [currentExport, setCurrentExport] = useState<File | null>(null);
  const [checkpoint, setCheckpoint] = useState<File | null>(null);
  const [mappingText, setMappingText] = useState("");
  const [preview, setPreview] = useState<LegacyBootstrapPreview | null>(null);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmingApply, setConfirmingApply] = useState(false);

  function resetPreview() {
    setPreview(null);
    setVerified(false);
    setMsg(null);
  }

  async function previewBootstrap() {
    if (!oldExport || !currentExport || !checkpoint) {
      setMsg("Choose the old export, current export, and last-downloaded-link file first.");
      return;
    }
    let segments: LegacyMappingSegment[] | undefined;
    try {
      segments = parseLegacyMappingText(mappingText);
    } catch (err) {
      setMsg((err as Error).message);
      return;
    }
    setBusy(true);
    setMsg("Validating exports and local archive numbers…");
    setPreview(null);
    setVerified(false);
    try {
      const next = await api.legacyBootstrapPreview(oldExport, currentExport, checkpoint, segments);
      setPreview(next);
      setMsg("Preview passed every safety check. Verify the sample mappings before applying it.");
    } catch (err) {
      setMsg(`Preview failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function applyBootstrap() {
    if (!oldExport || !currentExport || !checkpoint || !preview || !verified) return;
    let segments: LegacyMappingSegment[] | undefined;
    try {
      segments = parseLegacyMappingText(mappingText);
    } catch (err) {
      setMsg((err as Error).message);
      return;
    }
    setConfirmingApply(false);
    setBusy(true);
    setMsg("Creating the legacy library database…");
    try {
      const result = await api.legacyBootstrapApply(oldExport, currentExport, checkpoint, preview.token, segments);
      setMsg(
        `Bootstrap complete: ${result.local_done.toLocaleString()} local videos matched, ` +
        `${result.physical_gaps_ignored.toLocaleString()} missing filenames and ` +
        `${result.reused_number_markers.toLocaleString()} reused-number marker preserved, ` +
        `${result.offloaded.toLocaleString()} older favorites marked offloaded, and ` +
        `${result.new_pending.toLocaleString()} newer favorites queued.`,
      );
      setPreview(null);
      setVerified(false);
      // A rejecting refresh must not overwrite the success report — the
      // bootstrap already committed. (onApplied's type permits rejection.)
      await onApplied().catch(() => {});
    } catch (err) {
      setMsg(`Bootstrap failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="group mb-4 rounded-[var(--radius-media)] border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-semibold text-ink">
        <span>First-time setup from the old CLI</span>
        <CaretDown size={16} className="text-ink-faint transition group-open:rotate-180" />
      </summary>
      <div className="border-t border-line px-5 py-5">
        <p className="text-sm leading-relaxed text-ink-dim">
          Use this once if your numbered videos were downloaded before this app had a database. It compares your old
          export, latest export, checkpoint, and the MP4 numbers already in <code>downloads</code>. Preview is read-only;
          apply creates database records only. It never renames, deletes, moves, indexes, or downloads media, and it does
          not need your NAS to be connected.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <LegacyFileInput
            label="Old export"
            hint="From the last CLI run"
            accept="application/json,.json"
            file={oldExport}
            onChange={(file) => { setOldExport(file); resetPreview(); }}
          />
          <LegacyFileInput
            label="Current export"
            hint="Latest favorites export"
            accept="application/json,.json"
            file={currentExport}
            onChange={(file) => { setCurrentExport(file); resetPreview(); }}
          />
          <LegacyFileInput
            label="Checkpoint"
            hint="last_downloaded_link.txt"
            accept="text/plain,.txt"
            file={checkpoint}
            onChange={(file) => { setCheckpoint(file); resetPreview(); }}
          />
        </div>

        <label className="mt-4 block text-sm text-ink-dim">
          <span className="font-medium text-ink">Mapping segments</span>
          <span className="mt-0.5 block text-xs leading-relaxed text-ink-faint">
            Leave blank for one uninterrupted CLI run. If verified samples show a restart changed numbering, enter each run as <code>first-file:offset</code>, separated by commas. Example: <code>20968:5833, 22315:5832</code>.
          </span>
          <input
            value={mappingText}
            onChange={(event) => { setMappingText(event.target.value); resetPreview(); }}
            placeholder="Automatically infer one segment"
            spellCheck={false}
            className="mt-2 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 font-mono text-sm text-ink placeholder:text-ink-faint"
          />
        </label>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            variant="ghost"
            disabled={running || busy || !oldExport || !currentExport || !checkpoint}
            onClick={previewBootstrap}
          >
            <ArrowClockwise size={16} /> Preview mapping
          </Button>
          {msg && <p role="status" aria-live="polite" className="text-sm text-ink-dim">{msg}</p>}
        </div>

        {preview && (
          <div className="mt-5 rounded-[var(--radius-control)] border border-line bg-elevated p-4">
            <h3 className="text-sm font-semibold text-ink">Validated migration preview</h3>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat
                label={preview.segments.length > 1 ? "Mapping segments" : "Inferred offset"}
                value={preview.segments.length > 1 ? preview.segments.length : preview.offset.toLocaleString()}
                hint={preview.segments.map((segment) => segment.offset.toLocaleString()).join(" → ")}
              />
              <Stat label="Local videos" value={preview.inventory.local_files.toLocaleString()} hint={`#${preview.inventory.lowest_number}-#${preview.inventory.highest_number}`} />
              <Stat label="Legacy gaps" value={preview.inventory.gaps.toLocaleString()} hint={`${preview.inventory.physical_gaps} filenames + ${preview.inventory.reused_number_markers} reused`} />
              <Stat label="New downloads" value={preview.allocation.new_pending.toLocaleString()} hint="after the checkpoint" />
            </div>

            <div className="mt-4 grid gap-2 text-sm text-ink-dim sm:grid-cols-2">
              <p>Old export: <strong className="text-ink">{preview.exports.old_favorites.toLocaleString()}</strong> favorites</p>
              <p>Current export: <strong className="text-ink">{preview.exports.current_favorites.toLocaleString()}</strong> favorites</p>
              <p>Reserved NAS namespace: <strong className="text-ink">#{preview.allocation.reserved_physical_first}-#{preview.allocation.reserved_physical_last}</strong></p>
              <p>Older offloaded records: <strong className="text-ink">{preview.allocation.offloaded.toLocaleString()}</strong></p>
              <p>Local mapped positions: <strong className="text-ink">{preview.inventory.mapped_old_position_first.toLocaleString()}-{preview.inventory.mapped_old_position_last.toLocaleString()}</strong></p>
              <p>Next archive number: <strong className="text-ink">#{preview.allocation.next_archive_number.toLocaleString()}</strong></p>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[36rem] text-left text-xs">
                <thead className="text-ink-faint">
                  <tr><th className="pb-2 pr-3 font-medium">Physical files</th><th className="pb-2 pr-3 font-medium">Export positions</th><th className="pb-2 font-medium">Offset</th></tr>
                </thead>
                <tbody className="text-ink-dim">
                  {preview.segments.map((segment) => (
                    <tr key={segment.start_id} className="border-t border-line">
                      <td className="py-2 pr-3 text-ink">#{segment.start_id}-#{segment.end_id}</td>
                      <td className="py-2 pr-3">{segment.first_position.toLocaleString()}-{segment.last_position.toLocaleString()}</td>
                      <td className="py-2">{segment.offset.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[36rem] text-left text-xs">
                <thead className="text-ink-faint">
                  <tr><th className="pb-2 pr-3 font-medium">Local file</th><th className="pb-2 pr-3 font-medium">Old export position</th><th className="pb-2 font-medium">Favorite link</th></tr>
                </thead>
                <tbody className="text-ink-dim">
                  {preview.samples.map((sample) => {
                    const safeLink = isSafeHttpUrl(sample.link);
                    return (
                      <tr key={sample.archive_number} className="border-t border-line">
                        <td className="py-2 pr-3 text-ink">
                          <a className="text-active hover:underline" href={`/media/${sample.archive_number}.mp4`} target="_blank" rel="noreferrer">#{sample.archive_number}.mp4</a>
                        </td>
                        <td className="py-2 pr-3">#{sample.old_export_position}</td>
                        <td className="max-w-md truncate py-2">
                          {safeLink
                            ? <a className="text-active hover:underline" href={sample.link} target="_blank" rel="noreferrer">{sample.link}</a>
                            : <span>{sample.link}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <label className="mt-4 flex cursor-pointer items-start gap-2 text-sm text-ink-dim">
              <input
                className="mt-0.5"
                type="checkbox"
                checked={verified}
                onChange={(event) => setVerified(event.target.checked)}
              />
              <span>I verified that the sample links match those numbered local videos and understand this requires an empty library database.</span>
            </label>
            <div className="mt-4">
              <Button disabled={running || busy || !verified} onClick={() => setConfirmingApply(true)}>
                Apply legacy bootstrap
              </Button>
            </div>
          </div>
        )}
        {confirmingApply && preview && <ConfirmDialog
          title="Apply legacy bootstrap?"
          message={`This creates ${preview.allocation.total_rows.toLocaleString()} library records. Only ${preview.allocation.new_pending.toLocaleString()} newer favorites will be queued for download, and no media files are changed.`}
          confirmLabel="Apply bootstrap"
          busy={busy}
          onConfirm={() => void applyBootstrap()}
          onCancel={() => setConfirmingApply(false)}
        />}
      </div>
    </details>
  );
}

function LegacyFileInput({
  label,
  hint,
  accept,
  file,
  onChange,
}: {
  label: string;
  hint: string;
  accept: string;
  file: File | null;
  onChange: (file: File | null) => void;
}) {
  return (
    <label className="block rounded-[var(--radius-control)] border border-line bg-elevated p-3 text-sm">
      <span className="font-medium text-ink">{label}</span>
      <span className="mt-0.5 block text-xs text-ink-faint">{hint}</span>
      <input
        type="file"
        accept={accept}
        className="mt-3 block w-full min-w-0 text-xs text-ink-dim file:mr-2 file:rounded file:border-0 file:bg-surface file:px-2 file:py-1.5 file:text-xs file:text-ink"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      {file && <span className="mt-2 block truncate text-xs text-ok">{file.name}</span>}
    </label>
  );
}
