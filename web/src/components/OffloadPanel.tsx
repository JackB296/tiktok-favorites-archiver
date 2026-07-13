import { useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { OffloadSuggestion } from "../lib/api";
import { Button } from "./ui";

/** Mark favorite ranges as archived on external storage (or clear the mark). */
export function OffloadPanel({ running, onChanged }: { running: boolean; onChanged: () => Promise<void> }) {
  const [info, setInfo] = useState<OffloadSuggestion | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refreshSuggestion(prefillRange = false) {
    const next = await api.offloadSuggestion();
    setInfo(next);
    if (prefillRange && next.suggested) {
      setFrom(String(next.suggested.first_id));
      setTo(String(next.suggested.last_id));
    }
  }

  async function checkSuggestion() {
    setMsg("Checking…");
    try {
      await refreshSuggestion(true);
      setMsg(null);
    } catch (err) {
      setMsg((err as Error).message);
    }
  }

  async function markRange(action: "offload" | "unoffload") {
    const first = Number(from);
    const last = Number(to);
    if (!Number.isInteger(first) || !Number.isInteger(last) || first < 1 || last < first) {
      setMsg("Enter a valid range (from ≤ to).");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const range = { first_id: first, last_id: last };
      const preview = await api.markItems(action, { range }, true);
      if (!preview.matched) {
        setMsg("No favorites in that range need changing.");
        return;
      }
      const verb = action === "offload" ? "mark" : "unmark";
      if (!window.confirm(`This will ${verb} ${preview.matched} favorite${preview.matched === 1 ? "" : "s"} ${action === "offload" ? "as offloaded" : "as no longer offloaded"} — proceed?`)) return;
      const result = await api.markItems(action, { range });
      await Promise.all([refreshSuggestion(), onChanged()]);
      const requeued = result.requeued ? ` ${result.requeued} had no local video and returned to the download queue.` : "";
      setMsg(`${result.changed} favorite${result.changed === 1 ? "" : "s"} updated.${requeued}`);
    } catch (err) {
      setMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mb-4 rounded-[var(--radius-media)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">Offloaded media</h2>
          <p className="mt-1 text-sm text-ink-dim">If older favorites live on external storage (a NAS or drive), mark them offloaded so Sync and integrity checks stop treating them as missing. The external storage does not need to be connected, and nothing is downloaded or deleted.</p>
        </div>
        <Button variant="ghost" disabled={busy} onClick={checkSuggestion}>
          <ArrowClockwise size={16} /> Check
        </Button>
      </div>
      {info && (
        <div className="mt-3 space-y-3 text-sm text-ink-dim">
          {info.suggested ? (
            <p>
              Your earliest local video is #{info.earliest_local}. Mark favorites {info.suggested.first_id}–{info.suggested.last_id} as offloaded?
              {" "}({info.range_undownloaded} of {info.range_total} in the range are pending or failed{info.range_already_offloaded ? `, ${info.range_already_offloaded} already marked` : ""}.)
            </p>
          ) : (
            <p>No offload range to suggest{info.earliest_local != null ? ` — your earliest local video is #${info.earliest_local}` : ""}.</p>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-ink-dim">From #
              <input value={from} onChange={(e) => setFrom(e.target.value)} type="number" min="1" className="mt-1 block h-9 w-28 rounded border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim">To #
              <input value={to} onChange={(e) => setTo(e.target.value)} type="number" min="1" className="mt-1 block h-9 w-28 rounded border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <Button disabled={running || busy || !from || !to} onClick={() => markRange("offload")}>Mark range offloaded</Button>
            <Button variant="ghost" disabled={running || busy || !from || !to} onClick={() => markRange("unoffload")}>Unmark range</Button>
          </div>
        </div>
      )}
      {msg && <p className="mt-2 text-sm text-ink-dim">{msg}</p>}
    </section>
  );
}
