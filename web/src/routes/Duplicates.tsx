import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowClockwise, Play, ShieldCheck } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { DuplicateReport } from "../lib/types";
import { Button, EmptyState, Skeleton, Stat } from "../components/ui";
import { formatSize } from "../lib/format";

export function Duplicates() {
  const [report, setReport] = useState<DuplicateReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.duplicateReport().then(setReport).catch((error) => setMessage((error as Error).message));
  }, []);

  async function scan() {
    setBusy(true);
    setMessage(null);
    try {
      setReport(await api.scanDuplicates());
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Storage confidence</p>
            <h1 className="mt-1 text-2xl font-semibold text-ink">Duplicate Radar</h1>
            <p className="mt-1 max-w-2xl text-sm text-ink-dim">Find byte-for-byte duplicate videos with SHA-256. Scanning only reads media and never deletes or offloads anything.</p>
          </div>
          <Button onClick={() => void scan()} disabled={busy}><ArrowClockwise size={16} />{busy ? "Hashing media…" : "Scan local media"}</Button>
        </div>
        {message && <p role="alert" className="mb-4 rounded-[var(--radius-control)] border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">{message}</p>}
        {!report ? (
          <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-64" /></div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Exact groups" value={report.group_count} hint="same SHA-256" />
              <Stat label="Favorites involved" value={report.duplicate_items} hint="inspection only" />
              <Stat label="Potential reclaim" value={formatSize(report.reclaimable_bytes)} hint="no cleanup performed" />
            </div>
            {report.scan && <p className="mt-3 text-xs text-ink-faint">Last scan hashed {report.scan.hashed} changed file{report.scan.hashed === 1 ? "" : "s"} and reused {report.scan.reused} cached digest{report.scan.reused === 1 ? "" : "s"}.</p>}
            {report.groups.length ? (
              <ol className="mt-6 space-y-4">
                {report.groups.map((group, groupIndex) => (
                  <li key={group.sha256} className="rounded-[var(--radius-media)] border border-line bg-surface p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div><h2 className="text-sm font-semibold text-ink">Exact group {groupIndex + 1}</h2><p className="mt-0.5 font-mono text-[11px] text-ink-faint">{group.sha256.slice(0, 24)}…</p></div>
                      <span className="rounded-full bg-elevated px-3 py-1 text-xs text-ink-dim">{group.copies} copies · {formatSize(group.reclaimable_bytes)} reclaimable</span>
                    </div>
                    <div className="mt-4 grid gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
                      {group.items.map((item) => (
                        <Link key={item.id} to={`/?item=${item.id}`} className="group overflow-hidden rounded-[var(--radius-control)] border border-line bg-elevated">
                          <div className="relative aspect-video bg-black">
                            {item.thumbnail_url ? <img src={item.thumbnail_url} alt="" className="h-full w-full object-cover opacity-90 group-hover:opacity-100" /> : <span className="flex h-full items-center justify-center text-white/50">#{item.id}</span>}
                            <span className="absolute inset-0 flex items-center justify-center opacity-0 transition group-hover:bg-black/30 group-hover:opacity-100"><Play size={20} weight="fill" className="text-white" /></span>
                          </div>
                          <div className="p-2"><p className="truncate text-xs font-semibold text-ink">Favorite #{item.id}</p><p className="mt-0.5 truncate text-xs text-ink-faint">{item.caption || item.author || "No caption"}</p></div>
                        </Link>
                      ))}
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState icon={<ShieldCheck size={42} />} title="No exact duplicates found" hint={busy ? "Scanning…" : "Run a scan whenever media changes. Similar-looking but differently encoded files are intentionally not grouped yet."} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
