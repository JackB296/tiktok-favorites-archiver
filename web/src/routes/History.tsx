import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  ArrowDown,
  ArrowUp,
  ClockCounterClockwise,
  ShieldCheck,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { ImportChange, ImportRecord } from "../lib/types";
import { EmptyState, Skeleton, Stat, cx } from "../components/ui";
import {
  archiveItemUrl,
  importDisplayDate,
  importSummary,
} from "../lib/historyPresentation.js";

function ChangeList({
  title,
  changes,
  tone,
}: {
  title: string;
  changes: ImportChange[];
  tone: "new" | "missing";
}) {
  const Icon = tone === "new" ? ArrowUp : ArrowDown;
  return (
    <section className="rounded-[var(--radius-media)] border border-line bg-surface p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
        <Icon size={16} className={tone === "new" ? "text-ok" : "text-warn"} />
        {title}
      </h2>
      {changes.length ? (
        <ol className="mt-3 divide-y divide-line">
          {changes.map((change) => (
            <li key={change.link} className="flex min-w-0 items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm text-ink">{change.link}</p>
                <p className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-faint">
                  Favorite #{change.item_id}
                  {change.protected && <><span>·</span><ShieldCheck size={13} className="text-ok" /> safely archived</>}
                </p>
              </div>
              <Link to={archiveItemUrl(change.item_id)} className="shrink-0 text-xs font-medium text-accent hover:underline">
                View
              </Link>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-4 text-sm text-ink-dim">No favorites in this group.</p>
      )}
    </section>
  );
}

export function History() {
  const [records, setRecords] = useState<ImportRecord[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ImportRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.imports()
      .then((next) => {
        setRecords(next);
        setSelectedId(next[0]?.id ?? null);
      })
      .catch((error) => setMessage((error as Error).message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    let alive = true;
    setDetail(null);
    api.importDetail(selectedId)
      .then((next) => { if (alive) { setDetail(next); setMessage(null); } })
      .catch((error) => { if (alive) setMessage((error as Error).message); });
    return () => { alive = false; };
  }, [selectedId]);

  if (loading) {
    return <div className="mx-auto max-w-6xl space-y-3 px-4 py-8"><Skeleton className="h-24" /><Skeleton className="h-80" /></div>;
  }

  if (!records.length) {
    return (
      <div className="h-full overflow-y-auto px-4">
        <EmptyState
          icon={<ClockCounterClockwise size={40} />}
          title="No import history yet"
          hint={<>Upload a TikTok export from <Link to="/sync" className="text-accent hover:underline">Sync</Link>. Each future upload becomes a safe comparison point.</>}
        />
      </div>
    );
  }

  const counts = detail?.comparison.counts;
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Every export becomes a checkpoint</p>
          <h1 className="mt-1 text-2xl font-semibold text-ink">Archive Time Machine</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-dim">See what appeared or disappeared between TikTok exports. Removed favorites stay untouched in your local archive.</p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <aside className="rounded-[var(--radius-media)] border border-line bg-surface p-2 lg:self-start">
            <p className="px-3 py-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Checkpoints</p>
            <ol className="space-y-1">
              {records.map((record) => (
                <li key={record.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(record.id)}
                    className={cx(
                      "w-full rounded-[var(--radius-control)] px-3 py-3 text-left transition",
                      record.id === selectedId ? "bg-elevated text-ink" : "text-ink-dim hover:bg-elevated/60 hover:text-ink",
                    )}
                  >
                    <span className="block truncate text-sm font-medium">{record.source_name}</span>
                    <span className="mt-1 block text-xs text-ink-faint">{importDisplayDate(record.imported_at)}</span>
                    <span className="mt-1 block text-xs">{importSummary(record.comparison.counts)}</span>
                  </button>
                </li>
              ))}
            </ol>
          </aside>

          <section aria-label="Checkpoint details">
            {message && <p role="alert" className="mb-4 rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{message}</p>}
            {!detail || !counts ? (
              <Skeleton className="h-80" />
            ) : (
              <>
                <section className="rounded-[var(--radius-media)] border border-line bg-surface p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <h2 className="text-lg font-semibold text-ink">{detail.source_name}</h2>
                      <p className="mt-1 text-sm text-ink-dim">{importDisplayDate(detail.imported_at)} · {detail.favorite_count} favorites</p>
                    </div>
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-ok/10 px-3 py-1.5 text-xs font-medium text-ok">
                      <Archive size={14} /> Non-destructive
                    </span>
                  </div>
                  <div className="mt-5 grid gap-3 sm:grid-cols-4">
                    <Stat label="New" value={counts.new} hint="since prior export" />
                    <Stat label="Missing" value={counts.removed} hint="from this export" />
                    <Stat label="Unchanged" value={counts.unchanged} hint="still favorited" />
                    <Stat label="Protected" value={counts.protected} hint="missing but archived" />
                  </div>
                  {detail.previous_id == null && <p className="mt-4 text-xs text-ink-faint">This is the first checkpoint, so every favorite is counted as new.</p>}
                  {detail.comparison.truncated && <p className="mt-4 text-xs text-ink-faint">Showing the first 200 entries in each change group; totals remain complete.</p>}
                </section>

                <div className="mt-5 grid gap-5 xl:grid-cols-2">
                  <ChangeList title="New since the prior export" changes={detail.comparison.new ?? []} tone="new" />
                  <ChangeList title="Missing from this export" changes={detail.comparison.removed ?? []} tone="missing" />
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
