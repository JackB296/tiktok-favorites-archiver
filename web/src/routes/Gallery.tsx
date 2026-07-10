import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  MagnifyingGlass,
  Play,
  ImageSquare,
  SlidersHorizontal,
  BookmarkSimple,
  Trash,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { GalleryPreset, GalleryPresetFilters, Item } from "../lib/types";
import { EmptyState, Skeleton, cx } from "../components/ui";

const FILTERS = [
  { key: "", label: "All" },
  { key: "video", label: "Videos" },
  { key: "slideshow", label: "Slideshows" },
];

export function Gallery() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [items, setItems] = useState<Item[] | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
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
  const [presets, setPresets] = useState<GalleryPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetMessage, setPresetMessage] = useState<string | null>(null);

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

  useEffect(() => {
    api.galleryPresets().then(setPresets).catch(() => setPresetMessage("Could not load saved filters."));
  }, []);

  function currentFilters(): GalleryPresetFilters {
    return { search, kind, status, order, minDuration, maxDuration, minSize, maxSize, dateFrom, dateTo, orientation, include, exclude };
  }

  function applyPreset(filters: GalleryPresetFilters) {
    setSearch(filters.search ?? "");
    setKind(filters.kind ?? "");
    setStatus(filters.status ?? "");
    setOrder((filters.order as typeof order) || "latest");
    setMinDuration(filters.minDuration ?? "");
    setMaxDuration(filters.maxDuration ?? "");
    setMinSize(filters.minSize ?? "");
    setMaxSize(filters.maxSize ?? "");
    setDateFrom(filters.dateFrom ?? "");
    setDateTo(filters.dateTo ?? "");
    setOrientation(filters.orientation ?? "");
    setInclude(filters.include ?? "");
    setExclude(filters.exclude ?? "");
  }

  async function savePreset() {
    if (!presetName.trim()) return;
    try {
      const saved = await api.createGalleryPreset(presetName.trim(), currentFilters());
      setPresets((current) => [...current, saved].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedPresetId(String(saved.id));
      setPresetName("");
      setPresetMessage("Saved.");
    } catch (error) {
      setPresetMessage((error as Error).message);
    }
  }

  async function deletePreset() {
    const id = Number(selectedPresetId);
    if (!id) return;
    try {
      await api.deleteGalleryPreset(id);
      setPresets((current) => current.filter((preset) => preset.id !== id));
      setSelectedPresetId("");
      setPresetMessage("Deleted.");
    } catch (error) {
      setPresetMessage((error as Error).message);
    }
  }

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
          {search.trim() && <p className="mt-1 text-xs text-ink-faint">Best matches first. Choose an advanced sort to override relevance.</p>}
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
        <div className="flex flex-wrap items-end gap-2 sm:col-span-2 lg:col-span-3">
          <label className="min-w-48 flex-1 text-xs text-ink-dim">Saved filters
            <select value={selectedPresetId} onChange={(e) => { const preset = presets.find((item) => item.id === Number(e.target.value)); setSelectedPresetId(e.target.value); if (preset) applyPreset(preset.filters); }} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Apply a saved filter…</option>{presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}</select>
          </label>
          <label className="min-w-48 flex-1 text-xs text-ink-dim">Save current filters as
            <input value={presetName} onChange={(e) => setPresetName(e.target.value)} maxLength={80} placeholder="e.g. Games without fyp" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
          </label>
          <button type="button" onClick={savePreset} disabled={!presetName.trim()} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40"><BookmarkSimple size={15} /> Save</button>
          {selectedPresetId && <button type="button" onClick={deletePreset} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-bad"><Trash size={15} /> Delete</button>}
          {presetMessage && <span className="text-xs text-ink-faint">{presetMessage}</span>}
        </div>
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
              <Thumb key={it.id} item={it} onClick={() => navigate(`/?item=${it.id}`)} />
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
