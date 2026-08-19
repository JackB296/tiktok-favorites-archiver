import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChatsCircle, ClockCounterClockwise, MagnifyingGlass } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { CommentSearchResult } from "../lib/types";
import { EmptyState, Skeleton } from "../components/ui";

function displayDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

export function Comments() {
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(params.get("q") ?? "");
  const history = params.get("history") === "true";
  const [results, setResults] = useState<CommentSearchResult[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const query = params.get("q") ?? "";

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.searchComments(query, history).then((page) => {
      if (alive) { setResults(page.results); setCursor(page.next_cursor); setError(null); }
    }).catch((reason) => { if (alive) setError((reason as Error).message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [query, history]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = new URLSearchParams();
    if (draft.trim()) next.set("q", draft.trim());
    if (history) next.set("history", "true");
    setParams(next);
  };

  return <div className="h-full overflow-y-auto">
    <div className="mx-auto max-w-5xl px-4 py-8">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Offline conversations</p>
      <h1 className="mt-1 text-2xl font-semibold text-ink">Search archived comments</h1>
      <p className="mt-1 text-sm text-ink-dim">Search the local snapshots saved beside your media. Older snapshots can surface comments that were edited or removed later.</p>
      <form onSubmit={submit} className="mt-5 flex flex-col gap-3 sm:flex-row">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-[var(--radius-control)] border border-line bg-surface px-3">
          <MagnifyingGlass size={18} className="text-ink-faint" />
          <span className="sr-only">Search comments</span>
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={'Try “camera setup” author:alex likes:>20'} className="min-w-0 flex-1 bg-transparent py-2.5 text-sm text-ink outline-none" />
        </label>
        <button className="rounded-[var(--radius-control)] bg-accent px-4 py-2 text-sm font-medium text-on-accent">Search</button>
      </form>
      <label className="mt-3 inline-flex cursor-pointer items-center gap-2 text-sm text-ink-dim">
        <input type="checkbox" checked={history} onChange={(event) => {
          const next = new URLSearchParams(params);
          if (event.target.checked) next.set("history", "true"); else next.delete("history");
          setParams(next);
        }} />
        Include older snapshots and comments no longer present
      </label>
      {error && <p role="alert" className="mt-5 rounded border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{error}</p>}
      {loading ? <div className="mt-6 space-y-3"><Skeleton className="h-28" /><Skeleton className="h-28" /></div> : results.length ? <ol className="mt-6 space-y-3">
        {results.map((result) => <li key={result.id} className="rounded-[var(--radius-media)] border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-faint">
            <span className="font-medium text-ink-dim">@{result.author_username ?? result.author ?? "unknown"}{result.like_count != null ? ` · ${result.like_count.toLocaleString()} likes` : ""}</span>
            <span className="inline-flex items-center gap-1"><ClockCounterClockwise size={13} /> Captured {displayDate(result.captured_at)}{result.latest ? " · latest" : " · historical"}</span>
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-ink">{result.text}</p>
          {result.thread_context.length > 0 && <div className="mt-3 border-l-2 border-line pl-3"><p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">Saved thread context</p>{result.thread_context.map((reply) => <p key={reply.comment_key} className="mt-1 text-xs text-ink-dim"><span className="font-medium">@{reply.author_username ?? reply.author ?? "unknown"}</span> {reply.text}</p>)}</div>}
          <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3 text-xs">
            <span className="min-w-0 truncate text-ink-faint">#{result.item_id} · {result.item_author ?? "Unknown creator"} · {result.caption || "No caption"}</span>
            <Link to={`/?item=${result.item_id}`} className="shrink-0 font-medium text-accent hover:underline">Open post</Link>
          </div>
        </li>)}
      </ol> : <div className="mt-8"><EmptyState icon={<ChatsCircle size={40} />} title="No matching archived comments" hint="Try fewer terms, or include older snapshots." /></div>}
      {cursor != null && <button onClick={() => api.searchComments(query, history, cursor).then((page) => { setResults((current) => [...current, ...page.results]); setCursor(page.next_cursor); })} className="mt-5 rounded-[var(--radius-control)] border border-line px-4 py-2 text-sm text-ink-dim hover:text-ink">Load more</button>}
    </div>
  </div>;
}
