import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  MagnifyingGlass,
  X,
  Play,
  SpeakerSimpleHigh,
  SpeakerSimpleX,
  ImageSquare,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item } from "../lib/types";
import { PostMedia } from "../components/PostMedia";
import { PlaybackSession, usePlayback } from "../components/playback";
import { EmptyState, Skeleton, cx } from "../components/ui";

const FILTERS = [
  { key: "", label: "All" },
  { key: "video", label: "Videos" },
  { key: "slideshow", label: "Slideshows" },
];

export function Gallery() {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [items, setItems] = useState<Item[] | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selected, setSelected] = useState<Item | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [status, setStatus] = useState("");
  const [order, setOrder] = useState<"latest" | "archive" | "size_desc" | "duration_desc" | "duration_asc" | "favorite_date_desc" | "favorite_date_asc">("latest");
  const [minDuration, setMinDuration] = useState("");
  const [maxDuration, setMaxDuration] = useState("");
  const [minSize, setMinSize] = useState("");
  const [maxSize, setMaxSize] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [orientation, setOrientation] = useState("");
  const [include, setInclude] = useState("");
  const [exclude, setExclude] = useState("");

  const pageQuery = {
    search, kind, status, limit: 50, order,
    min_duration: minDuration ? Number(minDuration) : undefined,
    max_duration: maxDuration ? Number(maxDuration) : undefined,
    min_size: minSize ? Number(minSize) * 1024 * 1024 : undefined,
    max_size: maxSize ? Number(maxSize) * 1024 * 1024 : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
    orientation: orientation || undefined,
    include, exclude,
  };

  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => {
      api
        .itemPage(pageQuery)
        .then((page) => {
          if (!alive) return;
          setItems(page.items);
          setNextCursor(page.next_cursor);
        })
        .catch(() => alive && setItems([]));
    }, 200); // debounce typing
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [search, kind, status, order, minDuration, maxDuration, minSize, maxSize, dateFrom, dateTo, orientation, include, exclude]);

  async function loadMore() {
    if (nextCursor == null || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await api.itemPage({ ...pageQuery, cursor: nextCursor });
      setItems((current) => [...(current ?? []), ...page.items]);
      setNextCursor(page.next_cursor);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
    <div className="mx-auto max-w-[1400px] px-4 py-6">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-sm">
          <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search caption, hashtag, author"
            className="h-10 w-full rounded-[var(--radius-control)] border border-line bg-surface pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
          />
        </div>
        <div className="flex gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setKind(f.key)}
              className={cx(
                "rounded-full px-3 py-1.5 text-xs font-medium transition",
                kind === f.key ? "bg-accent text-on-accent" : "border border-line text-ink-dim hover:text-ink",
              )}
            >
              {f.label}
            </button>
          ))}
          <button onClick={() => setAdvanced((value) => !value)} aria-label="Toggle advanced filters" className="rounded-full border border-line p-1.5 text-ink-dim hover:text-ink"><SlidersHorizontal size={16} /></button>
        </div>
      </div>

      {advanced && <section className="mb-5 grid gap-3 rounded-[var(--radius-media)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-xs text-ink-dim">Sort
          <select value={order} onChange={(e) => setOrder(e.target.value as typeof order)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="latest">Latest imported favorite</option><option value="archive">Oldest imported favorite</option><option value="favorite_date_desc">Newest favorite date</option><option value="favorite_date_asc">Oldest favorite date</option><option value="size_desc">Largest file</option><option value="duration_desc">Longest video</option><option value="duration_asc">Shortest video</option></select>
        </label>
        <label className="text-xs text-ink-dim">Download status
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any status</option><option value="done">Ready</option><option value="pending">Pending</option><option value="failed">Failed</option><option value="skipped">Skipped</option><option value="expired">Expired</option></select>
        </label>
        <label className="text-xs text-ink-dim">Orientation
          <select value={orientation} onChange={(e) => setOrientation(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any orientation</option><option value="portrait">Portrait</option><option value="landscape">Landscape</option><option value="square">Square</option></select>
        </label>
        <label className="text-xs text-ink-dim">Minimum duration (seconds)
          <input value={minDuration} onChange={(e) => setMinDuration(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Maximum duration (seconds)
          <input value={maxDuration} onChange={(e) => setMaxDuration(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Minimum file size (MB)
          <input value={minSize} onChange={(e) => setMinSize(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Maximum file size (MB)
          <input value={maxSize} onChange={(e) => setMaxSize(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Favorited on or after
          <input value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} type="date" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Favorited on or before
          <input value={dateTo} onChange={(e) => setDateTo(e.target.value)} type="date" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Include authors / tags (comma-separated)<input value={include} onChange={(e) => setInclude(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" /></label>
        <label className="text-xs text-ink-dim">Exclude authors / tags<input value={exclude} onChange={(e) => setExclude(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" /></label>
      </section>}

      {!items ? (
        <Grid>
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="aspect-[9/16] !rounded-[var(--radius-media)]" />
          ))}
        </Grid>
      ) : !items.length ? (
        <EmptyState
          icon={<ImageSquare size={40} />}
          title="No matches"
          hint="Try a different search, or import your export and run a sync."
        />
      ) : (
        <>
          <Grid>
            {items.map((it) => (
              <Thumb key={it.id} item={it} onClick={() => setSelected(it)} />
            ))}
          </Grid>
          {nextCursor != null && (
            <div className="mt-6 flex justify-center">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-[var(--radius-control)] border border-line px-4 py-2 text-sm text-ink-dim transition hover:text-ink disabled:opacity-50"
              >
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </>
      )}

      {selected && <Lightbox item={selected} onClose={() => setSelected(null)} />}
    </div>
    </div>
  );
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">{children}</div>;
}

function Thumb({ item, onClick }: { item: Item; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group relative aspect-[9/16] overflow-hidden rounded-[var(--radius-media)] bg-black text-left"
    >
      {item.thumbnail_url ? (
        <img
          src={item.thumbnail_url}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100"
        />
      ) : item.images[0] ? (
        <img
          src={item.images[0]}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100"
        />
      ) : (
        <div className="tabular flex h-full w-full items-center justify-center text-ink-faint">#{item.id}</div>
      )}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
      <span className="tabular absolute left-2 top-2 rounded bg-black/50 px-1.5 py-0.5 text-[10px] text-white/80">
        #{item.id}
      </span>
      <span className="absolute right-2 top-2 rounded-full bg-black/40 p-1 text-white opacity-0 transition group-hover:opacity-100">
        <Play size={12} weight="fill" />
      </span>
      <div className="absolute inset-x-0 bottom-0 p-2.5">
        {item.author && <p className="truncate text-xs font-medium text-white">{item.author}</p>}
        {item.caption && <p className="truncate text-[11px] text-white/70">{item.caption}</p>}
      </div>
    </button>
  );
}

function Lightbox({ item, onClose }: { item: Item; onClose: () => void }) {
  return (
    <PlaybackSession initiallyMuted={false}>
      <LightboxContent item={item} onClose={onClose} />
    </PlaybackSession>
  );
}

function LightboxContent({ item, onClose }: { item: Item; onClose: () => void }) {
  const { muted, toggleMuted } = usePlayback();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const Speaker = muted ? SpeakerSimpleX : SpeakerSimpleHigh;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4" onClick={onClose}>
      <button
        onClick={onClose}
        aria-label="Close"
        className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white transition hover:bg-white/20"
      >
        <X size={20} />
      </button>
      <div
        className="relative flex h-full max-h-[90dvh] w-full max-w-md items-center justify-center"
        onClick={(e) => e.stopPropagation()}
      >
        <PostMedia item={item} active />
        <button
          onClick={toggleMuted}
          aria-label={muted ? "Unmute" : "Mute"}
          className="absolute right-3 top-3 rounded-full bg-black/40 p-2 text-white backdrop-blur-sm transition hover:bg-black/60"
        >
          <Speaker size={18} weight="fill" />
        </button>
        {(item.author || item.caption) && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-4">
            {item.author && <p className="text-sm font-semibold text-white">{item.author}</p>}
            {item.caption && <p className="mt-1 line-clamp-2 text-sm text-white/80">{item.caption}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
