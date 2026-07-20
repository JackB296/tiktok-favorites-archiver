import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Play, WaveSine } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { VibeResult } from "../lib/types";
import { Button, EmptyState } from "../components/ui";

export function Vibes() {
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("");
  const [results, setResults] = useState<VibeResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function search(event?: FormEvent) {
    event?.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    setMessage(null);
    setLabel(query.trim());
    try {
      setResults((await api.vibeSearch(query.trim())).results);
    } catch (error) {
      setResults([]);
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function related(result: VibeResult) {
    setBusy(true);
    setMessage(null);
    setLabel(`More like Favorite #${result.item_id}`);
    try {
      setResults((await api.vibeRelated(result.item_id)).results);
    } catch (error) {
      setResults([]);
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Search by feeling and meaning</p>
          <h1 className="mt-1 text-2xl font-semibold text-ink">Vibe Atlas</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-dim">Explore captions, creators, songs, transcripts, and screen text with a private local text embedding. Nothing leaves this machine.</p>
        </div>
        <form onSubmit={search} className="flex gap-2 rounded-[var(--radius-media)] border border-line bg-surface p-3">
          <label className="sr-only" htmlFor="vibe-query">Describe a vibe</label>
          <input id="vibe-query" value={query} maxLength={240} onChange={(event) => setQuery(event.target.value)} placeholder="late night cooking in a tiny kitchen" className="h-11 min-w-0 flex-1 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink placeholder:text-ink-faint" />
          <Button type="submit" disabled={busy || query.trim().length < 2}><WaveSine size={17} />{busy ? "Mapping…" : "Map this vibe"}</Button>
        </form>
        {results && <div className="mt-6">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-semibold text-ink">{label}</h2>
            <span className="text-xs text-ink-faint">{results.length} local match{results.length === 1 ? "" : "es"}</span>
          </div>
          {results.length ? (
            <ol className="grid gap-3 sm:grid-cols-2">
              {results.map((result) => (
                <li key={result.item_id} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-3 rounded-[var(--radius-media)] border border-line bg-surface p-3">
                  <Link to={`/?item=${result.item_id}`} className="group relative aspect-[3/4] overflow-hidden rounded-[var(--radius-control)] bg-elevated">
                    {result.item.thumbnail_url ? <img src={result.item.thumbnail_url} alt="" className="h-full w-full object-cover transition group-hover:scale-105" /> : <span className="flex h-full items-center justify-center text-ink-faint">#{result.item_id}</span>}
                    <span className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition group-hover:bg-black/30 group-hover:opacity-100"><Play size={20} weight="fill" className="text-white" /></span>
                  </Link>
                  <div className="min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-accent">{Math.round(result.score * 100)}% match</span>
                      <span className="text-xs text-ink-faint">#{result.item_id}</span>
                    </div>
                    <p className="mt-2 line-clamp-3 text-sm font-medium leading-relaxed text-ink">{result.item.caption || (result.item.author ? `@${result.item.author}` : "No caption")}</p>
                    <div className="mt-2 flex flex-wrap gap-1">{result.evidence.map((term) => <span key={term} className="rounded-full bg-elevated px-2 py-0.5 text-[11px] text-ink-dim">{term}</span>)}</div>
                    <button onClick={() => void related(result)} disabled={busy} className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline disabled:opacity-50">Find similar <ArrowRight size={12} /></button>
                  </div>
                </li>
              ))}
            </ol>
          ) : <EmptyState icon={<WaveSine size={40} />} title={message ? "Vibe search failed" : "No related text found"} hint={message ?? "Try different words, or run Local Lens to add transcript and screen text."} />}
        </div>}
      </div>
    </div>
  );
}

