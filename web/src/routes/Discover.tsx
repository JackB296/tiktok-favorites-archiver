import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Hash, Play, UserCircle } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { DiscoveryEntity } from "../lib/types";
import { Button, EmptyState, Skeleton } from "../components/ui";
import { discoveryFeedUrl, discoveryGalleryUrl } from "../lib/discoveryPresentation";

type Kind = "creator" | "hashtag";

function EntityList({ kind, rows }: { kind: Kind; rows: DiscoveryEntity[] }) {
  if (!rows.length) return <EmptyState icon={kind === "creator" ? <UserCircle size={36} /> : <Hash size={36} />} title={`No ${kind === "creator" ? "Creators" : "Hashtags"} found`} hint="Discovery fills automatically from archived captions and creator metadata." />;
  return <ul className="divide-y divide-line">
    {rows.map((row) => <li key={row.id} className="flex flex-wrap items-center gap-3 py-3">
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-elevated text-accent">{kind === "creator" ? <UserCircle size={20} /> : <Hash size={19} />}</span>
      <div className="min-w-0 flex-1"><Link to={discoveryGalleryUrl(kind, row.key)} className="font-medium text-ink hover:text-accent">{row.display}</Link><p className="text-xs text-ink-faint">{row.count} favorite{row.count === 1 ? "" : "s"}{row.latest_at ? ` · latest ${new Date(row.latest_at).toLocaleDateString()}` : ""}</p></div>
      <Link to={discoveryGalleryUrl(kind, row.key)} className="rounded px-2 py-1 text-xs font-medium text-ink-dim hover:text-ink">Gallery</Link>
      {row.first_item_id && <Link to={discoveryFeedUrl(kind, row.key, row.first_item_id)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-ink-dim hover:text-ink"><Play size={13} weight="fill" /> Play</Link>}
    </li>)}
  </ul>;
}

export function Discover() {
  const [query, setQuery] = useState("");
  const [order, setOrder] = useState("frequency");
  const [creators, setCreators] = useState<DiscoveryEntity[] | null>(null);
  const [hashtags, setHashtags] = useState<DiscoveryEntity[] | null>(null);
  const [creatorCursor, setCreatorCursor] = useState<number | null>(null);
  const [hashtagCursor, setHashtagCursor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const timer = window.setTimeout(() => {
      setError(null);
      Promise.all([api.creators(query, order), api.hashtags(query, order)])
        .then(([creatorPage, hashtagPage]) => {
          if (!alive) return;
          setCreators(creatorPage.items); setCreatorCursor(creatorPage.next_cursor);
          setHashtags(hashtagPage.items); setHashtagCursor(hashtagPage.next_cursor);
        })
        .catch((reason) => { if (alive) { setCreators([]); setHashtags([]); setError((reason as Error).message); } });
    }, 150);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [query, order]);

  async function more(kind: Kind) {
    const cursor = kind === "creator" ? creatorCursor : hashtagCursor;
    if (cursor == null) return;
    try {
      const page = kind === "creator" ? await api.creators(query, order, cursor) : await api.hashtags(query, order, cursor);
      if (kind === "creator") { setCreators((current) => [...(current ?? []), ...page.items]); setCreatorCursor(page.next_cursor); }
      else { setHashtags((current) => [...(current ?? []), ...page.items]); setHashtagCursor(page.next_cursor); }
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  return <div className="h-full overflow-y-auto"><div className="mx-auto max-w-5xl px-4 py-8">
    <div className="mb-6"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Explore the archive</p><h1 className="mt-1 text-2xl font-semibold text-ink">Discover</h1><p className="mt-1 max-w-2xl text-sm text-ink-dim">Browse exact Creator and Hashtag identities extracted from your archive. These links never rely on substring matching.</p></div>
    <div className="mb-6 grid gap-3 rounded-[var(--radius-media)] border border-line bg-surface p-4 sm:grid-cols-[1fr_auto]">
      <label className="text-xs text-ink-dim">Search Creators and Hashtags<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="@creator or #topic" className="mt-1 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink placeholder:text-ink-faint" /></label>
      <label className="text-xs text-ink-dim">Order<select value={order} onChange={(event) => setOrder(event.target.value)} className="mt-1 h-10 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink"><option value="frequency">Most favorites</option><option value="trend">Most recent</option><option value="name">Name</option></select></label>
    </div>
    {error && <p role="alert" className="mb-4 rounded-[var(--radius-control)] border border-bad/30 bg-bad/10 p-3 text-sm text-bad">{error}</p>}
    <div className="grid gap-5 lg:grid-cols-2">
      {(["creator", "hashtag"] as Kind[]).map((kind) => {
        const rows = kind === "creator" ? creators : hashtags;
        const cursor = kind === "creator" ? creatorCursor : hashtagCursor;
        return <section key={kind} className="rounded-[var(--radius-media)] border border-line bg-surface p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">{kind === "creator" ? <UserCircle size={18} /> : <Hash size={18} />}{kind === "creator" ? "Creators" : "Hashtags"}</h2>
          {rows === null ? <div className="mt-4 space-y-2">{[1, 2, 3, 4].map((n) => <Skeleton key={n} className="h-14" />)}</div> : <EntityList kind={kind} rows={rows} />}
          {cursor != null && <Button variant="ghost" size="sm" className="mt-3 w-full" onClick={() => void more(kind)}>Load more</Button>}
        </section>;
      })}
    </div>
  </div></div>;
}

