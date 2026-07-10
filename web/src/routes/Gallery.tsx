import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  MagnifyingGlass,
  Play,
  ImageSquare,
  SlidersHorizontal,
  BookmarkSimple,
  Trash,
  X,
  LinkSimple,
  SquaresFour,
  Info,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { GalleryPreset, GalleryPresetFilters, GalleryTermList, Item, PlaybackQueue } from "../lib/types";
import { EmptyState, Skeleton, cx } from "../components/ui";
import { VirtualGalleryGrid } from "../components/VirtualGalleryGrid";
import { canLoadNextPage } from "../lib/virtualGrid";

const FILTERS = [
  { key: "", label: "All" },
  { key: "video", label: "Videos" },
  { key: "slideshow", label: "Slideshows" },
];

type GalleryDensity = "compact" | "comfortable";

type GalleryOrder = "latest" | "archive" | "size_desc" | "duration_desc" | "duration_asc" | "favorite_date_desc" | "favorite_date_asc" | "attempts_desc" | "last_attempt_desc" | "author_asc" | "random";

/** One shuffle per Random selection; the seed keeps cursor pages repeat-free. */
function newShuffleSeed() {
  return Math.floor(Math.random() * 2_147_483_647);
}

function filtersToSearchParams(filters: GalleryPresetFilters) {
  const params = new URLSearchParams();
  const values: Record<string, string | undefined> = {
    q: filters.search, kind: filters.kind, status: filters.status, sort: filters.order,
    min_duration: filters.minDuration, max_duration: filters.maxDuration,
    min_size: filters.minSize, max_size: filters.maxSize,
    min_width: filters.minWidth, max_width: filters.maxWidth,
    min_height: filters.minHeight, max_height: filters.maxHeight, codec: filters.codec,
    min_attempts: filters.minAttempts, max_attempts: filters.maxAttempts,
    recovery: filters.recovery ? "1" : undefined,
    from: filters.dateFrom, to: filters.dateTo, orientation: filters.orientation, assets: filters.assets, index: filters.indexState,
    include: filters.include, exclude: filters.exclude,
  };
  Object.entries(values).forEach(([key, value]) => { if (value && !(key === "sort" && value === "latest")) params.set(key, value); });
  return params;
}

