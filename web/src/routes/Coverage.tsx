import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CheckCircle, FirstAid, WarningCircle } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { CoverageCategory, CoverageReport } from "../lib/types";
import { EmptyState, Skeleton } from "../components/ui";

export function Coverage() {
  const [params] = useSearchParams();
  const [report, setReport] = useState<CoverageReport | null>(null);
  const [selected, setSelected] = useState<Set<CoverageCategory["key"]>>(new Set());
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => { api.coverage().then(setReport).catch((error) => setMessage((error as Error).message)).finally(() => setLoading(false)); }, []);
  const repair = async () => {
    if (!selected.size) return;
    try {
      let filter: Record<string, string> | undefined;
      try {
        const candidate = JSON.parse(params.get("filter") ?? "null");
        if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) filter = candidate;
      } catch { /* malformed shared URL falls back to whole archive */ }
      const outcome = await api.repairCoverage([...selected], filter);
      setMessage(outcome.started ? "Repair started. You can follow progress on Sync." : "Another archive job is already running.");
    } catch (error) { setMessage((error as Error).message); }
  };
  if (loading) return <div className="mx-auto max-w-6xl space-y-3 px-4 py-8"><Skeleton className="h-28" /><Skeleton className="h-80" /></div>;
  if (!report) return <div className="h-full overflow-y-auto px-4"><EmptyState icon={<FirstAid size={40} />} title="Coverage is unavailable" hint={message ?? "The local coverage report could not be loaded."} /></div>;
  return <div className="h-full overflow-y-auto"><div className="mx-auto max-w-6xl px-4 py-8">
    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Archive maintenance</p>
    <h1 className="mt-1 text-2xl font-semibold text-ink">Coverage & repair</h1>
    <p className="mt-1 max-w-3xl text-sm text-ink-dim">See what is safely available offline and fill only the gaps you choose. The report reads indexed facts, so it stays quick even for large archives.{params.has("filter") ? " Repairs on this page are limited to the Gallery results you brought here." : ""}</p>
    {message && <p role="status" className="mt-4 rounded-[var(--radius-control)] border border-line bg-surface p-3 text-sm text-ink-dim">{message} <Link to="/sync" className="text-accent hover:underline">Open Sync</Link></p>}
    <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {report.categories.map((entry) => {
        const percent = entry.eligible ? Math.round(entry.ready / entry.eligible * 100) : 100;
        return <label key={entry.key} className="cursor-pointer rounded-[var(--radius-media)] border border-line bg-surface p-4 transition hover:border-accent/50">
          <div className="flex items-start justify-between gap-3"><span className="text-sm font-semibold text-ink">{entry.label}</span><input type="checkbox" checked={selected.has(entry.key)} disabled={!entry.missing} onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(entry.key); else next.delete(entry.key); return next; })} /></div>
          <div className="mt-4 flex items-end justify-between"><span className="text-3xl font-semibold text-ink">{percent}%</span><span className="text-xs text-ink-faint">{entry.ready.toLocaleString()} / {entry.eligible.toLocaleString()}</span></div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-elevated"><div className="h-full bg-accent" style={{ width: `${percent}%` }} /></div>
          <p className="mt-3 text-xs leading-5 text-ink-dim">{entry.description}</p>
          <p className="mt-2 flex items-center gap-1 text-xs text-ink-faint">{entry.missing ? <><WarningCircle size={13} className="text-warn" /> {entry.missing.toLocaleString()} missing</> : <><CheckCircle size={13} className="text-ok" /> Complete</>}{entry.failed ? ` · ${entry.failed} failed` : ""}</p>
        </label>;
      })}
    </div>
    {report.source_health.sources.length > 0 && <section className="mt-6 rounded-[var(--radius-media)] border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-ink">Source health</h2>
      <p className="mt-1 text-xs text-ink-dim">Recent extraction success is compared with its prior five runs, so upstream TikTok or yt-dlp changes become visible before they silently hollow out the archive.</p>
      <ul className="mt-3 divide-y divide-line">{report.source_health.sources.map((source) => <li key={source.source} className="flex flex-wrap items-start justify-between gap-3 py-3 text-sm">
        <div><p className="font-medium text-ink">{source.source}</p><p className="mt-1 text-xs text-ink-dim">{source.message}</p></div>
        <span className={source.severity === "ok" ? "text-ok" : source.severity === "warning" ? "text-warn" : "text-bad"}>{Math.round(source.current_rate * 100)}% successful · {source.current.failed} failed · {source.current.empty} empty</span>
      </li>)}</ul>
    </section>}
    <div className="sticky bottom-4 mt-6 flex items-center justify-between gap-3 rounded-[var(--radius-media)] border border-line bg-canvas/90 p-3 shadow-xl backdrop-blur">
      <span className="text-sm text-ink-dim">{selected.size ? `${selected.size} repair categories selected` : "Choose one or more incomplete categories"}</span>
      <button type="button" disabled={!selected.size} onClick={repair} className="rounded-[var(--radius-control)] bg-accent px-4 py-2 text-sm font-medium text-on-accent disabled:opacity-40">Repair selected gaps</button>
    </div>
  </div></div>;
}
