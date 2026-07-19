import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FileArrowUp, MagnifyingGlass, Play, Scan } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { LensResult, LensStatus } from "../lib/types";
import { Button, EmptyState, Skeleton } from "../components/ui";
import { formatMediaTime } from "../lib/format";
import { lensSnippetParts, lensSourceLabel } from "../lib/lensPresentation.js";

function ResultRow({ result }: { result: LensResult }) {
  const title = result.item.caption?.trim()
    || (result.item.author ? `@${result.item.author}` : `Favorite #${result.item.id}`);
  return (
    <li className="grid gap-3 border-b border-line py-4 sm:grid-cols-[5rem_minmax(0,1fr)_auto] sm:items-center">
      {result.item.thumbnail_url ? (
        <img src={result.item.thumbnail_url} alt="" className="h-24 w-20 rounded-[var(--radius-control)] bg-elevated object-cover" />
      ) : (
        <span aria-hidden className="flex h-24 w-20 items-center justify-center rounded-[var(--radius-control)] bg-elevated text-ink-faint"><Scan size={22} /></span>
      )}
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-ink">{title}</p>
        <p className="mt-1 text-sm leading-relaxed text-ink-dim">
          {lensSnippetParts(result.snippet).map((part, index) => part.highlight
            ? <mark key={index} className="rounded bg-accent/20 px-0.5 text-ink">{part.text}</mark>
            : <span key={index}>{part.text}</span>)}
        </p>
        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
          <span>{lensSourceLabel(result.source)}</span>
          <span>·</span>
          <span>{formatMediaTime(result.start_s)}</span>
          {result.item.author && <><span>·</span><span>@{result.item.author}</span></>}
        </p>
      </div>
      <Link to={result.feed_url} className="inline-flex h-9 items-center justify-center gap-1.5 rounded-[var(--radius-control)] bg-accent px-3 text-sm font-medium text-on-accent transition hover:bg-accent-strong">
        <Play size={14} weight="fill" /> Jump to match
      </Link>
    </li>
  );
}

export function Lens() {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState<LensStatus | null>(null);
  const [results, setResults] = useState<LensResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.lensStatus().then(setStatus).catch((error) => setMessage((error as Error).message));
  }, []);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setSearching(false);
      return;
    }
    let alive = true;
    setSearching(true);
    const timer = window.setTimeout(() => {
      api.lensSearch(query, source)
        .then((response) => {
          if (!alive) return;
          setResults(response.results);
          setStatus({ items: response.items, segments: response.segments });
          setMessage(null);
        })
        .catch((error) => { if (alive) { setResults([]); setMessage((error as Error).message); } })
        .finally(() => { if (alive) setSearching(false); });
    }, 180);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [query, source]);

  async function importAnalysis(file: File) {
    setMessage("Importing local analysis…");
    try {
      const imported = await api.importLens(file);
      const success = `Imported ${imported.segments} segment${imported.segments === 1 ? "" : "s"} for ${imported.items} favorite${imported.items === 1 ? "" : "s"}.`;
      try {
        if (query.trim()) {
          const response = await api.lensSearch(query, source);
          setResults(response.results);
          setStatus({ items: response.items, segments: response.segments });
        } else {
          setStatus(await api.lensStatus());
        }
        setMessage(success);
      } catch (error) {
        setMessage(`${success} Totals could not refresh: ${(error as Error).message}`);
      }
    } catch (error) {
      setMessage(`Import failed: ${(error as Error).message}`);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Search inside the media</p>
            <h1 className="mt-1 text-2xl font-semibold text-ink">Local Lens</h1>
            <p className="mt-1 max-w-2xl text-sm text-ink-dim">Search timestamped speech and on-screen text imported from tools running on your own machine.</p>
          </div>
          <div className="text-right text-xs text-ink-faint">
            <p className="tabular text-lg font-semibold text-ink">{status?.segments ?? 0}</p>
            <p>segments across {status?.items ?? 0} favorites</p>
          </div>
        </div>

        <section className="rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_10rem_auto] md:items-end">
            <label className="text-xs text-ink-dim">What do you remember?
              <span className="relative mt-1 block">
                <MagnifyingGlass size={16} className="pointer-events-none absolute left-3 top-3 text-ink-faint" />
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="crispy potatoes with parmesan" className="h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint" />
              </span>
            </label>
            <label className="text-xs text-ink-dim">Evidence
              <select value={source} onChange={(event) => setSource(event.target.value)} className="mt-1 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink">
                <option value="">Speech + screen text</option>
                <option value="transcript">Speech only</option>
                <option value="ocr">Screen text only</option>
              </select>
            </label>
            <Button variant="ghost" onClick={() => fileRef.current?.click()}><FileArrowUp size={16} />Import analysis</Button>
            <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void importAnalysis(file);
            }} />
          </div>
          <details className="mt-4 text-xs text-ink-dim">
            <summary className="cursor-pointer font-medium text-ink">Analysis JSON format</summary>
            <pre className="mt-2 overflow-x-auto rounded-[var(--radius-control)] bg-elevated p-3">{`{"items":[{"item_id":1,"segments":[{"source":"transcript","text":"...","start_s":4.2,"end_s":8.5}]}]}`}</pre>
          </details>
          {message && <p className="mt-3 text-sm text-ink-dim" role="status">{message}</p>}
        </section>

        <section className="mt-6">
          {searching ? (
            <div className="space-y-2">{[1, 2, 3].map((value) => <Skeleton key={value} className="h-28" />)}</div>
          ) : query.trim() && results.length ? (
            <ol>{results.map((result) => <ResultRow key={result.id} result={result} />)}</ol>
          ) : query.trim() ? (
            <EmptyState icon={<MagnifyingGlass size={36} />} title="No matching words found" hint="Try fewer terms, switch the evidence filter, or import more locally generated analysis." />
          ) : status?.segments ? (
            <EmptyState icon={<Scan size={38} />} title="Search what was said or shown" hint="Results include the matching evidence and jump directly to its timestamp." />
          ) : (
            <EmptyState icon={<FileArrowUp size={38} />} title="No local analysis imported" hint="Generate transcript or OCR segments with a local tool, then import the JSON document here. Media never leaves this machine." />
          )}
        </section>
      </div>
    </div>
  );
}