export function Gallery() {
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const loadMoreSentinelRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<() => void>(() => {});
  const loadingMoreRef = useRef(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const fromUrl = (name: string) => searchParams.get(name) ?? "";
  const [search, setSearch] = useState(() => fromUrl("q"));
  const [kind, setKind] = useState(() => fromUrl("kind"));
  const [items, setItems] = useState<Item[] | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [status, setStatus] = useState(() => fromUrl("status"));
  const [order, setOrder] = useState<GalleryOrder>(() => (fromUrl("sort") as GalleryOrder) || "latest");
  const [randomSeed, setRandomSeed] = useState(newShuffleSeed);
  const [minDuration, setMinDuration] = useState(() => fromUrl("min_duration"));
  const [maxDuration, setMaxDuration] = useState(() => fromUrl("max_duration"));
  const [minSize, setMinSize] = useState(() => fromUrl("min_size"));
  const [maxSize, setMaxSize] = useState(() => fromUrl("max_size"));
  const [minWidth, setMinWidth] = useState(() => fromUrl("min_width"));
  const [maxWidth, setMaxWidth] = useState(() => fromUrl("max_width"));
  const [minHeight, setMinHeight] = useState(() => fromUrl("min_height"));
  const [maxHeight, setMaxHeight] = useState(() => fromUrl("max_height"));
  const [minAttempts, setMinAttempts] = useState(() => fromUrl("min_attempts"));
  const [maxAttempts, setMaxAttempts] = useState(() => fromUrl("max_attempts"));
  const [recovery, setRecovery] = useState(() => fromUrl("recovery") === "1");
  const [recoveryInboxBusy, setRecoveryInboxBusy] = useState(false);
  const [recoveryInboxMessage, setRecoveryInboxMessage] = useState<string | null>(null);
  const [codec, setCodec] = useState(() => fromUrl("codec"));
  const [dateFrom, setDateFrom] = useState(() => fromUrl("from"));
  const [dateTo, setDateTo] = useState(() => fromUrl("to"));
  const [orientation, setOrientation] = useState(() => fromUrl("orientation"));
  const [assets, setAssets] = useState(() => fromUrl("assets"));
  const [indexState, setIndexState] = useState(() => fromUrl("index"));
  const [include, setInclude] = useState(() => fromUrl("include"));
  const [exclude, setExclude] = useState(() => fromUrl("exclude"));
  const [presets, setPresets] = useState<GalleryPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetMessage, setPresetMessage] = useState<string | null>(null);
  const [termLists, setTermLists] = useState<GalleryTermList[]>([]);
  const [selectedTermListId, setSelectedTermListId] = useState("");
  const [termListName, setTermListName] = useState("");
  const [termListMode, setTermListMode] = useState<"include" | "exclude">("exclude");
  const [termListTerms, setTermListTerms] = useState("");
  const [termListMessage, setTermListMessage] = useState<string | null>(null);
  const [playbackQueues, setPlaybackQueues] = useState<PlaybackQueue[]>([]);
  const [selectedPlaybackQueueId, setSelectedPlaybackQueueId] = useState("");
  const [playbackQueueName, setPlaybackQueueName] = useState("");
  const [playbackQueueMessage, setPlaybackQueueMessage] = useState<string | null>(null);
  const [density, setDensity] = useState<GalleryDensity>(() => localStorage.getItem("gallery-density") === "comfortable" ? "comfortable" : "compact");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [inspectionMode, setInspectionMode] = useState(false);
  const [inspectedItem, setInspectedItem] = useState<Item | null>(null);

  function changeOrder(next: GalleryOrder) {
    if (next === "random") setRandomSeed(newShuffleSeed());
    setOrder(next);
  }

  const pageQuery = {
    search, kind, status, limit: 50, order,
    seed: order === "random" ? randomSeed : undefined,
    min_duration: minDuration ? Number(minDuration) : undefined,
    max_duration: maxDuration ? Number(maxDuration) : undefined,
    min_size: minSize ? Number(minSize) * 1024 * 1024 : undefined,
    max_size: maxSize ? Number(maxSize) * 1024 * 1024 : undefined,
    min_width: minWidth ? Number(minWidth) : undefined,
    max_width: maxWidth ? Number(maxWidth) : undefined,
    min_height: minHeight ? Number(minHeight) : undefined,
    max_height: maxHeight ? Number(maxHeight) : undefined,
    min_attempts: minAttempts ? Number(minAttempts) : undefined,
    max_attempts: maxAttempts ? Number(maxAttempts) : undefined,
    recovery: recovery || undefined,
    codec: codec || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
    orientation: orientation || undefined,
    assets: (assets === "with" || assets === "without" ? assets : undefined) as "with" | "without" | undefined,
    index_state: (indexState === "indexed" || indexState === "missing" || indexState === "failed" ? indexState : undefined) as "indexed" | "missing" | "failed" | undefined,
    include, exclude,
  };

  const queryVersion = useRef(0);

  useEffect(() => {
    let alive = true;
    queryVersion.current += 1;
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
  }, [search, kind, status, order, randomSeed, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, indexState, include, exclude]);

  useEffect(() => {
    setSelectedIds(new Set());
    setRecoveryMessage(null);
  }, [search, kind, status, order, randomSeed, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, indexState, include, exclude]);

  useEffect(() => {
    api.galleryPresets().then(setPresets).catch(() => setPresetMessage("Could not load saved filters."));
  }, []);

  useEffect(() => {
    api.galleryTermLists().then(setTermLists).catch(() => setTermListMessage("Could not load saved term lists."));
  }, []);

  useEffect(() => {
    api.playbackQueues().then(setPlaybackQueues).catch(() => setPlaybackQueueMessage("Could not load saved playback queues."));
  }, []);

  function currentFilters(): GalleryPresetFilters {
    return { search, kind, status, order, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, indexState, include, exclude };
  }

  useEffect(() => {
    setSearchParams(filtersToSearchParams(currentFilters()), { replace: true });
  }, [search, kind, status, order, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, indexState, include, exclude, setSearchParams]);

  function applyPreset(filters: GalleryPresetFilters) {
    setSearch(filters.search ?? "");
    setKind(filters.kind ?? "");
    setStatus(filters.status ?? "");
    changeOrder((filters.order as GalleryOrder) || "latest");
    setMinDuration(filters.minDuration ?? "");
    setMaxDuration(filters.maxDuration ?? "");
    setMinSize(filters.minSize ?? "");
    setMaxSize(filters.maxSize ?? "");
    setMinWidth(filters.minWidth ?? "");
    setMaxWidth(filters.maxWidth ?? "");
    setMinHeight(filters.minHeight ?? "");
    setMaxHeight(filters.maxHeight ?? "");
    setMinAttempts(filters.minAttempts ?? "");
    setMaxAttempts(filters.maxAttempts ?? "");
    setRecovery(Boolean(filters.recovery));
    setCodec(filters.codec ?? "");
    setDateFrom(filters.dateFrom ?? "");
    setDateTo(filters.dateTo ?? "");
    setOrientation(filters.orientation ?? "");
    setAssets(filters.assets ?? "");
    setIndexState(filters.indexState ?? "");
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

  function parsedTerms(value: string) {
    return Array.from(new Set(value.split(",").map((term) => term.trim()).filter(Boolean)));
  }

  function applyTermList() {
    const list = termLists.find((item) => item.id === Number(selectedTermListId));
    if (!list) return;
    const merged = Array.from(new Set([...parsedTerms(list.mode === "include" ? include : exclude), ...list.terms]));
    if (list.mode === "include") setInclude(merged.join(", "));
    else setExclude(merged.join(", "));
    setTermListMessage(`${list.name} applied.`);
  }

  async function saveTermList() {
    const terms = parsedTerms(termListTerms);
    if (!termListName.trim() || !terms.length) return;
    try {
      const saved = await api.createGalleryTermList(termListName.trim(), termListMode, terms);
      setTermLists((current) => [...current, saved].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedTermListId(String(saved.id));
      setTermListName("");
      setTermListTerms("");
      setTermListMessage("Saved.");
    } catch (error) {
      setTermListMessage((error as Error).message);
    }
  }

  async function deleteTermList() {
    const id = Number(selectedTermListId);
    if (!id) return;
    try {
      await api.deleteGalleryTermList(id);
      setTermLists((current) => current.filter((list) => list.id !== id));
      setSelectedTermListId("");
      setTermListMessage("Deleted.");
    } catch (error) {
      setTermListMessage((error as Error).message);
    }
  }

  async function loadMore() {
    if (!canLoadNextPage(nextCursor, loadingMoreRef.current)) return;
    const version = queryVersion.current;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const page = await api.itemPage({ ...pageQuery, cursor: nextCursor });
      if (version !== queryVersion.current) return; // filters changed mid-flight
      setItems((current) => [...(current ?? []), ...page.items]);
      setNextCursor(page.next_cursor);
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    loadMoreRef.current = () => { void loadMore(); };
  });

  useEffect(() => {
    const sentinel = loadMoreSentinelRef.current;
    const scroller = scrollRef.current;
    if (!sentinel || !scroller || nextCursor == null || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMoreRef.current();
      },
      { root: scroller, rootMargin: "800px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [nextCursor, loadingMore]);

  async function copyFilteredLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setPresetMessage("Filtered link copied.");
    } catch {
      setPresetMessage("Could not copy the link.");
    }
  }

  function changeDensity(next: GalleryDensity) {
    setDensity(next);
    localStorage.setItem("gallery-density", next);
  }

  function clearAllFilters() {
    setSearch(""); setKind(""); setStatus(""); setOrder("latest");
    setMinDuration(""); setMaxDuration(""); setMinSize(""); setMaxSize("");
    setMinWidth(""); setMaxWidth(""); setMinHeight(""); setMaxHeight(""); setCodec("");
    setMinAttempts(""); setMaxAttempts("");
    setRecovery(false); setRecoveryInboxMessage(null);
    setDateFrom(""); setDateTo(""); setOrientation(""); setAssets(""); setIndexState(""); setInclude(""); setExclude("");
    setSelectedPresetId("");
  }

  function toggleSelection(itemId: number) {
    if (!selectedIds.has(itemId) && selectedIds.size >= 100) {
      setRecoveryMessage("A selection can contain up to 100 favorites.");
      return;
    }
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  function leaveSelectionMode() {
    setSelectionMode(false);
    setSelectedIds(new Set());
  }

  function playSelected() {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    navigate(`/?queue=${ids.join(",")}`);
  }

  async function savePlaybackQueue() {
    const itemIds = Array.from(selectedIds);
    if (!playbackQueueName.trim() || !itemIds.length) return;
    try {
      const saved = await api.createPlaybackQueue(playbackQueueName.trim(), itemIds);
      setPlaybackQueues((current) => [...current, saved].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedPlaybackQueueId(String(saved.id));
      setPlaybackQueueName("");
      setPlaybackQueueMessage("Saved.");
    } catch (error) {
      setPlaybackQueueMessage((error as Error).message);
    }
  }

  function playSavedQueue() {
    const queue = playbackQueues.find((item) => item.id === Number(selectedPlaybackQueueId));
    if (queue) navigate(`/?queue=${queue.item_ids.join(",")}`);
  }

  async function deletePlaybackQueue() {
    const id = Number(selectedPlaybackQueueId);
    if (!id) return;
    try {
      await api.deletePlaybackQueue(id);
      setPlaybackQueues((current) => current.filter((queue) => queue.id !== id));
      setSelectedPlaybackQueueId("");
      setPlaybackQueueMessage("Deleted.");
    } catch (error) {
      setPlaybackQueueMessage((error as Error).message);
    }
  }

  function enterSelectionMode() {
    setInspectionMode(false);
    setInspectedItem(null);
    setSelectionMode(true);
  }

  async function requeueSelected() {
    const ids = Array.from(selectedIds);
    if (!ids.length || recoveryBusy) return;
    setRecoveryBusy(true);
    setRecoveryMessage(null);
    try {
      const result = await api.requeueItems(ids);
      const requeued = new Set(result.requeued);
      setItems((current) => current?.flatMap((item) => {
        if (!requeued.has(item.id)) return [item];
        return status === "failed" ? [] : [{ ...item, status: "pending" }];
      }) ?? current);
      setSelectedIds(new Set());
      setRecoveryMessage(
        result.requeued.length
          ? `${result.requeued.length} item${result.requeued.length === 1 ? "" : "s"} queued for the next Sync.${result.skipped ? ` ${result.skipped} left unchanged.` : ""}`
          : "No selected items needed recovery.",
      );
    } catch (error) {
      setRecoveryMessage((error as Error).message);
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function toggleRecoveryInbox() {
    if (recovery) {
      setRecovery(false);
      setRecoveryInboxMessage(null);
      return;
    }
    setRecoveryInboxBusy(true);
    setRecoveryInboxMessage(null);
    try {
      await api.verify();
      setRecovery(true);
      setRecoveryInboxMessage("Integrity check complete. Showing failed, missing, and never-tried favorites.");
    } catch (error) {
      setRecoveryInboxMessage(`Could not refresh archive integrity: ${(error as Error).message}`);
    } finally {
      setRecoveryInboxBusy(false);
    }
  }

  const activeFilters: Array<{ label: string; clear: () => void }> = [];
  const addFilter = (value: string, label: string, clear: () => void) => value && activeFilters.push({ label, clear });
  addFilter(search, `Search: ${search}`, () => setSearch(""));
  addFilter(kind, kind === "video" ? "Videos" : "Slideshows", () => setKind(""));
  addFilter(status, `Status: ${status}`, () => setStatus(""));
  if (order !== "latest") activeFilters.push({ label: `Sort: ${order.replace(/_/g, " ")}`, clear: () => setOrder("latest") });
  addFilter(minDuration, `≥ ${minDuration}s`, () => setMinDuration("")); addFilter(maxDuration, `≤ ${maxDuration}s`, () => setMaxDuration(""));
  addFilter(minSize, `≥ ${minSize} MB`, () => setMinSize("")); addFilter(maxSize, `≤ ${maxSize} MB`, () => setMaxSize(""));
  addFilter(minWidth, `width ≥ ${minWidth}`, () => setMinWidth("")); addFilter(maxWidth, `width ≤ ${maxWidth}`, () => setMaxWidth(""));
  addFilter(minHeight, `height ≥ ${minHeight}`, () => setMinHeight("")); addFilter(maxHeight, `height ≤ ${maxHeight}`, () => setMaxHeight(""));
  addFilter(minAttempts, `≥ ${minAttempts} attempts`, () => setMinAttempts("")); addFilter(maxAttempts, `≤ ${maxAttempts} attempts`, () => setMaxAttempts(""));
  if (recovery) activeFilters.push({ label: "Recovery inbox", clear: () => setRecovery(false) });
  addFilter(codec, `Codec: ${codec}`, () => setCodec("")); addFilter(dateFrom, `After: ${dateFrom}`, () => setDateFrom("")); addFilter(dateTo, `Before: ${dateTo}`, () => setDateTo(""));
  addFilter(orientation, orientation, () => setOrientation("")); addFilter(assets, assets === "with" ? "Has raw assets" : "No raw assets", () => setAssets("")); addFilter(indexState, `Index: ${indexState}`, () => setIndexState("")); addFilter(include, `Include: ${include}`, () => setInclude("")); addFilter(exclude, `Exclude: ${exclude}`, () => setExclude(""));

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
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
          <button onClick={() => changeDensity(density === "compact" ? "comfortable" : "compact")} title={density === "compact" ? "Compact thumbnails (switch to comfortable)" : "Comfortable thumbnails (switch to compact)"} aria-label={density === "compact" ? "Use comfortable thumbnail density" : "Use compact thumbnail density"} aria-pressed={density === "compact"} className={cx("rounded-full border p-1.5 transition", density === "compact" ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}><SquaresFour size={16} /></button>
          <button onClick={() => selectionMode ? leaveSelectionMode() : enterSelectionMode()} aria-pressed={selectionMode} className={cx("rounded-full border px-3 py-1.5 text-xs font-medium transition", selectionMode ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>{selectionMode ? "Done selecting" : "Select"}</button>
          <button onClick={toggleRecoveryInbox} disabled={recoveryInboxBusy} aria-pressed={recovery} className={cx("rounded-full border px-3 py-1.5 text-xs font-medium transition disabled:opacity-40", recovery ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>{recoveryInboxBusy ? "Checking…" : recovery ? "Recovery inbox" : "Recovery"}</button>
          <button onClick={() => { if (inspectionMode) { setInspectionMode(false); setInspectedItem(null); } else { leaveSelectionMode(); setInspectionMode(true); } }} aria-pressed={inspectionMode} className={cx("rounded-full border p-1.5 transition", inspectionMode ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")} aria-label={inspectionMode ? "Leave inspect mode" : "Inspect Gallery metadata"}><Info size={16} /></button>
          <button onClick={() => setAdvanced((value) => !value)} aria-label="Toggle advanced filters" className="rounded-full border border-line p-1.5 text-ink-dim hover:text-ink"><SlidersHorizontal size={16} /></button>
        </div>
      </div>

      {recoveryInboxMessage && <p className="mb-5 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5 text-sm text-ink-dim" role="status">{recoveryInboxMessage}</p>}

      {selectionMode && <section className="mb-5 flex flex-wrap items-center gap-3 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5 text-sm text-ink-dim" aria-live="polite">
        <span>{selectedIds.size} selected (up to 100)</span>
        <button type="button" onClick={() => setSelectedIds(new Set())} disabled={!selectedIds.size || recoveryBusy} className="text-ink underline underline-offset-2 disabled:opacity-40">Clear</button>
        <button type="button" onClick={playSelected} disabled={!selectedIds.size || recoveryBusy} className="rounded border border-line px-3 py-1.5 text-xs font-medium text-ink hover:bg-elevated disabled:opacity-40"><Play size={14} weight="fill" /> Play selection</button>
        <input value={playbackQueueName} onChange={(event) => setPlaybackQueueName(event.target.value)} maxLength={80} placeholder="Save as queue…" className="h-8 rounded border border-line bg-elevated px-2 text-xs text-ink placeholder:text-ink-faint" />
        <button type="button" onClick={savePlaybackQueue} disabled={!selectedIds.size || !playbackQueueName.trim() || recoveryBusy} className="rounded border border-line px-3 py-1.5 text-xs font-medium text-ink hover:bg-elevated disabled:opacity-40"><BookmarkSimple size={14} /> Save queue</button>
        <button type="button" onClick={requeueSelected} disabled={!selectedIds.size || recoveryBusy} className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-on-accent disabled:opacity-40">{recoveryBusy ? "Queuing…" : "Queue selected for Sync"}</button>
        <span className="text-xs text-ink-faint">Only failed favorites and finished favorites missing their file will be queued.</span>
        {recoveryMessage && <span className="w-full text-xs text-ink-dim">{recoveryMessage}</span>}
        {playbackQueueMessage && <span className="w-full text-xs text-ink-dim">{playbackQueueMessage}</span>}
      </section>}

      {inspectionMode && <p className="mb-5 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5 text-sm text-ink-dim">Inspect mode: choose a thumbnail to view its full archive metadata. Click the <Info size={13} className="inline" /> button again to return to playback clicks.</p>}

      {activeFilters.length > 0 && <div className="mb-5 flex flex-wrap items-center gap-2" aria-label="Active Gallery filters">
        <span className="text-xs text-ink-faint">Active filters</span>
        {activeFilters.map((filter) => <button key={filter.label} type="button" onClick={() => { filter.clear(); setSelectedPresetId(""); }} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-dim hover:text-ink">{filter.label}<X size={12} aria-hidden="true" /></button>)}
        <button type="button" onClick={clearAllFilters} className="px-1 text-xs text-ink-dim underline underline-offset-2 hover:text-ink">Clear all</button>
        <button type="button" onClick={copyFilteredLink} className="inline-flex items-center gap-1 px-1 text-xs text-ink-dim underline underline-offset-2 hover:text-ink"><LinkSimple size={13} /> Copy link</button>
      </div>}

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
        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3 sm:col-span-2 lg:col-span-3">
          <label className="min-w-48 flex-1 text-xs text-ink-dim">Saved author / hashtag lists
            <select value={selectedTermListId} onChange={(e) => setSelectedTermListId(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Choose a list…</option>{termLists.map((list) => <option key={list.id} value={list.id}>{list.name} · {list.mode === "include" ? "whitelist" : "blacklist"}</option>)}</select>
          </label>
          <button type="button" onClick={applyTermList} disabled={!selectedTermListId} className="inline-flex h-9 rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40">Apply</button>
          {selectedTermListId && <button type="button" onClick={deleteTermList} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-bad"><Trash size={15} /> Delete</button>}
          <label className="min-w-36 flex-1 text-xs text-ink-dim">Save list as
            <input value={termListName} onChange={(e) => setTermListName(e.target.value)} maxLength={80} placeholder="e.g. No FYP" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
          </label>
          <label className="text-xs text-ink-dim">Kind
            <select value={termListMode} onChange={(e) => setTermListMode(e.target.value as "include" | "exclude")} className="mt-1 h-9 rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="exclude">Blacklist</option><option value="include">Whitelist</option></select>
          </label>
          <label className="min-w-48 flex-[2] text-xs text-ink-dim">Terms (comma-separated)
            <input value={termListTerms} onChange={(e) => setTermListTerms(e.target.value)} placeholder="#fyp, foryou" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
          </label>
          <button type="button" onClick={saveTermList} disabled={!termListName.trim() || !parsedTerms(termListTerms).length} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40"><BookmarkSimple size={15} /> Save list</button>
          {termListMessage && <span className="text-xs text-ink-faint">{termListMessage}</span>}
        </div>
        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3 sm:col-span-2 lg:col-span-3">
          <label className="min-w-48 flex-1 text-xs text-ink-dim">Saved playback queues
            <select value={selectedPlaybackQueueId} onChange={(e) => setSelectedPlaybackQueueId(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Choose a queue…</option>{playbackQueues.map((queue) => <option key={queue.id} value={queue.id}>{queue.name} · {queue.item_ids.length} favorites</option>)}</select>
          </label>
          <button type="button" onClick={playSavedQueue} disabled={!selectedPlaybackQueueId} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40"><Play size={15} weight="fill" /> Play queue</button>
          {selectedPlaybackQueueId && <button type="button" onClick={deletePlaybackQueue} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-bad"><Trash size={15} /> Delete</button>}
          {playbackQueueMessage && <span className="text-xs text-ink-faint">{playbackQueueMessage}</span>}
        </div>
        <label className="text-xs text-ink-dim">Sort
          <select value={order} onChange={(e) => changeOrder(e.target.value as GalleryOrder)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="latest">Latest imported favorite</option><option value="archive">Oldest imported favorite</option><option value="favorite_date_desc">Newest favorite date</option><option value="favorite_date_asc">Oldest favorite date</option><option value="author_asc">Creator A–Z</option><option value="size_desc">Largest file</option><option value="duration_desc">Longest video</option><option value="duration_asc">Shortest video</option><option value="attempts_desc">Most download attempts</option><option value="last_attempt_desc">Most recently attempted</option><option value="random">Random order</option></select>
        </label>
        <label className="text-xs text-ink-dim">Download status
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any status</option><option value="done">Ready</option><option value="pending">Pending</option><option value="failed">Failed</option><option value="skipped">Skipped</option><option value="expired">Expired</option></select>
        </label>
        <label className="text-xs text-ink-dim">Minimum download attempts
          <input value={minAttempts} onChange={(e) => setMinAttempts(e.target.value)} type="number" min="0" step="1" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Maximum download attempts
          <input value={maxAttempts} onChange={(e) => setMaxAttempts(e.target.value)} type="number" min="0" step="1" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Orientation
          <select value={orientation} onChange={(e) => setOrientation(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any orientation</option><option value="portrait">Portrait</option><option value="landscape">Landscape</option><option value="square">Square</option></select>
        </label>
        <label className="text-xs text-ink-dim">Raw slideshow assets
          <select value={assets} onChange={(e) => setAssets(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any asset state</option><option value="with">Has original assets</option><option value="without">No original assets</option></select>
        </label>
        <label className="text-xs text-ink-dim">Gallery index health
          <select value={indexState} onChange={(e) => setIndexState(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any index state</option><option value="indexed">Indexed</option><option value="missing">Not indexed</option><option value="failed">Index failed</option></select>
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
        <label className="text-xs text-ink-dim">Minimum width (px)
          <input value={minWidth} onChange={(e) => setMinWidth(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Maximum width (px)
          <input value={maxWidth} onChange={(e) => setMaxWidth(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Minimum height (px)
          <input value={minHeight} onChange={(e) => setMinHeight(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Maximum height (px)
          <input value={maxHeight} onChange={(e) => setMaxHeight(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim">Video codec (comma-separated)
          <input value={codec} onChange={(e) => setCodec(e.target.value)} placeholder="e.g. h264, hevc" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
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
        <Grid density={density}>
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
          <VirtualGalleryGrid
            items={items}
            density={density}
            scrollRef={scrollRef}
            renderItem={(it) => <Thumb key={it.id} item={it} selecting={selectionMode} inspecting={inspectionMode} selected={selectedIds.has(it.id)} onClick={() => selectionMode ? toggleSelection(it.id) : inspectionMode ? setInspectedItem(it) : navigate(`/?item=${it.id}`)} />}
          />
          {nextCursor != null && (
            <div ref={loadMoreSentinelRef} className="mt-6 flex flex-col items-center gap-2" aria-live="polite">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-[var(--radius-control)] border border-line px-4 py-2 text-sm text-ink-dim transition hover:text-ink disabled:opacity-50"
              >
                {loadingMore ? "Loading…" : "Load more"}
              </button>
              <p className="text-xs text-ink-faint">More favorites load automatically as you scroll.</p>
            </div>
          )}
        </>
      )}
    </div>
    {inspectedItem && <DetailsDialog item={inspectedItem} onClose={() => setInspectedItem(null)} onPlay={() => navigate(`/?item=${inspectedItem.id}`)} />}
    </div>
  );
}

function Grid({ children, density }: { children: ReactNode; density: GalleryDensity }) {
  return <div className={cx("grid", density === "compact" ? "grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10" : "grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5")}>{children}</div>;
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return null;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return minutes ? `${minutes}:${String(total % 60).padStart(2, "0")}` : `${total}s`;
}

function formatSize(bytes: number | null) {
  if (bytes == null) return null;
  return bytes >= 1_000_000_000 ? `${(bytes / 1_000_000_000).toFixed(1)} GB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
}

function Thumb({ item, onClick, selecting = false, inspecting = false, selected = false }: { item: Item; onClick: () => void; selecting?: boolean; inspecting?: boolean; selected?: boolean }) {
  const duration = formatDuration(item.duration_s);
  const resolution = item.media_width && item.media_height ? `${item.media_width}×${item.media_height}` : null;
  const size = formatSize(item.media_size);
  return (
    <button
      onClick={onClick}
      aria-label={`${selecting ? selected ? "Unselect" : "Select" : inspecting ? "Inspect" : "Play"} favorite #${item.id}${item.caption ? `: ${item.caption}` : ""}`}
      aria-pressed={selecting ? selected : undefined}
      className={cx("group relative aspect-[9/16] overflow-hidden rounded-[var(--radius-media)] bg-black text-left", selected && "ring-2 ring-accent ring-offset-2 ring-offset-canvas")}
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
      {selecting && <span aria-hidden="true" className={cx("absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full border text-xs", selected ? "border-accent bg-accent text-on-accent" : "border-white/70 bg-black/50 text-white/80")}>{selected ? "✓" : ""}</span>}
      {inspecting && <span aria-hidden="true" className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full border border-white/70 bg-black/50 text-xs text-white/80"><Info size={12} /></span>}
      <div className={cx("absolute top-2 flex max-w-[65%] flex-col items-end gap-1 text-[10px] text-white/85", selecting || inspecting ? "right-9" : "right-2")}>
        {(duration || resolution) && <span className="rounded bg-black/50 px-1.5 py-0.5">{[duration, resolution].filter(Boolean).join(" · ")}</span>}
        {!selecting && !inspecting && <span className="rounded-full bg-black/40 p-1 opacity-0 transition group-hover:opacity-100"><Play size={12} weight="fill" /></span>}
      </div>
      <div className="absolute inset-x-0 bottom-0 p-2.5">
        {item.status === "failed" && <p title={item.error ?? undefined} className="truncate text-[11px] font-medium text-bad">{item.error ?? "Download failed"}</p>}
        {item.author && <p className="truncate text-xs font-medium text-white">{item.author}</p>}
        {item.caption && <p className="truncate text-[11px] text-white/70">{item.caption}</p>}
        {(item.media_codec || size) && <p className="mt-0.5 truncate text-[10px] text-white/55 opacity-0 transition group-hover:opacity-100">{[item.media_codec, size].filter(Boolean).join(" · ")}</p>}
      </div>
    </button>
  );
}

function DetailsDialog({ item, onClose, onPlay }: { item: Item; onClose: () => void; onPlay: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);
  const resolution = item.media_width && item.media_height ? `${item.media_width} × ${item.media_height}` : "Not indexed";
  const rows = [
    ["Status", item.status], ["Type", item.kind], ["Favorited", item.favorited_at ?? "Unknown"],
    ["Duration", formatDuration(item.duration_s) ?? "Not indexed"], ["Resolution", resolution],
    ["Codec", item.media_codec ?? "Not indexed"], ["File size", formatSize(item.media_size) ?? "Not indexed"],
    ["Download attempts", String(item.attempt_count)], ["Last attempt", item.last_attempt_at ?? "Never"],
    ["Archive file", item.archive_missing ? "Missing (integrity scan)" : item.video_url ? "Ready" : "Not available"], ["Raw slideshow assets", item.has_assets ? "Available" : "None"],
  ];
  const safeLink = /^https?:\/\//i.test(item.link);
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="favorite-details-title">
    <div className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-[var(--radius-media)] border border-line bg-surface p-5 shadow-2xl">
      <div className="flex items-start justify-between gap-4"><div><p className="tabular text-xs text-ink-faint">Favorite #{item.id}</p><h2 id="favorite-details-title" className="mt-1 text-lg font-semibold text-ink">Archive details</h2></div><button ref={closeRef} type="button" onClick={onClose} aria-label="Close details" className="rounded-[var(--radius-control)] p-2 text-ink-dim hover:bg-elevated hover:text-ink"><X size={18} /></button></div>
      {item.caption && <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-ink">{item.caption}</p>}
      {item.author && <p className="mt-2 text-sm text-ink-dim">Creator: {item.author}</p>}
      {item.error && <p className="mt-3 rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">Last error: {item.error}</p>}
      <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 border-t border-line pt-4 sm:grid-cols-2">{rows.map(([label, value]) => <div key={label}><dt className="text-xs text-ink-faint">{label}</dt><dd className="mt-0.5 break-words text-sm text-ink">{value}</dd></div>)}</dl>
      <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4"><button type="button" onClick={onPlay} className="inline-flex items-center gap-1.5 rounded-[var(--radius-control)] bg-accent px-3 py-2 text-sm font-medium text-on-accent"><Play size={15} weight="fill" /> Play this favorite</button>{safeLink && <a href={item.link} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-[var(--radius-control)] border border-line px-3 py-2 text-sm text-ink-dim hover:text-ink">Open TikTok</a>}</div>
    </div>
  </div>;
}
