import { useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { OffloadSuggestion } from "../lib/api";
import { useDryRunConfirm } from "../lib/useDryRunConfirm";
import { Button, ConfirmDialog } from "./ui";

type RangeAction = { action: "offload" | "unoffload"; range: { first_id: number; last_id: number } };

/** Mark favorite ranges as archived on external storage (or clear the mark). */
export function OffloadPanel({ running, onChanged }: { running: boolean; onChanged: () => Promise<void> }) {
  const [info, setInfo] = useState<OffloadSuggestion | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  /** "Mark range offloaded / unmark": dry-run for a count, confirm, apply. */
  const mark = useDryRunConfirm<RangeAction>({
    preview: async ({ action, range }) => (await api.markItems(action, { range }, true)).matched,
    apply: async ({ action, range }) => {
      const result = await api.markItems(action, { range });
      // The marks landed — a failed refresh must not report the mutation as
      // failed. Stale panels are fine; the dashboard poll catches them up.
      await Promise.all([refreshSuggestion(), onChanged()]).catch(() => {});
      const requeued = result.requeued ? ` ${result.requeued} had no local video and returned to the download queue.` : "";
      return `${result.changed} favorite${result.changed === 1 ? "" : "s"} updated.${requeued}`;
    },
    emptyMessage: "No favorites in that range need changing.",
  });
  const { pending, busy, message: msg, setMessage: setMsg } = mark;

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

  function markRange(action: "offload" | "unoffload") {
    const first = Number(from);
    const last = Number(to);
    if (!Number.isInteger(first) || !Number.isInteger(last) || first < 1 || last < first) {
      setMsg("Enter a valid range (from ≤ to).");
      return;
    }
    void mark.request({ action, range: { first_id: first, last_id: last } });
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
              Your earliest local video is #{info.earliest_local}. Mark favorites {info.suggested.first_id}-{info.suggested.last_id} as offloaded?
              {" "}({info.range_undownloaded} of {info.range_total} in the range are pending or failed{info.range_already_offloaded ? `, ${info.range_already_offloaded} already marked` : ""}.)
            </p>
          ) : (
            <p>No offload range to suggest.{info.earliest_local != null ? ` Your earliest local video is #${info.earliest_local}.` : ""}</p>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-ink-dim">From #
              <input value={from} onChange={(e) => setFrom(e.target.value)} type="number" min="1" className="mt-1 block h-9 w-28 rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim">To #
              <input value={to} onChange={(e) => setTo(e.target.value)} type="number" min="1" className="mt-1 block h-9 w-28 rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <Button disabled={running || busy || !from || !to} onClick={() => markRange("offload")}>Mark range offloaded</Button>
            <Button variant="ghost" disabled={running || busy || !from || !to} onClick={() => markRange("unoffload")}>Unmark range</Button>
          </div>
        </div>
      )}
      {msg && <p className="mt-2 text-sm text-ink-dim">{msg}</p>}
      {pending && <ConfirmDialog
        title={pending.payload.action === "offload" ? "Mark range offloaded?" : "Unmark range?"}
        message={`This will ${pending.payload.action === "offload" ? "mark" : "unmark"} ${pending.matched} favorite${pending.matched === 1 ? "" : "s"} (#${pending.payload.range.first_id}-#${pending.payload.range.last_id}) ${pending.payload.action === "offload" ? "as offloaded" : "as no longer offloaded"}. Nothing is downloaded or deleted.`}
        confirmLabel={pending.payload.action === "offload" ? "Mark offloaded" : "Unmark range"}
        busy={busy}
        onConfirm={() => void mark.confirm()}
        onCancel={mark.cancel}
      />}
    </section>
  );
}
