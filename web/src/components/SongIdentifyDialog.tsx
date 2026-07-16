import { useEffect, useRef, useState } from "react";
import { MagnifyingGlass, MusicNotes, X } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item, SongCandidate } from "../lib/types";
import { songLabel } from "../lib/songLinks.js";
import { Dialog } from "./ui";

const SEARCH_DEBOUNCE_MS = 300;

// Manual "match it myself" fallback: search Apple's catalog by text as you type
// and attach the chosen track to this favorite. Used when auto-identification
// missed or picked the wrong song.
export function SongIdentifyDialog({ item, onClose, onSaved }: { item: Item; onClose: () => void; onSaved: (item: Item) => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState(item.song?.title ?? "");
  const [results, setResults] = useState<SongCandidate[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Monotonic id so an earlier, slower request can't overwrite a newer result.
  const requestSeq = useRef(0);
  const busy = savingKey !== null;

  // Search-as-you-type: debounce the query and show matches without a click.
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      requestSeq.current += 1; // cancel any in-flight result
      setResults(null);
      setSearching(false);
      setError(null);
      return;
    }
    const seq = ++requestSeq.current;
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const { results: found } = await api.searchSongs(q);
        if (seq !== requestSeq.current) return; // a newer keystroke won
        setResults(found);
        setError(null);
      } catch (requestError) {
        if (seq !== requestSeq.current) return;
        const message = requestError instanceof Error ? requestError.message : "Search failed.";
        setError(/enable song identification/i.test(message)
          ? "Turn on song identification in the Sync tab to search."
          : message);
        setResults(null);
      } finally {
        if (seq === requestSeq.current) setSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  async function choose(candidate: SongCandidate, index: number) {
    setSavingKey(candidate.key ?? `i${index}`);
    setError(null);
    try {
      onSaved(await api.setItemSong(item.id, candidate));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not save this song.");
      setSavingKey(null);
    }
  }

  return (
    <Dialog labelledBy="song-identify-title" onClose={onClose} closeDisabled={busy} initialFocusRef={inputRef} className="bg-black/75">
      <form onSubmit={(event) => event.preventDefault()} className="flex max-h-[85dvh] w-full max-w-lg flex-col rounded-[var(--radius-media)] border border-white/15 bg-surface p-5 text-ink shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="tabular text-xs text-ink-faint">Favorite #{item.id}</p>
            <h2 id="song-identify-title" className="mt-1 text-lg font-semibold">Identify song</h2>
            <p className="mt-1 text-sm leading-relaxed text-ink-dim">Start typing a title or artist and pick the match. This sets the song for this favorite by hand{item.song ? <>, replacing <span className="font-medium text-ink">{songLabel(item.song)}</span></> : null}.</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} disabled={busy} aria-label="Close" className="rounded-[var(--radius-control)] p-2 text-ink-dim hover:bg-elevated hover:text-ink disabled:opacity-40"><X size={18} /></button>
        </div>

        <div className="relative mt-5">
          <MagnifyingGlass size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Song title and artist" aria-label="Search for a song" className="h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated pl-9 pr-16 text-sm text-ink placeholder:text-ink-faint" />
          {searching && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink-faint">Searching…</span>}
        </div>

        {error && <p role="alert" className="mt-4 rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{error}</p>}

        <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
          {results && results.length === 0 && !searching && <p className="py-6 text-center text-sm text-ink-faint">No matches. Try a different title or artist.</p>}
          {results && results.length > 0 && (
            <ul className="divide-y divide-line">
              {results.map((candidate, index) => (
                <li key={candidate.key ?? `i${index}`} className="flex items-center gap-3 py-2.5">
                  {candidate.art_url
                    ? <img src={candidate.art_url} alt="" className="h-11 w-11 shrink-0 rounded-[var(--radius-control)] object-cover" />
                    : <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-control)] bg-elevated text-ink-faint"><MusicNotes size={18} /></span>}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{candidate.title}</p>
                    <p className="truncate text-xs text-ink-dim">{[candidate.artist, candidate.album].filter(Boolean).join(" · ") || "Unknown artist"}</p>
                  </div>
                  <button type="button" onClick={() => void choose(candidate, index)} disabled={busy} className="shrink-0 rounded-[var(--radius-control)] border border-line px-3 py-1.5 text-sm font-medium text-ink-dim hover:text-ink disabled:opacity-40">{savingKey === (candidate.key ?? `i${index}`) ? "Saving…" : "Use this"}</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </form>
    </Dialog>
  );
}
